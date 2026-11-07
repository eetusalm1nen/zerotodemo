from datetime import datetime
from zoneinfo import ZoneInfo

import pytest

from app.free_slots import find_free_slots, merge_intervals
from app.models import Event

TZ = ZoneInfo("Europe/Helsinki")


def dt(d, h, m=0):
    return datetime(2026, 11, d, h, m, tzinfo=TZ)


def ev(i, s, e, all_day=False):
    return Event(id=str(i), title=str(i), start=s, end=e, all_day=all_day)


def spans(slots):
    return [(s.start.strftime("%d %H:%M"), s.end.strftime("%H:%M")) for s in slots]


def test_merge_overlapping_and_touching():
    a = [(dt(9, 10), dt(9, 11)), (dt(9, 10, 30), dt(9, 12)), (dt(9, 12), dt(9, 13)), (dt(9, 14), dt(9, 15))]
    assert merge_intervals(a) == [(dt(9, 10), dt(9, 13)), (dt(9, 14), dt(9, 15))]


def test_basic_day_with_overlaps():
    events = [ev(1, dt(9, 10), dt(9, 11)), ev(2, dt(9, 10, 30), dt(9, 12)), ev(3, dt(9, 13), dt(9, 13, 15))]
    slots = find_free_slots(events, dt(9, 0), dt(10, 0), duration_minutes=30, tz=TZ, now=dt(1, 0))
    assert spans(slots) == [("09 09:00", "10:00"), ("09 12:00", "13:00"), ("09 13:15", "17:00")]


def test_duration_filter_and_hours():
    events = [ev(1, dt(9, 9, 20), dt(9, 16))]
    slots = find_free_slots(events, dt(9, 0), dt(10, 0), duration_minutes=30, earliest_hour=9, latest_hour=17,
                            tz=TZ, now=dt(1, 0))
    assert spans(slots) == [("09 16:00", "17:00")]


def test_skips_past_and_rounds_now():
    slots = find_free_slots([], dt(9, 0), dt(10, 0), tz=TZ, now=dt(9, 14, 7))
    assert spans(slots) == [("09 14:15", "17:00")]


def test_skips_weekends_and_all_day_does_not_block():
    # 2026-11-13 is Friday, 14-15 weekend
    events = [ev("x", dt(13, 0), dt(14, 0), all_day=True)]
    slots = find_free_slots(events, dt(13, 0), dt(16, 0), tz=TZ, now=dt(1, 0))
    assert spans(slots) == [("13 09:00", "17:00")]
    slots = find_free_slots([], dt(13, 0), dt(16, 0), tz=TZ, now=dt(1, 0), include_weekends=True)
    assert len(slots) == 3


def test_event_spanning_window_edges():
    events = [ev(1, dt(9, 7), dt(9, 9, 30)), ev(2, dt(9, 16, 45), dt(9, 20))]
    slots = find_free_slots(events, dt(9, 0), dt(10, 0), tz=TZ, now=dt(1, 0))
    assert spans(slots) == [("09 09:30", "16:45")]


def test_invalid_hours():
    with pytest.raises(ValueError):
        find_free_slots([], dt(9, 0), dt(10, 0), earliest_hour=18, latest_hour=9, tz=TZ, now=dt(1, 0))
