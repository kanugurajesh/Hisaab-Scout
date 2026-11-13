"""The /v1/events/import contract. Field names follow Hisaab's create-collection form."""

import datetime as dt
from typing import Literal

from pydantic import BaseModel, Field

Source = Literal["jsonld", "microdata", "opengraph", "meta", "llm"]
Confidence = Literal["high", "medium"]

WarningCode = Literal[
    "event_in_past",
    "event_far_future",
    "event_cancelled",
    "event_postponed",
    "online_event",
    "free_event",
    "several_prices",
    "not_rupees",
    "rounded_amount",
    "timezone_assumed",
    "several_events",
    "login_wall",
    "ai_unavailable",
    "instructions_for_ai",
]


class ImportRequest(BaseModel):
    url: str = Field(min_length=4, max_length=2048, examples=["https://lu.ma/diwali-tower-b"])


class Extracted[T](BaseModel):
    value: T
    source: Source
    confidence: Confidence
    # For AI-read values: the exact words on the page the value came from. Shown to the organizer.
    evidence: str | None = None


class ImportedEvent(BaseModel):
    """Everything is optional: a page may give only some of it. The organizer confirms before saving."""

    name: Extracted[str] | None = None
    date: Extracted[dt.date] | None = None
    start_time: Extracted[str] | None = Field(None, description='"HH:MM", 24-hour, IST')
    venue: Extracted[str] | None = Field(None, description="One line, at most 200 characters")
    per_head_amount: Extracted[int] | None = Field(None, description="Whole rupees")
    notes: Extracted[str] | None = Field(None, description="At most 500 characters")
    image_url: Extracted[str] | None = None
    organizer: Extracted[str] | None = None


class ImportWarning(BaseModel):
    code: WarningCode
    message: str


class ImportResponse(BaseModel):
    found: bool = Field(description="True when the page has an event name and a date, venue or price")
    event: ImportedEvent
    alternatives: list[ImportedEvent] = Field(
        default_factory=list, description="Other events on the same page, best first, at most 9"
    )
    needs_confirmation: list[str] = Field(
        default_factory=list,
        description="Form fields worth a second look: anything not read from the page's structured data",
    )
    warnings: list[ImportWarning] = Field(default_factory=list)
    source_url: str
    final_url: str
    used_ai: bool
    cached: bool = False


class ErrorBody(BaseModel):
    code: str
    message: str
    upstream_status: int | None = None


class ErrorResponse(BaseModel):
    error: ErrorBody
