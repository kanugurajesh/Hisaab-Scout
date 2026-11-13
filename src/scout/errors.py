from typing import Literal

ErrorCode = Literal[
    "invalid_url",
    "blocked_address",
    "fetch_failed",
    "timeout",
    "too_large",
    "not_html",
    "http_error",
    "too_many_redirects",
    "unauthorized",
    "rate_limited",
]

# Status codes the API answers with for each error. 4xx = the caller's input; 502/504 = the other site.
STATUS: dict[str, int] = {
    "invalid_url": 422,
    "blocked_address": 422,
    "fetch_failed": 502,
    "timeout": 504,
    "too_large": 502,
    "not_html": 422,
    "http_error": 502,
    "too_many_redirects": 502,
    "unauthorized": 401,
    "rate_limited": 429,
}


class ScoutError(Exception):
    """An error with a stable code the frontend can switch on, and a message a person can read."""

    def __init__(self, code: ErrorCode, message: str, *, upstream_status: int | None = None):
        super().__init__(message)
        self.code = code
        self.message = message
        self.upstream_status = upstream_status

    @property
    def status(self) -> int:
        return STATUS[self.code]
