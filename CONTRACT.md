# API CONTRACT v0

> Aligned with the UI's CONTRACT v0 (Eetu, Marius). `backend/app/models.py` mirrors this file one to one;
> change both in the same commit. Changes need sign-off from UI (Marius, Eetu) and agent (Tom).
> Defined by the backend, not by the UI's v0 (UI please confirm): the `/apply` response and
> failure shape, `status: "ok"`, and the `movable` field on events.
>
> Part 1 (Endpoints) is what the UI uses. Part 2 (Agent) is internal: how Tom's agent
> (`backend/agent/agent.py`) talks to the backend. The UI never calls it directly.

Base URL: the deployed Render service (see README). All bodies are JSON (`Content-Type: application/json`).

## Conventions

- **Datetimes**: ISO 8601 **with offset**, e.g. `2026-11-09T09:00:00+02:00`.
  Default timezone is `Europe/Helsinki`. The server always returns offset datetimes in that zone.
  For query parameters, a datetime with no offset is read as Europe/Helsinki time.
  (Watch out: a `+` in a query string must be URL-encoded as `%2B`. The server also accepts a raw `+` that arrives as a space.)
- **IDs** are opaque strings. Never parse them.
- **Recurring events**: each instance is its own event with its own `id`. `recurring_event_id`
  is set when the instance belongs to a series. Moving or deleting an instance affects **only that instance**.

## Rules

1. **Times** are ISO 8601 with a timezone offset (see Conventions).
2. **IDs are unique** and created by the server. That includes proposal ids and the ids of new events; the LLM never makes them up.
3. **Locked events are never changed.** An event with `movable: false` is never proposed for a move or delete, and `/apply` refuses one with `event_locked`.
4. **Nothing changes without the user's approval.** `/chat` only *proposes*. The calendar changes only through `/apply`.
5. **Approving several changes is all or nothing.** If one change fails, the changes already made are rolled back and nothing stays applied.

## Error format (every non-2xx response)

```json
{
  "error": {
    "code": "validation_error",
    "message": "Human-readable explanation",
    "details": {}
  }
}
```

| HTTP | `code`              | When                                              |
|------|---------------------|---------------------------------------------------|
| 400  | `bad_request`       | Request is well-formed JSON but semantically wrong (e.g. `end` before `start`) |
| 404  | `not_found`         | Unknown route or resource                          |
| 404  | `session_not_found` | `session_id` unknown (for example after a server restart) |
| 404  | `change_not_found`  | `/apply`: a change id is not in this session |
| 409  | `already_applied`   | `/apply`: a change was already applied |
| 409  | `event_locked`      | `/apply`: the event is locked (`movable: false`) |
| 409  | `not_found`         | `/apply`: the event no longer exists |
| 422  | `validation_error`  | Body or query failed schema validation. `details.errors` lists the problems |
| 502  | `calendar_error`    | Google Calendar call failed (in `/apply`: after rollback) |
| 502  | `agent_error`       | `/chat`: the AI agent failed (e.g. Claude API down). `message` is safe to show to the user |
| 503  | `agent_unavailable` | Chat agent not configured                          |
| 500  | `internal_error`    | Anything else                                      |

`details` is always an object. It may be empty.

## Objects

### Event
```json
{
  "id": "evt_8f2a",
  "title": "1:1 with Tom",
  "start": "2026-11-09T10:00:00+02:00",
  "end": "2026-11-09T10:30:00+02:00",
  "all_day": false,
  "location": "Zoom",
  "description": null,
  "attendees": ["tom@example.com"],
  "recurring_event_id": null,
  "movable": true
}
```
- `movable`: `false` for a locked event, which the assistant never changes.
- `location`, `description`, `recurring_event_id`: string or `null` (always present).
- `attendees`: list of email strings, possibly empty.
- All-day events: `all_day: true`. `start` is local midnight of the first day and `end` is local midnight after the last day (exclusive).

### ProposedChange
A change the agent suggests. Nothing touches the calendar until it is sent to `/apply`.
```json
{
  "id": "chg_1a2b3c",
  "type": "move",
  "event_id": "evt_8f2a",
  "title": "1:1 with Tom",
  "old_start": "2026-11-09T10:00:00+02:00",
  "old_end": "2026-11-09T10:30:00+02:00",
  "new_start": "2026-11-10T14:00:00+02:00",
  "new_end": "2026-11-10T14:30:00+02:00",
  "reason": "You asked for tomorrow afternoon; 14:00 is the first free slot."
}
```
| `type`   | `event_id` | `old_start`/`old_end` | `new_start`/`new_end` |
|----------|------------|-----------------------|-----------------------|
| `move`   | required   | required              | required              |
| `create` | `null`     | `null`                | required              |
| `delete` | required   | required              | `null`                |

All keys are always present. A key that does not apply is `null`. `reason` is a short explanation for the UI.

### Slot (used by the agent tool `find_free_slots`; listed here for reference)
```json
{ "start": "2026-11-10T13:00:00+02:00", "end": "2026-11-10T15:30:00+02:00" }
```

## Endpoints

### GET /health
`200`
```json
{ "status": "ok", "mock": true, "calendar": "mock", "version": "0.1.0" }
```
`calendar` is `"mock"` or `"google"`.

### GET /events?start=...&end=...
Both parameters are optional. The default `start` is today 00:00 (Europe/Helsinki), and the default `end` is `start` + 7 days.
`end` must be after `start`, and the range can be at most 62 days.

`200`
```json
{
  "timezone": "Europe/Helsinki",
  "start": "2026-11-09T00:00:00+02:00",
  "end": "2026-11-16T00:00:00+02:00",
  "events": [ Event, ... ]
}
```
Events are sorted by `start`. The list includes events that overlap the range.

### POST /chat
Request:
```json
{ "session_id": null, "message": "Move my 1:1 with Tom to tomorrow afternoon" }
```
- `session_id`: omit or send `null` to start a new session. Send back the returned id to continue the conversation.
- `message`: non-empty string.

`200`
```json
{
  "session_id": "ses_4b1c...",
  "reply": "You're free Tuesday 13:00–15:30. I suggest 14:00–14:30.",
  "status": "needs_confirmation",
  "proposed_changes": [ ProposedChange, ... ]
}
```
- `status`: `"needs_confirmation"` when `proposed_changes` is non-empty (the changes wait for approval), otherwise `"ok"`.
- `proposed_changes` lists the changes proposed in **this** turn, and may be empty.
- **A new set of proposals replaces the previous pending set.** When a turn proposes changes,
  earlier unapplied proposals in the session are discarded, and `/apply` with their ids returns
  `change_not_found`. A turn with no proposals (for example a question) keeps the pending set.
  The UI should show only the latest set.
- The call can take 5–20 seconds with the real agent. Show a loading state.

### POST /apply
Request:
```json
{ "session_id": "ses_4b1c...", "change_ids": ["chg_1a2b3c", "chg_9d8e7f"] }
```
`change_ids`: at least one item and no duplicates. The changes are applied in the given order, **all or nothing**:
1. Every change is checked first: it exists, it is not applied yet, its event exists, and the event is not locked.
   If any check fails, nothing is changed.
2. The changes are applied one by one. If one fails, the changes already made are undone in reverse order.

`200`: every change was applied.
```json
{
  "session_id": "ses_4b1c...",
  "status": "applied",
  "applied": [
    { "change_id": "chg_1a2b3c", "type": "move",   "event": Event },
    { "change_id": "chg_9d8e7f", "type": "delete", "event": Event }
  ]
}
```
`event` is the event after the change. For `delete`, it is the event as it was before deletion.

On failure, the response uses the normal error format, and nothing is applied:
```json
{
  "error": {
    "code": "event_locked",
    "message": "\"Customer demo: Acme Oy\" is locked and cannot be changed",
    "details": { "failed_change_id": "chg_9d8e7f", "rolled_back": false, "rollback_errors": [] }
  }
}
```
- `failed_change_id`: the change that failed.
- `rolled_back`: `true` when earlier changes in the batch had been made and were successfully undone.
  `false` when the request failed during the checks, before anything was changed.
- `rollback_errors`: present only after a failure while applying. It lists any undo that failed, so the calendar may need a manual fix (this is rare).
- A rolled-back delete is restored with the same details but a **new event id** (Google Calendar cannot restore an id).
- After a failure the changes are not marked applied, so the same request can be retried.
- An unknown `session_id` returns `404 session_not_found`.

---

# Part 2: Agent (internal)

How the AI agent plugs into the backend. Owner of the agent: Tom. Owner of the calendar layer: Topi.

## Flow of one `/chat` turn

```
POST /chat ──► app/agent_adapter.py ──► agent.run_chat(session, message, calendar)
                                             │  loop: Claude ⇄ tools (max AGENT_MAX_STEPS)
                                             ▼
               calendar = AgentCalendar ──► CalendarBackend (mock or Google)
```
1. The backend calls `run_chat(session, message, calendar)` in `backend/agent/agent.py`.
2. The agent asks Claude, which calls the tools below. Read tools go to the calendar; propose tools only record proposals.
3. `run_chat` returns `{"reply", "proposed_changes", "status"}`. The backend validates every change against the `ProposedChange` model and stores them in the session.
4. The calendar changes only later, through `POST /apply` (validate everything, apply in order, roll back on failure).

Status mapping from the agent to the API: `needs_confirmation` → `needs_confirmation`, `done` → `ok`,
`error` → HTTP 502 `agent_error`.

## Agent tools (what Claude can call)

| Tool | Input | Output | Changes the calendar? |
|---|---|---|---|
| `list_events` | `start`, `end` | `{"events": [AgentEvent]}` | no |
| `find_free_slots` | `duration_minutes`, `range_start`, `range_end`, `earliest_hour` (8), `latest_hour` (18) | `{"slots": [{"start", "end"}], "note"?}` | no |
| `propose_move` | `event_id`, `new_start`, `new_end`, `reason` | `{"recorded": ProposedChange}` | no, proposal only |
| `propose_create` | `title`, `start`, `end`, `reason` | `{"recorded": ProposedChange}` | no, proposal only |
| `propose_delete` | `event_id`, `reason` | `{"recorded": ProposedChange}` | no, proposal only |

A rejected call (unknown id, locked event, overlap, time in the past, missing reason) returns an
error message to Claude so it can correct itself. The exact schemas are `TOOLS` in `agent.py`.

**AgentEvent** (what `list_events` gives Claude):
```json
{ "id": "evt_8f2a", "title": "1:1 with Tom", "start": "2026-11-09T10:00:00+02:00",
  "end": "2026-11-09T10:30:00+02:00", "movable": true, "category": "meeting",
  "all_day": false, "location": "Zoom" }
```
`category` is `meeting`, `focus`, `personal` or `other`. The backend derives it from the title and
attendees (Google Calendar has no such field).

## Calendar interface the agent needs (provided by the backend)

```python
class Calendar(Protocol):
    def list_events(self, start: str, end: str) -> list[dict]: ...            # AgentEvent dicts
    def find_free_slots(self, duration_minutes: int, range_start: str, range_end: str,
                        earliest_hour: int = 8, latest_hour: int = 18) -> list[dict]: ...
```
All times are ISO 8601 strings with an offset. `AgentCalendar` in `app/agent_adapter.py` implements
this on top of the backend's calendar (mock or Google). `find_free_slots` is deterministic code:
it merges busy times, skips weekends and the past, and ignores all-day events.

## Rules the agent follows (enforced in code, not only in the prompt)

- It never writes to the calendar; it only proposes.
- It never proposes changes to events with `movable: false`.
- Proposals must not overlap existing events or each other, must not be in the past, and must have a short `reason`.
- Change ids are generated in code, never by the model.
- A failed turn does not change the session history.

## Configuration

| Variable | Meaning | Default |
|---|---|---|
| `AGENT` | `real` = Tom's agent, `mock` = keyword bot (no API key needed) | follows `MOCK` |
| `ANTHROPIC_API_KEY` | Claude API key. Set it in Render's environment, never in git | none |
| `AGENT_MODEL` | Claude model | `claude-sonnet-5-5` |
| `AGENT_MAX_STEPS` | max tool-loop steps per turn | `10` |
| `DEMO_NOW` | fixed "now" for rehearsals, e.g. `2026-11-10T08:30:00+02:00` | real time |

## Local development (Tom)

From `backend/agent/`: `python cli.py` chats with the agent against `fake_calendar.py`.
To use the full backend instead, from `backend/`:
`AGENT=real CALENDAR=mock uvicorn app.main:app --port 8000`, then `POST /chat`.
