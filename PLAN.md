# Hack the Valley: Master Plan

**Idea:** Detect a possible fall or collapse from a camera feed, then automatically start a welfare check that a responder must acknowledge.

**Owners:** Vision: ____ · Backend: ____ · Frontend: ____ · Pitch/Write-up: ____

---

## 0. Setup
- [ ] Everyone has access to the GitHub repo (kaleyw/hackthevalley)
- [ ] Agree on the stack (Python + OpenCV + YOLO Pose, FastAPI backend, frontend framework: ____)
- [ ] Create the folder structure: `vision/`, `backend/`, `dashboard/`, `data/` (keep `data/` out of git)
- [ ] Add `requirements.txt` and a quick-start section in the README
- [ ] Make a shared doc or channel for links, decisions and blockers

## 1. Research and scope
- [ ] Find 3–5 stats on falls and slow emergency response (with sources) for the pitch
- [ ] Pick the specific setting (e.g. transit station, campus building, care home, public washroom)
- [ ] Write a one-sentence problem statement
- [ ] Write a one-sentence solution statement
- [ ] Decide what is in scope for the MVP (one fixed camera, one or two people, side or angled view)
- [ ] List what is out of scope (calling 911, real CCTV access, medical diagnosis)
- [ ] Check the hackathon's judging criteria and prize tracks, and note which ones we're aiming for

## 2. Name and branding
- [ ] Brainstorm names (shortlist of 5)
- [ ] Pick a name and check the domain or Devpost name isn't taken
- [ ] Make a simple logo and colour scheme
- [ ] Write a one-line tagline

## 3. Vision pipeline
### 3a. Video ingestion
- [ ] Read frames from a video file with OpenCV
- [ ] Read frames from the webcam
- [ ] Add a configurable camera location (e.g. "Demo venue — Room A")

### 3b. Pose extraction
- [ ] Install Ultralytics and run `yolo11n-pose.pt` on a test clip
- [ ] Run on the Mac GPU (`device="mps"`)
- [ ] Draw the skeleton overlay on each frame
- [ ] Log hip and shoulder keypoints per frame
- [ ] **Go/no-go:** keypoints are stable on a side-view clip (if not, narrow the camera conditions)

### 3c. Tracking
- [ ] Turn on tracking with ByteTrack (`model.track(..., tracker="bytetrack.yaml")`)
- [ ] Confirm each person keeps the same ID across frames
- [ ] Store a short history of keypoints per track ID (last ~2–3 seconds)

### 3d. Fall-like sequence detection
- [ ] Measure body size per person (e.g. shoulder-to-hip distance) to normalise movement
- [ ] Signal 1: rapid downward movement of hips/shoulders
- [ ] Signal 2: torso angle changes toward horizontal
- [ ] Signal 3: person stays low afterward
- [ ] Signal 4: little movement afterward (adds context, never required)
- [ ] Treat missing keypoints as "visibility uncertain", not "motionless"
- [ ] Build the state machine: Monitoring → Possible fall → Persistent concerning posture → Alert
- [ ] Put all thresholds and time windows in one config file
- [ ] Send a fall event (JSON) to the backend when an alert fires

## 4. Event management (backend)
- [ ] Agree on the event JSON format with the vision and frontend owners
- [ ] Set up the FastAPI server
- [ ] Create the events store (id, timestamp, camera location, track ID, status, clip path, history)
- [ ] Statuses: `open` → `acknowledged` → `resolved`, plus `dismissed` and `escalated`
- [ ] Endpoint: create event (called by the vision pipeline)
- [ ] Endpoint: list events and get one event
- [ ] Endpoints: acknowledge, dismiss (with reason), escalate, resolve
- [ ] Keep a log of every status change (who, what, when)
- [ ] Duplicate suppression: one alert per ongoing event for the same person/camera
- [ ] Save a short event clip (a few seconds before and after)

## 5. Responder dashboard
- [ ] Mockup or wireframe of the main screen
- [ ] Live list of events with status, location and time
- [ ] Event detail view with clip or preview
- [ ] Buttons: Accept, Dismiss (with reason), Escalate
- [ ] Alert sound and visual highlight for new events
- [ ] Event history/log view
- [ ] Optional: live camera view with skeleton overlay

## 6. Live updates
- [ ] WebSocket from backend to dashboard (or polling as a fallback)
- [ ] New events appear without refreshing
- [ ] Status changes sync across open dashboards

## 7. Notifications and escalation
- [ ] Dashboard alert works first
- [ ] Backup responder is notified if nobody acknowledges within ___ seconds
- [ ] Optional: email or SMS alert (only if setup is quick, e.g. Twilio trial)
- [ ] "Contact emergency services" is a simulated action after human review (never auto-call 911)

## 8. Gemini API (stretch)
- [ ] Decide the use case (e.g. second-opinion check on the event clip to cut false alarms, or a plain-language event summary for the responder)
- [ ] Get an API key and keep it in `.env` (never commit it)
- [ ] Send only the short event clip or frames, never the full feed
- [ ] Keep output factual ("person on the floor, not getting up"); no medical claims
- [ ] Make the system still work if the Gemini call fails or is slow

## 9. Privacy and safety
- [ ] Process video locally; only save short clips when an event fires
- [ ] Blur faces in the dashboard preview, or show the skeleton only
- [ ] Auto-delete clips after a set time (e.g. 24 hours) in the design
- [ ] Note the dataset license (UR Fall Detection: non-commercial, with attribution)

## 10. Testing
- [ ] Download test clips (UR Fall Detection Dataset + any other public fall footage)
- [ ] Split clips into a tuning set and a held-out test set
- [ ] Test case: walking normally (should not alert)
- [ ] Test case: sitting down quickly (should not alert)
- [ ] Test case: bending to pick something up (should not alert)
- [ ] Test case: kneeling or stretching (should not alert)
- [ ] Test case: lying down on purpose (should not alert, or low priority)
- [ ] Test case: fall, then staying down (should alert)
- [ ] Test case: fall, then getting up (should detect but may cancel)
- [ ] Test case: person partly leaves the frame
- [ ] Test case: temporary occlusion (someone walks in front)
- [ ] Test case: two or more people in frame, one falls
- [ ] Record results: falls detected, false alerts, time to alert
- [ ] Write down known failure cases honestly
- [ ] Never ask teammates to perform real falls

## 11. Integration and demo
- [ ] End-to-end test: video → detection → event → dashboard → acknowledge
- [ ] Test the backup escalation path
- [ ] Prepare demo clips that reliably trigger (and ones that correctly don't)
- [ ] Record a backup demo video in case the live demo fails
- [ ] Do a full demo run-through at least twice

## 12. Presentation
- [ ] Slide: problem + stats
- [ ] Slide: solution + how it works (diagram)
- [ ] Slide: live demo
- [ ] Slide: results from testing (honest numbers)
- [ ] Slide: privacy and safety
- [ ] Slide: limitations and future work (fine-tuning on overhead CCTV, real responder integration)
- [ ] Slide: team
- [ ] Practise the pitch and time it
- [ ] Prepare answers to likely judge questions (false alarms, privacy, accuracy, 911)

## 13. Write-up and submission
- [ ] Devpost: inspiration, what it does, how we built it
- [ ] Devpost: challenges, accomplishments, what we learned, what's next
- [ ] Add screenshots, demo video and repo link
- [ ] Clean up the README (setup, how to run, architecture, credits, dataset attribution)
- [ ] Submit before the deadline: ____
