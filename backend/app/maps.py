"""Incident geography and demo responder handoff; no dispatch/calling integration."""
import asyncio
import hashlib
import hmac
import json
import logging
import os
import secrets
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Literal, Protocol
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
FRESH_SECONDS = 10
LINK_TTL = timedelta(hours=1)


def now():
    return datetime.now(timezone.utc)


def operator_secret():
    # Read only new map settings; do not change existing escalation environment.
    return os.getenv('MAP_OPERATOR_KEY') or dotenv_values(ROOT / '.env').get('MAP_OPERATOR_KEY')


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


def train_view(train_id):
    record = store.train(train_id) if train_id else None
    if not record:
        return None
    age = max(0, (now() - datetime.fromisoformat(record['latest']['observed_at'])).total_seconds())
    connected = store.simulation_mode() != 'disconnected' if record['latest']['source'] == 'simulated' else True
    return {**record, 'age_seconds': round(age, 1), 'stale': age > FRESH_SECONDS, 'connected': connected,
            'fresh_for_seconds': FRESH_SECONDS}


def capture(event):
    metadata = store.camera(event['camera_id'])
    snapshot = {'captured_at': event['detected_at'], 'location': metadata, 'train_position': None}
    if metadata and metadata.get('kind') == 'train':
        train = train_view(metadata.get('train_id'))
        if train:
            delta = (datetime.fromisoformat(event['detected_at']) - datetime.fromisoformat(train['latest']['observed_at'])).total_seconds()
            if 0 <= delta <= FRESH_SECONDS:
                snapshot['train_position'] = train['latest']
    store.capture(event['id'], snapshot)


def ensure_record(event):
    if not store.incident(event['id']):
        # A legacy event has no known historical location. Do not backfill it from
        # today's camera configuration and misrepresent it as a detection snapshot.
        store.capture(event['id'], {'captured_at': event['detected_at'], 'location': None, 'train_position': None})
    return store.incident(event['id'])


def ensure_handoff(event_id, escalation=False, renew=False):
    return store.ensure_handoff(event_id, secrets.token_urlsafe(32), (now() + LINK_TTL).isoformat(), escalation, renew)


def on_escalation(event_id):
    # Called only after the existing escalation has committed and broadcast.
    ensure_handoff(event_id, escalation=True)


def handoff_status(event_id):
    row = store.handoff(event_id)
    if not row:
        return {'state': 'not_prepared', 'delivery': 'unsupported', 'attempted_at': None,
                'delivered_at': None, 'responder_acknowledged_at': None}
    state = 'revoked' if row['revoked_at'] else 'expired' if datetime.fromisoformat(row['expires_at']) <= now() else 'generated'
    key = operator_secret()
    if state == 'generated' and (not key or len(key) < 24):
        state = 'prepared_key_required'
    return {'state': state, 'generated_at': row['generated_at'], 'expires_at': row['expires_at'],
            'escalation_seen': bool(row['escalation_seen']), 'delivery': 'unsupported',
            'attempted_at': None, 'delivered_at': None, 'responder_acknowledged_at': None}


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


def briefing(event, record, train):
    location = record['transfer']['location'] if record['transfer'] else record['supplemental'] or record['snapshot']['location']
    pieces = [f"Incident #{event['id']}: possible fall detected", event['detected_at'], f"Status: {event['status']}"]
    if location:
        for key in ('station_name', 'platform_label', 'line', 'direction', 'train_id', 'car_id'):
            if location.get(key):
                pieces.append(f"{key.replace('_', ' ')}: {location[key]}")
        c = location.get('coordinates')
        if c:
            precision = 'approximate station location' if c['precision'] == 'station_centroid' else c['precision'].replace('_', ' ')
            pieces.append(f"{c['lat']:.5f}, {c['lon']:.5f} ({precision}; source: {location['source']})")
        elif not record['snapshot'].get('train_position'):
            pieces.append('location unavailable')
        meeting = location.get('meeting_point')
        if meeting:
            pieces.append(f"Verified meeting point: {meeting['label']}")
    else:
        pieces.append('location unavailable')
    if record['transfer']:
        pieces.append(f"Staff-confirmed transfer at {record['transfer']['confirmed_at']}")
    snapshot = record['snapshot']
    detected = snapshot.get('train_position') or (snapshot.get('location') or {}).get('coordinates')
    if detected:
        pieces.append(f"Detection snapshot: {detected['lat']:.5f}, {detected['lon']:.5f}, captured {snapshot['captured_at']}")
    else:
        pieces.append('Detection snapshot: location unavailable')
    if train:
        latest = train['latest']
        pieces.append(f"Train location ({latest['source']}; {'STALE' if train['stale'] else 'fresh'}): {latest['lat']:.5f}, {latest['lon']:.5f}, observed {latest['observed_at']}; train position is not verified person location")
    return ' · '.join(pieces)


def context(event, restricted=False):
    record = ensure_record(event)
    # Reconcile a failed additive hook after storage recovers. Only map state
    # changes; existing escalation state is the source of truth, never a trigger.
    if event['escalation_level'] > 0 and not store.handoff(event['id']):
        ensure_handoff(event['id'], escalation=True)
    original = record['snapshot']['location'] or {}
    supplemental = record['supplemental'] or {}
    train_id = original.get('train_id') or supplemental.get('train_id')
    train = train_view(train_id)
    # Deliberate allowlist: no camera video, responder names, reasons, or full event log.
    incident = {k: event[k] for k in ('id', 'detected_at', 'status', 'escalation_level', 'updated_at')}
    latest_at = max(event['updated_at'], record['updated_at'], train['latest']['observed_at'] if train else '')
    result = {'incident': incident, 'description': 'Possible fall detected', **record,
              'latest_train': train, 'last_updated_at': latest_at, 'server_time': now().isoformat(),
              'briefing': briefing(event, record, train), 'demo': True,
              'delivery_notice': 'Demo responder view. No emergency-service link delivery or calls are supported.'}
    if not restricted:
        result['handoff'] = handoff_status(event['id'])
    return result


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


class TransferIn(BaseModel):
    location: LocationMetadata


@router.post('/maps/events/{event_id}/transfer', dependencies=[Depends(operator)])
def confirm_transfer(event_id: int, body: TransferIn):
    event = require_event(event_id)
    if body.location.kind != 'platform':
        raise HTTPException(422, 'Transfer must be to a platform')
    ensure_record(event)
    store.annotate(event_id, 'transfer', {'location': station_location(body.location.model_dump()),
                                       'confirmed_at': db.now()})
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
    origin = os.getenv('MAP_RESPONDER_ORIGIN') or dotenv_values(ROOT / '.env').get('MAP_RESPONDER_ORIGIN') or 'http://localhost:8001'
    parsed = urlsplit(origin)
    if parsed.scheme not in ('http', 'https') or not parsed.netloc or parsed.username or parsed.password:
        raise HTTPException(503, 'MAP_RESPONDER_ORIGIN must be an HTTP(S) origin')
    path = f"/demo/responder/{event_id}#token={sign_link(row)}"
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


class TrainLocationProvider(Protocol):
    def samples(self, at: datetime) -> list[dict]: ...


class SimulatedTrainProvider:
    """Synthetic, straight station-to-station travel; not track telemetry."""
    train_id = 'DEMO-T1'

    def __init__(self):
        self.mode = 'disconnected'
        self.progress = 0.0
        self.last_tick = None

    def control(self, mode):
        self.mode = mode
        self.last_tick = None

    def samples(self, at):
        if self.mode == 'disconnected':
            self.last_tick = None
            return []
        stations = json.loads((NETWORK / 'ttc-stations.geojson').read_text())['features']
        points = []
        for name in ('Union', 'King', 'Queen', 'Dundas'):
            feature = next((f for f in stations if f['properties'].get('PT_NAME', '').casefold() == name.casefold()), None)
            if not feature:
                raise ValueError(f'Demo station missing: {name}')
            points.append(feature['geometry']['coordinates'])
        if self.last_tick is not None and self.mode == 'running':
            self.progress = (self.progress + max(0, (at - self.last_tick).total_seconds()) / 20) % (2 * (len(points) - 1))
        self.last_tick = at
        # Ping-pong rather than jumping from the end back to the start.
        position = min(self.progress, 2 * (len(points) - 1) - self.progress)
        index = min(int(position), len(points) - 2)
        fraction = position - index
        a, b = points[index:index + 2]
        return [{'train_id': self.train_id, 'lat': a[1] + fraction * (b[1] - a[1]),
                 'lon': a[0] + fraction * (b[0] - a[0]), 'source': 'simulated',
                 'precision': 'approximate', 'observed_at': at.isoformat(),
                 'line': '1', 'direction': 'northbound' if self.progress < len(points) - 1 else 'southbound',
                 'provider_mode': self.mode}]


provider = SimulatedTrainProvider()


async def train_loop():
    while True:
        try:
            for sample in provider.samples(now()):
                store.save_train(sample)
        except Exception:
            log.exception('Map simulator update failed; existing alerts continue')
        await asyncio.sleep(2)


class SimulationIn(BaseModel):
    mode: Literal['running', 'paused', 'disconnected']


@router.get('/maps/simulator', dependencies=[Depends(operator)])
def simulator_status():
    return {'mode': provider.mode, 'train_id': provider.train_id, 'source': 'simulated'}


@router.post('/maps/simulator', dependencies=[Depends(operator)])
def simulator_control(body: SimulationIn):
    provider.control(body.mode)
    store.simulation_mode(body.mode)
    for sample in provider.samples(now()):
        store.save_train(sample)
    return simulator_status()
