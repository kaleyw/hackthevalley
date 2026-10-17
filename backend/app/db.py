"""SQLite storage for events, their status history, and camera heartbeats."""

import json
import sqlite3
from datetime import datetime, timezone
from pathlib import Path

DB_PATH = Path(__file__).resolve().parent.parent / "events.db"

SCHEMA = """
CREATE TABLE IF NOT EXISTS events (
    id               INTEGER PRIMARY KEY AUTOINCREMENT,
    camera_id        TEXT NOT NULL,
    location         TEXT NOT NULL,
    type             TEXT NOT NULL,
    track_id         INTEGER,
    detected_at      TEXT NOT NULL,          -- when the alert fired
    went_down_at     TEXT,                   -- when the person went down (before the alert wait)
    created_at       TEXT NOT NULL,
    updated_at       TEXT NOT NULL,
    status           TEXT NOT NULL,          -- open, acknowledged, on_scene, resolved, dismissed
    escalation_level INTEGER NOT NULL DEFAULT 0,  -- 0 none, 1 backup notified, 2 supervisor notified
    assigned_to      TEXT,
    acknowledged_at  TEXT,
    arrived_at       TEXT,                   -- responder tapped "I'm here"
    help_detected_at TEXT,                   -- camera saw someone stay with the person
    resolved_at      TEXT,
    outcome          TEXT,
    details          TEXT NOT NULL DEFAULT '{}'
);
CREATE TABLE IF NOT EXISTS event_log (
    id       INTEGER PRIMARY KEY AUTOINCREMENT,
    event_id INTEGER NOT NULL REFERENCES events(id),
    at       TEXT NOT NULL,
    action   TEXT NOT NULL,
    actor    TEXT,
    reason   TEXT
);
CREATE TABLE IF NOT EXISTS cameras (
    id        TEXT PRIMARY KEY,
    location  TEXT NOT NULL,
    last_seen TEXT NOT NULL
);
"""

# Columns added after the first version; added to older databases on startup
NEW_EVENT_COLUMNS = {
    "went_down_at": "TEXT", "escalation_level": "INTEGER NOT NULL DEFAULT 0", "assigned_to": "TEXT",
    "acknowledged_at": "TEXT", "arrived_at": "TEXT", "help_detected_at": "TEXT",
    "resolved_at": "TEXT", "outcome": "TEXT",
}


def now():
    return datetime.now(timezone.utc).isoformat()


def connect():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn


def init():
    with connect() as conn:
        conn.executescript(SCHEMA)
        existing = {r["name"] for r in conn.execute("PRAGMA table_info(events)")}
        for col, decl in NEW_EVENT_COLUMNS.items():
            if col not in existing:
                conn.execute(f"ALTER TABLE events ADD COLUMN {col} {decl}")


def _row_to_event(conn, row):
    e = dict(row)
    e["details"] = json.loads(e["details"])
    e["log"] = [dict(r) for r in conn.execute(
        "SELECT at, action, actor, reason FROM event_log WHERE event_id = ? ORDER BY id", (e["id"],))]
    return e


def get_event(event_id):
    with connect() as conn:
        row = conn.execute("SELECT * FROM events WHERE id = ?", (event_id,)).fetchone()
        return _row_to_event(conn, row) if row else None


def list_events(limit=100):
    with connect() as conn:
        rows = conn.execute("SELECT * FROM events ORDER BY id DESC LIMIT ?", (limit,)).fetchall()
        return [_row_to_event(conn, r) for r in rows]


def find_active_duplicate(camera_id, track_id, since_iso):
    """An unresolved event for the same person on the same camera, created after `since_iso`."""
    with connect() as conn:
        row = conn.execute(
            """SELECT id FROM events
               WHERE camera_id = ? AND track_id IS ? AND created_at >= ?
                 AND status IN ('open', 'acknowledged', 'on_scene')
               ORDER BY id DESC LIMIT 1""",
            (camera_id, track_id, since_iso)).fetchone()
        return row["id"] if row else None


def create_event(camera_id, location, type_, track_id, detected_at, went_down_at, details):
    ts = now()
    with connect() as conn:
        cur = conn.execute(
            """INSERT INTO events (camera_id, location, type, track_id, detected_at, went_down_at,
                                   created_at, updated_at, status, details)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, 'open', ?)""",
            (camera_id, location, type_, track_id, detected_at, went_down_at, ts, ts, json.dumps(details)))
        conn.execute("INSERT INTO event_log (event_id, at, action, actor) VALUES (?, ?, 'created', 'system')",
                     (cur.lastrowid, ts))
        return cur.lastrowid


def update_event(event_id, action, actor=None, reason=None, **fields):
    """Set any event columns and record the action in the event's log."""
    ts = now()
    fields["updated_at"] = ts
    cols = ", ".join(f"{k} = ?" for k in fields)
    with connect() as conn:
        conn.execute(f"UPDATE events SET {cols} WHERE id = ?", (*fields.values(), event_id))
        conn.execute("INSERT INTO event_log (event_id, at, action, actor, reason) VALUES (?, ?, ?, ?, ?)",
                     (event_id, ts, action, actor, reason))
    return ts


def unacknowledged_events(created_before_iso):
    """Open events nobody accepted in time (once someone accepts, they know where to go)."""
    with connect() as conn:
        rows = conn.execute(
            "SELECT id FROM events WHERE status = 'open' AND escalation_level < 1 AND created_at < ?",
            (created_before_iso,)).fetchall()
        return [r["id"] for r in rows]


def camera_heartbeat(camera_id, location):
    with connect() as conn:
        conn.execute(
            """INSERT INTO cameras (id, location, last_seen) VALUES (?, ?, ?)
               ON CONFLICT(id) DO UPDATE SET location = excluded.location, last_seen = excluded.last_seen""",
            (camera_id, location, now()))


def list_cameras():
    with connect() as conn:
        return [dict(r) for r in conn.execute("SELECT * FROM cameras ORDER BY id")]
