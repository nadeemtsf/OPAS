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

ALLOWED_ORIGINS = os.getenv("ALLOWED_ORIGINS", "http://localhost:5173").split(",")
app.add_middleware(
    CORSMiddleware,
    allow_origins=ALLOWED_ORIGINS,
    allow_methods=["*"],
    allow_headers=["*"],
)

client = MongoClient(os.getenv("MONGO_URI"))
collection = client["opas_db"]["debris"]
ts = load.timescale()

EARTH_R = 6371


def _propagate_at(doc, t):
    sat = EarthSatellite(doc["tle_line1"], doc["tle_line2"], doc["name"], ts)
    sub = sat.at(t).subpoint()
    return sat, sub.latitude.degrees, sub.longitude.degrees, sub.elevation.km


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

    # ~600 s ascent from ground to target altitude
    step_sec = (period * 60) / steps
    ascent_steps = min(steps, max(1, round(600 / step_sec)))

    waypoints = []
    for i in range(steps + 1):
        u = u0 + (i / steps) * 2 * pi
        wlat = degrees(asin(sin_inc * sin(u)))
        wlon = launch_lon + degrees(atan2(cos(inc) * sin(u), cos(u))) - lon0 - drift * period * i / steps
        wlon = ((wlon + 540) % 360) - 180
        wp_alt = alt_km * min(1.0, i / ascent_steps) if ascent_steps > 0 else alt_km
        waypoints.append({"lat": round(wlat, 4), "lon": round(wlon, 4), "alt": round(wp_alt, 2)})
    return waypoints


def _tle_epoch_age_days(tle_line1):
    try:
        yr2 = int(tle_line1[18:20])
        day_frac = float(tle_line1[20:32])
        year = yr2 + (1900 if yr2 >= 57 else 2000)
        epoch = datetime(year, 1, 1, tzinfo=timezone.utc) + timedelta(days=day_frac - 1)
        return (datetime.now(timezone.utc) - epoch).total_seconds() / 86400.0
    except Exception:
        return None


def _count_threats(candidates, trajectory, target_lat, target_lon, target_alt, t, proximity_km=200):
    count = 0

    time_varying = trajectory is not None and t is not None and len(trajectory) > 1
    if time_varying:
        steps = len(trajectory) - 1
        r = EARTH_R + target_alt
        period_sec = 2 * pi * sqrt(r ** 3 / 398600.4418)
        stride = max(1, steps // 12)
        sample_indices = list(range(0, steps + 1, stride))
        sample_wps = [trajectory[idx] for idx in sample_indices]
        t_samples = ts.tt_jd([t.tt + period_sec * idx / (steps * 86400.0)
                              for idx in sample_indices])

    for doc in candidates:
        has_tle = t is not None and doc.get("tle_line1")

        if time_varying and has_tle:
            try:
                _, lats, lons, alts = _propagate_at(doc, t_samples)
            except Exception:
                continue

            threat_found = False
            for i, wp in enumerate(sample_wps):
                wp_alt = wp["alt"]
                if abs(float(alts[i]) - wp_alt) > 50:
                    continue
                if haversine_km(wp["lat"], wp["lon"], float(lats[i]), float(lons[i])) < proximity_km:
                    threat_found = True
                    break
            if threat_found:
                count += 1

        elif has_tle:
            try:
                _, d_lat, d_lon, d_alt = _propagate_at(doc, t)
            except Exception:
                continue
            if abs(d_alt - target_alt) > 50:
                continue
            min_dist = haversine_km(target_lat, target_lon, d_lat, d_lon)
            if min_dist < proximity_km:
                count += 1

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


def _count_threats_fast(scan_items, trajectory, target_alt, t, proximity_km):
    """Optimized for safe-window scanning: pre-built sats, fewer samples, skips ascent."""
    count = 0
    steps = len(trajectory) - 1
    if steps < 1:
        return 0
    r = EARTH_R + target_alt
    period_sec = 2 * pi * sqrt(r ** 3 / 398600.4418)
    step_sec = period_sec / steps
    ascent_steps = min(steps, max(1, round(600 / step_sec)))
    stride = max(1, (steps - ascent_steps) // 6)
    sample_indices = list(range(ascent_steps, steps + 1, stride))
    if not sample_indices:
        sample_indices = [steps]
    sample_wps = [trajectory[idx] for idx in sample_indices]
    t_samples = ts.tt_jd([t.tt + period_sec * idx / (steps * 86400.0)
                          for idx in sample_indices])

    for sat, doc in scan_items:
        if sat is not None:
            try:
                sub = sat.at(t_samples).subpoint()
                lats, lons, alts = sub.latitude.degrees, sub.longitude.degrees, sub.elevation.km
            except Exception:
                continue
            for i, wp in enumerate(sample_wps):
                if abs(float(alts[i]) - target_alt) > 50:
                    continue
                if haversine_km(wp["lat"], wp["lon"], float(lats[i]), float(lons[i])) < proximity_km:
                    count += 1
                    break
        else:
            coords = doc["location"]["coordinates"]
            d_lat, d_lon, d_alt = coords[1], coords[0], doc["altitude_km"]
            if abs(d_alt - target_alt) > 50:
                continue
            for wp in sample_wps:
                if haversine_km(wp["lat"], wp["lon"], d_lat, d_lon) < proximity_km:
                    count += 1
                    break

    return count


def _full_check(candidates, trajectory, target_lat, target_lon, target_alt, t,
                launch_dt=None):
    threats = []

    time_varying = trajectory is not None and t is not None and len(trajectory) > 1
    if trajectory:
        r = EARTH_R + target_alt
        period_sec = 2 * pi * sqrt(r ** 3 / 398600.4418)
        steps = len(trajectory) - 1

    if time_varying:
        stride = max(1, steps // 12)
        coarse_indices = list(range(0, steps + 1, stride))
        coarse_set = set(coarse_indices)
        t_coarse = ts.tt_jd([t.tt + period_sec * idx / (steps * 86400.0)
                             for idx in coarse_indices])

    for doc in candidates:
        has_tle = t is not None and doc.get("tle_line1")

        if time_varying and has_tle:
            try:
                sat, lats, lons, alts = _propagate_at(doc, t_coarse)
            except Exception:
                continue

            min_dist = float("inf")
            best_ci = 0
            best_d_lat, best_d_lon, best_d_alt = 0.0, 0.0, 0.0
            for i, ci in enumerate(coarse_indices):
                d_alt = float(alts[i])
                wp_alt = trajectory[ci]["alt"]
                if abs(d_alt - wp_alt) > 50:
                    continue
                d_lat, d_lon = float(lats[i]), float(lons[i])
                d = haversine_km(trajectory[ci]["lat"], trajectory[ci]["lon"], d_lat, d_lon)
                if d < min_dist:
                    min_dist = d
                    best_ci = i
                    best_d_lat, best_d_lon, best_d_alt = d_lat, d_lon, d_alt

            closest_idx = coarse_indices[best_ci]

            # Refine around closest coarse sample if promising
            if min_dist < 500:
                ref_start = max(0, closest_idx - stride)
                ref_end = min(steps, closest_idx + stride)
                ref_indices = [j for j in range(ref_start, ref_end + 1)
                               if j not in coarse_set]
                if ref_indices:
                    t_ref = ts.tt_jd([t.tt + period_sec * j / (steps * 86400.0)
                                      for j in ref_indices])
                    try:
                        rsub = sat.at(t_ref).subpoint()
                        rlats = rsub.latitude.degrees
                        rlons = rsub.longitude.degrees
                        ralts = rsub.elevation.km
                    except Exception:
                        pass
                    else:
                        for i, ri in enumerate(ref_indices):
                            r_alt = float(ralts[i])
                            wp_alt = trajectory[ri]["alt"]
                            if abs(r_alt - wp_alt) > 50:
                                continue
                            r_lat, r_lon = float(rlats[i]), float(rlons[i])
                            d = haversine_km(trajectory[ri]["lat"], trajectory[ri]["lon"],
                                             r_lat, r_lon)
                            if d < min_dist:
                                min_dist = d
                                closest_idx = ri
                                best_d_lat, best_d_lon, best_d_alt = r_lat, r_lon, r_alt

            if min_dist >= 200:
                continue
            d_lat, d_lon, d_alt = best_d_lat, best_d_lon, best_d_alt
            alt_ref = trajectory[closest_idx]["alt"]

        elif has_tle:
            try:
                _, d_lat, d_lon, d_alt = _propagate_at(doc, t)
            except Exception:
                continue
            if abs(d_alt - target_alt) > 50:
                continue

            closest_idx = 0
            alt_ref = target_alt
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

        else:
            coords = doc["location"]["coordinates"]
            d_lat, d_lon, d_alt = coords[1], coords[0], doc["altitude_km"]
            if abs(d_alt - target_alt) > 50:
                continue

            closest_idx = 0
            alt_ref = target_alt
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
                "altitude_diff_km": round(abs(d_alt - alt_ref), 2),
                "distance_meters": round(min_dist * 1000, 2),
                "location": {
                    "type": "Point",
                    "coordinates": [round(d_lon, 4), round(d_lat, 4)],
                },
            }

            if doc.get("tle_line1"):
                age = _tle_epoch_age_days(doc["tle_line1"])
                if age is not None:
                    threat["tle_age_days"] = round(age, 1)
                    if age < 1:
                        threat["confidence"] = "high"
                    elif age < 3:
                        threat["confidence"] = "medium"
                    elif age < 7:
                        threat["confidence"] = "low"
                    else:
                        threat["confidence"] = "very_low"

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

    if launch_time:
        t = _make_skyfield_time(launch_time)
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

    threats = _full_check(candidates, trajectory, target_lat, target_lon, target_alt, t, launch_dt)

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


SAFE_WINDOW_PROXIMITY_KM = 50


def _scan_windows(candidates, trajectory, target_lat, target_lon, target_alt,
                  start_dt, end_dt, proximity_km):
    coarse_step = timedelta(minutes=30)
    fine_step = timedelta(minutes=5)

    # Pre-build satellite objects once (avoids repeated construction per time-step)
    scan_items = []
    for doc in candidates:
        sat = None
        if doc.get("tle_line1"):
            try:
                sat = EarthSatellite(doc["tle_line1"], doc["tle_line2"], doc["name"], ts)
            except Exception:
                pass
        scan_items.append((sat, doc))


    coarse_results = []
    cursor = start_dt
    while cursor <= end_dt:
        t = ts.from_datetime(cursor)
        threat_count = _count_threats_fast(scan_items, trajectory, target_alt, t, proximity_km)
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
            if _count_threats_fast(scan_items, trajectory, target_alt, t, proximity_km) == 0:
                refined_start = check
                break

        refined_end = raw_end
        check = raw_end
        limit = raw_end + coarse_step
        while check < limit:
            t = ts.from_datetime(check)
            if _count_threats_fast(scan_items, trajectory, target_alt, t, proximity_km) > 0:
                break
            refined_end = check
            check += fine_step

        # Verify interior — catch fast-movers that slip through the 30-min coarse grid
        verify_cursor = refined_start + fine_step
        while verify_cursor < refined_end:
            t = ts.from_datetime(verify_cursor)
            if _count_threats_fast(scan_items, trajectory, target_alt, t, proximity_km) > 0:
                refined_end = verify_cursor
                break
            verify_cursor += fine_step

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
