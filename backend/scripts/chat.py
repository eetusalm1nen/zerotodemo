"""Chat with the agent in the terminal, against the real calendar. Uses the same code as POST /chat and /apply.

Run from the backend/ folder:

    python scripts/chat.py

Defaults: CALENDAR=google, AGENT=real (needs ANTHROPIC_API_KEY in .env).
Try without Google or Claude: CALENDAR=mock AGENT=mock python scripts/chat.py

Commands: week = show the next 7 days, apply = approve the latest proposals, quit = exit.
"""

import logging
import os
import sys
from datetime import timedelta
from pathlib import Path

os.environ.setdefault("CALENDAR", "google")
os.environ.setdefault("AGENT", "real")
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.calendar import get_calendar  # noqa: E402
from app.config import settings  # noqa: E402
from app.errors import ApiError  # noqa: E402
from app.main import apply, chat  # noqa: E402
from app.models import ApplyRequest, ChatRequest  # noqa: E402
from app.timeutil import now, start_of_day  # noqa: E402

logging.basicConfig(level=logging.WARNING)


def when(dt) -> str:
    return f"{dt:%a %d.%m %H:%M}" if dt else "-"


def show_week() -> None:
    start = start_of_day(now())
    for ev in get_calendar().list_events(start, start + timedelta(days=7)):
        span = "all day" if ev.all_day else f"{ev.start:%a %d.%m %H:%M}–{ev.end:%H:%M}"
        print(f"  {span:<22} {ev.title}{'  [locked]' if not ev.movable else ''}")


def main() -> None:
    print(f"Calendar: {settings.calendar}, agent: {settings.agent}. Now: {now():%a %d.%m %H:%M}")
    print("Type a message. Commands: week, apply, quit\n")
    session_id = None
    pending: list[str] = []
    while True:
        try:
            msg = input("you> ").strip()
        except (EOFError, KeyboardInterrupt):
            print()
            break
        if not msg:
            continue
        try:
            if msg in ("quit", "exit"):
                break
            if msg == "week":
                show_week()
            elif msg == "apply":
                if not pending:
                    print("  Nothing to apply.")
                    continue
                res = apply(ApplyRequest(session_id=session_id, change_ids=pending))
                print(f"  Applied {len(res.applied)} change(s). Check the calendar.")
                pending = []
            else:
                print("  ...thinking")
                res = chat(ChatRequest(session_id=session_id, message=msg))
                session_id = res.session_id
                print(f"\nagent> {res.reply}")
                if res.proposed_changes:
                    pending = [c.id for c in res.proposed_changes]
                    for c in res.proposed_changes:
                        print(f"  {c.type.upper():<6} {c.title}: {when(c.old_start)} -> {when(c.new_start)}  ({c.reason})")
                    print("  Type 'apply' to make these changes, or keep chatting.")
                print()
        except ApiError as exc:
            print(f"  Error ({exc.code}): {exc.message}")


if __name__ == "__main__":
    main()
