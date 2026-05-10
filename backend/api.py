import os
import sys
import time
import logging
from datetime import datetime, timezone, timedelta
from fastapi import FastAPI, Query
from fastapi.middleware.cors import CORSMiddleware

from db import collection, make_skyfield_time, ts
from orbital import EARTH_R, generate_trajectory
from proximity import HAS_NATIVE_MATH
from scanner import full_check, scan_windows, SAFE_WINDOW_PROXIMITY_KM

logging.basicConfig(level=logging.INFO, format="%(levelname)s | %(message)s")
log = logging.getLogger("opas")

app = FastAPI(title="OPAS – Orbital Proximity Alert System")

ALLOWED_ORIGINS = os.getenv("ALLOWED_ORIGINS", "http://localhost:5173").split(",")
app.add_middleware(
    CORSMiddleware,
    allow_origins=ALLOWED_ORIGINS,
    allow_methods=["*"],
    allow_headers=["*"],
)

log.info("CORS origins: %s", ALLOWED_ORIGINS)
log.info("Native C++ math (opas_math): %s", "ACTIVE" if HAS_NATIVE_MATH else "FALLBACK to Python")
log.info("Python %s | Workers: %d", sys.version.split()[0], os.cpu_count() or 4)


@app.get("/debris")
def get_debris():
    docs = list(collection.find({}, {"_id": 0, "tle_line1": 0, "tle_line2": 0}))
    return {"count": len(docs), "debris": docs}


@app.get("/alert")
def alert(
    target_lat: float = Query(...),
    target_lon: float = Query(...),
    target_alt: float = Query(...),
    launch_time: str = Query(None),
    inclination: float = Query(None),
):
    trajectory = None
    if inclination is not None:
        trajectory = generate_trajectory(target_lat, target_lon, target_alt, inclination)

    if launch_time:
        t = make_skyfield_time(launch_time)
        launch_dt = datetime.fromisoformat(launch_time.replace("Z", "+00:00"))
        if launch_dt.tzinfo is None:
            launch_dt = launch_dt.replace(tzinfo=timezone.utc)
    else:
        t = ts.now()
        launch_dt = datetime.now(timezone.utc)

    if trajectory:
        candidates = list(collection.find(
            {"altitude_km": {"$gte": 0, "$lte": target_alt + 200}},
            {"_id": 0},
        ))
    else:
        candidates = list(collection.find(
            {"altitude_km": {"$gte": target_alt - 200, "$lte": target_alt + 200}},
            {"_id": 0},
        ))

    threats = full_check(candidates, trajectory, target_lat, target_lon, target_alt, t, launch_dt)

    result = {
        "status": "danger" if threats else "safe",
        "target_coordinates": {"lat": target_lat, "lon": target_lon, "alt_km": target_alt},
        "candidates_checked": len(candidates),
        "threats": threats,
    }
    if trajectory:
        result["trajectory"] = [
            {"lat": w["lat"], "lng": w["lon"], "alt": w["alt"] / EARTH_R}
            for w in trajectory
        ]
    result["launch_time"] = launch_time or launch_dt.isoformat()
    return result


@app.get("/safe-windows")
def safe_windows(
    target_lat: float = Query(...),
    target_lon: float = Query(...),
    target_alt: float = Query(...),
    inclination: float = Query(...),
    search_hours: int = Query(24, ge=1, le=336),
):
    log.info("safe-windows | REQUEST lat=%.3f lon=%.3f alt=%.0f inc=%.1f hours=%d",
             target_lat, target_lon, target_alt, inclination, search_hours)
    t_req = time.perf_counter()

    trajectory = generate_trajectory(target_lat, target_lon, target_alt, inclination)

    t0 = time.perf_counter()
    candidates = list(collection.find(
        {"altitude_km": {"$gte": target_alt - 100, "$lte": target_alt + 100}},
        {"_id": 0},
    ))
    log.info("safe-windows | DB query: %.2fs — %d candidates (alt ±100km)", time.perf_counter() - t0, len(candidates))

    now = datetime.now(timezone.utc)
    end = now + timedelta(hours=search_hours)
    windows = scan_windows(
        candidates, trajectory, target_lat, target_lon, target_alt,
        now, end, SAFE_WINDOW_PROXIMITY_KM,
    )

    log.info("safe-windows | RESPONSE total: %.2fs", time.perf_counter() - t_req)
    return {
        "search_hours": search_hours,
        "candidates_checked": len(candidates),
        "windows": windows,
    }
