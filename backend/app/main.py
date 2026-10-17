"""Event management API + WebSocket for live dashboard updates.

Run from the repo root:
    uvicorn backend.app.main:app --reload
Docs at http://localhost:8000/docs
"""

from contextlib import asynccontextmanager
from datetime import datetime, timedelta, timezone

from fastapi import FastAPI, HTTPException, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel

from . import db

DEDUP_WINDOW = timedelta(minutes=2)  # one alert per ongoing event for the same person/camera

# Which status changes are allowed: current status -> {action: new status}
TRANSITIONS = {
    "open":         {"acknowledge": "acknowledged", "dismiss": "dismissed", "escalate": "escalated"},
    "acknowledged": {"resolve": "resolved", "dismiss": "dismissed", "escalate": "escalated"},
    "escalated":    {"acknowledge": "acknowledged", "resolve": "resolved"},
    "dismissed":    {},
    "resolved":     {},
}


class EventIn(BaseModel):
    camera_id: str
    location: str
    type: str = "possible_fall"
    track_id: int | None = None
    detected_at: str
    urgency: str = "medium"          # "high" for a fast fall, "medium" for a slow collapse
    summary: str | None = None       # one-line headline for responders
    reasons: list[str] = []          # plain-language "why this alert" lines
    metrics: dict = {}               # raw numbers behind the reasons


class ActionIn(BaseModel):
    actor: str | None = None   # responder name
    reason: str | None = None  # required for dismiss


class Hub:
    """Keeps open dashboard WebSockets and pushes event updates to all of them."""

    def __init__(self):
        self.clients: set[WebSocket] = set()

    async def broadcast(self, message):
        for ws in list(self.clients):
            try:
                await ws.send_json(message)
            except Exception:
                self.clients.discard(ws)


hub = Hub()


@asynccontextmanager
async def lifespan(_):
    db.init()
    yield


app = FastAPI(title="Hack the Valley fall alerts", lifespan=lifespan)
app.add_middleware(CORSMiddleware, allow_origins=["http://localhost:5173"],
                   allow_methods=["*"], allow_headers=["*"])


@app.get("/health")
def health():
    return {"ok": True}


@app.post("/events")
async def create_event(e: EventIn):
    since = (datetime.now(timezone.utc) - DEDUP_WINDOW).isoformat()
    dup = db.find_active_duplicate(e.camera_id, e.track_id, since)
    if dup:
        return {"id": dup, "duplicate": True}
    details = {"urgency": e.urgency, "summary": e.summary, "reasons": e.reasons, "metrics": e.metrics}
    event_id = db.create_event(e.camera_id, e.location, e.type, e.track_id, e.detected_at, details)
    event = db.get_event(event_id)
    await hub.broadcast({"kind": "created", "event": event})
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
    db.set_status(event_id, new_status, body.actor, body.reason)
    event = db.get_event(event_id)
    await hub.broadcast({"kind": "updated", "event": event})
    return event


@app.websocket("/ws")
async def ws(websocket: WebSocket):
    await websocket.accept()
    hub.clients.add(websocket)
    try:
        while True:
            await websocket.receive_text()  # keep the connection open; we only push
    except WebSocketDisconnect:
        hub.clients.discard(websocket)
