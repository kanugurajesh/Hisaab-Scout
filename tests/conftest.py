import datetime as dt
from pathlib import Path

import pytest

from scout.config import Settings
from scout.events.importer import EventImporter
from scout.events.normalize import IST
from scout.fetch import FetchedPage
from scout.llm import CallStats, LlmError

FIXTURES = Path(__file__).resolve().parents[1] / "eval" / "fixtures" / "events"
NOW = dt.datetime(2026, 11, 12, 10, 0, tzinfo=IST)


def settings(**kw) -> Settings:
    """Never reads .env, so a developer's real API key can't leak into tests."""
    base = dict(_env_file=None, ai_mock=False, groq_api_key="", scout_api_keys="")
    return Settings(**(base | kw))


def fixture_html(name: str) -> str:
    return (FIXTURES / name).read_text(encoding="utf-8")


def serve(html: str):
    async def fetcher(url: str, _s: Settings) -> FetchedPage:
        return FetchedPage(url, url, 200, "text/html", html, 1)
    return fetcher


class FakeLlm:
    """Returns a canned answer, or raises, and records what it was asked."""

    def __init__(self, answer=None, *, fail: bool = False):
        self.answer = answer
        self.fail = fail
        self.calls: list[CallStats] = []
        self.messages: list[list[dict]] = []

    def call(self, *, task, schema, messages, mock):
        self.messages.append(messages)
        if self.fail:
            raise LlmError("rate limited", task)
        self.calls.append(CallStats(task=task, model="fake", latency_ms=0, ok=True))
        return self.answer if self.answer is not None else mock()


def importer_for(html: str, llm=None) -> EventImporter:
    return EventImporter(settings(), llm, fetcher=serve(html), clock=lambda: NOW)


@pytest.fixture
def s() -> Settings:
    return settings()
