"""Additive map storage. Never updates event lifecycle or escalation columns."""
import json
from . import db

SCHEMA = """
CREATE TABLE IF NOT EXISTS map_cameras (camera_id TEXT PRIMARY KEY, metadata TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS map_incidents (
 event_id INTEGER PRIMARY KEY REFERENCES events(id), snapshot TEXT NOT NULL,
 supplemental TEXT, transfer TEXT, updated_at TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS map_handoffs (
 event_id INTEGER PRIMARY KEY REFERENCES events(id), nonce TEXT NOT NULL,
 generated_at TEXT NOT NULL, expires_at TEXT NOT NULL, revoked_at TEXT,
 escalation_seen INTEGER NOT NULL DEFAULT 0);
"""


def init():
    with db.connect() as conn:
        conn.executescript(SCHEMA)


def camera(camera_id):
    with db.connect() as conn:
        row = conn.execute('SELECT metadata FROM map_cameras WHERE camera_id=?', (camera_id,)).fetchone()
        return json.loads(row['metadata']) if row else None


def set_camera(camera_id, metadata):
    with db.connect() as conn:
        conn.execute('INSERT INTO map_cameras VALUES (?,?) ON CONFLICT(camera_id) DO UPDATE SET metadata=excluded.metadata',
                     (camera_id, json.dumps(metadata)))


def capture(event_id, snapshot):
    with db.connect() as conn:
        conn.execute('INSERT OR IGNORE INTO map_incidents (event_id,snapshot,updated_at) VALUES (?,?,?)',
                     (event_id, json.dumps(snapshot), db.now()))


def incident(event_id):
    with db.connect() as conn:
        row = conn.execute('SELECT * FROM map_incidents WHERE event_id=?', (event_id,)).fetchone()
    if not row:
        return None
    result = dict(row)
    result.pop('transfer', None)  # column kept for older databases; no longer used
    for key in ('snapshot', 'supplemental'):
        result[key] = json.loads(result[key]) if result[key] else None
    return result


def annotate(event_id, field, value):
    if field != 'supplemental':
        raise ValueError('unsupported map field')
    with db.connect() as conn:
        conn.execute(f'UPDATE map_incidents SET {field}=?, updated_at=? WHERE event_id=?',
                     (json.dumps(value), db.now(), event_id))


def handoff(event_id):
    with db.connect() as conn:
        row = conn.execute('SELECT * FROM map_handoffs WHERE event_id=?', (event_id,)).fetchone()
        return dict(row) if row else None


def ensure_handoff(event_id, nonce, expires_at, escalation=False, renew=False):
    with db.connect() as conn:
        if renew:
            conn.execute('DELETE FROM map_handoffs WHERE event_id=?', (event_id,))
        conn.execute('INSERT OR IGNORE INTO map_handoffs (event_id,nonce,generated_at,expires_at) VALUES (?,?,?,?)',
                     (event_id, nonce, db.now(), expires_at))
        if escalation:
            conn.execute('UPDATE map_handoffs SET escalation_seen=1 WHERE event_id=?', (event_id,))
    return handoff(event_id)


def revoke(event_id):
    with db.connect() as conn:
        conn.execute('UPDATE map_handoffs SET revoked_at=? WHERE event_id=?', (db.now(), event_id))
