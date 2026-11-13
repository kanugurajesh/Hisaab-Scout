"""Is the shop on this bill a real, registered business? Every verdict here is decided by code."""

import re

from rapidfuzz import fuzz

from .gstin import inspect
from .models import Check, RegistryInfo, VendorCheckRequest, VendorCheckResponse
from .registry import Registry, RegistryUnavailable

NAME_MATCH = 85
# Words that differ between a bill and the registration without meaning a different business.
FILLER = re.compile(
    r"\b(m/?s|messrs|sri|shri|sree|shree|the|and|private|pvt|limited|ltd|llp|co|company|"
    r"enterprises?|traders?|stores?|shop)\b\.?", re.I)


def _name_key(s: str) -> str:
    s = s.lower().replace("&", " ")
    s = FILLER.sub(" ", s)
    return re.sub(r"[^a-z0-9 ]+", " ", re.sub(r"\s+", " ", s)).strip()


def names_match(on_bill: str, *registered: str | None) -> bool:
    bill = _name_key(on_bill)
    return any(
        r and (fuzz.token_set_ratio(bill, _name_key(r)) >= NAME_MATCH)
        for r in registered
    )


def check_vendor(req: VendorCheckRequest, registry: Registry | None) -> VendorCheckResponse:
    facts = inspect(req.gstin)
    checks: list[Check] = [
        Check(id="format", passed=facts.format_ok,
              message="Has the shape of a GSTIN." if facts.format_ok
              else "Doesn't have the shape of a GSTIN (15 characters: state, PAN, entity, Z, check digit)."),
        Check(id="checksum", passed=facts.checksum_ok,
              message="The check digit is right." if facts.checksum_ok
              else "The last character doesn't match the rest. The number is mistyped or made up."),
        Check(id="state_code", passed=facts.state is not None,
              message=f"Registered in {facts.state}." if facts.state else "The first two digits aren't a state code."),
    ]
    offline_ok = facts.format_ok and facts.checksum_ok and facts.state is not None

    info = RegistryInfo(status="not_configured")
    where = "the demo registry" if registry is not None and registry.source == "demo_fixture" else "the GST registry"
    record = None
    if offline_ok and registry is not None:
        try:
            record = registry.lookup(facts.gstin)
            info = RegistryInfo(status="checked" if record else "not_found", source=registry.source)
        except RegistryUnavailable:
            info = RegistryInfo(status="unavailable", source=registry.source)

    if record is not None:
        info = info.model_copy(update=dict(
            legal_name=record.legal_name, trade_name=record.trade_name,
            registration_status=record.status, registered_on=record.registered_on,
            cancelled_on=record.cancelled_on))
        checks.append(Check(id="registered", passed=True, message=f"Found in {where}."))
        if req.bill_date:
            active = record.registered_on <= req.bill_date and (
                record.cancelled_on is None or req.bill_date < record.cancelled_on)
            msg = (f"Registered on the bill date ({req.bill_date:%d %b %Y})." if active
                   else f"Not registered on the bill date ({req.bill_date:%d %b %Y}).")
        else:
            active = record.status.lower() == "active"
            msg = "Registration is active." if active else f"Registration is {record.status.lower()}."
        checks.append(Check(id="active_on_bill_date", passed=active, message=msg))
        if req.vendor_name:
            ok = names_match(req.vendor_name, record.trade_name, record.legal_name)
            checks.append(Check(
                id="name_matches", passed=ok,
                message=f'"{req.vendor_name}" matches the registered name.' if ok
                else f'"{req.vendor_name}" doesn\'t match the registered name '
                     f'"{record.trade_name or record.legal_name}".'))
    elif info.status == "not_found":
        checks.append(Check(id="registered", passed=False, message=f"Not found in {where}."))
    else:
        why = {"not_configured": "No GST registry is connected, so registration wasn't checked.",
               "unavailable": "The GST registry didn't answer, so registration wasn't checked."}
        if offline_ok:
            checks.append(Check(id="registered", passed=None, message=why.get(info.status, "")))

    if not offline_ok or info.status == "not_found":
        verdict = "invalid"
    elif record is None:
        verdict = "format_ok"
    elif all(c.passed for c in checks):
        verdict = "verified"
    else:
        verdict = "mismatch"

    summary = {
        "verified": "Registered business, active on the bill date, and the name matches.",
        "format_ok": "The GSTIN is well-formed. Registration wasn't checked.",
        "mismatch": "This GSTIN is registered, but it doesn't fit this bill.",
        "invalid": "This can't be a real GSTIN." if not offline_ok else "This GSTIN isn't registered.",
    }[verdict]
    if facts.suggestion and verdict == "invalid":
        summary += f" Did the bill say {facts.suggestion}?"
    if info.source == "demo_fixture":
        summary += " (Demo registry.)"

    return VendorCheckResponse(
        gstin=facts.gstin, verdict=verdict, summary=summary, checks=checks, state=facts.state,
        entity_type=facts.entity_type, suggested_gstin=facts.suggestion, registry=info)
