"""Scheduling agent: Claude tool loop + proposal logic.

The agent NEVER writes to the calendar. It only reads (list_events, find_free_slots)
and records ProposedChanges. Writes happen through /apply (Topi's apply_change).

Public interface for the backend:
    Session                         - per-chat state (history + pending proposals)
    run_chat(session, message, calendar) -> {"reply", "proposed_changes", "status"}
"""
from __future__ import annotations

import json
import logging
import os
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from typing import Any, Protocol
from zoneinfo import ZoneInfo

log = logging.getLogger("agent")

TZ = ZoneInfo("Europe/Helsinki")
MODEL = os.getenv("AGENT_MODEL", "claude-sonnet-5-5")
MAX_STEPS = int(os.getenv("AGENT_MAX_STEPS", "10"))
MAX_TOKENS = 2048
MAX_REASON_CHARS = 160


# ---------------------------------------------------------------- interfaces

class Calendar(Protocol):
    """Implemented by Topi (real Google) and by fake_calendar.FakeCalendar."""

    def list_events(self, start: str, end: str) -> list[dict]: ...

    def find_free_slots(self, duration_minutes: int, range_start: str, range_end: str,
                        earliest_hour: int = 8, latest_hour: int = 18) -> list[dict]: ...


@dataclass
class Session:
    id: str = field(default_factory=lambda: uuid.uuid4().hex[:12])
    messages: list = field(default_factory=list)
    # Pending ProposedChanges from the latest turn that proposed anything, by change id.
    # /apply looks change ids up here.
    proposals: dict[str, dict] = field(default_factory=dict)


class ToolError(Exception):
    """Error message that is sent back to the model so it can correct itself."""


# ---------------------------------------------------------------- time helpers

def parse_iso(value: Any) -> datetime:
    if not isinstance(value, str):
        raise ToolError(f"Expected an ISO 8601 string, got {value!r}.")
    try:
        dt = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        raise ToolError(f"Invalid datetime {value!r}. Use ISO 8601 with offset, "
                        "e.g. 2026-11-10T09:00:00+02:00.")
    if dt.tzinfo is None:
        raise ToolError(f"Datetime {value!r} has no UTC offset. Add one, e.g. +02:00.")
    return dt


def fmt(dt: datetime) -> str:
    return dt.astimezone(TZ).isoformat(timespec="seconds")


def current_time() -> datetime:
    """Real Helsinki time, or DEMO_NOW (e.g. 2026-11-10T08:30:00+02:00) for rehearsals."""
    demo = os.getenv("DEMO_NOW")
    if demo:
        dt = datetime.fromisoformat(demo)
        return dt if dt.tzinfo else dt.replace(tzinfo=TZ)
    return datetime.now(TZ)


def _overlaps(a_start: datetime, a_end: datetime, b_start: datetime, b_end: datetime) -> bool:
    return a_start < b_end and b_start < a_end


# ---------------------------------------------------------------- prompt

def system_prompt(now: datetime) -> str:
    monday = (now - timedelta(days=now.weekday())).date()
    week = ", ".join(f"{(monday + timedelta(days=i)):%a %Y-%m-%d}" for i in range(7))
    next_monday = monday + timedelta(days=7)
    return f"""You are a scheduling assistant that reorganizes the user's calendar on request.

Current time: {fmt(now)} ({now:%A}). Timezone: Europe/Helsinki.
This week: {week}. Next week starts {next_monday:%a %Y-%m-%d}.
Every time you send must be ISO 8601 with a UTC offset, e.g. {fmt(now.replace(hour=9, minute=0, second=0, microsecond=0))}.

How to work:
1. Start every request by calling list_events for the range that matters (usually from now until the end of next week). Results from earlier in this conversation may be outdated.
2. Decide what to change. Use find_free_slots to find new times.
3. Record each change with propose_move, propose_create or propose_delete. These only record a proposal: the user reviews the changes and presses Apply in the app. You can never apply changes yourself. If the user says "yes" or "apply" in chat, tell them to press Apply.
4. Finish with a short reply.

Rules:
- Never move or delete events with movable=false. They are fixed commitments (client calls, exams, appointments). "Essential" means movable=false. If a fixed event conflicts with the request, say so in your reply.
- If the user is unavailable for a period (sick, travelling), move every movable event in that period unless they say otherwise.
- Never schedule anything in the past. Place new times on weekdays between 08:00 and 18:00 unless the user asks otherwise.
- Never create overlaps. If a propose tool returns an error, fix the problem and try again.
- Keep each event's original duration when moving it.
- Make the smallest set of changes that fulfils the request. Prefer moving over deleting. Only delete when the user asks to cancel something.
- Each time you propose, propose the complete set of changes you recommend. Earlier proposals are discarded when you make new ones, so re-propose anything you still want.
- If the request is unclear or impossible, ask one short question or explain why, and propose nothing.

Reason for each change: one short sentence for the user, max 12 words, e.g. "Moved to Thursday afternoon so you can rest today."

Your final reply: plain text, no markdown, 1-3 sentences, in the user's language. The app shows the list of changes separately, so summarize the plan instead of listing every change. Mention anything you could not do. If you proposed changes, end by asking the user to review them and press Apply."""


# ---------------------------------------------------------------- tool schemas

_ISO = {"type": "string", "description": "ISO 8601 with UTC offset, e.g. 2026-11-10T09:00:00+02:00"}
_REASON = {"type": "string", "description": "One short sentence for the user, max 12 words."}

TOOLS = [
    {
        "name": "list_events",
        "description": "List calendar events overlapping a time range. Each event has id, title, "
                       "start, end, movable (false = fixed, never change) and category.",
        "input_schema": {"type": "object", "properties": {"start": _ISO, "end": _ISO},
                         "required": ["start", "end"]},
    },
    {
        "name": "find_free_slots",
        "description": "Find free time intervals of at least duration_minutes within a range, "
                       "between earliest_hour and latest_hour (Helsinki time). Does not account "
                       "for changes you have already proposed.",
        "input_schema": {
            "type": "object",
            "properties": {
                "duration_minutes": {"type": "integer", "minimum": 5},
                "range_start": _ISO,
                "range_end": _ISO,
                "earliest_hour": {"type": "integer", "default": 8},
                "latest_hour": {"type": "integer", "default": 18},
            },
            "required": ["duration_minutes", "range_start", "range_end"],
        },
    },
    {
        "name": "propose_move",
        "description": "Propose moving an existing event to a new time. Only records a proposal.",
        "input_schema": {
            "type": "object",
            "properties": {"event_id": {"type": "string"}, "new_start": _ISO,
                           "new_end": _ISO, "reason": _REASON},
            "required": ["event_id", "new_start", "new_end", "reason"],
        },
    },
    {
        "name": "propose_create",
        "description": "Propose creating a new event. Only records a proposal.",
        "input_schema": {
            "type": "object",
            "properties": {"title": {"type": "string"}, "start": _ISO, "end": _ISO,
                           "reason": _REASON},
            "required": ["title", "start", "end", "reason"],
        },
    },
    {
        "name": "propose_delete",
        "description": "Propose deleting an existing event. Only when the user asks to cancel "
                       "something. Only records a proposal.",
        "input_schema": {
            "type": "object",
            "properties": {"event_id": {"type": "string"}, "reason": _REASON},
            "required": ["event_id", "reason"],
        },
    },
]


# ---------------------------------------------------------------- proposal logic

class Turn:
    """State for one /chat request: events seen this turn and changes proposed this turn."""

    def __init__(self, calendar: Calendar, now: datetime):
        self.cal = calendar
        self.now = now
        self.known: dict[str, dict] = {}       # events seen via list_events THIS turn
        self.proposals: dict[str, dict] = {}   # change_id -> ProposedChange

    # -- read tools

    def list_events(self, start: str, end: str) -> dict:
        s, e = parse_iso(start), parse_iso(end)
        if e <= s:
            raise ToolError("end must be after start.")
        events = self.cal.list_events(fmt(s), fmt(e))
        for ev in events:
            self.known[ev["id"]] = ev
        return {"events": events}

    def find_free_slots(self, duration_minutes: int, range_start: str, range_end: str,
                        earliest_hour: int = 8, latest_hour: int = 18) -> dict:
        s, e = parse_iso(range_start), parse_iso(range_end)
        s = max(s, self.now)
        if e <= s:
            raise ToolError("Range is empty or entirely in the past.")
        slots = self.cal.find_free_slots(int(duration_minutes), fmt(s), fmt(e),
                                         int(earliest_hour), int(latest_hour))
        result: dict[str, Any] = {"slots": slots}
        taken = [f'{c["new_start"]} to {c["new_end"]} ({c["title"]})'
                 for c in self.proposals.values() if c["new_start"]]
        if taken:
            result["note"] = "These times are already taken by your proposals: " + "; ".join(taken)
        return result

    # -- propose tools

    def propose_move(self, event_id: str, new_start: str, new_end: str, reason: str) -> dict:
        ev = self._event(event_id)
        s, e = self._check_times(new_start, new_end)
        if s == parse_iso(ev["start"]) and e == parse_iso(ev["end"]):
            raise ToolError("New time equals the current time; nothing to move.")
        self._check_conflicts(s, e, moving_id=event_id)
        self._drop_for_event(event_id)
        return self._add("move", ev["id"], ev["title"], ev["start"], ev["end"], fmt(s), fmt(e), reason)

    def propose_create(self, title: str, start: str, end: str, reason: str) -> dict:
        title = (title or "").strip()
        if not title:
            raise ToolError("title must not be empty.")
        s, e = self._check_times(start, end)
        self._check_conflicts(s, e)
        return self._add("create", None, title, None, None, fmt(s), fmt(e), reason)

    def propose_delete(self, event_id: str, reason: str) -> dict:
        ev = self._event(event_id)
        self._drop_for_event(event_id)
        return self._add("delete", ev["id"], ev["title"], ev["start"], ev["end"], None, None, reason)

    # -- helpers

    def _event(self, event_id: str) -> dict:
        ev = self.known.get(event_id)
        if ev is None:
            raise ToolError(f"Unknown event_id {event_id!r}. Call list_events for the relevant "
                            "range first and use an id from its results.")
        if not ev.get("movable", True):
            raise ToolError(f"'{ev['title']}' is fixed (movable=false). Do not move or delete it.")
        return ev

    def _check_times(self, start: str, end: str) -> tuple[datetime, datetime]:
        s, e = parse_iso(start), parse_iso(end)
        if e <= s:
            raise ToolError("end must be after start.")
        if s < self.now:
            raise ToolError(f"Start {fmt(s)} is in the past (now is {fmt(self.now)}).")
        return s, e

    def _check_conflicts(self, s: datetime, e: datetime, moving_id: str | None = None) -> None:
        vacated = {c["event_id"] for c in self.proposals.values() if c["type"] in ("move", "delete")}
        clashes = []
        for ev in self.cal.list_events(fmt(s), fmt(e)):
            self.known.setdefault(ev["id"], ev)
            if ev["id"] == moving_id or ev["id"] in vacated:
                continue
            if _overlaps(s, e, parse_iso(ev["start"]), parse_iso(ev["end"])):
                clashes.append(f"'{ev['title']}' ({ev['start']} to {ev['end']})")
        for c in self.proposals.values():
            if not c["new_start"]:
                continue  # deletes take no time
            if moving_id is not None and c["event_id"] == moving_id:
                continue  # earlier proposal for the same event; it gets replaced
            if _overlaps(s, e, parse_iso(c["new_start"]), parse_iso(c["new_end"])):
                clashes.append(f"your proposed '{c['title']}' ({c['new_start']} to {c['new_end']})")
        if clashes:
            raise ToolError("That time overlaps " + ", ".join(clashes) + ". Pick another time, "
                            "or first move/delete the conflicting event if that is intended.")

    def _drop_for_event(self, event_id: str) -> None:
        for cid in [cid for cid, c in self.proposals.items() if c["event_id"] == event_id]:
            del self.proposals[cid]

    def _add(self, type_, event_id, title, old_start, old_end, new_start, new_end, reason) -> dict:
        reason = (reason or "").strip()
        if not reason:
            raise ToolError("reason must not be empty.")
        if len(reason) > MAX_REASON_CHARS:
            raise ToolError(f"reason is too long; keep it to one short sentence "
                            f"(max {MAX_REASON_CHARS} characters).")
        change = {
            "id": "chg_" + uuid.uuid4().hex[:8],
            "type": type_,
            "event_id": event_id,
            "title": title,
            "old_start": old_start, "old_end": old_end,
            "new_start": new_start, "new_end": new_end,
            "reason": reason,
        }
        self.proposals[change["id"]] = change
        return {"recorded": change}

    # -- dispatch

    def run_tool(self, name: str, args: dict) -> tuple[str, bool]:
        """Returns (content, is_error)."""
        fn = {
            "list_events": self.list_events,
            "find_free_slots": self.find_free_slots,
            "propose_move": self.propose_move,
            "propose_create": self.propose_create,
            "propose_delete": self.propose_delete,
        }.get(name)
        try:
            if fn is None:
                raise ToolError(f"Unknown tool {name!r}.")
            try:
                result = fn(**args)
            except TypeError as exc:
                raise ToolError(f"Bad arguments for {name}: {exc}")
            return json.dumps(result, ensure_ascii=False), False
        except ToolError as exc:
            log.info("tool %s rejected: %s", name, exc)
            return str(exc), True
        except Exception as exc:  # calendar/network failure: let the model see it, loop cap protects us
            log.exception("tool %s crashed", name)
            return f"Internal error in {name}: {exc}", True


# ---------------------------------------------------------------- agent loop

_client = None


def _get_client():
    global _client
    if _client is None:
        import anthropic
        _client = anthropic.Anthropic(max_retries=2, timeout=60.0)  # reads ANTHROPIC_API_KEY
    return _client


def run_chat(session: Session, message: str, calendar: Calendar, client=None) -> dict:
    """One /chat turn. Returns {"reply", "proposed_changes", "status"}.

    Blocking (5-20 s). Never raises: failures come back as status "error".
    Session history is only updated if the turn succeeds, so a crash mid-turn
    cannot leave a broken history that makes every later call fail.
    """
    client = client or _get_client()
    now = current_time()
    turn = Turn(calendar, now)
    messages = list(session.messages)
    messages.append({"role": "user", "content": message})
    system = system_prompt(now)

    try:
        reply = ""
        for step in range(MAX_STEPS):
            last_step = step == MAX_STEPS - 1
            kwargs = {"tool_choice": {"type": "none"}} if last_step else {}
            resp = client.messages.create(model=MODEL, max_tokens=MAX_TOKENS, system=system,
                                          tools=TOOLS, messages=messages, **kwargs)
            messages.append({"role": "assistant", "content": resp.content})
            if resp.stop_reason != "tool_use":
                reply = "".join(b.text for b in resp.content if b.type == "text").strip()
                break
            results = []
            for block in resp.content:
                if block.type != "tool_use":
                    continue
                content, is_error = turn.run_tool(block.name, block.input or {})
                log.info("step %d %s(%s) error=%s", step, block.name,
                         json.dumps(block.input, ensure_ascii=False)[:200], is_error)
                results.append({"type": "tool_result", "tool_use_id": block.id,
                                "content": content, "is_error": is_error})
            messages.append({"role": "user", "content": results})
    except Exception:
        log.exception("agent turn failed")
        return {"reply": "Sorry, I ran into a problem planning that. Please try again.",
                "proposed_changes": [], "status": "error"}

    changes = list(turn.proposals.values())
    if not reply:
        reply = ("Here is my suggested plan. Review the changes and press Apply."
                 if changes else "Sorry, I couldn't come up with a plan. Could you rephrase?")

    session.messages = messages
    if changes:  # a turn without proposals (e.g. a question) keeps the previous pending set
        session.proposals = turn.proposals
    return {"reply": reply, "proposed_changes": changes,
            "status": "needs_confirmation" if changes else "done"}
