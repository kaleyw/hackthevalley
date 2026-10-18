"""Incident locations on the TTC map, and restricted responder links. No dispatch/calling integration."""
import hashlib
import hmac
import json
import logging
import os
import secrets
from datetime import datetime, timedelta, timezone
from pathlib import Path
from urllib.parse import urlsplit

from dotenv import dotenv_values
from fastapi import APIRouter, Depends, Header, HTTPException, Response
from pydantic import BaseModel

from . import db, map_store as store
from .map_models import LocationMetadata

ROOT = Path(__file__).resolve().parents[2]
NETWORK = ROOT / 'dashboard' / 'public' / 'maps'
router = APIRouter()
log = logging.getLogger('uvicorn.error')
LINK_TTL = timedelta(hours=1)


def now():
    return datetime.now(timezone.utc)


def setting(name, default=None):
    """From the environment, else .env, else the default. An empty value means "off"."""
    value = os.getenv(name)
    if value is None:
        value = dotenv_values(ROOT / '.env').get(name)
    return default if value is None else value


def operator_secret():
    return setting('MAP_OPERATOR_KEY')


def operator(x_map_operator_key: str | None = Header(default=None)):
    key = operator_secret()
    if not key or len(key) < 24:
        raise HTTPException(503, 'Set MAP_OPERATOR_KEY to a random secret of at least 24 characters')
    if not x_map_operator_key or not hmac.compare_digest(x_map_operator_key.encode(), key.encode()):
        raise HTTPException(401, 'Map operator key required')


def require_event(event_id):
    event = db.get_event(event_id)
    if not event:
        raise HTTPException(404, 'event not found')
    return event


def station_location(metadata):
    """Use official station points as approximate locations, never as entrances."""
    data = dict(metadata)
    if not data.get('coordinates') and (data.get('station_id') or data.get('station_name')):
        stations = json.loads((NETWORK / 'ttc-stations.geojson').read_text())
        for feature in stations['features']:
            props = feature['properties']
            if ((data.get('station_id') and str(props.get('PT_ID')) == data['station_id'])
                or (data.get('station_name') and props.get('PT_NAME', '').casefold() == data['station_name'].casefold())):
                lon, lat = feature['geometry']['coordinates']
                data['station_id'] = str(props['PT_ID'])
                data['station_name'] = props['PT_NAME']
                data['coordinates'] = {'lat': lat, 'lon': lon, 'precision': 'station_centroid'}
                break
    return data


def camera_location(camera_id):
    """A camera's configured station; cameras without one default to CAMERA_STATION (Union)."""
    configured = store.camera(camera_id)
    if configured:
        return configured
    station = setting('CAMERA_STATION', 'Union')
    return station_location({'kind': 'platform', 'station_name': station, 'source': 'configured'}) if station else None


def capture(event):
    store.capture(event['id'], {'captured_at': event['detected_at'], 'location': camera_location(event['camera_id'])})


def ensure_record(event):
    if not store.incident(event['id']):
        # A legacy event has no known historical location. Do not backfill it from
        # today's camera configuration and misrepresent it as a detection snapshot.
        store.capture(event['id'], {'captured_at': event['detected_at'], 'location': None})
    return store.incident(event['id'])


def ensure_handoff(event_id, escalation=False, renew=False):
    return store.ensure_handoff(event_id, secrets.token_urlsafe(32), (now() + LINK_TTL).isoformat(), escalation, renew)


def on_escalation(event_id):
    # Called only after the escalation has committed and broadcast.
    ensure_handoff(event_id, escalation=True)


def handoff_status(event_id):
    row = store.handoff(event_id)
    # Links are never sent automatically: these fields say so explicitly
    not_sent = {'delivery': 'unsupported', 'attempted_at': None, 'delivered_at': None, 'responder_acknowledged_at': None}
    if not row:
        return {'state': 'not_prepared', **not_sent}
    state = 'revoked' if row['revoked_at'] else 'expired' if datetime.fromisoformat(row['expires_at']) <= now() else 'generated'
    key = operator_secret()
    if state == 'generated' and (not key or len(key) < 24):
        state = 'prepared_key_required'
    return {'state': state, 'generated_at': row['generated_at'], 'expires_at': row['expires_at'],
            'escalation_seen': bool(row['escalation_seen']), **not_sent}


def sign_link(row):
    key = operator_secret()
    if not key or len(key) < 24:
        raise HTTPException(503, 'Configure MAP_OPERATOR_KEY before creating a restricted link')
    payload = f"{row['event_id']}.{row['nonce']}.{row['expires_at']}"
    signature = hmac.new(key.encode(), payload.encode(), hashlib.sha256).hexdigest()
    return f"{row['nonce']}.{signature}"


def check_token(event_id, token):
    row = store.handoff(event_id)
    if not row or row['revoked_at'] or datetime.fromisoformat(row['expires_at']) <= now():
        raise HTTPException(404, 'Responder link invalid, expired, or revoked')
    if not token or not hmac.compare_digest(token.encode(), sign_link(row).encode()):
        raise HTTPException(404, 'Responder link invalid, expired, or revoked')


def station_display(name):
    return f"{name.title()} Station" if name else None


def briefing(event, record):
    location = record['supplemental'] or record['snapshot']['location']
    pieces = [f"Incident #{event['id']}: person may need help", event['detected_at'], f"Status: {event['status']}"]
    if location:
        if location.get('station_name'):
            pieces.append(station_display(location['station_name']))
        for key in ('platform_label', 'line', 'direction'):
            if location.get(key):
                pieces.append(f"{key.replace('_', ' ')}: {location[key]}")
        c = location.get('coordinates')
        if c:
            precision = 'approximate station location' if c['precision'] == 'station_centroid' else c['precision'].replace('_', ' ')
            pieces.append(f"{c['lat']:.5f}, {c['lon']:.5f} ({precision})")
        meeting = location.get('meeting_point')
        if meeting:
            pieces.append(f"Verified meeting point: {meeting['label']}")
    else:
        pieces.append('location unavailable')
    return ' · '.join(pieces)


def context(event, restricted=False):
    record = ensure_record(event)
    # Reconcile a failed additive hook after storage recovers. Only map state
    # changes; escalation state is the source of truth, never a trigger.
    if event['escalation_level'] > 0 and not store.handoff(event['id']):
        ensure_handoff(event['id'], escalation=True)
    # Deliberate allowlist: no camera video, responder names, reasons, or full event log.
    incident = {k: event[k] for k in ('id', 'detected_at', 'status', 'escalation_level', 'updated_at')}
    result = {'incident': incident, 'description': 'Person may need help', **record,
              'last_updated_at': max(event['updated_at'], record['updated_at']),
              'server_time': now().isoformat(), 'briefing': briefing(event, record)}
    if not restricted:
        result['handoff'] = handoff_status(event['id'])
    return result


@router.get('/maps/monitored')
def monitored_stations():
    """Stations with a camera, so the map can show where we're watching even with no alerts."""
    camera_ids = [c['id'] for c in db.list_cameras()] or ['cam-1']
    stations = {}
    for camera_id in camera_ids:
        location = camera_location(camera_id)
        if location and location.get('coordinates'):
            entry = stations.setdefault(location.get('station_name'), {
                'station_name': location.get('station_name'), 'coordinates': location['coordinates'], 'cameras': []})
            entry['cameras'].append(camera_id)
    return list(stations.values())


@router.get('/maps/events/{event_id}')
def event_map(event_id: int):
    return context(require_event(event_id))


@router.put('/maps/cameras/{camera_id}', dependencies=[Depends(operator)])
def configure_camera(camera_id: str, metadata: LocationMetadata):
    try:
        data = station_location(metadata.model_dump())
    except (OSError, ValueError):
        data = metadata.model_dump()  # map data failure must not prevent configuration
    store.set_camera(camera_id, data)
    return data


@router.get('/maps/cameras/{camera_id}', dependencies=[Depends(operator)])
def camera_config(camera_id: str):
    return store.camera(camera_id)


@router.put('/maps/events/{event_id}/location', dependencies=[Depends(operator)])
def update_location(event_id: int, metadata: LocationMetadata):
    event = require_event(event_id)
    ensure_record(event)
    store.annotate(event_id, 'supplemental', station_location(metadata.model_dump()))
    return context(event)


class LinkIn(BaseModel):
    renew: bool = False


@router.post('/maps/events/{event_id}/link', dependencies=[Depends(operator)])
def prepare_link(event_id: int, body: LinkIn):
    require_event(event_id)
    row = ensure_handoff(event_id, renew=body.renew)
    if row['revoked_at'] or datetime.fromisoformat(row['expires_at']) <= now():
        raise HTTPException(410, 'Link expired or revoked; explicitly renew to replace it')
    # Fragment tokens are not sent in page URLs, access logs, or Referer headers.
    origin = setting('MAP_RESPONDER_ORIGIN') or 'http://localhost:8001'
    parsed = urlsplit(origin)
    if parsed.scheme not in ('http', 'https') or not parsed.netloc or parsed.username or parsed.password:
        raise HTTPException(503, 'MAP_RESPONDER_ORIGIN must be an HTTP(S) origin')
    path = f"/responder/{event_id}#token={sign_link(row)}"
    return {'url': f'{parsed.scheme}://{parsed.netloc}{path}', **handoff_status(event_id)}


@router.delete('/maps/events/{event_id}/link', dependencies=[Depends(operator)])
def revoke_link(event_id: int):
    require_event(event_id)
    store.revoke(event_id)
    return handoff_status(event_id)


@router.get('/responder/events/{event_id}')
def responder_context(event_id: int, response: Response, x_responder_token: str | None = Header(default=None)):
    check_token(event_id, x_responder_token)
    response.headers['Cache-Control'] = 'no-store'
    response.headers['Referrer-Policy'] = 'no-referrer'
    response.headers['X-Content-Type-Options'] = 'nosniff'
    return context(require_event(event_id), restricted=True)
