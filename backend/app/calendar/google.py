"""Google Calendar backend for one pre-authorized demo account.

Auth: run scripts/google_auth.py once locally. It writes token.json (with a refresh token).
On the server, put that JSON in GOOGLE_TOKEN_JSON. Access tokens refresh automatically.

Notes:
- Recurring series are expanded (singleEvents=True); each instance has its own id, and
  patching or deleting an instance id affects only that instance.
- An event is locked (movable=False) when it carries the private extended property
  zerotodemo_locked=true, or when the demo account is not its organizer (the API can't move those).
- sendUpdates="none" everywhere: never email attendees from the demo.
"""

from __future__ import annotations

import json
import os
import threading
from datetime import date, datetime, time
from typing import Any

from google.auth.transport.requests import Request
from google.oauth2.credentials import Credentials
from googleapiclient.discovery import build
from googleapiclient.errors import HttpError

from ..errors import ApiError, CalendarError
from ..models import Event
from ..timeutil import to_local

SCOPES = ["https://www.googleapis.com/auth/calendar.events"]
LOCKED_KEY = "zerotodemo_locked"
SEED_KEY = "zerotodemo_seed"


def load_credentials(token_json: str | None, token_file: str) -> Credentials:
    if token_json:
        info = json.loads(token_json)
    elif os.path.exists(token_file):
        with open(token_file) as f:
            info = json.load(f)
    else:
        raise ApiError(
            503, "calendar_error",
            "Google credentials missing: set GOOGLE_TOKEN_JSON or run scripts/google_auth.py",
        )
    creds = Credentials.from_authorized_user_info(info, SCOPES)
    if not creds.valid and creds.refresh_token:
        creds.refresh(Request())
    return creds


def _parse_when(when: dict[str, Any], tz) -> tuple[datetime, bool]:
    if "dateTime" in when:
        return to_local(datetime.fromisoformat(when["dateTime"].replace("Z", "+00:00"))), False
    d = date.fromisoformat(when["date"])
    return datetime.combine(d, time(0), tzinfo=tz), True


def to_event(item: dict[str, Any], tz) -> Event:
    start, all_day = _parse_when(item["start"], tz)
    end, _ = _parse_when(item["end"], tz)
    private = (item.get("extendedProperties") or {}).get("private") or {}
    # Google sets organizer.self=true only when the demo account is the organizer and omits it otherwise.
    organizer = item.get("organizer")
    organizer_is_me = True if organizer is None else bool(organizer.get("self", False))
    return Event(
        id=item["id"],
        title=item.get("summary") or "(no title)",
        start=start,
        end=end,
        all_day=all_day,
        location=item.get("location"),
        description=item.get("description"),
        attendees=[a["email"] for a in item.get("attendees", []) if a.get("email")],
        recurring_event_id=item.get("recurringEventId"),
        movable=organizer_is_me and private.get(LOCKED_KEY) != "true" and not all_day,
    )


def _when(dt: datetime, tz_name: str) -> dict[str, str]:
    return {"dateTime": to_local(dt).isoformat(), "timeZone": tz_name}


class GoogleCalendar:
    name = "google"

    def __init__(self, service, calendar_id: str, tz, tz_name: str):
        self._service = service
        self._calendar_id = calendar_id
        self._tz = tz
        self._tz_name = tz_name
        self._lock = threading.Lock()  # the underlying httplib2 client is not thread-safe

    @classmethod
    def from_settings(cls, settings) -> GoogleCalendar:  # noqa: ANN001
        creds = load_credentials(settings.google_token_json, settings.google_token_file)
        service = build("calendar", "v3", credentials=creds, cache_discovery=False)
        return cls(service, settings.google_calendar_id, settings.tz, settings.timezone)

    # ---- helpers

    def _call(self, request):
        try:
            with self._lock:
                return request.execute()
        except HttpError as exc:
            status = getattr(exc.resp, "status", None)
            if status in (404, 410):
                raise CalendarError("Event not found", code="not_found") from None
            raise CalendarError(f"Google Calendar error ({status}): {exc.reason}") from None

    @property
    def _events(self):
        return self._service.events()

    # ---- CalendarBackend

    def list_events(self, start: datetime, end: datetime) -> list[Event]:
        out: list[Event] = []
        token = None
        while True:
            resp = self._call(
                self._events.list(
                    calendarId=self._calendar_id,
                    timeMin=to_local(start).isoformat(),
                    timeMax=to_local(end).isoformat(),
                    singleEvents=True,
                    orderBy="startTime",
                    maxResults=250,
                    pageToken=token,
                )
            )
            out.extend(to_event(i, self._tz) for i in resp.get("items", []) if i.get("status") != "cancelled")
            token = resp.get("nextPageToken")
            if not token:
                break
        return sorted(out, key=lambda e: (e.start, e.end, e.id))

    def get_event(self, event_id: str) -> Event:
        item = self._call(self._events.get(calendarId=self._calendar_id, eventId=event_id))
        if item.get("status") == "cancelled":
            raise CalendarError("Event not found", code="not_found")
        return to_event(item, self._tz)

    def insert_raw(self, body: dict[str, Any]) -> Event:
        """Insert a full Google event body (used by the seed script)."""
        item = self._call(self._events.insert(calendarId=self._calendar_id, body=body, sendUpdates="none"))
        return to_event(item, self._tz)

    def create_event(self, title, start, end, *, description=None, location=None, attendees=None) -> Event:
        body: dict[str, Any] = {
            "summary": title,
            "start": _when(start, self._tz_name),
            "end": _when(end, self._tz_name),
            # Tag it so `scripts/seed.py --reset` also removes events the demo created.
            "extendedProperties": {"private": {SEED_KEY: "1"}},
        }
        if description:
            body["description"] = description
        if location:
            body["location"] = location
        if attendees:
            body["attendees"] = [{"email": a} for a in attendees]
        return self.insert_raw(body)

    def move_event(self, event_id: str, start: datetime, end: datetime) -> Event:
        item = self._call(
            self._events.patch(
                calendarId=self._calendar_id,
                eventId=event_id,
                body={"start": _when(start, self._tz_name), "end": _when(end, self._tz_name)},
                sendUpdates="none",
            )
        )
        return to_event(item, self._tz)

    def delete_event(self, event_id: str) -> Event:
        ev = self.get_event(event_id)
        self._call(self._events.delete(calendarId=self._calendar_id, eventId=event_id, sendUpdates="none"))
        return ev

    def list_seeded_ids(self, start: datetime, end: datetime) -> list[str]:
        """Ids of events created by the seed script or by the app, in [start, end) (for --clear)."""
        ids: list[str] = []
        token = None
        while True:
            resp = self._call(
                self._events.list(
                    calendarId=self._calendar_id,
                    timeMin=to_local(start).isoformat(),
                    timeMax=to_local(end).isoformat(),
                    privateExtendedProperty=f"{SEED_KEY}=1",
                    singleEvents=False,
                    maxResults=250,
                    pageToken=token,
                )
            )
            ids.extend(i["id"] for i in resp.get("items", []) if i.get("status") != "cancelled")
            token = resp.get("nextPageToken")
            if not token:
                break
        return ids
