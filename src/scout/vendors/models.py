"""The /v1/vendors/check contract."""

import datetime as dt
from typing import Literal

from pydantic import BaseModel, Field

Verdict = Literal["verified", "format_ok", "mismatch", "invalid"]
CheckId = Literal["format", "checksum", "state_code", "registered", "active_on_bill_date", "name_matches"]


class VendorCheckRequest(BaseModel):
    gstin: str = Field(min_length=1, max_length=40, examples=["36AABCS1234L1Z5"])
    vendor_name: str | None = Field(None, max_length=200, description="The shop name as printed on the bill")
    bill_date: dt.date | None = None


class Check(BaseModel):
    id: CheckId
    passed: bool | None = Field(description="null = couldn't be checked (no registry configured)")
    message: str


class RegistryInfo(BaseModel):
    status: Literal["checked", "not_found", "not_configured", "unavailable"]
    source: str | None = Field(None, description='"demo_fixture" means demo data, not the real registry')
    legal_name: str | None = None
    trade_name: str | None = None
    registration_status: str | None = None
    registered_on: dt.date | None = None
    cancelled_on: dt.date | None = None


class VendorCheckResponse(BaseModel):
    gstin: str = Field(description="As checked: upper case, spaces removed")
    verdict: Verdict = Field(description=(
        "verified: the registry confirms it. format_ok: the number is well-formed but no registry was "
        "checked. mismatch: registered, but the name or dates disagree with the bill. invalid: this "
        "number can't be a real GSTIN, or isn't registered."))
    summary: str
    checks: list[Check]
    state: str | None = None
    entity_type: str | None = None
    suggested_gstin: str | None = Field(None, description="A likely misreading that would make it valid")
    registry: RegistryInfo
