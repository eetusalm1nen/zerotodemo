# API CONTRACT v0

> Aligned with the UI's CONTRACT v0 (Eetu, Marius). `backend/app/models.py` mirrors this file one to one;
> change both in the same commit. Changes need sign-off from UI (Marius, Eetu) and agent (Tom).
> Defined by the backend, not by the UI's v0 (UI please confirm): the `/apply` response and
> failure shape, `status: "ok"`, and the `movable` field on events.

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
`proposed_changes` lists only the changes proposed in **this** turn, and may be empty.
Every proposed change stays in the session and can be applied later by `id`.

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
