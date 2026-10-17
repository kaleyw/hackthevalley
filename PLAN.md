# Hack the Valley: Master Plan

**Idea:** A fixed security camera detects when someone collapses or falls and doesn't get up, then automatically starts a welfare check that a responder must acknowledge. It's for people who can no longer ask for help themselves.

**Target challenge:** Project KAZE (main). Its judges prioritize safety, dignity, privacy and autonomy. PointClickCare "Catch It Early" is a possible second entry (our "why this alert" explanations earn its bonus), but we're not reframing for it.

**Setting:** Transit station and university campus buildings. One fixed security camera, shown by a webcam mounted high and angled down.

**Owners:** Vision: ____ · Backend: ____ · Frontend: ____ · Pitch/Write-up: ____

---

## 0. Setup
- [ ] Everyone has access to the GitHub repo (kaleyw/hackthevalley)
- [x] Agree on the stack (Python + OpenCV + YOLO Pose + ByteTrack, FastAPI + SQLite backend, React + Vite + Tailwind dashboard)
- [x] Create the folder structure: `vision/`, `backend/`, `dashboard/`, `data/` (keep `data/` out of git)
- [x] Add `requirements.txt` and a quick-start section in the README
- [x] Make a shared doc for links, decisions and blockers (Team Hub Google Doc)

## 1. Research and scope
- [ ] Find 3–5 stats (with sources) on drink spiking, severe intoxication and people collapsing in public, and on delays before help arrives
- [x] Pick the specific setting (transit station + campus building, one fixed camera)
- [ ] Write a one-sentence problem statement (the gap between someone becoming unable to help themselves and someone noticing)
- [ ] Write a one-sentence solution statement
- [x] Decide what is in scope for the MVP (one fixed camera, one or two people, camera mounted high)
- [ ] List what is out of scope (calling 911, real TTC/campus CCTV access, figuring out *why* someone collapsed, identifying people)
- [x] Check the hackathon's judging criteria and prize tracks (KAZE main, PointClickCare maybe)

## 2. Name and branding
- [ ] Brainstorm names (shortlist of 5)
- [ ] Pick a name and check the Devpost name isn't taken
- [ ] Make a simple logo and colour scheme
- [ ] Write a one-line tagline

## 3. Vision pipeline
### 3a. Video ingestion
- [x] Read frames from a video file with OpenCV
- [ ] Test with the webcam mounted high and angled down, like a security camera
- [x] Add a configurable camera location (in `.env`)

### 3b. Pose extraction
- [x] Install Ultralytics and run `yolo11n-pose.pt` on a test clip
- [x] Run on the Mac GPU (`device="mps"`)
- [x] Draw the skeleton overlay on each frame
- [ ] **Go/no-go:** keypoints are stable from the high camera angle (if not, lower the camera or try `yolo11s-pose.pt`)

### 3c. Tracking
- [x] Turn on tracking with ByteTrack (`vision/bytetrack.yaml`, tuned to keep IDs through falls)
- [ ] Confirm each person keeps the same ID in a real two-person webcam test
- [x] Store a short history of keypoints per track ID

### 3d. Collapse and fall detection
- [x] Measure body size per person to normalise movement
- [x] Fast-fall path: hips drop fast + torso horizontal + stays down 3 s → "Possible fall" (high urgency)
- [x] Slow-collapse path: ends up lying at any speed + stays down 12 s → "Person down" (medium urgency)
- [x] Measure movement after going down (adds context, never required)
- [x] Treat missing keypoints as "visibility uncertain", not "motionless"
- [x] Plain-language "why this alert" reasons on every alert
- [x] Put all thresholds and time windows in `vision/config.py`
- [x] Send events (JSON) to the backend when an alert fires
- [ ] Tune thresholds with the webcam angled down (a high camera changes how torso angles look)
- [ ] Stretch: detect slumping while seated (e.g. on a bench) and not moving

## 4. Event management (backend)
- [x] Agree on the event JSON format (in the README)
- [x] Set up the FastAPI server
- [x] Create the events store (SQLite: id, time, location, track ID, status, urgency, reasons, history)
- [x] Statuses: `open` → `acknowledged` → `resolved`, plus `dismissed` and `escalated`
- [x] Endpoints: create, list, get, acknowledge, dismiss (with reason), escalate, resolve
- [x] Keep a log of every status change (who, what, when)
- [x] Duplicate suppression: one alert per ongoing event for the same person/camera
- [ ] Save a skeleton-only snapshot when an alert fires (no faces, no raw footage)
- [ ] Camera heartbeat: mark a camera offline if the vision script stops sending updates

## 5. Responder dashboard
- [x] Live list of active alerts and history
- [x] Urgency badge and "Why this alert" list on each alert
- [x] Buttons: Accept, Escalate, Dismiss (with reason), Resolve
- [x] Alert sound and visual highlight for new alerts
- [x] Event history/log view (who did what, when)
- [ ] Show the skeleton-only snapshot on each alert
- [ ] Show a "Camera offline" warning
- [ ] Show "Backup notified" when an alert auto-escalates
- [ ] Check the dashboard works at phone width (responders on the move)

## 6. Live updates
- [x] WebSocket from backend to dashboard, with auto-reconnect
- [x] New alerts appear without refreshing
- [x] Status changes sync across open dashboards

## 7. Notifications and escalation
- [x] Dashboard alert works
- [ ] Backup escalation: if nobody accepts within ___ seconds, escalate automatically and notify a backup responder
- [ ] Optional: SMS or email to the on-duty responder (only if setup is quick, e.g. Twilio trial)
- [ ] "Contact emergency services" is a simulated action after human review (never auto-call 911)

## 8. Gemini API (stretch, only after 4–7)
- [ ] Use case: second-opinion check on the skeleton snapshot to cut false alarms
- [ ] Only describe posture ("person on the floor, not moving"); never guess about intoxication, drugs or medical causes
- [ ] Get an API key and keep it in `.env` (never commit it)
- [ ] The system still works if the Gemini call fails or is slow

## 9. Privacy, dignity and safety
- [x] Process video locally on the device
- [ ] Show only the skeleton on the dashboard (no faces, no identity)
- [ ] Keep no footage except the snapshot when an alert fires; auto-delete after a set time in the design
- [x] Neutral wording: "person may need help", never "possibly drugged"
- [ ] Response is a welfare check, never enforcement (e.g. someone sleeping in a station); say this in the pitch
- [ ] Note the dataset license (UR Fall Detection: non-commercial, with attribution)

## 10. Testing
- [ ] Mount the webcam high and angled down for all tests
- [ ] Get public fall footage (UR Fall Detection Dataset) for fast-fall tests
- [ ] Split clips into a tuning set and a held-out test set
- [ ] Should not alert: walking, sitting down quickly, bending to pick something up, kneeling, stretching
- [ ] Should alert (high): fast fall, then staying down
- [ ] Should alert (medium): slow collapse or sliding down a wall, then staying down
- [ ] Should cancel: going down, then getting up within the wait time
- [ ] Judgement call: someone lying on a bench to sleep (welfare check, medium urgency)
- [ ] Edge cases: person partly leaves the frame, someone walks in front, two people and one collapses
- [ ] Record results: alerts caught, false alerts, time to alert
- [ ] Write down known failure cases honestly
- [ ] Never ask teammates to perform real falls (slow collapses onto a mat are safe to act out)

## 11. Integration and demo
- [x] End-to-end test: event → backend → dashboard → acknowledge
- [ ] Full live test: webcam → detection → dashboard → acknowledge
- [ ] Test the backup escalation path
- [ ] Rehearse the demo: teammate slowly collapses onto a mat, alert appears with reasons, responder accepts
- [ ] Record a backup demo video in case the live demo fails
- [ ] Do a full demo run-through at least twice

## 12. Presentation
- [ ] Slide: the gap (someone can't ask for help; nobody notices in time) + stats
- [ ] Slide: solution + how it works (camera → pose → detection → welfare check)
- [ ] Slide: live demo
- [ ] Slide: why each alert fires (explanations) and how responders act
- [ ] Slide: safety, dignity, privacy and autonomy (KAZE's four priorities, one point each)
- [ ] Slide: results from testing (honest numbers)
- [ ] Slide: limitations and future work (fine-tuning on real CCTV angles, multi-camera, real responder integration)
- [ ] Slide: team
- [ ] Practise the pitch and time it
- [ ] Prepare answers to likely judge questions (false alarms, privacy, people sleeping in stations, accuracy, why not call 911)

## 13. Write-up and submission
- [ ] Devpost: inspiration, what it does, how we built it
- [ ] Devpost: challenges, accomplishments, what we learned, what's next
- [ ] Add screenshots, demo video and repo link
- [ ] Select the Project KAZE challenge (and PointClickCare if allowed)
- [ ] Clean up the README (setup, how to run, architecture, credits, dataset attribution)
- [ ] Submit before the deadline: ____
