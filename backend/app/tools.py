"""Internal agent tools (implementations). Tom owns the tool *schemas* and the agent loop;
these are the Python functions those tools call.

    tools = AgentTools(calendar, session)
    tools.list_events(start, end)               -> list[Event]
    tools.find_free_slots(start, end, ...)      -> list[Slot]
    tools.propose_move(event_id, start, end)    -> ProposedChange  (stored in session, nothing applied)
    tools.propose_create(title, start, end)     -> ProposedChange
    tools.propose_delete(event_id)              -> ProposedChange
    apply_change(calendar, change)              -> Event           (used by POST /apply)
"""

from __future__ import annotations

import uuid
from datetime import datetime

from .calendar.base import CalendarBackend
from .config import settings
from .errors import CalendarError
from .free_slots import find_free_slots as _find_free_slots
from .models import Event, ProposedChange, Slot
from .sessions import Session
from .timeutil import fmt_short, now, to_local


def _change_id() -> str:
    return "chg_" + uuid.uuid4().hex[:10]


def apply_change(calendar: CalendarBackend, change: ProposedChange) -> Event:
    """Run one change against the calendar. Raises CalendarError on failure."""
    if change.action == "move":
        return calendar.move_event(change.event_id, change.start, change.end)  # type: ignore[arg-type]
    if change.action == "create":
        return calendar.create_event(change.title, change.start, change.end)  # type: ignore[arg-type]
    if change.action == "delete":
        return calendar.delete_event(change.event_id)  # type: ignore[arg-type]
    raise CalendarError(f"Unknown action {change.action}", code="bad_request")


class AgentTools:
    def __init__(self, calendar: CalendarBackend, session: Session):
        self.calendar = calendar
        self.session = session
        self.proposed_this_turn: list[ProposedChange] = []

    # ---- read tools

    def list_events(self, start: datetime, end: datetime) -> list[Event]:
        return self.calendar.list_events(to_local(start), to_local(end))

    def find_free_slots(
        self,
        start: datetime,
        end: datetime,
        duration_minutes: int = 30,
        earliest_hour: int = 9,
        latest_hour: int = 17,
        include_weekends: bool = False,
        max_results: int | None = 10,
    ) -> list[Slot]:
        start, end = to_local(start), to_local(end)
        return _find_free_slots(
            self.calendar.list_events(start, end),
            start,
            end,
            duration_minutes=duration_minutes,
            earliest_hour=earliest_hour,
            latest_hour=latest_hour,
            include_weekends=include_weekends,
            max_results=max_results,
            tz=settings.tz,
            now=now(),
        )

    # ---- proposal tools (record only; nothing touches the calendar until /apply)

    def _record(self, change: ProposedChange) -> ProposedChange:
        self.session.add_proposals([change])
        self.proposed_this_turn.append(change)
        return change

    def propose_move(self, event_id: str, start: datetime, end: datetime) -> ProposedChange:
        ev = self.calendar.get_event(event_id)
        start, end = to_local(start), to_local(end)
        return self._record(
            ProposedChange(
                id=_change_id(),
                action="move",
                event_id=ev.id,
                title=ev.title,
                start=start,
                end=end,
                original_start=ev.start,
                original_end=ev.end,
                summary=f'Move "{ev.title}" from {fmt_short(ev.start)} to {fmt_short(start)}',
            )
        )

    def propose_create(self, title: str, start: datetime, end: datetime) -> ProposedChange:
        start, end = to_local(start), to_local(end)
        return self._record(
            ProposedChange(
                id=_change_id(),
                action="create",
                title=title,
                start=start,
                end=end,
                summary=f'Create "{title}" on {fmt_short(start)}–{end:%H:%M}',
            )
        )

    def propose_delete(self, event_id: str) -> ProposedChange:
        ev = self.calendar.get_event(event_id)
        return self._record(
            ProposedChange(
                id=_change_id(),
                action="delete",
                event_id=ev.id,
                title=ev.title,
                original_start=ev.start,
                original_end=ev.end,
                summary=f'Delete "{ev.title}" on {fmt_short(ev.start)}',
            )
        )
