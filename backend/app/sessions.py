"""In-memory session store (good enough for the hackathon; lost on restart)."""

from __future__ import annotations

import threading
import uuid
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any

from .errors import ApiError
from .models import ProposedChange
from .timeutil import now


@dataclass
class Session:
    id: str
    created_at: datetime
    # Chat history in whatever shape the agent wants, e.g. Anthropic messages:
    # [{"role": "user", "content": "..."}, {"role": "assistant", "content": [...]}]
    history: list[dict[str, Any]] = field(default_factory=list)
    proposed: dict[str, ProposedChange] = field(default_factory=dict)
    applied: set[str] = field(default_factory=set)
    lock: threading.Lock = field(default_factory=threading.Lock, repr=False)

    def add_proposals(self, changes: list[ProposedChange]) -> None:
        for c in changes:
            self.proposed[c.id] = c


class SessionStore:
    def __init__(self) -> None:
        self._sessions: dict[str, Session] = {}
        self._lock = threading.Lock()

    def create(self) -> Session:
        s = Session(id="ses_" + uuid.uuid4().hex, created_at=now())
        with self._lock:
            self._sessions[s.id] = s
        return s

    def get(self, session_id: str) -> Session:
        with self._lock:
            s = self._sessions.get(session_id)
        if s is None:
            raise ApiError(404, "session_not_found", f"Session {session_id} not found", {"session_id": session_id})
        return s

    def get_or_create(self, session_id: str | None) -> Session:
        return self.create() if session_id is None else self.get(session_id)

    def clear(self) -> None:
        with self._lock:
            self._sessions.clear()


sessions = SessionStore()
