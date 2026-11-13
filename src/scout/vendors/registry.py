"""Where a GSTIN is looked up, if anywhere.

The government's public "Search Taxpayer" page is behind a captcha, so it isn't scraped. A real
deployment plugs in a licensed lookup (a GST Suvidha Provider or a paid GSTIN API) as another class
with the same `lookup` method. Until then, "none" skips the lookup and says so, and "fixture" serves
a small demo registry that is labelled as demo data in every response.
"""

import datetime as dt
import json
from dataclasses import dataclass
from pathlib import Path
from typing import Protocol


class RegistryUnavailable(Exception):
    pass


@dataclass(frozen=True)
class RegistryRecord:
    gstin: str
    legal_name: str
    trade_name: str | None
    status: str  # "Active" | "Cancelled" | "Suspended"
    registered_on: dt.date
    cancelled_on: dt.date | None


class Registry(Protocol):
    source: str

    def lookup(self, gstin: str) -> RegistryRecord | None: ...


class FixtureRegistry:
    source = "demo_fixture"

    def __init__(self, path: str | Path):
        rows = json.loads(Path(path).read_text(encoding="utf-8"))["records"]
        self._by_gstin = {
            r["gstin"]: RegistryRecord(
                gstin=r["gstin"], legal_name=r["legal_name"], trade_name=r.get("trade_name"),
                status=r["status"], registered_on=dt.date.fromisoformat(r["registered_on"]),
                cancelled_on=dt.date.fromisoformat(r["cancelled_on"]) if r.get("cancelled_on") else None,
            )
            for r in rows
        }

    def lookup(self, gstin: str) -> RegistryRecord | None:
        return self._by_gstin.get(gstin)
