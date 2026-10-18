# TTC incident map and responder links

The dashboard shows every alert on an offline TTC map (no external map tiles), at the
station its camera is at. Cameras default to **Union Station** (`CAMERA_STATION` in `.env`);
staff can change a camera's station from the map panel ("Change camera location").
Station points are approximate station locations, never invented platform or entrance points.

## Setup

1. Add to `.env` (only needed for responder links and changing camera locations):

   ```dotenv
   MAP_OPERATOR_KEY=   # a random secret of at least 24 characters
   MAP_RESPONDER_ORIGIN=http://localhost:8001
   ```

   Generate a key with `python -c "import secrets; print(secrets.token_urlsafe(32))"`.

2. Build the dashboard once (the responder page serves the built files), then start the
   read-only responder server next to the main backend and dashboard:

   ```bash
   npm run build --prefix dashboard
   .venv/bin/uvicorn backend.app.responder:app --port 8001
   ```

## Sharing an alert with a responder

1. Enter `MAP_OPERATOR_KEY` in the map panel (kept only for the browser session).
2. Select an alert and click **Prepare / reuse map link**, then **Copy map link** or
   **Open responder view**. Escalating an alert prepares the link automatically.
3. The responder page (port 8001) is read-only and shows only that alert's location and
   status: no camera video, responder names, or event log.
4. **Revoke link** disables it on the next refresh; **Renew link** replaces it. Links
   expire after one hour.

Links are never sent automatically: there is no SMS, email or emergency-service delivery.

## Tests

```bash
.venv/bin/pip install -r requirements-test.txt
.venv/bin/python -m unittest backend.test_maps -v
node --test dashboard/src/mapLayout.test.js
```
