# Hack the Valley: Fall Alerts

For the map feature's behavior, architecture, and live-alert walkthrough, see
[TTC map overview](docs/TTC_MAP_OVERVIEW.md).

TTC incident maps and restricted responder sharing: see [the map demo guide](docs/TTC_MAP_DEMO.md)
for setup, camera location configuration, simulated train controls, security boundaries,
and verification. Existing escalation remains log/dashboard-only; no emergency calls
or outbound map delivery are configured.

A fixed security camera detects when someone collapses or falls and doesn't get up, then starts a welfare check that a responder has to acknowledge. Built for Project KAZE: helping people who can no longer ask for help themselves.

```
camera / video ──► vision/ (YOLO Pose + ByteTrack + fall detector) ──POST /events──► backend/ (FastAPI + SQLite)
                                                                                         │ WebSocket
                                                                                         ▼
                                                                          dashboard/ (React responder view)
```

## Stack

| Part | Tech |
|---|---|
| Video ingestion | Python + OpenCV |
| Pose estimation | Ultralytics YOLO Pose (`yolo11n-pose.pt`) |
| Tracking | ByteTrack (built into Ultralytics, settings in `vision/bytetrack.yaml`) |
| Collapse detection | Temporal rules + state machine over keypoints (`vision/detector.py`): fast fall (high urgency) or slow collapse (medium), each alert with plain-language reasons |
| Backend | FastAPI + SQLite, WebSocket for live updates |
| Dashboard | React + Vite + Tailwind CSS |

## Quick start

You need **Python 3.12** (3.14 is too new for some ML packages) and **Node 20+**.

**1. One-time setup**
```bash
python3.12 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env
npm install --prefix dashboard
```

**2. Run it** (three terminals, all from the repo root, with `source .venv/bin/activate` in the Python ones)
```bash
uvicorn backend.app.main:app --reload            # backend on :8000, API docs at /docs
npm run dev --prefix dashboard                   # dashboard on http://localhost:5173
python vision/run.py                             # webcam, or: --source data/tune/clip.mp4
```

Press `q` in the preview window to stop the vision script. On a Mac with Apple Silicon it runs on the GPU (`--device mps`). Use `--device cpu` if that errors, or `--device 0` on an NVIDIA GPU.

**Test the dashboard without a camera:**
```bash
curl -X POST localhost:8000/events -H 'Content-Type: application/json' \
  -d '{"camera_id":"cam-1","location":"Demo venue - Room A","type":"person_down","urgency":"medium","summary":"Person down and not getting up","reasons":["Went down slowly","Lying down for 12s"],"track_id":1,"detected_at":"2026-10-17T18:00:00Z"}'
```

## Repo layout

```
vision/      run.py (main loop), detector.py (collapse logic), help_watch.py (camera-confirmed help),
             config.py (all thresholds), bytetrack.yaml
backend/     app/main.py (API + WebSocket), app/db.py (SQLite)
dashboard/   src/App.jsx (responder dashboard)
data/        test videos (not committed; see data/README.md)
PLAN.md      master checklist
```

## Event format (vision → backend)

`POST /events`
```json
{
  "camera_id": "cam-1",
  "location": "Demo venue - Room A",
  "type": "possible_fall",
  "urgency": "high",
  "summary": "Possible fall, person not getting up",
  "reasons": [
    "Went down fast: hips dropped 1.1 body-lengths in 0.6s",
    "Lying down for 3s (torso 85° from upright)",
    "Very little movement in the last 2s"
  ],
  "track_id": 3,
  "detected_at": "2026-10-17T18:00:00+00:00",
  "went_down_at": "2026-10-17T17:59:57+00:00",
  "metrics": {"down_seconds": 3.0, "torso_angle_deg": 85, "drop_torsos": 1.1, "movement_torsos_per_sec": 0.02, "hidden_fraction": 0.0}
}
```
`type` is `possible_fall` (fast fall, high urgency, alerts after 3 s down) or `person_down` (slow collapse, medium urgency, alerts after 12 s down). `went_down_at` is when the person went down, so we can measure the whole gap until help arrives.

## Confirming help actually reaches the person

Every alert is tracked until someone is confirmed with the person:

```
went down → alert (open) → responder accepts (acknowledged) → responder arrives (on_scene) → resolved + outcome
                 │ nobody accepts in 30 s               │ accepted, nobody arrives in 90 s
                 ▼                                      ▼
           backup responder notified              escalated again
```

- **Responder confirms:** `POST /events/{id}/acknowledge`, then `/arrive` ("I'm here"), then `/resolve` with an `outcome`: `person_ok`, `helped_on_site`, `medical_help_called` or `person_gone`. Resolving requires arriving first. `/dismiss` (with a `reason`) is for false alarms.
- **Camera confirms:** after an alert, if another person stays next to the person for 3 s, the vision script calls `POST /events/{id}/help-detected`.
- **Watchdog:** escalates alerts that stall. Timeouts are set with `ACK_TIMEOUT_SECONDS` and `ARRIVAL_TIMEOUT_SECONDS` (defaults 30 and 90).
- **Camera heartbeat:** the vision script calls `POST /cameras/{id}/heartbeat` every 2 s; the dashboard warns when a camera goes quiet.
- **Stats:** `GET /stats` returns % of alerts where help reached the person, median time from going down to help, camera-verified count and escalations.

A second alert for the same person on the same camera within 2 minutes is suppressed.

## Notes

- Detection thresholds in `vision/config.py` are prototype values to tune on our clips. They are not medically validated.
- The system never calls emergency services itself; escalation is a human decision on the dashboard.
- Test footage: [UR Fall Detection Dataset](http://fenix.ur.edu.pl/mkepski/ds/uf.html) (non-commercial academic use, attribution required).
