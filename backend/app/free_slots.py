"""Deterministic free-slot finder. No LLM involved.

Algorithm:
  1. Clip the search range to [max(range_start, now), range_end].
  2. Merge the busy intervals of all timed events. All-day events do not block,
     because they are usually markers such as holidays or "WFH".
  3. For each local day, take the working window [earliest_hour, latest_hour]
     (DST-safe through zoneinfo) and subtract the busy intervals.
  4. Keep the free windows that are at least duration_minutes long.
"""

from __future__ import annotations

from collections.abc import Iterable
from datetime import datetime, time, timedelta
from zoneinfo import ZoneInfo

from .models import Event, Slot

Interval = tuple[datetime, datetime]


def merge_intervals(intervals: Iterable[Interval]) -> list[Interval]:
    merged: list[Interval] = []
    for s, e in sorted(i for i in intervals if i[1] > i[0]):
        if merged and s <= merged[-1][1]:
            if e > merged[-1][1]:
                merged[-1] = (merged[-1][0], e)
        else:
            merged.append((s, e))
    return merged


def _ceil_to(dt: datetime, minutes: int) -> datetime:
    """Round up to the next multiple of `minutes` past the hour, so free slots don't start at 10:07."""
    bump = timedelta(minutes=1) if (dt.second or dt.microsecond) else timedelta()
    dt = dt.replace(second=0, microsecond=0) + bump
    step = max(minutes, 1)
    return dt + timedelta(minutes=(step - dt.minute % step) % step)


def find_free_slots(
    events: Iterable[Event],
    range_start: datetime,
    range_end: datetime,
    *,
    duration_minutes: int = 30,
    earliest_hour: int = 9,
    latest_hour: int = 17,
    tz: ZoneInfo,
    now: datetime,
    include_weekends: bool = False,
    round_to_minutes: int = 15,
    max_results: int | None = None,
) -> list[Slot]:
    if not 0 <= earliest_hour < latest_hour <= 24:
        raise ValueError("need 0 <= earliest_hour < latest_hour <= 24")
    if duration_minutes <= 0:
        raise ValueError("duration_minutes must be positive")

    start = max(range_start, _ceil_to(now.astimezone(tz), round_to_minutes))
    end = range_end
    if start >= end:
        return []

    busy = merge_intervals((e.start, e.end) for e in events if not e.all_day)
    need = timedelta(minutes=duration_minutes)
    out: list[Slot] = []

    day = start.astimezone(tz).date()
    last_day = end.astimezone(tz).date()
    while day <= last_day:
        if include_weekends or day.weekday() < 5:
            w_start = datetime.combine(day, time(earliest_hour), tzinfo=tz)
            w_end = (
                datetime.combine(day + timedelta(days=1), time(0), tzinfo=tz)
                if latest_hour == 24
                else datetime.combine(day, time(latest_hour), tzinfo=tz)
            )
            cur = max(w_start, start)
            w_end = min(w_end, end)
            for b_start, b_end in busy:
                if b_end <= cur:
                    continue
                if b_start >= w_end:
                    break
                if b_start - cur >= need:
                    out.append(Slot(start=cur, end=b_start))
                cur = max(cur, b_end)
            if w_end - cur >= need:
                out.append(Slot(start=cur, end=w_end))
            if max_results is not None and len(out) >= max_results:
                return out[:max_results]
        day += timedelta(days=1)
    return out
