# API CONTRACT — DRAFT v0.1

> **Status: DRAFT, proposed by backend (Topi).** No CONTRACT.md existed in the repo when
> the backend skeleton was started, so this is the version `backend/app/models.py` mirrors.
> Changes need sign-off from UI (Marius, Eetu) and agent (Tom). After any change here,
> update `backend/app/models.py` to match one to one.

Base URL: the deployed Render service (see README). All bodies are JSON (`Content-Type: application/json`).

## Conventions

- **Datetimes**: ISO 8601 **with offset**, e.g. `2026-11-09T09:00:00+02:00`.
  Default timezone is `Europe/Helsinki`. The server always returns offset datetimes in that zone.
  For query parameters, a datetime with no offset is read as Europe/Helsinki time.
  (Watch out: a `+` in a query string must be URL-encoded as `%2B`. The server also accepts a raw `+` that arrives as a space.)
- **IDs** are opaque strings. Never parse them.
- **Recurring events**: each instance is its own event with its own `id`. `recurring_event_id`
  is set when the instance belongs to a series. Moving or deleting an instance affects **only that instance**.

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
| 422  | `validation_error`  | Body or query failed schema validation. `details.errors` lists the problems |
| 502  | `calendar_error`    | Google Calendar call failed                        |
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
  "recurring_event_id": null
}
```
- `location`, `description`, `recurring_event_id`: string or `null` (always present).
- `attendees`: list of email strings, possibly empty.
- All-day events: `all_day: true`. `start` is local midnight of the first day and `end` is local midnight after the last day (exclusive).

### ProposedChange
A change the agent suggests. Nothing touches the calendar until it is sent to `/apply`.
```json
{
  "id": "chg_1a2b3c",
  "action": "move",
  "event_id": "evt_8f2a",
  "title": "1:1 with Tom",
  "start": "2026-11-10T14:00:00+02:00",
  "end": "2026-11-10T14:30:00+02:00",
  "original_start": "2026-11-09T10:00:00+02:00",
  "original_end": "2026-11-09T10:30:00+02:00",
  "summary": "Move \"1:1 with Tom\" from Mon 10:00 to Tue 14:00"
}
```
| `action` | `event_id` | `start`/`end`   | `original_start`/`original_end` |
|----------|------------|-----------------|---------------------------------|
| `move`   | required   | new time, required | old time, required           |
| `create` | `null`     | required        | `null`                          |
| `delete` | required   | `null`          | old time, required              |

All keys are always present. A key that does not apply is `null`.

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
  "proposed_changes": [ ProposedChange, ... ]
}
```
`proposed_changes` lists only the changes proposed in **this** turn, and may be empty.
Every proposed change stays in the session and can be applied later by `id`.

### POST /apply
Request:
```json
{ "session_id": "ses_4b1c...", "change_ids": ["chg_1a2b3c", "chg_9d8e7f"] }
```
`change_ids`: at least one item. Each change runs **independently**, in the given order.
A failing change does not stop the others.

`200`, even when some or all changes fail:
```json
{
  "session_id": "ses_4b1c...",
  "results": [
    { "change_id": "chg_1a2b3c", "status": "applied", "event": Event, "error": null },
    { "change_id": "chg_9d8e7f", "status": "failed", "event": null,
      "error": { "code": "not_found", "message": "Event no longer exists", "details": {} } }
  ]
}
```
- `status`: `"applied"` or `"failed"`.
- `event`: the resulting event for `move` or `create`, and the deleted event for `delete`. It is `null` on failure.
- Per-change error codes: `change_not_found`, `already_applied`, `not_found` (the event is gone), `calendar_error`.
- An unknown `session_id` makes the whole request fail with `404 session_not_found`.
