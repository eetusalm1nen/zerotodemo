"""In-memory calendar with a seeded busy week. Same interface as Topi's real calendar layer.

Used for local agent development (cli.py) and as a reference for the demo seed data.
"""
from __future__ import annotations

from datetime import datetime, timedelta

from agent import TZ, fmt, parse_iso

# (weekday 0=Mon, "HH:MM", minutes, title, movable, category)
SEED = [
    (0, "09:00", 15, "Team standup", True, "meeting"),
    (0, "10:00", 120, "Deep work: Q4 report", True, "focus"),
    (0, "13:00", 60, "Client call: Nordic Logistics", False, "meeting"),
    (0, "17:30", 60, "Gym", True, "personal"),
    (1, "09:00", 15, "Team standup", True, "meeting"),
    (1, "10:00", 30, "1:1 with Anna", True, "meeting"),
    (1, "11:00", 60, "Product review", True, "meeting"),
    (1, "14:00", 120, "Focus: pitch deck", True, "focus"),
    (1, "16:30", 45, "Dentist", False, "personal"),
    (2, "09:00", 15, "Team standup", True, "meeting"),
    (2, "10:00", 90, "Sprint planning", True, "meeting"),
    (2, "13:00", 60, "Lunch with Mikko", True, "personal"),
    (2, "15:00", 60, "Customer demo: Kesko", False, "meeting"),
    (2, "17:30", 60, "Gym", True, "personal"),
    (3, "09:00", 15, "Team standup", True, "meeting"),
    (3, "09:30", 180, "Exam: Computer Architecture", False, "other"),
    (3, "14:00", 60, "Design sync", True, "meeting"),
    (3, "15:30", 90, "Focus: code review", True, "focus"),
    (4, "09:00", 15, "Team standup", True, "meeting"),
    (4, "10:00", 60, "All-hands", True, "meeting"),
    (4, "11:30", 60, "Recruiting interview", False, "meeting"),
    (4, "14:00", 30, "Weekly planning", True, "meeting"),
    (4, "16:00", 120, "Team sauna", True, "personal"),
]


class FakeCalendar:
    def __init__(self, now: datetime):
        monday = (now - timedelta(days=now.weekday())).replace(hour=0, minute=0, second=0, microsecond=0)
        self.events: dict[str, dict] = {}
        for i, (day, hhmm, minutes, title, movable, category) in enumerate(SEED):
            h, m = map(int, hhmm.split(":"))
            start = (monday + timedelta(days=day)).replace(hour=h, minute=m)
            ev_id = f"evt{i:02d}"
            self.events[ev_id] = {
                "id": ev_id, "title": title, "start": fmt(start),
                "end": fmt(start + timedelta(minutes=minutes)),
                "movable": movable, "category": category,
            }

    def list_events(self, start: str, end: str) -> list[dict]:
        s, e = parse_iso(start), parse_iso(end)
        hits = [dict(ev) for ev in self.events.values()
                if parse_iso(ev["start"]) < e and s < parse_iso(ev["end"])]
        return sorted(hits, key=lambda ev: parse_iso(ev["start"]))

    def find_free_slots(self, duration_minutes: int, range_start: str, range_end: str,
                        earliest_hour: int = 8, latest_hour: int = 18) -> list[dict]:
        """Free intervals >= duration on weekdays within working hours (Helsinki)."""
        rs, re_ = parse_iso(range_start).astimezone(TZ), parse_iso(range_end).astimezone(TZ)
        need = timedelta(minutes=duration_minutes)
        slots = []
        day = rs.replace(hour=0, minute=0, second=0, microsecond=0)
        while day < re_:
            if day.weekday() < 5:
                win_s = max(day.replace(hour=earliest_hour), rs)
                win_e = min(day.replace(hour=latest_hour), re_)
                cursor = win_s
                for ev in self.list_events(fmt(win_s), fmt(win_e)):
                    ev_s, ev_e = parse_iso(ev["start"]), parse_iso(ev["end"])
                    if ev_s - cursor >= need:
                        slots.append({"start": fmt(cursor), "end": fmt(ev_s)})
                    cursor = max(cursor, ev_e)
                if win_e - cursor >= need:
                    slots.append({"start": fmt(cursor), "end": fmt(win_e)})
            day += timedelta(days=1)
        return slots

    def apply_change(self, change: dict) -> dict | None:
        """Local stand-in for Topi's apply_change, so the CLI can test the full flow."""
        if change["type"] == "delete":
            self.events.pop(change["event_id"], None)
            return None
        if change["type"] == "move":
            ev = self.events[change["event_id"]]
            ev["start"], ev["end"] = change["new_start"], change["new_end"]
            return dict(ev)
        ev_id = f"new{len(self.events):02d}"
        ev = {"id": ev_id, "title": change["title"], "start": change["new_start"],
              "end": change["new_end"], "movable": True, "category": "other"}
        self.events[ev_id] = ev
        return dict(ev)
