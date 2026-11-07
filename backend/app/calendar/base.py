"""Interface every calendar backend implements (mock now, Google next).

Methods are synchronous: the Google client is sync, and FastAPI runs sync
endpoints in a threadpool. Raise errors.CalendarError (code="not_found" for a
missing event) on failure.
"""

from __future__ import annotations

from datetime import datetime
from typing import Protocol

from ..models import Event


class CalendarBackend(Protocol):
    name: str  # "mock" | "google"

    def list_events(self, start: datetime, end: datetime) -> list[Event]:
        """Events overlapping [start, end), recurring series expanded, sorted by start."""
        ...

    def get_event(self, event_id: str) -> Event: ...

    def create_event(
        self,
        title: str,
        start: datetime,
        end: datetime,
        *,
        description: str | None = None,
        location: str | None = None,
        attendees: list[str] | None = None,
    ) -> Event: ...

    def move_event(self, event_id: str, start: datetime, end: datetime) -> Event:
        """Move one event. For a recurring instance, move only that instance."""
        ...

    def delete_event(self, event_id: str) -> Event:
        """Delete one event and return it as it was. For a recurring instance, delete only that instance."""
        ...
