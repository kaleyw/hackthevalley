"""SQLite storage for events and their status history."""

import json
import sqlite3
from datetime import datetime, timezone
from pathlib import Path

DB_PATH = Path(__file__).resolve().parent.parent / "events.db"

SCHEMA = """
CREATE TABLE IF NOT EXISTS events (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    camera_id   TEXT NOT NULL,
    location    TEXT NOT NULL,
    type        TEXT NOT NULL,
    track_id    INTEGER,
    detected_at TEXT NOT NULL,
    created_at  TEXT NOT NULL,
    updated_at  TEXT NOT NULL,
    status      TEXT NOT NULL,
    details     TEXT NOT NULL DEFAULT '{}'
);
CREATE TABLE IF NOT EXISTS event_log (
    id       INTEGER PRIMARY KEY AUTOINCREMENT,
    event_id INTEGER NOT NULL REFERENCES events(id),
    at       TEXT NOT NULL,
    action   TEXT NOT NULL,
    actor    TEXT,
    reason   TEXT
);
"""


def now():
    return datetime.now(timezone.utc).isoformat()


def connect():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn


def init():
    with connect() as conn:
        conn.executescript(SCHEMA)


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
                 AND status IN ('open', 'acknowledged', 'escalated')
               ORDER BY id DESC LIMIT 1""",
            (camera_id, track_id, since_iso)).fetchone()
        return row["id"] if row else None


def create_event(camera_id, location, type_, track_id, detected_at, details):
    ts = now()
    with connect() as conn:
        cur = conn.execute(
            """INSERT INTO events (camera_id, location, type, track_id, detected_at,
                                   created_at, updated_at, status, details)
               VALUES (?, ?, ?, ?, ?, ?, ?, 'open', ?)""",
            (camera_id, location, type_, track_id, detected_at, ts, ts, json.dumps(details)))
        conn.execute("INSERT INTO event_log (event_id, at, action, actor) VALUES (?, ?, 'created', 'system')",
                     (cur.lastrowid, ts))
        return cur.lastrowid


def set_status(event_id, status, actor=None, reason=None):
    ts = now()
    with connect() as conn:
        conn.execute("UPDATE events SET status = ?, updated_at = ? WHERE id = ?", (status, ts, event_id))
        conn.execute("INSERT INTO event_log (event_id, at, action, actor, reason) VALUES (?, ?, ?, ?, ?)",
                     (event_id, ts, status, actor, reason))
