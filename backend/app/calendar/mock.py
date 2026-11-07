"""In-memory calendar with a believable busy week. Used when MOCK=1.

Data is generated relative to the current week, so the demo always looks current.
Changes made through /apply stick until the process restarts.
"""

from __future__ import annotations

import hashlib
import threading
import uuid
from datetime import date, datetime, time, timedelta

from ..config import settings
from ..errors import CalendarError
from ..models import Event
from ..timeutil import now, to_local, week_start

ME = "demo@zerotodemo.app"
TOM = "tom@zerotodemo.app"
MARIUS = "marius@zerotodemo.app"
EETU = "eetu@zerotodemo.app"

# (weekday 0=Mon, start "HH:MM", minutes, title, location, attendees, description)
_ONE_OFFS_WEEK1 = [
    (0, "10:00", 30, "1:1 with Tom", "Zoom", [TOM], "Weekly check-in"),
    (0, "13:00", 60, "Product review", "Room Helsinki", [TOM, MARIUS, EETU], None),
    (0, "15:30", 45, "Recruiting: backend candidate", "Google Meet", [], "Second-round interview"),
    (1, "11:00", 60, "Investor call prep", None, [TOM], "Go through deck v3"),
    (1, "14:00", 90, "Design sync with Marius & Eetu", "Room Espoo", [MARIUS, EETU], None),
    (2, "12:00", 60, "Lunch with Anna", "Café Regatta", ["anna@example.com"], None),
    (2, "15:00", 60, "Customer demo: Acme Oy", "Zoom", ["juha@acme.example.com", TOM], None),
    (3, "10:00", 120, "Focus: hackathon build", None, [], "No meetings please"),
    (3, "14:00", 30, "Call with accountant", "Phone", [], None),
    (3, "16:00", 30, "Dentist", "Kamppi Dental", [], None),
    (4, "11:00", 60, "Board update draft", None, [TOM], None),
    (4, "17:00", 120, "Team drinks", "Bar Molotow", [TOM, MARIUS, EETU], None),
]
_ONE_OFFS_WEEK2 = [
    (0, "10:00", 30, "1:1 with Tom", "Zoom", [TOM], "Weekly check-in"),
    (0, "14:00", 60, "Investor call: Northstar VC", "Zoom", [TOM, "partner@northstar.example.com"], None),
    (1, "13:00", 60, "Sprint planning", "Room Helsinki", [TOM, MARIUS, EETU], None),
    (2, "09:00", 180, "Offsite planning workshop", "Slush HQ", [TOM, MARIUS, EETU], None),
    (3, "15:00", 45, "Gym with Marius", "Urban Gym", [MARIUS], None),
]


def _stable_id(*parts: object) -> str:
    return "evt_" + hashlib.sha1("|".join(map(str, parts)).encode()).hexdigest()[:10]


def _at(day: date, hhmm: str) -> datetime:
    h, m = map(int, hhmm.split(":"))
    return datetime.combine(day, time(h, m), tzinfo=settings.tz)


def seed_events(anchor: datetime | None = None) -> list[Event]:
    """Two busy work weeks: the current one, or on Sat/Sun the coming one, plus the week after."""
    today = to_local(anchor or now())
    shift = timedelta(days=2) if today.weekday() >= 5 else timedelta()
    monday = week_start(today + shift).date()
    events: list[Event] = []

    def add(day: date, hhmm: str, minutes: int, title: str, location, attendees, description, rec=None):
        start = _at(day, hhmm)
        ev_id = f"{rec}_{day:%Y%m%d}" if rec else _stable_id(title, day, hhmm)
        events.append(
            Event(
                id=ev_id,
                title=title,
                start=start,
                end=start + timedelta(minutes=minutes),
                location=location,
                description=description,
                attendees=[ME, *attendees] if attendees else [],
                recurring_event_id=rec,
            )
        )

    for week, one_offs in enumerate((_ONE_OFFS_WEEK1, _ONE_OFFS_WEEK2)):
        wk = monday + timedelta(weeks=week)
        for d in range(5):
            day = wk + timedelta(days=d)
            # Recurring series: each instance is its own event with its own id.
            add(day, "09:30", 15, "Daily standup", "Google Meet", [TOM, MARIUS, EETU], None, rec="rec_standup")
            if d != 2:  # Wednesday is lunch with Anna
                add(day, "12:00", 30, "Lunch", None, [], None, rec="rec_lunch")
        add(wk + timedelta(days=4), "14:00", 60, "Weekly retro", "Room Helsinki", [TOM, MARIUS, EETU], None, rec="rec_retro")
        for d, hhmm, minutes, title, loc, att, desc in one_offs:
            add(wk + timedelta(days=d), hhmm, minutes, title, loc, att, desc)

    # An all-day event on the nearest Saturday (today, if it is Saturday).
    d = today.date()
    sat = d + timedelta(days=(5 - d.weekday()) % 7) if d.weekday() != 6 else d - timedelta(days=1)
    events.append(
        Event(
            id=_stable_id("hackathon", sat),
            title="Zero To Demo hackathon",
            start=datetime.combine(sat, time(0), tzinfo=settings.tz),
            end=datetime.combine(sat + timedelta(days=1), time(0), tzinfo=settings.tz),
            all_day=True,
            location="San Francisco",
        )
    )
    events.sort(key=lambda e: e.start)
    return events


class MockCalendar:
    name = "mock"

    def __init__(self, events: list[Event] | None = None):
        self._lock = threading.Lock()
        self._events: dict[str, Event] = {e.id: e for e in (events if events is not None else seed_events())}

    def reset(self, events: list[Event] | None = None) -> None:
        with self._lock:
            self._events = {e.id: e for e in (events if events is not None else seed_events())}

    def list_events(self, start: datetime, end: datetime) -> list[Event]:
        with self._lock:
            hits = [e for e in self._events.values() if e.start < end and e.end > start]
        return sorted(hits, key=lambda e: (e.start, e.end, e.id))

    def get_event(self, event_id: str) -> Event:
        with self._lock:
            ev = self._events.get(event_id)
        if ev is None:
            raise CalendarError(f"Event {event_id} not found", code="not_found")
        return ev

    def create_event(self, title, start, end, *, description=None, location=None, attendees=None) -> Event:
        ev = Event(
            id="evt_" + uuid.uuid4().hex[:10],
            title=title,
            start=to_local(start),
            end=to_local(end),
            description=description,
            location=location,
            attendees=attendees or [],
        )
        with self._lock:
            self._events[ev.id] = ev
        return ev

    def move_event(self, event_id: str, start: datetime, end: datetime) -> Event:
        with self._lock:
            ev = self._events.get(event_id)
            if ev is None:
                raise CalendarError(f"Event {event_id} not found", code="not_found")
            moved = ev.model_copy(update={"start": to_local(start), "end": to_local(end)})
            self._events[event_id] = moved
        return moved

    def delete_event(self, event_id: str) -> Event:
        with self._lock:
            ev = self._events.pop(event_id, None)
        if ev is None:
            raise CalendarError(f"Event {event_id} not found", code="not_found")
        return ev
