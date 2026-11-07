"""Fill the demo Google Calendar with a believable busy fortnight (the same data as mock mode).

Run locally, from the backend/ folder (after scripts/google_auth.py):

    python scripts/seed.py            # add the demo events
    python scripts/seed.py --clear    # remove only events this script (or the app) added
    python scripts/seed.py --reset    # clear, then add again (fresh demo)

Seeded events are tagged with a private property, so --clear never touches your own events.
Attendees are @example.com / @example.com addresses and no invitations are sent.
"""

import argparse
import sys
from datetime import timedelta
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.calendar.google import LOCKED_KEY, SEED_KEY, GoogleCalendar  # noqa: E402
from app.calendar.mock import seed_events  # noqa: E402
from app.config import settings  # noqa: E402
from app.timeutil import now  # noqa: E402


def body_for(ev) -> dict:
    if ev.all_day:
        start = {"date": ev.start.date().isoformat()}
        end = {"date": ev.end.date().isoformat()}
    else:
        start = {"dateTime": ev.start.isoformat(), "timeZone": settings.timezone}
        end = {"dateTime": ev.end.isoformat(), "timeZone": settings.timezone}
    private = {SEED_KEY: "1"}
    if not ev.movable:
        private[LOCKED_KEY] = "true"
    body = {"summary": ev.title, "start": start, "end": end, "extendedProperties": {"private": private}}
    if ev.location:
        body["location"] = ev.location
    if ev.description:
        body["description"] = ev.description
    # The demo account itself is the organizer, so it is not listed as an attendee.
    others = [a for a in ev.attendees if a != "demo@example.com"]
    if others:
        body["attendees"] = [{"email": a} for a in others]
    return body


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--clear", action="store_true", help="remove seeded events only")
    parser.add_argument("--reset", action="store_true", help="clear, then seed again")
    args = parser.parse_args()

    cal = GoogleCalendar.from_settings(settings)
    t0 = now()
    window = (t0 - timedelta(days=14), t0 + timedelta(days=28))

    if args.clear or args.reset:
        ids = cal.list_seeded_ids(*window)
        for event_id in ids:
            cal.delete_event(event_id)
        print(f"Removed {len(ids)} seeded event(s).")
        if args.clear:
            return

    events = seed_events(t0)
    for ev in events:
        cal.insert_raw(body_for(ev))
    print(f"Added {len(events)} events ({events[0].start:%a %d.%m} – {events[-1].end:%a %d.%m}).")


if __name__ == "__main__":
    main()
