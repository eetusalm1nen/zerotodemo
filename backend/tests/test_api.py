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
                                     "attendees", "recurring_event_id"}
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


def test_chat_move_then_apply(client):
    r = client.post("/chat", json={"message": "Move my 1:1 with Tom"})
    assert r.status_code == 200, r.text
    chat = ChatResponse.model_validate(r.json())
    if not chat.proposed_changes:  # 1:1 already in the past this week -> fine, try standup
        r = client.post("/chat", json={"session_id": chat.session_id, "message": "move daily standup"})
        chat = ChatResponse.model_validate(r.json())
    assert chat.proposed_changes, chat.reply
    change = chat.proposed_changes[0]
    assert change.action == "move"

    r = client.post("/apply", json={"session_id": chat.session_id, "change_ids": [change.id, "chg_missing", change.id]})
    assert r.status_code == 200
    res = ApplyResponse.model_validate(r.json()).results
    assert [x.status for x in res] == ["applied", "failed", "failed"]
    assert res[0].event.start == change.start
    assert res[1].error.code == "change_not_found"
    assert res[2].error.code == "already_applied"


def test_apply_reports_missing_event(client):
    r = client.post("/chat", json={"message": "cancel the daily standup"})
    chat = ChatResponse.model_validate(r.json())
    if not chat.proposed_changes:
        return  # all standups this week already past
    cid = chat.proposed_changes[0].id
    from app.calendar import get_calendar

    get_calendar().delete_event(chat.proposed_changes[0].event_id)
    r = client.post("/apply", json={"session_id": chat.session_id, "change_ids": [cid]})
    res = r.json()["results"][0]
    assert res["status"] == "failed" and res["error"]["code"] == "not_found"


def test_chat_create_and_free(client):
    r = client.post("/chat", json={"message": "Schedule a 1 hour meeting with Anna"})
    chat = ChatResponse.model_validate(r.json())
    assert chat.proposed_changes and chat.proposed_changes[0].action == "create"
    r = client.post("/chat", json={"session_id": chat.session_id, "message": "When am I free?"})
    assert r.status_code == 200 and r.json()["session_id"] == chat.session_id


def test_cors_lovable(client):
    r = client.options("/events", headers={"Origin": "https://my-app.lovable.app", "Access-Control-Request-Method": "GET"})
    assert r.headers.get("access-control-allow-origin") == "https://my-app.lovable.app"
    r = client.options("/events", headers={"Origin": "https://evil.example.com", "Access-Control-Request-Method": "GET"})
    assert "access-control-allow-origin" not in r.headers
