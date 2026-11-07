"""FastAPI app. Endpoints and shapes follow CONTRACT.md exactly."""

from __future__ import annotations

import logging
from datetime import timedelta

from fastapi import FastAPI, Query
from fastapi.middleware.cors import CORSMiddleware

from .agent_adapter import run_turn
from .calendar import get_calendar
from .config import VERSION, settings
from .errors import ApiError, install_error_handlers
from .models import (
    AppliedChange,
    ApplyRequest,
    ApplyResponse,
    ChatRequest,
    ChatResponse,
    ErrorResponse,
    Event,
    EventsResponse,
    HealthResponse,
    ProposedChange,
)
from .sessions import sessions
from .timeutil import now, parse_query_dt, start_of_day
from .tools import apply_change, undo_change

logging.basicConfig(level=logging.INFO)
log = logging.getLogger("calendar-api")

MAX_RANGE = timedelta(days=62)

app = FastAPI(
    title="Calendar Handler API",
    version=VERSION,
    responses={
        400: {"model": ErrorResponse},
        404: {"model": ErrorResponse},
        422: {"model": ErrorResponse},
        409: {"model": ErrorResponse},
        500: {"model": ErrorResponse},
        502: {"model": ErrorResponse},
        503: {"model": ErrorResponse},
    },
)
app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origins,
    allow_origin_regex=settings.cors_origin_regex,
    allow_credentials=False,
    allow_methods=["GET", "POST", "OPTIONS"],
    allow_headers=["*"],
)
install_error_handlers(app)


@app.get("/health", response_model=HealthResponse)
def health() -> HealthResponse:
    return HealthResponse(mock=settings.mock, calendar="mock" if settings.calendar == "mock" else "google",
                          version=VERSION)


@app.get("/events", response_model=EventsResponse)
def list_events(
    start: str | None = Query(None, description="ISO 8601; default: today 00:00"),
    end: str | None = Query(None, description="ISO 8601; default: start + 7 days"),
) -> EventsResponse:
    s = parse_query_dt(start, "start") or start_of_day(now())
    e = parse_query_dt(end, "end") or s + timedelta(days=7)
    if e <= s:
        raise ApiError(400, "bad_request", "'end' must be after 'start'")
    if e - s > MAX_RANGE:
        raise ApiError(400, "bad_request", "Range can be at most 62 days")
    events = get_calendar().list_events(s, e)
    return EventsResponse(timezone=settings.timezone, start=s, end=e, events=events)


@app.post("/chat", response_model=ChatResponse)
def chat(req: ChatRequest) -> ChatResponse:
    session = sessions.get_or_create(req.session_id)
    with session.lock:
        reply, changes = run_turn(req.message, session, get_calendar())
        if changes:
            # A new set of proposals replaces the previous pending set (as the agent's prompt promises).
            session.proposed = {c.id: c for c in changes}
    return ChatResponse(
        session_id=session.id,
        reply=reply,
        status="needs_confirmation" if changes else "ok",
        proposed_changes=changes,
    )


def _fail(code: str, message: str, change_id: str | None, **details) -> ApiError:
    status = {"change_not_found": 404, "event_locked": 409, "already_applied": 409,
              "not_found": 409, "bad_request": 400}.get(code, 502)
    return ApiError(status, code, message, {"failed_change_id": change_id, **details})


@app.post("/apply", response_model=ApplyResponse)
def apply(req: ApplyRequest) -> ApplyResponse:
    """All or nothing: validate every change first, then apply in order; on failure, roll back."""
    session = sessions.get(req.session_id)
    calendar = get_calendar()
    if len(set(req.change_ids)) != len(req.change_ids):
        raise ApiError(400, "bad_request", "change_ids contains duplicates")

    with session.lock:
        # 1) Validate everything before touching the calendar.
        changes = []
        for cid in req.change_ids:
            change = session.proposed.get(cid)
            if change is None:
                raise _fail("change_not_found", f"Change {cid} not found in this session", cid, rolled_back=False)
            if cid in session.applied:
                raise _fail("already_applied", f"Change {cid} was already applied", cid, rolled_back=False)
            if change.event_id is not None:
                try:
                    ev = calendar.get_event(change.event_id)
                except ApiError as exc:
                    raise _fail(exc.code, exc.message, cid, rolled_back=False) from None
                if not ev.movable:
                    raise _fail("event_locked", f'"{ev.title}" is locked and cannot be changed', cid,
                                rolled_back=False)
            changes.append(change)

        # 2) Apply in order; on any failure, undo what was done (reverse order).
        done: list[tuple[ProposedChange, Event]] = []
        for change in changes:
            try:
                done.append((change, apply_change(calendar, change)))
            except Exception as exc:  # noqa: BLE001
                log.exception("apply_change failed for %s; rolling back %d change(s)", change.id, len(done))
                rollback_errors = []
                for prev, result in reversed(done):
                    try:
                        undo_change(calendar, prev, result)
                    except Exception as undo_exc:  # noqa: BLE001
                        log.exception("rollback failed for %s", prev.id)
                        rollback_errors.append({"change_id": prev.id, "message": str(undo_exc)})
                code = exc.code if isinstance(exc, ApiError) else "calendar_error"
                message = exc.message if isinstance(exc, ApiError) else (str(exc) or exc.__class__.__name__)
                raise _fail(code, message, change.id, rolled_back=bool(done) and not rollback_errors,
                            rollback_errors=rollback_errors) from None

        session.applied.update(c.id for c in changes)
    return ApplyResponse(
        session_id=session.id,
        applied=[AppliedChange(change_id=c.id, type=c.type, event=e) for c, e in done],
    )
