# How HEADS-UP works

The detailed reference behind the [README](../README.md): detection, the alert lifecycle,
and the API between the camera, backend and dashboard.

## Detection (`vision/`)

`vision/run.py` runs Ultralytics YOLO Pose with ByteTrack tracking on each camera frame and
feeds every tracked person's keypoints to a per-person state machine in `vision/detector.py`:

- **Lying down** means the torso is near horizontal (60°+ from upright), or the torso is visibly
  tilted (35°+) and the body's box is clearly wider than tall. Frames where the shoulders and
  hips aren't visible are "uncertain" and never count either way.
- **Fast fall:** hips drop at least 0.8 torso-lengths within 0.6 s, then the person stays down
  for 3 s → `possible_fall`, high urgency.
- **Slow collapse:** ends up lying at any speed and stays down for 12 s → `person_down`, medium urgency.
- **Getting up** for 2 s cancels a pending alert. A glitchy frame (someone walking past) doesn't.
- If the tracker gives a person on the ground a new ID, the new ID takes over their countdown.
- Every alert carries plain-language reasons and the numbers behind them.
- After an alert, `vision/help_watch.py` watches for someone staying next to the person for 10 s
  (camera-confirmed help); someone walking past restarts the count.

All thresholds are in `vision/config.py`. They are prototype values, not medically validated.
Each run writes a per-frame CSV log to `data/logs/` for tuning.

## Event format (vision → backend)

`POST /events`
```json
{
  "camera_id": "cam-1",
  "location": "Union Station",
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
                 │ nobody accepts in 60 s
                 ▼
           backup responder notified
```

- **Responder confirms:** `POST /events/{id}/acknowledge`, then `/arrive` ("I'm here"), then `/resolve` with an `outcome`: `person_ok`, `helped_on_site`, `medical_help_called` or `person_gone`. Resolving requires arriving first. `/dismiss` (with a `reason`) is for false alarms.
- **Camera confirms:** after an alert, if another person stays next to the person for 10 s, the vision script calls `POST /events/{id}/help-detected`. Someone walking past (gone for 1.5+ s) restarts the count.
- **Watchdog:** if nobody accepts an alert within `ACK_TIMEOUT_SECONDS` (default 60) and the camera doesn't already see someone with the person, a backup responder is notified. Once someone accepts, it doesn't auto-escalate: they know where to go. Responders can still click Escalate.
- **Speaker for bystanders:** when an alert fires, the backend chimes and says *"Attention please. Someone near [CAMERA_LOCATION] may need help. If you are nearby, please check on them. Staff have been notified."* It repeats every 20 s (saying "Staff are on the way" once accepted), says *"Thank you. Help has arrived."* when someone is with them, then stops. Several people down at the same location are announced together ("2 people near ..."), and each one getting help is announced separately ("Thank you. Help has arrived near ... One more person near ... still needs help."). If the person gets back up after the alert, the camera calls `POST /events/{id}/got-up`: the speaker says *"Update: the person near ... is now back on their feet. Staff will still check on them."* and stops asking bystanders, while the alert stays open for staff. If they go down again, it's announced again right away. It names the location only, never describes the person. Uses the Mac's built-in `say`, so it plays through the Mac's current sound output (laptop speakers or a Bluetooth speaker like a JBL). Responders can silence it from the dashboard (`POST /events/{id}/silence`). Turn it off with `SPEAKER_ENABLED=0`.
- **Dashboard dings for security:** a ding-dong for a new alert; an urgent ding when an alert escalates to backup; a low warning tone when a camera goes offline. Browsers only allow sound after a click, so the dashboard shows a "click to turn on alert sounds" banner until you do. There's a mute button in the header.
- **Camera heartbeat:** the vision script calls `POST /cameras/{id}/heartbeat` every 2 s; the dashboard warns when a camera goes quiet.
- **Stats:** `GET /stats` returns % of alerts where help reached the person, median time from going down to help, camera-verified count and escalations.

A second alert for the same person on the same camera within 2 minutes is suppressed.

## Map and responder links

See [MAP.md](MAP.md).
