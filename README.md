# OPAS — Orbital Proximity Alert System

OPAS is a lightweight toolchain for assessing orbital collision risk for launch trajectories and finding safe launch windows. It combines a Python FastAPI backend that ingests TLEs from Space-Track and computes proximity checks (using Skyfield and MongoDB spatial queries) with a React + Vite frontend that visualizes debris and launch trajectories on an interactive globe.

Key ideas
- Ingest recent TLEs from Space-Track, compute subpoints for each object, and store them in MongoDB (`opas_db.debris`) with a `2dsphere` index.
- Provide REST endpoints to list debris, run an instantaneous collision check (`/alert`), and scan for safe launch windows (`/safe-windows`).
- Frontend visualizes debris and allows interactive collision checks and safe-window queries.

Table of contents
- Features
- Architecture & components
- Quickstart — run locally
- Backend: environment variables & ingestion
- API reference
- Frontend: running & configuration
- Data model
- Development notes & troubleshooting

Features
- FastAPI backend with three main endpoints: `/debris`, `/alert`, `/safe-windows`.
- Ingestion pipeline (`backend/ingest.py`) that queries Space-Track, computes current subpoints using `skyfield`, and writes GeoJSON `Point` documents into MongoDB.
- Spatial queries using MongoDB `2dsphere` index for efficient proximity searches.
- A React + Vite frontend using `react-globe.gl` and Three.js to render debris and launch trajectories.

Architecture & components
- backend/: FastAPI application and ingestion script.
	- `api.py` — API implementation and collision/safe-window algorithms.
	- `ingest.py` — Space-Track TLE fetcher → convert to positions → upload to MongoDB (wipes existing collection).
	- `requirements.txt` — Python dependencies.
- frontend/: React + TypeScript UI built with Vite.
	- `src/App.tsx` — main UI, queries backend endpoints and renders globe.
	- `package.json` — frontend dependencies & scripts.

Quickstart — run locally

Prerequisites
- Python 3.10+ and pip
- Node.js 18+ and npm/yarn
- MongoDB Atlas connection string or local MongoDB instance

Backend (recommended from a terminal inside `backend/`)

1. Create a virtual environment and install requirements

```bash
cd backend
python -m venv .venv
# Windows
.venv\Scripts\Activate
# macOS / Linux
source .venv/bin/activate
pip install -r requirements.txt
```

2. Create a `.env` file (kept out of git). Required variables:

```
MONGO_URI="mongodb+srv://<user>:<pass>@cluster.example/?retryWrites=true&w=majority"
SPACE_TRACK_USER=<your_space-track-username>
SPACE_TRACK_PASS=<your_space-track-password>
```

Note: `backend/ingest.py` will authenticate to Space-Track using these credentials and replace the contents of the `opas_db.debris` collection.

3. Ingest debris (this deletes and repopulates the `debris` collection):

```bash
cd backend
python ingest.py
```

4. Start the API server

```bash
uvicorn api:app --reload --host 0.0.0.0 --port 8000
```

The backend serves on port `8000` by default. CORS is configured to allow `http://localhost:5173` (the default Vite dev server).

Frontend

1. Install and run the frontend

```bash
cd frontend
npm install
npm run dev
```

2. Open the Vite dev URL (typically `http://localhost:5173`) and interact with the globe. The frontend calls the backend at `http://localhost:8000` for `/debris`, `/alert`, and `/safe-windows`.

Backend — environment variables & important notes
- `MONGO_URI` — MongoDB connection string (required).
- `SPACE_TRACK_USER`, `SPACE_TRACK_PASS` — Space-Track credentials used by `ingest.py` (required if you want to run ingestion).
- The ingestion script deletes existing `opas_db.debris` documents and inserts newly-computed positions; schedule/update as appropriate.
- The backend uses `python-dotenv` so place the `.env` file in `backend/` (or ensure env vars are loaded from your environment).

API reference
- GET `/debris?limit=<n>`
	- Returns a list of stored debris documents (default `limit=3000`). Response: `{ count, debris }`.

- GET `/alert` (query parameters)
	- `target_lat` (float, required)
	- `target_lon` (float, required)
	- `target_alt` (float, km, required)
	- `inclination` (float, degrees, optional) — when provided triggers a generated trajectory around the target site to simulate a launch orbit.
	- `launch_time` (ISO 8601 string, optional) — when provided the backend will compute skyfield times from this timestamp.

	Response fields
	- `status`: `safe` or `danger`.
	- `threats`: list of threat objects (name, `norad_id`, `altitude_km`, `altitude_diff_km`, `distance_meters`, `location` GeoJSON Point). If `inclination`/trajectory are supplied, threats include `approach_location` and `closest_approach_time`.
	- `candidates_checked`: number of debris objects considered for the check.
	- `trajectory`: when applicable, an array of trajectory waypoints (for visualization). Note: `alt` in the returned trajectory is normalized for the globe visualization (the frontend divides by Earth radius).

- GET `/safe-windows` (query parameters)
	- `target_lat`, `target_lon`, `target_alt`, `inclination` (all required for trajectory-based scanning)
	- `search_hours` (optional; default `24`, allowed `1..72`) — how many hours ahead to scan for safe windows

	Returns a prioritized list of candidate windows with `start`/`end` ISO timestamps and `duration_minutes`.

Data model (collection: `opas_db.debris`)
- Example document shape

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

Development notes & algorithms
- The backend will attempt to use `tle_line1`/`tle_line2` with Skyfield to compute exact subpoints at requested times. If TLEs are missing, it falls back to stored `location` and `altitude_km` values.
- Distance computations use a Haversine approximation on the subpoint lat/lon and altitude-based filtering; altitude differences greater than ~50 km are ignored for proximity checks.
- Safe-window scanning performs a coarse 30-minute sweep and refines candidate windows with 5-minute steps. The default proximity thresholds used in the code are: candidate proximity window 200 km for threat detection, and a `SAFE_WINDOW_PROXIMITY_KM = 50` km used when scanning windows.

Security & operational guidance
- Do NOT check secrets (`.env`, Space-Track credentials, or `MONGO_URI`) into source control. `.gitignore` already lists `.env`.
- Consider adding `.claude/` to `.gitignore` if you keep local assistant notes there.
- Space-Track credentials are subject to Space-Track terms; keep them private and avoid overloading their API (use sensible polling cadence).

Troubleshooting
- If the frontend shows an empty globe or fails to fetch debris, confirm the backend is running on port `8000` and `MONGO_URI` is correct.
- If ingestion fails, check your Space-Track credentials and network connectivity. The ingest script prints progress and skips TLEs it cannot parse.

Next steps & suggestions
- Add a scheduled job or cron task to run `backend/ingest.py` periodically to keep debris positions current.
- Add tests for the proximity and safe-window algorithms.
- Provide optional Dockerfiles or compose files for reproducible local deployment.

License & authors
- OPAS — project structure and code provided in this repository. Add a `LICENSE` file if you wish to apply a specific open-source license.

----

Path references
- Backend: [backend/api.py](backend/api.py#L1)
- Ingest: [backend/ingest.py](backend/ingest.py#L1)
- Frontend: [frontend/src/App.tsx](frontend/src/App.tsx#L1)
