"""Tom's agent (backend/agent/agent.py) wired to our calendar, with a scripted fake Claude client."""

from datetime import timedelta
from types import SimpleNamespace as NS

import pytest

from app.agent_adapter import AgentCalendar, run_real_agent
from app.calendar import get_calendar
from app.errors import ApiError
from app.models import ChatResponse
from app.sessions import sessions
from app.timeutil import now


class FakeClient:
    """Plays back a list of responses; each is a list of content blocks."""

    def __init__(self, script):
        self.script = list(script)
        self.calls = []
        self.messages = self

    def create(self, **kw):
        self.calls.append(kw)
        if isinstance(self.script[0], Exception):
            raise self.script.pop(0)
        blocks = self.script.pop(0)
        stop = "tool_use" if any(b.type == "tool_use" for b in blocks) else "end_turn"
        return NS(content=blocks, stop_reason=stop)


def tool(name, **inp):
    return NS(type="tool_use", id=f"tu_{name}", name=name, input=inp)


def text(t):
    return NS(type="text", text=t)


def _tom():
    cal = get_calendar()
    return next(e for e in cal.list_events(now(), now() + timedelta(days=5)) if e.title == "1:1 with Tom")


def test_agent_calendar_shape(client):
    cal = AgentCalendar(get_calendar())
    t0 = now().isoformat()
    evs = cal.list_events(t0, (now() + timedelta(days=3)).isoformat())
    assert {"id", "title", "start", "end", "movable", "category"} <= set(evs[0])
    assert evs[0]["start"][-6] in "+-"
    slots = cal.find_free_slots(30, t0, (now() + timedelta(days=2)).isoformat())
    assert slots and set(slots[0]) == {"start", "end"}


def test_real_agent_move_then_apply(client):
    ev = _tom()
    from datetime import datetime

    free = AgentCalendar(get_calendar()).find_free_slots(
        30, (ev.start + timedelta(days=1)).isoformat(), (ev.start + timedelta(days=2)).isoformat())
    new_start = datetime.fromisoformat(free[0]["start"])
    script = [
        [tool("list_events", start=now().isoformat(), end=(now() + timedelta(days=7)).isoformat())],
        [tool("propose_move", event_id=ev.id, new_start=new_start.isoformat(),
              new_end=(new_start + timedelta(minutes=30)).isoformat(), reason="Freed up your Monday.")],
        [text("I moved your 1:1 with Tom. Review and press Apply.")],
    ]
    fake = FakeClient(script)
    s = sessions.create()
    reply, changes = run_real_agent("Move my 1:1 with Tom", s, get_calendar(), client=fake)
    assert reply.startswith("I moved") and len(changes) == 1
    c = changes[0]
    assert c.type == "move" and c.event_id == ev.id and c.old_start == ev.start and c.new_start == new_start
    ChatResponse(session_id=s.id, reply=reply, status="needs_confirmation", proposed_changes=changes)
    assert s.history and s.history[0] == {"role": "user", "content": "Move my 1:1 with Tom"}

    # same path as POST /chat: store, then apply through the API
    s.proposed = {c.id: c for c in changes}
    r = client.post("/apply", json={"session_id": s.id, "change_ids": [c.id]})
    assert r.status_code == 200, r.text
    assert r.json()["applied"][0]["event"]["start"] == new_start.isoformat()


def test_real_agent_refuses_locked_event(client):
    cal = get_calendar()
    locked = next(e for e in cal.list_events(now(), now() + timedelta(days=7)) if not e.movable and not e.all_day)
    later = locked.start + timedelta(days=1)
    fake = FakeClient([
        [tool("list_events", start=now().isoformat(), end=(now() + timedelta(days=7)).isoformat())],
        [tool("propose_move", event_id=locked.id, new_start=later.isoformat(),
              new_end=(later + (locked.end - locked.start)).isoformat(), reason="x")],
        [text("That meeting is fixed, so I left it.")],
    ])
    reply, changes = run_real_agent("move it", sessions.create(), cal, client=fake)
    assert changes == []
    results = [b for m in fake.calls[-1]["messages"] if m["role"] == "user" and isinstance(m["content"], list)
               for b in m["content"] if isinstance(b, dict) and b.get("tool_use_id") == "tu_propose_move"]
    assert results and results[0]["is_error"] and "movable=false" in results[0]["content"]


def test_real_agent_failure_is_error_response(client):
    s = sessions.create()
    with pytest.raises(ApiError) as e:
        run_real_agent("hi", s, get_calendar(), client=FakeClient([RuntimeError("API down")]))
    assert e.value.status == 502 and e.value.code == "agent_error"
    assert s.history == []  # a failed turn leaves no broken history
