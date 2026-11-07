"""Datetime helpers. Every datetime that leaves the server is timezone-aware in settings.tz."""

from __future__ import annotations

from datetime import datetime, timedelta

from .config import settings
from .errors import ApiError


def now() -> datetime:
    return datetime.now(settings.tz)


def to_local(dt: datetime) -> datetime:
    if dt.tzinfo is None:
        return dt.replace(tzinfo=settings.tz)
    return dt.astimezone(settings.tz)


def parse_query_dt(value: str | None, name: str) -> datetime | None:
    """Parse an ISO 8601 query param. A missing offset means local time.

    An unencoded '+' in a query string arrives as a space, so put it back.
    """
    if value is None or value == "":
        return None
    raw = value.strip().replace(" ", "+")
    if raw.endswith("Z"):
        raw = raw[:-1] + "+00:00"
    try:
        return to_local(datetime.fromisoformat(raw))
    except ValueError:
        raise ApiError(
            422,
            "validation_error",
            f"'{name}' must be an ISO 8601 datetime, e.g. 2026-11-09T09:00:00+02:00",
            {"errors": [{"loc": ["query", name], "msg": "invalid datetime", "type": "datetime_parsing"}]},
        ) from None


def week_start(dt: datetime) -> datetime:
    local = to_local(dt)
    monday = local.date() - timedelta(days=local.weekday())
    return datetime(monday.year, monday.month, monday.day, tzinfo=settings.tz)


def start_of_day(dt: datetime) -> datetime:
    local = to_local(dt)
    return datetime(local.year, local.month, local.day, tzinfo=settings.tz)


def fmt_short(dt: datetime) -> str:
    """'Mon 10:00', for human-readable summaries."""
    return to_local(dt).strftime("%a %H:%M")
