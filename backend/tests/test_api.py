from app.models import (
    ApplyResponse,
    ChatResponse,
    ErrorResponse,
    EventsResponse,
    HealthResponse,
)


def _offset(s: str) -> bool:
    return s[-6] in "+-" and s[-3] == ":"


def test_health(client):
    r = client.get("/health")
    assert r.status_code == 200
    HealthResponse.model_validate(r.json())
    assert r.json()["mock"] is True


def test_events_default_range(client):
    r = client.get("/events")
    assert r.status_code == 200
    body = EventsResponse.model_validate(r.json())
    assert body.timezone == "Europe/Helsinki"
    assert len(body.events) > 20
    raw = r.json()
    assert all(_offset(e["start"]) and _offset(e["end"]) for e in raw["events"])
    # every key present, even nulls
    assert set(raw["events"][0]) == {"id", "title", "start", "end", "all_day", "location", "description",
                                     "attendees", "recurring_event_id", "movable"}
    assert any(not e.movable for e in body.events)
    standups = [e for e in body.events if e.recurring_event_id == "rec_standup"]
    assert len(standups) >= 5 and len({e.id for e in standups}) == len(standups)


def test_events_query_with_unencoded_plus(client):
    r = client.get("/events?start=2026-11-09T00:00:00+02:00&end=2026-11-10T00:00:00+02:00")
    assert r.status_code == 200
    assert r.json()["start"] == "2026-11-09T00:00:00+02:00"


def test_events_errors(client):
    r = client.get("/events", params={"start": "nope"})
    assert r.status_code == 422
    assert ErrorResponse.model_validate(r.json()).error.code == "validation_error"
    r = client.get("/events", params={"start": "2026-11-10T00:00:00+02:00", "end": "2026-11-09T00:00:00+02:00"})
    assert r.status_code == 400 and r.json()["error"]["code"] == "bad_request"


def test_unknown_route_uses_error_format(client):
    r = client.get("/nope")
    assert r.status_code == 404
    assert ErrorResponse.model_validate(r.json()).error.code == "not_found"


def test_chat_validation_error(client):
    r = client.post("/chat", json={"message": ""})
    assert r.status_code == 422
    assert r.json()["error"]["code"] == "validation_error"
    assert r.json()["error"]["details"]["errors"]


def test_chat_unknown_session(client):
    r = client.post("/chat", json={"session_id": "ses_bogus", "message": "hi"})
    assert r.status_code == 404 and r.json()["error"]["code"] == "session_not_found"


CHANGE_KEYS = {"id", "type", "event_id", "title", "old_start", "old_end", "new_start", "new_end", "reason"}


def _propose(client, message, session_id=None):
    r = client.post("/chat", json={"session_id": session_id, "message": message})
    assert r.status_code == 200, r.text
    return r.json(), ChatResponse.model_validate(r.json())


def test_chat_move_shape_and_status(client):
    raw, chat = _propose(client, "Move my 1:1 with Tom")
    assert chat.status == "needs_confirmation"
    assert set(raw["proposed_changes"][0]) == CHANGE_KEYS
    c = chat.proposed_changes[0]
    assert c.type == "move" and c.event_id and c.old_start and c.new_start and c.reason


def test_chat_no_changes_status_ok(client):
    _, chat = _propose(client, "When am I free?")
    assert chat.status == "ok" and chat.proposed_changes == []


def test_create_has_null_old_and_event_id(client):
    raw, chat = _propose(client, "Schedule a 1 hour meeting with Anna")
    c = raw["proposed_changes"][0]
    assert c["type"] == "create" and c["event_id"] is None and c["old_start"] is None and c["old_end"] is None


def test_delete_has_null_new(client):
    raw, _ = _propose(client, "cancel the dentist")
    c = raw["proposed_changes"][0]
    assert c["type"] == "delete" and c["new_start"] is None and c["new_end"] is None


def test_locked_event_is_not_proposed(client):
    _, chat = _propose(client, "Move the customer demo with Acme")
    assert chat.proposed_changes == [] and "locked" in chat.reply


def _batch():
    """A session with three pending changes (move, create, delete), built without chat."""
    from datetime import timedelta

    from app.calendar import get_calendar
    from app.sessions import sessions
    from app.timeutil import now
    from app.tools import AgentTools

    cal = get_calendar()
    s = sessions.create()
    t = AgentTools(cal, s)
    evs = {e.title: e for e in cal.list_events(now(), now() + timedelta(days=5))}
    tom, dentist = evs["1:1 with Tom"], evs["Dentist"]
    a = t.propose_move(tom.id, tom.start + timedelta(days=1), tom.end + timedelta(days=1))
    b = t.propose_create("Meeting with Anna", tom.start + timedelta(days=2), tom.end + timedelta(days=2))
    c = t.propose_delete(dentist.id)
    return s.id, [a, b, c]


def test_apply_all_succeed(client):
    sid, changes = _batch()
    ids = [c.id for c in changes]
    r = client.post("/apply", json={"session_id": sid, "change_ids": ids})
    assert r.status_code == 200, r.text
    body = ApplyResponse.model_validate(r.json())
    assert body.status == "applied" and [x.change_id for x in body.applied] == ids
    assert body.applied[0].event.start == changes[0].new_start
    # applying again is rejected
    r = client.post("/apply", json={"session_id": sid, "change_ids": ids[:1]})
    assert r.status_code == 409 and r.json()["error"]["code"] == "already_applied"


def test_new_proposals_replace_pending_ones(client):
    _, first = _propose(client, "Move my 1:1 with Tom")
    _, second = _propose(client, "cancel the dentist", first.session_id)
    r = client.post("/apply", json={"session_id": first.session_id, "change_ids": [first.proposed_changes[0].id]})
    assert r.status_code == 404 and r.json()["error"]["code"] == "change_not_found"
    r = client.post("/apply", json={"session_id": first.session_id, "change_ids": [second.proposed_changes[0].id]})
    assert r.status_code == 200
    # a turn without proposals keeps the pending set
    _, third = _propose(client, "Move my 1:1 with Tom", first.session_id)
    _propose(client, "When am I free?", first.session_id)
    r = client.post("/apply", json={"session_id": first.session_id, "change_ids": [third.proposed_changes[0].id]})
    assert r.status_code == 200


def test_apply_unknown_change_touches_nothing(client):
    _, a = _propose(client, "Move my 1:1 with Tom")
    before = client.get("/events").json()
    r = client.post("/apply", json={"session_id": a.session_id, "change_ids": [a.proposed_changes[0].id, "chg_nope"]})
    assert r.status_code == 404
    err = ErrorResponse.model_validate(r.json()).error
    assert err.code == "change_not_found" and err.details["failed_change_id"] == "chg_nope"
    assert client.get("/events").json() == before


def test_apply_rolls_back_on_midway_failure(client, monkeypatch):
    sid, changes = _batch()
    before = client.get("/events").json()

    from app import main

    real = main.apply_change

    def flaky(calendar, change):
        if change.type == "delete":
            raise RuntimeError("Google exploded")
        return real(calendar, change)

    monkeypatch.setattr(main, "apply_change", flaky)
    ids = [c.id for c in changes]
    r = client.post("/apply", json={"session_id": sid, "change_ids": ids})
    assert r.status_code == 502
    err = r.json()["error"]
    assert err["code"] == "calendar_error" and err["details"]["failed_change_id"] == ids[2]
    assert err["details"]["rolled_back"] is True
    assert client.get("/events").json() == before
    # nothing marked applied, so a retry works once the problem is gone
    monkeypatch.setattr(main, "apply_change", real)
    assert client.post("/apply", json={"session_id": sid, "change_ids": ids}).status_code == 200


def test_apply_duplicate_ids(client):
    _, a = _propose(client, "Move my 1:1 with Tom")
    cid = a.proposed_changes[0].id
    r = client.post("/apply", json={"session_id": a.session_id, "change_ids": [cid, cid]})
    assert r.status_code == 400


def test_apply_unknown_session(client):
    r = client.post("/apply", json={"session_id": "ses_nope", "change_ids": ["chg_x"]})
    assert r.status_code == 404 and r.json()["error"]["code"] == "session_not_found"


def test_cors_lovable(client):
    r = client.options("/events", headers={"Origin": "https://my-app.lovable.app", "Access-Control-Request-Method": "GET"})
    assert r.headers.get("access-control-allow-origin") == "https://my-app.lovable.app"
    r = client.options("/events", headers={"Origin": "https://evil.example.com", "Access-Control-Request-Method": "GET"})
    assert "access-control-allow-origin" not in r.headers
