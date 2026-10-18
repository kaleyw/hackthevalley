# TTC incident maps and restricted demo handoff

## Existing behavior inspected and preserved

- `vision/run.py` posts incidents to `POST /events`. `backend/app/db.py` stores
  incidents, action history, and camera heartbeats in `backend/events.db`.
- Vision camera ID is configured in `vision/config.py`; its display location
  comes from `CAMERA_LOCATION` in `.env`. Existing heartbeat records need no new fields.
- The lifecycle remains open → acknowledged → on_scene → resolved, with dismissal
  available for active incidents. Arrival is required before resolving, an outcome
  is required for resolution, and dismissal needs a reason. Direct arrival from
  open remains supported. Responder names are browser-local labels, not authentication.
- **There is no automatic 911 call or emergency-call integration in this repository.**
  Automatic escalation is the existing watchdog: open incidents older than
  `ACK_TIMEOUT_SECONDS` (default 30) escalate once to level 1; acknowledged incidents
  older than `ARRIVAL_TIMEOUT_SECONDS` (default 90), with neither arrival nor
  camera-confirmed help, escalate until level 2. The watchdog checks every 2 seconds.
  Comparisons, thresholds, and conditions have not changed.
- The existing manual Escalate endpoint increments the same level, capped at 2,
  and records/broadcasts the action. “Backup responder notified” / “Supervisor
  notified” are existing log/UI labels; no SMS, email, telephony provider,
  emergency recipient, or delivery receipt exists.
- Existing dashboard updates still use WebSockets with reconnect/catch-up.
  New map context polls every 2 seconds independently. Location failures do not
  disable existing cards, actions, notifications, or the watchdog.

## Run locally

Use the existing Python environment and Node setup. Install the new Leaflet
package and build the responder page:

```bash
source .venv/bin/activate
npm install --prefix dashboard
npm run build --prefix dashboard
```

Add these entries to your existing `.env`; do not overwrite existing settings:

```dotenv
MAP_OPERATOR_KEY=replace-with-a-random-secret-of-at-least-24-characters
MAP_RESPONDER_ORIGIN=http://localhost:8001
```

Generate your own secret with:

```bash
python -c "import secrets; print(secrets.token_urlsafe(32))"
```

Run each service in a separate terminal from the repository root:

```bash
source .venv/bin/activate
uvicorn backend.app.main:app --reload --port 8000
```

```bash
npm run dev --prefix dashboard
```

```bash
source .venv/bin/activate
uvicorn backend.app.responder:app --port 8001
```

Continue running vision normally if desired; its detection code, thresholds,
models, and timers were not modified for the map feature.

The restricted service serves the **built** UI, so rebuild the dashboard after
frontend edits. It shares the SQLite database and map key with the main backend;
run one main backend worker for this single-process simulator demo.

## Live webcam rehearsal at a configured Union Station location

The ordinary demo script creates a synthetic alert without camera detection.
For a live presentation, configure the webcam first **without creating an alert**:

1. Start the main backend, dashboard, and responder service as described above.
2. Open `.env` with `open -e .env` and set
   `CAMERA_LOCATION=Union Station - simulated webcam location`, preserving the map key.
3. Assign approximate Union station metadata to the webcam camera ID:

   ```bash
   python scripts/map_demo.py --kind platform --camera-id cam-1 --configure-only
   ```

   This only configures metadata. It does not create an incident, start a timer,
   escalate, or start the train simulator. A mocked regression checks both kinds.
4. Dismiss active rehearsal incidents with a reason before repeating. Existing
   active duplicates for the same camera/track can otherwise reuse an old incident.
5. Restart vision so it picks up the display location:

   ```bash
   python -u vision/run.py --device cpu --debug
   ```

   Use `--device mps` instead if it works better on the Mac. The current runner's
   `--debug` flag shows detector measurements in the preview.
6. Verify the dashboard says **Live** and `cam-1` is online before acting.
   Reconnecting/offline badges mean the demo is not ready. Check
   `http://localhost:8000/health`, the backend terminal, and the vision terminal.
7. Safely lower onto a mat and stay in a clearly lying posture. Watch the preview
   countdown, then verify the camera-created incident appears and its map highlights
   Union automatically. No synthetic incident command is needed during this step.
8. Demonstrate Escalate → Prepare / reuse map link → Open demo responder view,
   then Accept → a teammate stays nearby → I'm here → Resolve with an outcome.
   Camera-confirmed proximity is not proof of medical assistance.

Describe it honestly: **live camera detection, a configured simulated Union
camera location, and a demo responder handoff**. This is not a live TTC camera,
device geolocation, verified platform coordinate, or emergency-service delivery.
For a shorter main presentation, rehearse the platform flow first; demonstrate
moving trains separately as a simulator extension.

## Platform demo (no camera needed)

```bash
source .venv/bin/activate
python scripts/map_demo.py --kind platform
```

Open http://localhost:5173. The panel opens automatically for the incident,
with a marker at the official approximate UNION station location, not an
invented platform or entrance point. Click the marker or its card's “View on map”
control to select the existing incident.

All located alerts are shown together. Incidents sharing coordinates appear in
a labelled stack with active incidents first, so a dismissed Union alert cannot
cover a new Union alert. Selecting incident details leaves the other markers visible.
The view fits all incident locations when new incidents arrive; **Fit all alerts**
restores the overview after manually panning/zooming. Missing locations are counted
but never assigned invented coordinates.

1. Enter your `MAP_OPERATOR_KEY` in the map panel (stored only for the browser session).
2. Click the **existing Escalate** button. The existing escalation commits and
   broadcasts, then the additive hook prepares a reusable map handoff record.
   Leaving a fresh alert unaccepted for the existing timeout exercises the same
   handoff via automatic escalation. Neither path makes an emergency call.
3. Click **Prepare / reuse map link**, then **Copy map link** or **Open demo
   responder view**. The view on port 8001 is read-only and clearly labelled demo.
4. Copy the concise textual briefing. It remains available when map geography fails.
5. Test **Revoke link**; the responder view rejects it on the next poll. **Renew
   link** explicitly replaces it and invalidates the previous token. Default expiry
   is one hour; reading/opening a link never restarts incident timers or token expiry.
6. Complete Accept → I'm here → Resolve with an outcome, or Dismiss with a reason.

Repeating the script uses the existing two-minute active duplicate suppression.
Resolve/dismiss the previous incident first if you want a new demo incident.

## Train and connectivity demo

```bash
python scripts/map_demo.py --kind train
```

This creates a separate demo camera associated with **DEMO-T1 / demo-car-1**, starts
simulated updates, and creates an incident with its detection snapshot. It never
reconfigures `cam-1` unless you explicitly supply `--camera-id cam-1`.

- In the panel open **Configure camera location & train demo**.
- The distinct train marker follows simulated Union → King → Queen → Dundas
  travel and back; it is **not a verified person location**. The detection snapshot
  stays fixed and is drawn as a dashed ring when coordinates were available.
- **Pause movement** keeps sending fresh, stationary samples.
- **Disconnect telemetry** stops samples, freezes movement, and retains coordinates.
  After 10 seconds, the latest position is explicitly stale.
- **Start / reconnect** resumes from the saved simulated position without jumping
  forward to account for disconnected time.
- Select a station, enter a staff-observed platform label/direction, and use
  **Confirm transfer to selected platform** after staff actually confirms transfer.
  This adds a timestamped location record; it does not accept, arrive, resolve,
  escalate, or modify the original snapshot.
- To test network failure, stop the main backend. The map retains its last context
  and stops animation. Restart to reconcile; no extra incidents or escalations are
  created by map polling. Backend downtime still has the same consequences for
  existing alert handling as before this feature.

Animation interpolates only between two fresh, known samples and never extrapolates
from a timetable. Station-to-station simulator travel is synthetic, not track geometry.
The replaceable provider interface lives in `backend/app/maps.py`.

## Camera metadata and late information

Optional metadata is stored in `map_cameras`, separate from existing heartbeat
records. Configure it before an incident to capture it in the immutable snapshot:

```json
{
  "kind": "platform",
  "station_id": "1036",
  "platform_label": "Staff-configured northbound platform",
  "direction": "northbound",
  "line": "1",
  "source": "configured"
}
```

Use `PUT /maps/cameras/{camera_id}` with `X-Map-Operator-Key`. Stations can be
resolved by official station ID or exact station name (case-insensitive). Optional
coordinates require lat, lon, and an explicit precision: `station_centroid`,
`verified_platform`, `verified_meeting_point`, or `approximate`. Staff-supplied
verified coordinates must actually be verified; this application cannot verify them.
A meeting point requires a description and `verified: true`; coordinates are optional.
Train cameras additionally require `train_id` and can include `car_id`.

The panel's **Save location** configures the camera for future detections and
adds supplemental context to the selected incident. `PUT /maps/events/{id}/location`
can add/correct late information independently. Neither overwrites the snapshot.
Legacy incidents and missing configurations show “location unavailable”; no historical
location is invented. A previously prepared responder link reads the updated context.

## Security and delivery boundaries

- Shared links use a 256-bit random nonce plus an HMAC signature bound to incident
  ID and server-stored expiry. The database stores the nonce and revocation state;
  the signature is derived using `MAP_OPERATOR_KEY`. Tokens are incident-specific,
  expire server-side, and can be revoked. Key rotation also invalidates old signatures.
- Tokens travel in the URL **fragment**, then a request header, not a query string.
  The responder service sends no-store/no-referrer headers and a restrictive CSP.
- The responder service exposes only its read-only incident endpoint, built UI
  assets, and public geographic data. It does not expose the full dashboard,
  event lists, action routes, video, responder names, contacts, or event logs.
- Keep ports **8000 and 5173 private/trusted**: their existing unauthenticated
  dashboard/API behavior was deliberately preserved. Share only the separate
  responder origin. For another device, configure `MAP_RESPONDER_ORIGIN` to a
  reachable HTTPS origin and proxy only the responder service there; localhost
  links work only on the same machine. This change does not deploy public hosting.
- A link is generated/prepared, never claimed sent or acknowledged. Handoff
  delivery is `unsupported`; attempted/sent/acknowledged timestamps remain null.
  Opening it is not acknowledgment. There is no supported outbound payload to
  attach it to and no public 911 map API.
- Map hooks run after committed escalation and are exception-isolated. Repeated
  handoff preparation reuses the same record, never repeats escalation, and never
  silently renews expired/revoked tokens. Failures are logged separately.
  If preparation failed, opening/polling the map after recovery reconciles the
  handoff from the stored escalation level without repeating escalation.
- Link possession grants read access until expiry/revocation. Do not paste links
  or the operator key into public channels. No new personal contact fields exist.

## Geography and optional routing

See `dashboard/public/maps/SOURCES.md` for official layers, attribution, retrieval
method, coverage caveats, and synthetic demo movement. All geometry is stored
locally; no tile or live-feed network dependency is required. The dataset is not
proof of current operating service or verified emergency access.

Routing is intentionally omitted. No verified responder bases or entrances have
been configured, and the app makes no claims about route optimization, responder
availability, or transporting an unresponsive person.

## Verification

```bash
python -m pip install -r requirements-test.txt
python -m unittest backend.test_maps -v
node --test dashboard/src/mapLayout.test.js
npm run build --prefix dashboard
```

The isolated tests cover original lifecycle actions, exact escalation boundaries,
manual/automatic handoffs, map failure isolation, immutable snapshots, late location,
simulator pause/disconnect/reconnect, stale telemetry, coordinate validation, token
scope/expiry/revocation/renewal, and the responder service's limited route surface.
No external emergency services are contacted.

## Implementation files

- `backend/app/main.py`: additive snapshot capture, post-escalation handoff hook,
  and separately managed simulator task. Existing transitions/watchdog queries unchanged.
- `backend/app/maps.py`: map API, briefing generation, signed/revocable links,
  recovery reconciliation, and replaceable simulated train provider.
- `backend/app/map_store.py`: separate SQLite map configuration/snapshot/handoff/train tables.
- `backend/app/map_models.py`: optional validated geographic metadata.
- `backend/app/responder.py`: isolated read-only responder service.
- `dashboard/src/IncidentMap.jsx`, `ResponderView.jsx`, `map.css`: vector map,
  location panel, restricted UI, simulator controls, freshness and offline handling.
- `dashboard/src/App.jsx`, `main.jsx`, `dashboard/index.html`: integrated panel,
  responder page selection, and referrer policy; existing action handlers retained.
- `dashboard/package.json`, `package-lock.json`: Leaflet dependency; no dependency upgrades requested.
- `dashboard/public/maps/`: attributed local station/route GeoJSON and sources.
- `backend/test_maps.py`, `requirements-test.txt`: isolated acceptance tests.
- `scripts/map_demo.py`: explicit synthetic platform/train incident creation.
- `.env.example`, `README.md`, this guide: configuration and safe demo instructions.

No files under `vision/` were changed for this feature.
