# OPAS - Orbital Proximity Alert System

OPAS is a lightweight toolchain for assessing orbital collision risk for launch trajectories and scanning for safe launch windows. It combines a Python FastAPI backend (TLE ingestion, proximity checks, optional native math acceleration) with a React + Vite frontend that visualizes debris and trajectories on an interactive globe.

## Contents
- Features
- Project layout
- Quickstart (local)
- Configuration
- API reference
- Data model
- Native math extension
- Deployment
- Security
- License

## Features
- FastAPI backend with `/debris`, `/alert`, and `/safe-windows` endpoints.
- Ingestion pipeline that pulls recent Space-Track TLEs, computes subpoints with Skyfield, and stores GeoJSON points in MongoDB with a `2dsphere` index.
- Collision checks that compute 3D ECEF distances, plus optional TLE age-based uncertainty and threat scoring.
- Safe-window scanning with interval close-approach refinement between trajectory waypoints, altitude-dependent screening radii, 10-second candidate checks and a final 5-second launch validation pass.
- Live request progress, correlated server/browser logs, downloadable verification details and endpoint/duration/coverage checks for returned windows.
- React + Vite UI using `react-globe.gl` and Three.js, with interactive tooltips and report export.
- Optional native `opas_math` extension (pybind11) for faster proximity checks.

## Research audit

An independent study auditing the `/safe-windows` endpoint's collision-screening accuracy is available on the [`research-branch`](https://github.com/nadeemtsf/OPAS/tree/research-branch/research). The fixes applied in this branch were derived from that study's findings.

The frozen six-hour ISS replay found agreement at all 691 production launch checks and no observed false-safe samples among 565 clear samples. The instrumented search took 18.44 minutes on the measured host. See the [numerical verification report](validation/results/rerun_20261006T115728Z/report.md) for exact scope, runtime, environment and code checksums, and [validation instructions](validation/README.md) to reproduce it.

For the exact files behind each table in the revised audit report, use the [report evidence index](validation/EVIDENCE.md). It maps historical research, the corrected duration recount, the full ISS search and later integration checks to their records and code versions.

The app now adds runtime diagnostics and 5-second checks of qualifying spans. These changes follow the measured research versions above; their focused checks do not constitute a new full six-hour benchmark. See [runtime checks and testing instructions](validation/RUNTIME_CHECKS.md).

Windows describe checked launch times in the post-ascent model. The current search uses an altitude filter of ±100 km and starts checking the flight at approximately 600 seconds. Accuracy between launch samples, ascent coverage and real-world propagation uncertainty require separate validation.

## Project layout
- backend/
  - api.py: FastAPI app and endpoints.
  - ingest.py: Space-Track ingestion and MongoDB loader.
  - refresh_catalogue.py: validated refresh of named existing objects without deleting the catalogue.
  - db.py: MongoDB connection and Skyfield helpers.
  - orbital.py, proximity.py, scanner.py: orbital math and scanning logic.
  - encounters.py, windows.py: interval encounter refinement and launch-window discovery.
  - tests/: focused detector, window and HTTP integration tests.
  - native/: pybind11 extension source and build config.
- frontend/
  - src/App.tsx and components: UI and globe visualization.
  - src/hooks: globe sizing and debris rendering.
  - src/utils/reportGenerator.ts: text report download.
  - public/ and src/assets/: app icons and UI assets.
- render.yaml: Render deployment config.

## Quickstart (local)

Prerequisites
- Python 3.10+ and pip
- Node.js 22.12+ and npm
- MongoDB Atlas connection string or local MongoDB instance

Backend

```bash
cd backend
python -m venv .venv
.venv\Scripts\Activate
pip install -r requirements.txt
```

Create `backend/.env` (kept out of git):

```
MONGO_URI="mongodb+srv://<user>:<pass>@cluster.example/?retryWrites=true&w=majority"
SPACE_TRACK_USER=<your_space-track-username>
SPACE_TRACK_PASS=<your_space-track-password>
```

Ingest debris (this deletes and repopulates `opas_db.debris`):

```bash
python ingest.py
```

Run the API:

```bash
python -m uvicorn api:app --reload --host 0.0.0.0 --port 8000
```

Frontend

```bash
cd frontend
npm install
npm run dev
```

Open the Vite dev URL (typically `http://localhost:5173`). The frontend calls the backend at `http://localhost:8000`.

If a window request fails because an object's orbital prediction is invalid,
refresh that specific object from the backend directory, for example:

```bash
python refresh_catalogue.py --norad-id 69980
```

This uses the Space-Track credentials in `backend/.env`, validates the fetched
TLE at one-minute samples over eight hours, and updates only the existing named
object. It does not delete the catalogue or silently remove failed objects.
The scanner still checks actual launch/flight times; this data validation is not
a collision-safety certificate. See [recovery instructions](validation/RUNTIME_CHECKS.md#recovering-an-invalid-orbital-prediction).

## Configuration

Backend env vars
- `MONGO_URI` (required)
- `SPACE_TRACK_USER`, `SPACE_TRACK_PASS` (required for ingestion)
- `ALLOWED_ORIGINS` (optional, comma-separated; defaults to `http://localhost:5173`)
- `OPAS_LOG_LEVEL` (optional, defaults to `INFO`; `DEBUG` also logs every safe-window launch classification)

Frontend env vars
- `VITE_API_URL` (optional; defaults to `http://localhost:8000`)

## API reference

GET `/debris`
- Returns `{ count, debris }` with TLE lines omitted in the response.

GET `/alert`
Query parameters:
- `target_lat`, `target_lon` (float, required)
- `target_alt` (float, km, required)
- `inclination` (float, degrees, optional)
- `launch_time` (ISO 8601 string, optional; defaults to now)

Response fields:
- `status`: `safe` or `danger`
- `candidates_checked`
- `threats`: list of threat objects (see Data model)
- `trajectory`: optional list of waypoints with `{ lat, lng, alt }` where `alt` is normalized as `alt_km / EARTH_RADIUS_KM` for the globe
- `launch_time`: resolved ISO timestamp

GET `/safe-windows`
Query parameters:
- `target_lat`, `target_lon`, `target_alt`, `inclination` (required)
- `search_hours` (optional; default `24`, allowed `1..336`)

Returns up to five windows of at least 15 minutes, sorted by actual duration, with `start`, `end`, `duration_minutes`, and `verification`. Candidate windows are checked at 10-second launch spacing; all qualifying spans then receive additional 5-second checks before selection. New obstructions split spans. A final audit requires clear endpoints, correct duration, requested-horizon bounds and complete sampled coverage.

The response includes `diagnostics`: request ID, exact horizon, catalogue fingerprint, screened object count, model scope, screening radii, clear/obstructed launch counts, extra validation results, timings and per-window checks. An empty catalogue or failed prediction produces an incomplete search instead of a clear window.

If an orbital object cannot be loaded, the endpoint returns HTTP 503 with a `detail` message. The frontend displays the incomplete search separately from a successful result with no qualifying windows. Selecting a window sends its exact checked ISO timestamp, including fractional seconds; the launch-time input represents UTC.

GET `/safe-windows/stream`
- Accepts the same query parameters and runs the same search.
- Streams `progress`, followed by either `result` or `error`, as server-sent events, with ten-second heartbeat comments while calculations run.
- Used by the frontend for live phase/count/timing updates. An `error` event is incomplete even if the stream's HTTP headers already returned 200.
- Closing the stream cancels further work between bounded batches; already running prediction work finishes first.

Every API response has an `X-Request-ID` header to match browser messages with server logs. In the UI, start with a one-hour test, open the browser console, and use **Download check details** to retain the model and coverage evidence. Mission inputs are locked while requests run so their results cannot be mistaken for another mission.

## Verification

```bash
pip install -r backend/requirements-dev.txt
OPENBLAS_NUM_THREADS=1 OMP_NUM_THREADS=1 python validation/run_focused_tests.py --output /tmp/opas-focused-tests.json
cd frontend
npm ci
npm test
npm run build
npm run lint
```

The focused tests use frozen fixtures and mock database reads. HTTP tests exercise the production scanner with spawned workers. Frontend tests cover exact checked timestamps, UTC input in multiple timezones and manual edits.

## Data model

Collection: `opas_db.debris`

```json
{
  "name": "OBJECT NAME",
  "norad_id": 12345,
  "altitude_km": 412.34,
  "tle_line1": "1 ...",
  "tle_line2": "2 ...",
  "location": { "type": "Point", "coordinates": [lon, lat] }
}
```

Threat object fields (from `/alert`):
- `name`, `norad_id`, `altitude_km`, `altitude_diff_km`, `distance_km`, `location`
- Optional TLE-derived fields: `tle_age_days`, `collision_probability`, `threat_level`, `position_uncertainty_km`
- Trajectory context: `approach_location`, `closest_approach_time`

## Native math extension

`backend/native/opas_math.cpp` provides optional pybind11 helpers for fast 3D proximity checks. The backend falls back to pure Python if the module is not available.

## Deployment

`render.yaml` defines a Render web service for the backend and a static frontend build. The backend build step attempts to compile the native extension and falls back if it fails.

## Security

- Do not commit secrets (`.env`, Space-Track credentials, or `MONGO_URI`).
- Space-Track credentials are subject to Space-Track terms; avoid excessive polling.

## License

See [LICENSE](LICENSE).
