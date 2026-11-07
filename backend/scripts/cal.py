"""Small terminal tool for the calendar, without chat or approval. For testing the Google connection.

Run from the backend/ folder (uses Google by default; CALENDAR=mock to try it without Google):

    python scripts/cal.py list                      # events for the next 7 days, with numbers
    python scripts/cal.py list --days 14
    python scripts/cal.py move 3 --days 1           # move event no. 3 from the list to the next day, same time
    python scripts/cal.py move 3 --to 2026-11-10T14:00   # move event no. 3 to a given start time

An event can be given by its number from the latest `list` or by its full id.
Locked events (movable=false) are refused unless you add --force.
"""

import argparse
import json
import os
import sys
from datetime import datetime, timedelta
from pathlib import Path

os.environ.setdefault("CALENDAR", "google")
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.calendar import get_calendar  # noqa: E402
from app.errors import ApiError  # noqa: E402
from app.timeutil import now, start_of_day, to_local  # noqa: E402

LAST = Path(__file__).resolve().parent.parent / ".cal_last_list.json"


def show(ev, n=None):
    prefix = f"{n:>3}. " if n is not None else "     "
    when = "all day" if ev.all_day else f"{ev.start:%a %d.%m %H:%M}–{ev.end:%H:%M}"
    lock = "  [locked]" if not ev.movable else ""
    print(f"{prefix}{when:<24} {ev.title}{lock}")


def resolve(ref: str) -> str:
    if ref.isdigit() and LAST.exists():
        ids = json.loads(LAST.read_text())
        i = int(ref)
        if 1 <= i <= len(ids):
            return ids[i - 1]
        sys.exit(f"No event number {ref} in the latest list (1–{len(ids)}). Run `list` again.")
    return ref


def main() -> None:
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = p.add_subparsers(dest="cmd", required=True)
    pl = sub.add_parser("list")
    pl.add_argument("--days", type=int, default=7)
    pm = sub.add_parser("move")
    pm.add_argument("event")
    g = pm.add_mutually_exclusive_group(required=True)
    g.add_argument("--days", type=int, help="shift by N days, same time of day")
    g.add_argument("--to", help="new start time, e.g. 2026-11-10T14:00 (Helsinki time)")
    pm.add_argument("--force", action="store_true", help="move even a locked event")
    args = p.parse_args()

    cal = get_calendar()
    try:
        if args.cmd == "list":
            start = start_of_day(now())
            events = cal.list_events(start, start + timedelta(days=args.days))
            LAST.write_text(json.dumps([e.id for e in events]))
            for n, ev in enumerate(events, 1):
                show(ev, n)
            print(f"\n{len(events)} event(s). Move one with: python scripts/cal.py move <number> --days 1")
            return

        ev = cal.get_event(resolve(args.event))
        if not ev.movable and not args.force:
            sys.exit(f'"{ev.title}" is locked. Add --force to move it anyway.')
        if ev.all_day:
            sys.exit("All-day events can't be moved with this tool.")
        new_start = ev.start + timedelta(days=args.days) if args.days is not None else to_local(datetime.fromisoformat(args.to))
        moved = cal.move_event(ev.id, new_start, new_start + (ev.end - ev.start))
        print("Before:")
        show(ev)
        print("After:")
        show(moved)
    except ApiError as exc:
        sys.exit(f"Error ({exc.code}): {exc.message}")


if __name__ == "__main__":
    main()
