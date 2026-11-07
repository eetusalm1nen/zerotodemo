"""GoogleCalendar against an in-memory fake of the Calendar v3 `events()` resource."""

import copy
import uuid
from zoneinfo import ZoneInfo

import pytest

pytest.importorskip("googleapiclient")

from app.calendar.google import LOCKED_KEY, SEED_KEY, GoogleCalendar  # noqa: E402
from app.errors import CalendarError  # noqa: E402
from tests.test_free_slots import dt  # noqa: E402

TZ = ZoneInfo("Europe/Helsinki")


class _Req:
    def __init__(self, fn):
        self.fn = fn

    def execute(self):
        return self.fn()


class FakeEvents:
    def __init__(self):
        self.items: dict[str, dict] = {}
        self.calls: list[tuple[str, dict]] = []

    def _404(self):
        from googleapiclient.errors import HttpError

        class Resp(dict):
            status = 404
            reason = "Not Found"

        raise HttpError(Resp(), b"not found")

    def list(self, **kw):
        self.calls.append(("list", kw))

        def run():
            items = list(self.items.values())
            if kw.get("privateExtendedProperty"):
                k, v = kw["privateExtendedProperty"].split("=")
                items = [i for i in items if i.get("extendedProperties", {}).get("private", {}).get(k) == v]
            return {"items": copy.deepcopy(items)}

        return _Req(run)

    def get(self, calendarId, eventId):
        return _Req(lambda: copy.deepcopy(self.items[eventId]) if eventId in self.items else self._404())

    def insert(self, calendarId, body, sendUpdates):
        self.calls.append(("insert", {"sendUpdates": sendUpdates}))

        def run():
            item = {"id": uuid.uuid4().hex[:8], "status": "confirmed", "organizer": {"self": True}, **body}
            self.items[item["id"]] = item
            return copy.deepcopy(item)

        return _Req(run)

    def patch(self, calendarId, eventId, body, sendUpdates):
        self.calls.append(("patch", {"sendUpdates": sendUpdates}))

        def run():
            if eventId not in self.items:
                self._404()
            self.items[eventId].update(body)
            return copy.deepcopy(self.items[eventId])

        return _Req(run)

    def delete(self, calendarId, eventId, sendUpdates):
        self.calls.append(("delete", {"sendUpdates": sendUpdates}))
        return _Req(lambda: self.items.pop(eventId) and None if eventId in self.items else self._404())


class FakeService:
    def __init__(self):
        self.ev = FakeEvents()

    def events(self):
        return self.ev


@pytest.fixture()
def gcal():
    svc = FakeService()
    return GoogleCalendar(svc, "primary", TZ, "Europe/Helsinki"), svc.ev


def test_create_move_delete_roundtrip(gcal):
    cal, fake = gcal
    ev = cal.create_event("Sync", dt(9, 10), dt(9, 11), attendees=["a@example.com"], location="Zoom")
    assert ev.start == dt(9, 10) and ev.movable and ev.attendees == ["a@example.com"]
    assert fake.items[ev.id]["extendedProperties"]["private"][SEED_KEY] == "1"
    moved = cal.move_event(ev.id, dt(10, 14), dt(10, 15))
    assert moved.start == dt(10, 14) and moved.start.utcoffset().total_seconds() == 7200
    assert [e.id for e in cal.list_events(dt(9, 0), dt(11, 0))] == [ev.id]
    gone = cal.delete_event(ev.id)
    assert gone.title == "Sync" and cal.list_events(dt(9, 0), dt(11, 0)) == []
    # never emails attendees
    assert all(c[1]["sendUpdates"] == "none" for c in fake.calls if c[0] != "list")


def test_missing_event_is_not_found(gcal):
    cal, _ = gcal
    with pytest.raises(CalendarError) as e:
        cal.get_event("nope")
    assert e.value.code == "not_found"


def test_movable_rules(gcal):
    cal, fake = gcal
    locked = cal.insert_raw({"summary": "Board", "start": {"dateTime": dt(9, 9).isoformat()},
                             "end": {"dateTime": dt(9, 10).isoformat()},
                             "extendedProperties": {"private": {LOCKED_KEY: "true"}}})
    assert not locked.movable
    fake.items["x"] = {"id": "x", "summary": "Their meeting", "organizer": {"email": "boss@example.com"},
                       "start": {"dateTime": "2026-11-09T08:00:00Z"}, "end": {"dateTime": "2026-11-09T09:00:00Z"}}
    theirs = cal.get_event("x")
    assert not theirs.movable and theirs.start == dt(9, 10)  # UTC converted to Helsinki
    fake.items["y"] = {"id": "y", "summary": "Holiday", "organizer": {"self": True},
                       "start": {"date": "2026-11-14"}, "end": {"date": "2026-11-15"}}
    allday = cal.get_event("y")
    assert allday.all_day and not allday.movable and allday.start == dt(14, 0)


def test_seeded_ids_only_tagged(gcal):
    cal, fake = gcal
    mine = cal.create_event("A", dt(9, 10), dt(9, 11))
    fake.items["own"] = {"id": "own", "summary": "Personal", "start": {"dateTime": dt(9, 12).isoformat()},
                         "end": {"dateTime": dt(9, 13).isoformat()}}
    assert cal.list_seeded_ids(dt(9, 0), dt(10, 0)) == [mine.id]
