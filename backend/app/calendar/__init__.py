"""Picks the calendar backend: MockCalendar when MOCK=1, Google Calendar otherwise."""

from __future__ import annotations

from functools import lru_cache

from ..config import settings
from .base import CalendarBackend
from .mock import MockCalendar


@lru_cache(maxsize=1)
def get_calendar() -> CalendarBackend:
    if settings.mock:
        return MockCalendar()
    # Task 2: Google Calendar backend (app/calendar/google.py).
    from .google import GoogleCalendar  # noqa: PLC0415

    return GoogleCalendar.from_settings(settings)


__all__ = ["CalendarBackend", "MockCalendar", "get_calendar"]
