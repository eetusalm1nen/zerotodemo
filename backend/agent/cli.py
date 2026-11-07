"""Chat with the agent in the terminal against the fake calendar.

    python cli.py
Commands: 'week' shows the calendar, 'apply' applies pending proposals, 'quit' exits.
"""
import logging
import os
from datetime import timedelta

from dotenv import load_dotenv

load_dotenv()

from agent import Session, current_time, parse_iso, run_chat  # noqa: E402
from fake_calendar import FakeCalendar  # noqa: E402

logging.basicConfig(level=os.getenv("LOG_LEVEL", "INFO"), format="  [%(name)s] %(message)s")
logging.getLogger("httpx").setLevel(logging.WARNING)


def short(iso):
    return parse_iso(iso).strftime("%a %H:%M") if iso else "-"


def show_week(cal, now):
    monday = (now - timedelta(days=now.weekday())).replace(hour=0, minute=0)
    for ev in cal.list_events(monday.isoformat(), (monday + timedelta(days=7)).isoformat()):
        lock = "" if ev["movable"] else "  [fixed]"
        print(f"  {short(ev['start'])}-{parse_iso(ev['end']):%H:%M}  {ev['title']}{lock}")


def main():
    now = current_time()
    cal = FakeCalendar(now)
    session = Session()
    print(f"Now: {now:%A %Y-%m-%d %H:%M}. Seeded week:")
    show_week(cal, now)
    while True:
        try:
            msg = input("\nyou> ").strip()
        except (EOFError, KeyboardInterrupt):
            break
        if msg in ("quit", "exit"):
            break
        if msg == "week":
            show_week(cal, now)
            continue
        if msg == "apply":
            for change in session.proposals.values():
                cal.apply_change(change)
            print(f"  applied {len(session.proposals)} change(s)")
            session.proposals = {}
            show_week(cal, now)
            continue
        if not msg:
            continue
        out = run_chat(session, msg, cal)
        print(f"\nagent [{out['status']}]> {out['reply']}")
        for c in out["proposed_changes"]:
            print(f"  {c['type'].upper():6} {c['title']}: {short(c['old_start'])} -> "
                  f"{short(c['new_start'])}  ({c['reason']})")


if __name__ == "__main__":
    main()
