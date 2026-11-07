"""Pydantic models that mirror CONTRACT.md one to one.

If you change anything here, change CONTRACT.md in the same commit (and vice versa).
"""

from __future__ import annotations

from typing import Any, Literal

from pydantic import AwareDatetime, BaseModel, ConfigDict, Field, model_validator


class _Strict(BaseModel):
    # Reject unknown keys so contract drift fails loudly instead of silently.
    model_config = ConfigDict(extra="forbid")


# ---------------------------------------------------------------- errors


class ErrorBody(_Strict):
    code: str
    message: str
    details: dict[str, Any] = Field(default_factory=dict)


class ErrorResponse(_Strict):
    error: ErrorBody


# ---------------------------------------------------------------- core objects


class Event(_Strict):
    id: str
    title: str
    start: AwareDatetime
    end: AwareDatetime
    all_day: bool = False
    location: str | None = None
    description: str | None = None
    attendees: list[str] = Field(default_factory=list)
    recurring_event_id: str | None = None


ChangeAction = Literal["move", "create", "delete"]


class ProposedChange(_Strict):
    id: str
    action: ChangeAction
    event_id: str | None = None
    title: str
    start: AwareDatetime | None = None
    end: AwareDatetime | None = None
    original_start: AwareDatetime | None = None
    original_end: AwareDatetime | None = None
    summary: str

    @model_validator(mode="after")
    def _check_shape(self) -> ProposedChange:
        a = self.action
        need_event = a in ("move", "delete")
        need_new = a in ("move", "create")
        need_orig = a in ("move", "delete")

        def present(*vals: object) -> bool:
            return all(v is not None for v in vals)

        def absent(*vals: object) -> bool:
            return all(v is None for v in vals)

        if need_event != (self.event_id is not None):
            raise ValueError(f"{a}: event_id must be {'set' if need_event else 'null'}")
        if need_new and not present(self.start, self.end):
            raise ValueError(f"{a}: start and end are required")
        if not need_new and not absent(self.start, self.end):
            raise ValueError(f"{a}: start and end must be null")
        if need_orig and not present(self.original_start, self.original_end):
            raise ValueError(f"{a}: original_start and original_end are required")
        if not need_orig and not absent(self.original_start, self.original_end):
            raise ValueError(f"{a}: original_start and original_end must be null")
        if self.start and self.end and self.end <= self.start:
            raise ValueError("end must be after start")
        return self


class Slot(_Strict):
    start: AwareDatetime
    end: AwareDatetime


# ---------------------------------------------------------------- endpoints


class HealthResponse(_Strict):
    status: Literal["ok"] = "ok"
    mock: bool
    calendar: Literal["mock", "google"]
    version: str


class EventsResponse(_Strict):
    timezone: str
    start: AwareDatetime
    end: AwareDatetime
    events: list[Event]


class ChatRequest(_Strict):
    session_id: str | None = None
    message: str = Field(min_length=1)


class ChatResponse(_Strict):
    session_id: str
    reply: str
    proposed_changes: list[ProposedChange]


class ApplyRequest(_Strict):
    session_id: str
    change_ids: list[str] = Field(min_length=1)


class ApplyResult(_Strict):
    change_id: str
    status: Literal["applied", "failed"]
    event: Event | None = None
    error: ErrorBody | None = None


class ApplyResponse(_Strict):
    session_id: str
    results: list[ApplyResult]
