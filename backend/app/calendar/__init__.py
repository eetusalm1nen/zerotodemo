"""Picks the calendar backend from settings.calendar: "mock" or "google"."""

from __future__ import annotations

from functools import lru_cache

from ..config import settings
from .base import CalendarBackend
from .mock import MockCalendar


@lru_cache(maxsize=1)
def get_calendar() -> CalendarBackend:
    if settings.calendar == "mock":
        return MockCalendar()
    from .google import GoogleCalendar  # noqa: PLC0415

    return GoogleCalendar.from_settings(settings)


__all__ = ["CalendarBackend", "MockCalendar", "get_calendar"]
