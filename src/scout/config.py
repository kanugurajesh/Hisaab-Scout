from functools import lru_cache
from typing import Literal

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    # Comma-separated keys accepted in "Authorization: Bearer <key>". Empty = open (local dev only).
    scout_api_keys: str = ""
    # Requests per minute per caller (API key, or IP when open).
    scout_rate_limit_per_minute: int = 30

    # Sent with every page fetch. Point the "+" URL at your deployment's README if you like.
    scout_user_agent: str = "ScoutLinkPreview/0.1 (+link preview; one fetch per user request)"
    fetch_timeout_seconds: float = 10.0
    fetch_max_bytes: int = 2_000_000
    fetch_max_redirects: int = 5
    cache_ttl_seconds: int = 900

    groq_api_key: str = ""
    groq_text_model: str = "openai/gpt-oss-120b"
    groq_max_retries: int = 2
    # "true" = deterministic fake model (tests, offline demos).
    ai_mock: bool = False

    # Where vendor checks look GSTINs up. "none" = offline checks only; "fixture" = the demo
    # registry in data/gst_registry_demo.json (labelled as demo data in every response).
    gst_registry: Literal["none", "fixture"] = "none"
    gst_registry_fixture_path: str = "data/gst_registry_demo.json"

    @property
    def api_keys(self) -> set[str]:
        return {k.strip() for k in self.scout_api_keys.split(",") if k.strip()}


@lru_cache
def get_settings() -> Settings:
    return Settings()
