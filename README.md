# Hack the Valley: Fall Alerts

Detects a possible fall or collapse from a camera feed, then starts a welfare check that a responder has to acknowledge.

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
| Fall detection | Temporal rules + state machine over keypoints (`vision/detector.py`) |
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
  -d '{"camera_id":"cam-1","location":"Demo venue - Room A","track_id":1,"detected_at":"2026-10-17T18:00:00Z","lying_seconds":3}'
```

## Repo layout

```
vision/      run.py (main loop), detector.py (fall logic), config.py (all thresholds), bytetrack.yaml
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
  "track_id": 3,
  "detected_at": "2026-10-17T18:00:00+00:00",
  "lying_seconds": 3.0,
  "torso_angle_deg": 84
}
```
Statuses: `open` → `acknowledged` → `resolved`, plus `escalated` and `dismissed` (dismiss needs a reason). Actions: `POST /events/{id}/acknowledge|escalate|dismiss|resolve` with `{"actor": "name", "reason": "..."}`. A second alert for the same person on the same camera within 2 minutes is suppressed.

## Notes

- Detection thresholds in `vision/config.py` are prototype values to tune on our clips. They are not medically validated.
- The system never calls emergency services itself; escalation is a human decision on the dashboard.
- Test footage: [UR Fall Detection Dataset](http://fenix.ur.edu.pl/mkepski/ds/uf.html) (non-commercial academic use, attribution required).
