"""Seam between POST /chat and the agent.

The agent (system prompt, tool schemas, loop) belongs to Tom. The proposed interface,
to agree with Tom:

    # app/agent.py
    def run_agent(message: str, session: Session, tools: AgentTools) -> str:
        '''Run one user turn and return the assistant's reply text.
        - Read and append session.history yourself (any message format you like).
        - Call tools.list_events / tools.find_free_slots to read the calendar.
        - Call tools.propose_move / propose_create / propose_delete to suggest changes.
          They are recorded on the session and returned to the UI. Never apply changes directly.
        '''

With MOCK=1, or while app/agent.py doesn't exist, the keyword-based mock_agent below is used,
so the UI always gets realistic replies and proposals.
"""

from __future__ import annotations

import re
from collections.abc import Callable
from datetime import timedelta

from .config import settings
from .errors import ApiError
from .models import Event
from .sessions import Session
from .timeutil import fmt_short, now
from .tools import AgentTools

AgentFn = Callable[[str, Session, AgentTools], str]


def get_agent() -> AgentFn:
    if settings.mock:
        return mock_agent
    try:
        from .agent import run_agent  # type: ignore[import-not-found]  # noqa: PLC0415
    except ImportError as exc:
        raise ApiError(503, "agent_unavailable", "Agent is not installed yet (app/agent.py missing)") from exc
    return run_agent


# ------------------------------------------------------------------ mock agent

_STOP = {"my", "the", "with", "to", "a", "an", "on", "at", "and", "meeting", "please", "can", "you", "me",
         "move", "reschedule", "push", "cancel", "delete", "remove", "tomorrow", "today", "next", "week",
         "afternoon", "morning", "later", "earlier", "book", "schedule", "add", "create", "for", "i", "is"}


def _best_match(message: str, events: list[Event]) -> tuple[Event | None, int]:
    words = [w for w in re.findall(r"[a-zA-Z0-9:]+", message.lower()) if w not in _STOP and len(w) > 1]
    best, best_score = None, 0
    for ev in events:
        title = ev.title.lower()
        score = sum(1 for w in words if w in title)
        if score > best_score:
            best, best_score = ev, score
    return best, best_score


def _match_event(message: str, events: list[Event]) -> Event | None:
    return _best_match(message, events)[0]


def mock_agent(message: str, session: Session, tools: AgentTools) -> str:
    msg = message.lower()
    t0 = now()
    horizon = t0 + timedelta(days=7)
    upcoming = [e for e in tools.list_events(t0, horizon) if not e.all_day]
    changeable = [e for e in upcoming if e.movable]
    session.history.append({"role": "user", "content": message})

    def slots_after(start, minutes: int):
        if "afternoon" in msg:
            return tools.find_free_slots(start, horizon, minutes, earliest_hour=13, latest_hour=17, max_results=3)
        if "morning" in msg:
            return tools.find_free_slots(start, horizon, minutes, earliest_hour=8, latest_hour=12, max_results=3)
        return tools.find_free_slots(start, horizon, minutes, max_results=3)

    def search_from():
        if "tomorrow" in msg:
            d = (t0 + timedelta(days=1)).date()
            return t0.replace(year=d.year, month=d.month, day=d.day, hour=0, minute=0, second=0, microsecond=0)
        return t0

    if any(k in msg for k in ("move", "reschedule", "push", "postpone")):
        locked, locked_score = _best_match(message, [e for e in upcoming if not e.movable])
        ev, ev_score = _best_match(message, changeable)
        if locked is not None and locked_score > ev_score:
            ev, reply = None, f'"{locked.title}" is locked, so I can\'t move it.'
        elif ev is None:
            reply = "Which meeting should I move? I couldn't match one in the next 7 days."
        if ev is not None:
            minutes = int((ev.end - ev.start).total_seconds() // 60)
            slots = [s for s in slots_after(search_from(), minutes) if s.start != ev.start]
            if not slots:
                reply = f'I couldn\'t find a free {minutes}-minute slot for "{ev.title}" this week.'
            else:
                new_start = slots[0].start
                tools.propose_move(ev.id, new_start, new_start + (ev.end - ev.start),
                                   reason=f"First free {minutes}-minute slot that fits your request.")
                reply = (
                    f'"{ev.title}" is on {fmt_short(ev.start)}. The first free {minutes}-minute slot is '
                    f"{fmt_short(new_start)}. Want me to move it there?"
                )
    elif any(k in msg for k in ("cancel", "delete", "remove", "clear")):
        ev = _match_event(message, changeable)
        if ev is None:
            reply = "Which event should I cancel?"
        else:
            tools.propose_delete(ev.id, reason="You asked to cancel it.")
            reply = f'I can cancel "{ev.title}" on {fmt_short(ev.start)}. Confirm to apply.'
    elif any(k in msg for k in ("book", "schedule", "add", "create", "set up", "plan")):
        minutes = 60 if ("hour" in msg or "60" in msg) else 30
        slots = slots_after(search_from(), minutes)
        if not slots:
            reply = "Your week is fully booked. I couldn't find a slot."
        else:
            m = re.search(r"(?:with|called|for)\s+([A-Za-z][\w ]{1,40})", message)
            title = f"Meeting with {m.group(1).strip().title()}" if m and "with" in m.group(0) else "New meeting"
            start = slots[0].start
            tools.propose_create(title, start, start + timedelta(minutes=minutes),
                                 reason=f"First free {minutes}-minute slot in your working hours.")
            reply = f'How about {fmt_short(start)} for "{title}" ({minutes} min)? I\'ve prepared it for you to confirm.'
    elif any(k in msg for k in ("free", "available", "open", "gap")):
        slots = slots_after(search_from(), 30)
        if slots:
            lines = ", ".join(f"{fmt_short(s.start)}–{s.end:%H:%M}" for s in slots)
            reply = f"You're free {lines}."
        else:
            reply = "No free slots in working hours this week."
    else:
        today = [e for e in upcoming if e.start.date() == t0.date()]
        if today:
            items = "; ".join(f"{e.start:%H:%M} {e.title}" for e in today[:5])
            reply = f"You have {len(today)} more event(s) today: {items}. Want me to move or cancel anything?"
        else:
            nxt = upcoming[0] if upcoming else None
            reply = f'Nothing else today. Next up: "{nxt.title}" on {fmt_short(nxt.start)}.' if nxt else "Your week is clear."

    session.history.append({"role": "assistant", "content": reply})
    return reply
