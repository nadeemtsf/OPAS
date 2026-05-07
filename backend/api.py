import os
from math import radians, degrees, sin, cos, asin, atan2, sqrt, pi
from datetime import datetime, timezone, timedelta
from dotenv import load_dotenv
from fastapi import FastAPI, Query
from fastapi.middleware.cors import CORSMiddleware
from pymongo import MongoClient
from skyfield.api import load, EarthSatellite

load_dotenv()

app = FastAPI(title="OPAS – Orbital Proximity Alert System")
app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:5173"],
    allow_methods=["*"],
    allow_headers=["*"],
)

client = MongoClient(os.getenv("MONGO_URI"))
collection = client["opas_db"]["debris"]
ts = load.timescale()

EARTH_R = 6371


def haversine_km(lat1, lon1, lat2, lon2):
    lat1, lon1, lat2, lon2 = map(radians, [lat1, lon1, lat2, lon2])
    dlat, dlon = lat2 - lat1, lon2 - lon1
    a = sin(dlat / 2) ** 2 + cos(lat1) * cos(lat2) * sin(dlon / 2) ** 2
    return EARTH_R * 2 * atan2(sqrt(a), sqrt(1 - a))


def generate_trajectory(launch_lat, launch_lon, alt_km, inc_deg, steps=120):
    inc = radians(max(inc_deg, 0.5))
    r = EARTH_R + alt_km
    period = 2 * pi * sqrt(r ** 3 / 398600.4418) / 60
    drift = 360 / 1440

    sin_lat = sin(radians(launch_lat))
    sin_inc = sin(inc)
    u0 = asin(max(-1.0, min(1.0, sin_lat / sin_inc)))
    lon0 = degrees(atan2(cos(inc) * sin(u0), cos(u0)))

    waypoints = []
    for i in range(steps + 1):
        u = u0 + (i / steps) * 2 * pi
        wlat = degrees(asin(sin_inc * sin(u)))
        wlon = launch_lon + degrees(atan2(cos(inc) * sin(u), cos(u))) - lon0 - drift * period * i / steps
        wlon = ((wlon + 540) % 360) - 180
        waypoints.append({"lat": round(wlat, 4), "lon": round(wlon, 4)})
    return waypoints


def _count_threats(candidates, trajectory, target_lat, target_lon, target_alt, t, proximity_km=200):
    count = 0
    for doc in candidates:
        if t is not None and doc.get("tle_line1"):
            try:
                sat = EarthSatellite(doc["tle_line1"], doc["tle_line2"], doc["name"], ts)
                sub = sat.at(t).subpoint()
                d_lat, d_lon, d_alt = sub.latitude.degrees, sub.longitude.degrees, sub.elevation.km
            except Exception:
                continue
        else:
            coords = doc["location"]["coordinates"]
            d_lat, d_lon, d_alt = coords[1], coords[0], doc["altitude_km"]

        if abs(d_alt - target_alt) > 50:
            continue

        if trajectory:
            min_dist = float("inf")
            for wp in trajectory:
                d = haversine_km(wp["lat"], wp["lon"], d_lat, d_lon)
                if d < min_dist:
                    min_dist = d
                if min_dist < proximity_km * 0.25:
                    break
        else:
            min_dist = haversine_km(target_lat, target_lon, d_lat, d_lon)

        if min_dist < proximity_km:
            count += 1
    return count


def _full_check(candidates, trajectory, target_lat, target_lon, target_alt, t,
                launch_dt=None):
    threats = []

    if trajectory:
        r = EARTH_R + target_alt
        period_sec = 2 * pi * sqrt(r ** 3 / 398600.4418)
        steps = len(trajectory) - 1

    for doc in candidates:
        if t is not None and doc.get("tle_line1"):
            try:
                sat = EarthSatellite(doc["tle_line1"], doc["tle_line2"], doc["name"], ts)
                sub = sat.at(t).subpoint()
                d_lat, d_lon, d_alt = sub.latitude.degrees, sub.longitude.degrees, sub.elevation.km
            except Exception:
                continue
        else:
            coords = doc["location"]["coordinates"]
            d_lat, d_lon, d_alt = coords[1], coords[0], doc["altitude_km"]

        if abs(d_alt - target_alt) > 50:
            continue

        closest_idx = 0
        if trajectory:
            min_dist = float("inf")
            for idx, wp in enumerate(trajectory):
                d = haversine_km(wp["lat"], wp["lon"], d_lat, d_lon)
                if d < min_dist:
                    min_dist = d
                    closest_idx = idx
                if min_dist < 50:
                    break
        else:
            min_dist = haversine_km(target_lat, target_lon, d_lat, d_lon)

        if min_dist < 200:
            threat = {
                "name": doc["name"],
                "norad_id": doc["norad_id"],
                "altitude_km": round(d_alt, 2),
                "altitude_diff_km": round(abs(d_alt - target_alt), 2),
                "distance_meters": round(min_dist * 1000, 2),
                "location": {
                    "type": "Point",
                    "coordinates": [round(d_lon, 4), round(d_lat, 4)],
                },
            }

            if trajectory:
                threat["approach_location"] = {
                    "lat": trajectory[closest_idx]["lat"],
                    "lon": trajectory[closest_idx]["lon"],
                }
                if launch_dt and steps > 0:
                    offset = timedelta(seconds=period_sec * closest_idx / steps)
                    threat["closest_approach_time"] = (launch_dt + offset).isoformat()

            threats.append(threat)
    return threats


def _make_skyfield_time(iso_str):
    dt = datetime.fromisoformat(iso_str.replace("Z", "+00:00"))
    return ts.from_datetime(dt.replace(tzinfo=timezone.utc) if dt.tzinfo is None else dt)


@app.get("/debris")
def get_debris(limit: int = Query(3000, ge=1, le=50000)):
    docs = list(collection.find({}, {"_id": 0, "tle_line1": 0, "tle_line2": 0}).limit(limit))
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

    t = _make_skyfield_time(launch_time) if launch_time else None

    launch_dt = None
    if launch_time:
        launch_dt = datetime.fromisoformat(launch_time.replace("Z", "+00:00"))
        if launch_dt.tzinfo is None:
            launch_dt = launch_dt.replace(tzinfo=timezone.utc)

    if trajectory is None and t is None:
        return _instant_check(target_lat, target_lon, target_alt)

    candidates = list(collection.find(
        {"altitude_km": {"$gte": target_alt - 200, "$lte": target_alt + 200}},
        {"_id": 0},
    ))

    threats = _full_check(candidates, trajectory, target_lat, target_lon, target_alt, t, launch_dt)

    result = {
        "status": "danger" if threats else "safe",
        "target_coordinates": {"lat": target_lat, "lon": target_lon, "alt_km": target_alt},
        "candidates_checked": len(candidates),
        "threats": threats,
    }
    if trajectory:
        result["trajectory"] = [
            {"lat": w["lat"], "lng": w["lon"], "alt": target_alt / EARTH_R}
            for w in trajectory
        ]
    if launch_time:
        result["launch_time"] = launch_time
    return result


SAFE_WINDOW_PROXIMITY_KM = 50


def _scan_windows(candidates, trajectory, target_lat, target_lon, target_alt,
                  start_dt, end_dt, proximity_km):
    coarse_step = timedelta(minutes=30)
    fine_step = timedelta(minutes=5)

    coarse_results = []
    cursor = start_dt
    while cursor <= end_dt:
        t = ts.from_datetime(cursor)
        threat_count = _count_threats(
            candidates, trajectory, target_lat, target_lon, target_alt, t,
            proximity_km=proximity_km,
        )
        coarse_results.append((cursor, threat_count))
        cursor += coarse_step

    raw_windows = []
    in_window = False
    window_start = None

    for dt_val, count in coarse_results:
        if count == 0 and not in_window:
            window_start = dt_val
            in_window = True
        elif count > 0 and in_window:
            raw_windows.append((window_start, dt_val))
            in_window = False

    if in_window:
        raw_windows.append((window_start, end_dt))

    windows = []
    for raw_start, raw_end in raw_windows[:5]:
        refined_start = raw_start
        check = raw_start - coarse_step
        while check < raw_start:
            check += fine_step
            if check >= raw_start:
                break
            t = ts.from_datetime(check)
            if _count_threats(candidates, trajectory, target_lat, target_lon, target_alt, t,
                              proximity_km=proximity_km) == 0:
                refined_start = check
                break

        refined_end = raw_end
        check = raw_end
        limit = raw_end + coarse_step
        while check < limit:
            t = ts.from_datetime(check)
            if _count_threats(candidates, trajectory, target_lat, target_lon, target_alt, t,
                              proximity_km=proximity_km) > 0:
                break
            refined_end = check
            check += fine_step

        duration = (refined_end - refined_start).total_seconds() / 60
        if duration >= 15:
            windows.append({
                "start": refined_start.isoformat(),
                "end": refined_end.isoformat(),
                "duration_minutes": round(duration),
            })

    windows.sort(key=lambda w: -w["duration_minutes"])
    return windows[:5]


@app.get("/safe-windows")
def safe_windows(
    target_lat: float = Query(...),
    target_lon: float = Query(...),
    target_alt: float = Query(...),
    inclination: float = Query(...),
    search_hours: int = Query(24, ge=1, le=72),
):
    trajectory = generate_trajectory(target_lat, target_lon, target_alt, inclination)

    candidates = list(collection.find(
        {"altitude_km": {"$gte": target_alt - 200, "$lte": target_alt + 200}},
        {"_id": 0},
    ))

    now = datetime.now(timezone.utc)

    # Progressive search: try initial hours, then extend if nothing found
    for hours in [search_hours, min(search_hours * 2, 72), 72]:
        end = now + timedelta(hours=hours)
        windows = _scan_windows(
            candidates, trajectory, target_lat, target_lon, target_alt,
            now, end, SAFE_WINDOW_PROXIMITY_KM,
        )
        if windows:
            return {
                "search_hours": hours,
                "candidates_checked": len(candidates),
                "windows": windows,
            }
        if hours >= 72:
            break

    return {
        "search_hours": 72,
        "candidates_checked": len(candidates),
        "windows": [],
    }


def _instant_check(target_lat, target_lon, target_alt):
    pipeline = [
        {
            "$geoNear": {
                "near": {"type": "Point", "coordinates": [target_lon, target_lat]},
                "distanceField": "distance_meters",
                "spherical": True,
            }
        },
        {
            "$match": {
                "$expr": {
                    "$lt": [
                        {"$abs": {"$subtract": ["$altitude_km", target_alt]}},
                        50,
                    ]
                }
            }
        },
        {"$project": {"_id": 0, "tle_line1": 0, "tle_line2": 0}},
    ]
    threats = list(collection.aggregate(pipeline))
    return {
        "status": "danger" if threats else "safe",
        "target_coordinates": {"lat": target_lat, "lon": target_lon, "alt_km": target_alt},
        "threats": threats,
    }
