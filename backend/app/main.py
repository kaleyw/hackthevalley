"""Event management API + WebSocket for live dashboard updates.

Tracks every alert until help is confirmed to have reached the person:
went down -> alert (open) -> responder accepts (acknowledged) -> responder arrives (on_scene)
-> resolved with an outcome. A watchdog notifies a backup responder when nobody accepts
an alert in time; once someone accepts, they know where to go, so it doesn't escalate
further. The camera can also confirm someone stayed with the person. A speaker near the
camera announces the location so bystanders can help (see speaker.py).

Run from the repo root:
    uvicorn backend.app.main:app --reload
Docs at http://localhost:8000/docs
"""

import asyncio
import logging
import os
import statistics
from contextlib import asynccontextmanager, suppress
from datetime import datetime, timedelta, timezone

from fastapi import FastAPI, HTTPException, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel

from . import db
from . import maps
from .speaker import speaker

DEDUP_WINDOW = timedelta(minutes=2)  # one alert per ongoing event for the same person/camera
ACK_TIMEOUT = timedelta(seconds=int(os.getenv("ACK_TIMEOUT_SECONDS", 60)))          # nobody accepted
CAMERA_OFFLINE_AFTER = timedelta(seconds=6)
ESCALATION_NAMES = {1: "backup responder notified", 2: "supervisor notified"}
log = logging.getLogger("uvicorn.error")

# Which status changes are allowed: current status -> {action: new status}
TRANSITIONS = {
    "open":         {"acknowledge": "acknowledged", "arrive": "on_scene", "dismiss": "dismissed"},
    "acknowledged": {"arrive": "on_scene", "dismiss": "dismissed"},
    "on_scene":     {"resolve": "resolved", "dismiss": "dismissed"},
    "dismissed":    {},
    "resolved":     {},
}
ACTIVE = {"open", "acknowledged", "on_scene"}
OUTCOMES = {
    "person_ok": "Person OK, no help needed",
    "helped_on_site": "Helped on site",
    "medical_help_called": "Medical help called",
    "person_gone": "Person gone when we arrived",
}


class EventIn(BaseModel):
    camera_id: str
    location: str
    type: str = "possible_fall"
    track_id: int | None = None
    detected_at: str
    went_down_at: str | None = None  # when the person went down, before the alert wait
    urgency: str = "medium"          # "high" for a fast fall, "medium" for a slow collapse
    summary: str | None = None       # one-line headline for responders
    reasons: list[str] = []          # plain-language "why this alert" lines
    metrics: dict = {}               # raw numbers behind the reasons


class ActionIn(BaseModel):
    actor: str | None = None    # responder name
    reason: str | None = None   # required for dismiss
    outcome: str | None = None  # required for resolve, one of OUTCOMES


class HeartbeatIn(BaseModel):
    location: str


class Hub:
    """Keeps open dashboard WebSockets and pushes updates to all of them."""

    def __init__(self):
        self.clients: set[WebSocket] = set()

    async def broadcast(self, message):
        for ws in list(self.clients):
            try:
                await ws.send_json(message)
            except Exception:
                self.clients.discard(ws)


hub = Hub()


def utcnow():
    return datetime.now(timezone.utc)


def cameras_with_status():
    cutoff = (utcnow() - CAMERA_OFFLINE_AFTER).isoformat()
    return [{**c, "online": c["last_seen"] >= cutoff} for c in db.list_cameras()]


async def publish(event_id, kind="updated"):
    """After any change: push the event to dashboards and let the speaker react."""
    event = db.get_event(event_id)
    await hub.broadcast({"kind": kind, "event": event})
    speaker.update(event, active_events())
    return event


def active_events():
    return [e for e in db.list_events() if e["status"] in ACTIVE]


async def escalate(event_id, reason, actor="system"):
    event = db.get_event(event_id)
    level = min(event["escalation_level"] + 1, 2)
    db.update_event(event_id, f"escalated: {ESCALATION_NAMES[level]}", actor, reason, escalation_level=level)
    await publish(event_id)
    try:
        maps.on_escalation(event_id)
    except Exception:
        log.exception("Map handoff preparation failed; escalation already completed")


async def watchdog():
    """Runs forever: one failed pass is logged, never allowed to stop escalation for good."""
    state = {"cameras": None}
    while True:
        await asyncio.sleep(2)
        try:
            await watchdog_pass(state)
        except Exception:
            log.exception("watchdog pass failed; retrying")


async def watchdog_pass(state):
    """Escalate alerts that stall, and tell dashboards when a camera goes online/offline."""
    now = utcnow()
    for event_id in db.unacknowledged_events((now - ACK_TIMEOUT).isoformat()):
        await escalate(event_id, f"Nobody accepted within {ACK_TIMEOUT.seconds}s")
    active = active_events()
    for event in active:
        speaker.update(event, active)  # repeats announcements that are due

    cameras = cameras_with_status()
    status = {c["id"]: c["online"] for c in cameras}
    if status != state["cameras"]:
        state["cameras"] = status
        await hub.broadcast({"kind": "cameras", "cameras": cameras})


@asynccontextmanager
async def lifespan(_):
    db.init()
    try:
        maps.store.init()
        maps.store.simulation_mode(maps.provider.mode)
    except Exception:
        log.exception("Map storage unavailable; existing alerts continue")
    task = asyncio.create_task(watchdog())
    map_task = asyncio.create_task(maps.train_loop())
    yield
    task.cancel()
    map_task.cancel()
    with suppress(asyncio.CancelledError):
        await task
    with suppress(asyncio.CancelledError):
        await map_task


app = FastAPI(title="Hack the Valley collapse alerts", lifespan=lifespan)
app.add_middleware(CORSMiddleware, allow_origins=["http://localhost:5173"],
                   allow_methods=["*"], allow_headers=["*"])


@app.get("/health")
def health():
    return {"ok": True}


@app.post("/events")
async def create_event(e: EventIn):
    since = (utcnow() - DEDUP_WINDOW).isoformat()
    dup = db.find_active_duplicate(e.camera_id, e.track_id, since)
    if dup:
        if db.get_event(dup)["got_up_at"]:
            # They got up after the alert and are down again: same incident, announce again
            db.update_event(dup, "camera: person down again", "camera", got_up_at=None)
            await publish(dup)
        return {"id": dup, "duplicate": True}
    details = {"urgency": e.urgency, "summary": e.summary, "reasons": e.reasons, "metrics": e.metrics}
    event_id = db.create_event(e.camera_id, e.location, e.type, e.track_id, e.detected_at,
                               e.went_down_at, details)
    try:
        maps.capture(db.get_event(event_id))
    except Exception:
        log.exception("Map snapshot unavailable; incident creation continues")
    await publish(event_id, kind="created")
    return {"id": event_id, "duplicate": False}


@app.get("/events")
def list_events(limit: int = 100):
    return db.list_events(limit)


@app.get("/events/{event_id}")
def get_event(event_id: int):
    event = db.get_event(event_id)
    if not event:
        raise HTTPException(404, "event not found")
    return event


@app.post("/events/{event_id}/help-detected")
async def help_detected(event_id: int):
    """Called by the camera when someone has stayed next to the person for a few seconds."""
    event = db.get_event(event_id)
    if not event:
        raise HTTPException(404, "event not found")
    if event["help_detected_at"] or event["status"] not in ACTIVE:
        return event
    db.update_event(event_id, "camera: someone is with the person", "camera", help_detected_at=db.now())
    return await publish(event_id)


@app.post("/events/{event_id}/got-up")
async def got_up(event_id: int):
    """Called by the camera when the person gets back up after the alert. The alert stays
    open: staff should still check on them."""
    event = db.get_event(event_id)
    if not event:
        raise HTTPException(404, "event not found")
    if event["got_up_at"] or event["status"] not in ACTIVE:
        return event
    db.update_event(event_id, "camera: person got up", "camera", got_up_at=db.now())
    return await publish(event_id)


@app.post("/events/{event_id}/silence")
async def silence_speaker(event_id: int, body: ActionIn | None = None):
    """Stop the spoken announcement for this alert (e.g. a false alarm)."""
    body = body or ActionIn()
    event = db.get_event(event_id)
    if not event:
        raise HTTPException(404, "event not found")
    if not event["speaker_silenced"]:
        db.update_event(event_id, "speaker silenced", body.actor, speaker_silenced=1)
    return await publish(event_id)


@app.post("/events/{event_id}/escalate")
async def escalate_event(event_id: int, body: ActionIn | None = None):
    body = body or ActionIn()
    event = db.get_event(event_id)
    if not event:
        raise HTTPException(404, "event not found")
    if event["status"] not in ACTIVE or event["escalation_level"] >= 2:
        raise HTTPException(409, "can't escalate this event further")
    await escalate(event_id, body.reason or "Escalated by responder", body.actor)
    return db.get_event(event_id)


@app.post("/events/{event_id}/{action}")
async def act_on_event(event_id: int, action: str, body: ActionIn | None = None):
    body = body or ActionIn()
    event = db.get_event(event_id)
    if not event:
        raise HTTPException(404, "event not found")
    new_status = TRANSITIONS[event["status"]].get(action)
    if not new_status:
        raise HTTPException(409, f"can't {action} an event that is {event['status']}")
    if action == "dismiss" and not body.reason:
        raise HTTPException(422, "dismiss needs a reason")
    if action == "resolve" and body.outcome not in OUTCOMES:
        raise HTTPException(422, f"resolve needs an outcome: {', '.join(OUTCOMES)}")

    ts = db.now()
    fields = {"status": new_status}
    if action == "acknowledge":
        fields |= {"acknowledged_at": ts, "assigned_to": body.actor}
    elif action == "arrive":
        fields["arrived_at"] = ts
        if not event["acknowledged_at"]:
            fields |= {"acknowledged_at": ts, "assigned_to": body.actor}
    elif action in ("resolve", "dismiss"):
        fields |= {"resolved_at": ts, "outcome": body.outcome}
    reason = OUTCOMES.get(body.outcome) if action == "resolve" else body.reason
    db.update_event(event_id, new_status, body.actor, reason, **fields)
    return await publish(event_id)


@app.get("/outcomes")
def outcomes():
    return OUTCOMES


@app.get("/stats")
def stats():
    """The numbers that matter: did help reach the person, and how fast."""
    events = db.list_events(limit=10_000)

    def secs(a, b):
        return (datetime.fromisoformat(b) - datetime.fromisoformat(a)).total_seconds() if a and b else None

    def median(xs):
        xs = [x for x in xs if x is not None]
        return round(statistics.median(xs)) if xs else None

    real = [e for e in events if e["status"] != "dismissed"]
    reached = [e for e in real if e["arrived_at"] or e["help_detected_at"]]
    help_times = []
    for e in reached:
        first_help = min(t for t in (e["arrived_at"], e["help_detected_at"]) if t)
        help_times.append(secs(e["went_down_at"] or e["created_at"], first_help))

    return {
        "total": len(events),
        "active": sum(e["status"] in ACTIVE for e in events),
        "dismissed": len(events) - len(real),
        "help_reached": len(reached),
        "help_reached_pct": round(100 * len(reached) / len(real)) if real else None,
        "camera_verified": sum(bool(e["help_detected_at"]) for e in real),
        "escalated": sum(e["escalation_level"] > 0 for e in events),
        "median_down_to_alert_s": median(secs(e["went_down_at"], e["created_at"]) for e in events),
        "median_alert_to_accept_s": median(secs(e["created_at"], e["acknowledged_at"]) for e in events),
        "median_down_to_help_s": median(help_times),
    }


@app.post("/cameras/{camera_id}/heartbeat")
def heartbeat(camera_id: str, body: HeartbeatIn):
    db.camera_heartbeat(camera_id, body.location)
    return {"ok": True}


@app.get("/cameras")
def cameras():
    return cameras_with_status()


@app.websocket("/ws")
async def ws(websocket: WebSocket):
    await websocket.accept()
    hub.clients.add(websocket)
    try:
        while True:
            await websocket.receive_text()  # keep the connection open; we only push
    except WebSocketDisconnect:
        hub.clients.discard(websocket)


app.include_router(maps.router)
