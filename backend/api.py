import os
from math import radians, degrees, sin, cos, asin, atan2, sqrt, pi
from datetime import datetime, timezone
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

    use_propagation = False
    t = None
    if launch_time:
        dt = datetime.fromisoformat(launch_time.replace("Z", "+00:00"))
        t = ts.from_datetime(dt.replace(tzinfo=timezone.utc) if dt.tzinfo is None else dt)
        use_propagation = True

    if trajectory is None and not use_propagation:
        return _instant_check(target_lat, target_lon, target_alt)

    candidates = list(collection.find(
        {"altitude_km": {"$gte": target_alt - 200, "$lte": target_alt + 200}},
        {"_id": 0},
    ))

    threats = []
    for doc in candidates:
        if use_propagation and doc.get("tle_line1"):
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
                if min_dist < 50:
                    break
        else:
            min_dist = haversine_km(target_lat, target_lon, d_lat, d_lon)

        if min_dist < 200:
            threats.append({
                "name": doc["name"],
                "norad_id": doc["norad_id"],
                "altitude_km": round(d_alt, 2),
                "distance_meters": round(min_dist * 1000, 2),
                "location": {
                    "type": "Point",
                    "coordinates": [round(d_lon, 4), round(d_lat, 4)],
                },
            })

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
