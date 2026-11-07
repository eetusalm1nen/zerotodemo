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
    # Locked events (movable=false) are never moved or deleted.
    movable: bool = True


ChangeType = Literal["move", "create", "delete"]


class ProposedChange(_Strict):
    """Field names follow the UI's CONTRACT v0."""

    id: str
    type: ChangeType
    event_id: str | None = None
    title: str
    old_start: AwareDatetime | None = None
    old_end: AwareDatetime | None = None
    new_start: AwareDatetime | None = None
    new_end: AwareDatetime | None = None
    reason: str

    @model_validator(mode="after")
    def _check_shape(self) -> ProposedChange:
        t = self.type
        has_event = t in ("move", "delete")
        has_old = t in ("move", "delete")
        has_new = t in ("move", "create")

        def both(a: object, b: object) -> bool:
            return a is not None and b is not None

        def neither(a: object, b: object) -> bool:
            return a is None and b is None

        if has_event != (self.event_id is not None):
            raise ValueError(f"{t}: event_id must be {'set' if has_event else 'null'}")
        if has_old and not both(self.old_start, self.old_end):
            raise ValueError(f"{t}: old_start and old_end are required")
        if not has_old and not neither(self.old_start, self.old_end):
            raise ValueError(f"{t}: old_start and old_end must be null")
        if has_new and not both(self.new_start, self.new_end):
            raise ValueError(f"{t}: new_start and new_end are required")
        if not has_new and not neither(self.new_start, self.new_end):
            raise ValueError(f"{t}: new_start and new_end must be null")
        if self.new_start and self.new_end and self.new_end <= self.new_start:
            raise ValueError("new_end must be after new_start")
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
    # "needs_confirmation" when proposed_changes is non-empty, otherwise "ok".
    status: Literal["needs_confirmation", "ok"]
    proposed_changes: list[ProposedChange]


class ApplyRequest(_Strict):
    session_id: str
    change_ids: list[str] = Field(min_length=1)


class AppliedChange(_Strict):
    change_id: str
    type: ChangeType
    # The event after the change; for delete, the event as it was before deletion.
    event: Event


class ApplyResponse(_Strict):
    """Returned only when every change succeeded (all or nothing)."""

    session_id: str
    status: Literal["applied"] = "applied"
    applied: list[AppliedChange]
