"""One structured LLM call, the same contract as Hisaab's callStructured.

Strict JSON schema on Groq, re-validated with pydantic, retried once on malformed output. The caller
always passes a `mock` so AI_MOCK=true (tests, offline demos) never touches the network.

The model only ever *reads*. Every value it returns is checked by code before it's used.
"""

import json
import logging
import time
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any, Protocol

from pydantic import BaseModel, ValidationError

from .config import Settings

log = logging.getLogger("scout.llm")


class LlmError(Exception):
    def __init__(self, message: str, task: str):
        super().__init__(message)
        self.task = task


@dataclass
class CallStats:
    task: str
    model: str
    latency_ms: int
    ok: bool
    input_tokens: int | None = None
    output_tokens: int | None = None
    error: str | None = None


class StructuredLlm(Protocol):
    calls: list[CallStats]

    def call[T: BaseModel](
        self, *, task: str, schema: type[T], messages: list[dict[str, str]], mock: Callable[[], T]
    ) -> T: ...


def strict_schema(model: type[BaseModel]) -> dict[str, Any]:
    """Pydantic's JSON schema, tightened for strict mode: every property required, no extras."""

    def tighten(node: Any) -> Any:
        if isinstance(node, dict):
            node = {k: tighten(v) for k, v in node.items() if k not in ("title", "default")}
            if node.get("type") == "object" and "properties" in node:
                node["required"] = list(node["properties"].keys())
                node["additionalProperties"] = False
            return node
        if isinstance(node, list):
            return [tighten(v) for v in node]
        return node

    return tighten(model.model_json_schema())


@dataclass
class GroqLlm:
    settings: Settings
    calls: list[CallStats] = field(default_factory=list)
    _client: Any = None

    def _groq(self) -> Any:
        if self._client is None:
            from groq import Groq

            self._client = Groq(api_key=self.settings.groq_api_key or None,
                                max_retries=self.settings.groq_max_retries, timeout=30.0)
        return self._client

    def call[T: BaseModel](
        self, *, task: str, schema: type[T], messages: list[dict[str, str]], mock: Callable[[], T]
    ) -> T:
        if self.settings.ai_mock:
            self.calls.append(CallStats(task=task, model="mock", latency_ms=0, ok=True))
            return schema.model_validate(mock().model_dump())

        model = self.settings.groq_text_model
        last_error = "unknown error"
        for _attempt in range(2):
            started = time.monotonic()
            try:
                res = self._groq().chat.completions.create(
                    model=model,
                    messages=messages,
                    temperature=0.1,
                    reasoning_effort="low",
                    response_format={
                        "type": "json_schema",
                        "json_schema": {"name": schema.__name__, "strict": True,
                                        "schema": strict_schema(schema)},
                    },
                )
                content = res.choices[0].message.content or ""
                usage = getattr(res, "usage", None)
                stats = CallStats(
                    task=task, model=model, latency_ms=int((time.monotonic() - started) * 1000), ok=True,
                    input_tokens=getattr(usage, "prompt_tokens", None),
                    output_tokens=getattr(usage, "completion_tokens", None),
                )
                try:
                    parsed = schema.model_validate(json.loads(content))
                except (json.JSONDecodeError, ValidationError) as err:
                    stats.ok, stats.error = False, f"schema validation failed: {err}"[:500]
                    self.calls.append(stats)
                    last_error = stats.error
                    continue
                self.calls.append(stats)
                return parsed
            except Exception as err:  # network, auth, rate limit: the SDK has already retried what's worth it
                last_error = str(err)[:500]
                self.calls.append(CallStats(task=task, model=model, ok=False, error=last_error,
                                            latency_ms=int((time.monotonic() - started) * 1000)))
                log.warning("llm call %s failed: %s", task, last_error)
                break  # only malformed output is worth asking again
        raise LlmError(last_error, task)


def make_llm(settings: Settings) -> StructuredLlm | None:
    """None when there's no way to call a model; callers then skip the AI step instead of failing."""
    if settings.ai_mock or settings.groq_api_key:
        return GroqLlm(settings)
    return None
