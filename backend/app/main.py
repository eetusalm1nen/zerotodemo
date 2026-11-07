"""FastAPI app. Endpoints and shapes follow CONTRACT.md exactly."""

from __future__ import annotations

import logging
from datetime import timedelta

from fastapi import FastAPI, Query
from fastapi.middleware.cors import CORSMiddleware

from .agent_adapter import get_agent
from .calendar import get_calendar
from .config import VERSION, settings
from .errors import ApiError, install_error_handlers
from .models import (
    ApplyRequest,
    ApplyResponse,
    ApplyResult,
    ChatRequest,
    ChatResponse,
    ErrorBody,
    ErrorResponse,
    EventsResponse,
    HealthResponse,
)
from .sessions import sessions
from .timeutil import now, parse_query_dt, start_of_day
from .tools import AgentTools, apply_change

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
    return HealthResponse(mock=settings.mock, calendar="mock" if settings.mock else "google", version=VERSION)


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
    agent = get_agent()
    with session.lock:
        tools = AgentTools(get_calendar(), session)
        reply = agent(req.message, session, tools)
    return ChatResponse(session_id=session.id, reply=reply, proposed_changes=tools.proposed_this_turn)


@app.post("/apply", response_model=ApplyResponse)
def apply(req: ApplyRequest) -> ApplyResponse:
    session = sessions.get(req.session_id)
    calendar = get_calendar()
    results: list[ApplyResult] = []
    with session.lock:
        for cid in req.change_ids:
            change = session.proposed.get(cid)
            if change is None:
                err = ErrorBody(code="change_not_found", message=f"Change {cid} not found in this session")
                results.append(ApplyResult(change_id=cid, status="failed", error=err))
                continue
            if cid in session.applied:
                err = ErrorBody(code="already_applied", message=f"Change {cid} was already applied")
                results.append(ApplyResult(change_id=cid, status="failed", error=err))
                continue
            try:
                event = apply_change(calendar, change)
            except ApiError as exc:
                results.append(ApplyResult(change_id=cid, status="failed", error=exc.body()))
            except Exception as exc:  # each change is independent; never let one kill the batch
                log.exception("apply_change failed for %s", cid)
                err = ErrorBody(code="calendar_error", message=str(exc) or exc.__class__.__name__)
                results.append(ApplyResult(change_id=cid, status="failed", error=err))
            else:
                session.applied.add(cid)
                results.append(ApplyResult(change_id=cid, status="applied", event=event))
    return ApplyResponse(session_id=session.id, results=results)
