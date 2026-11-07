"""Settings read from the environment (and a local .env file, if there is one)."""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from zoneinfo import ZoneInfo

from dotenv import load_dotenv

load_dotenv()

VERSION = "0.1.0"

# Lovable preview and published domains.
DEFAULT_CORS_REGEX = r"https://([a-z0-9-]+\.)*(lovable\.app|lovable\.dev|lovableproject\.com)"


def _flag(name: str, default: str = "0") -> bool:
    return os.getenv(name, default).strip().lower() in ("1", "true", "yes", "on")


def _list(name: str) -> list[str]:
    return [x.strip() for x in os.getenv(name, "").split(",") if x.strip()]


@dataclass(frozen=True)
class Settings:
    mock: bool = field(default_factory=lambda: _flag("MOCK", "1"))
    timezone: str = field(default_factory=lambda: os.getenv("TIMEZONE", "Europe/Helsinki"))
    cors_origins: list[str] = field(
        default_factory=lambda: _list("CORS_ORIGINS")
        or ["http://localhost:5173", "http://localhost:3000", "http://localhost:8080"]
    )
    cors_origin_regex: str = field(
        default_factory=lambda: os.getenv("CORS_ORIGIN_REGEX", DEFAULT_CORS_REGEX)
    )
    # Optional fixed "now" (ISO 8601), e.g. 2026-11-09T08:00:00+02:00. Makes tests and demos repeatable.
    demo_now: str | None = field(default_factory=lambda: os.getenv("DEMO_NOW") or None)
    # Google Calendar (used when MOCK=0)
    google_calendar_id: str = field(default_factory=lambda: os.getenv("GOOGLE_CALENDAR_ID", "primary"))
    google_token_json: str | None = field(default_factory=lambda: os.getenv("GOOGLE_TOKEN_JSON"))
    google_token_file: str = field(default_factory=lambda: os.getenv("GOOGLE_TOKEN_FILE", "token.json"))

    @property
    def tz(self) -> ZoneInfo:
        return ZoneInfo(self.timezone)


settings = Settings()
