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
- Safe-window scanning with coarse and refined passes to identify low-risk windows.
- React + Vite UI using `react-globe.gl` and Three.js, with interactive tooltips and report export.
- Optional native `opas_math` extension (pybind11) for faster proximity checks.

## Project layout
- backend/
  - api.py: FastAPI app and endpoints.
  - ingest.py: Space-Track ingestion and MongoDB loader.
  - db.py: MongoDB connection and Skyfield helpers.
  - orbital.py, proximity.py, scanner.py: orbital math and scanning logic.
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
- Node.js 18+ and npm
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
uvicorn api:app --reload --host 0.0.0.0 --port 8000
```

Frontend

```bash
cd frontend
npm install
npm run dev
```

Open the Vite dev URL (typically `http://localhost:5173`). The frontend calls the backend at `http://localhost:8000`.

## Configuration

Backend env vars
- `MONGO_URI` (required)
- `SPACE_TRACK_USER`, `SPACE_TRACK_PASS` (required for ingestion)
- `ALLOWED_ORIGINS` (optional, comma-separated; defaults to `http://localhost:5173`)

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

Returns up to five windows sorted by duration, with `start`, `end`, and `duration_minutes`.

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
