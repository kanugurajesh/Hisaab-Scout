"""Who may call, and how often. Hisaab's server is the only intended caller, server to server."""

import hmac
import time
from collections import deque

from fastapi import Request

from .config import Settings
from .errors import ScoutError


def caller_id(request: Request, settings: Settings) -> str:
    keys = settings.api_keys
    if not keys:
        return f"ip:{request.client.host if request.client else 'unknown'}"
    auth = request.headers.get("authorization", "")
    token = auth.removeprefix("Bearer ").strip() if auth.lower().startswith("bearer ") else ""
    for k in keys:
        if token and hmac.compare_digest(token, k):
            return f"key:{k[:6]}"
    raise ScoutError("unauthorized", "Missing or wrong API key. Send 'Authorization: Bearer <key>'.")


class RateLimiter:
    """Sliding window per caller, in memory. One instance on Render's free tier, so this is enough;
    more instances would need a shared store."""

    def __init__(self, per_minute: int):
        self.per_minute = per_minute
        self.hits: dict[str, deque[float]] = {}

    def check(self, caller: str) -> None:
        now = time.monotonic()
        q = self.hits.setdefault(caller, deque())
        while q and now - q[0] > 60:
            q.popleft()
        if len(q) >= self.per_minute:
            raise ScoutError("rate_limited", "Too many requests. Try again in a minute.")
        q.append(now)
