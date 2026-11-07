"""Google Calendar backend. This is task 2; it is a placeholder until then."""

from __future__ import annotations

from ..errors import ApiError


class GoogleCalendar:
    name = "google"

    @classmethod
    def from_settings(cls, settings):  # noqa: ANN001
        raise ApiError(503, "calendar_error", "Google Calendar backend is not implemented yet; run with MOCK=1")
