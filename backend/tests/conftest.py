import os

os.environ["MOCK"] = "1"
os.environ["DEMO_NOW"] = "2026-11-09T08:00:00+02:00"  # a Monday morning

import pytest  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402

from app.calendar import get_calendar  # noqa: E402
from app.main import app  # noqa: E402
from app.sessions import sessions  # noqa: E402


@pytest.fixture()
def client():
    get_calendar().reset()
    sessions.clear()
    return TestClient(app)
