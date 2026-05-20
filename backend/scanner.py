import time
import logging
import concurrent.futures
import os
from math import pi, sqrt
from datetime import timedelta

from skyfield.framelib import itrs

from db import ts, get_sat, _sat_cache
from orbital import EARTH_R, tle_epoch_age_days
from proximity import (
    geodetic_to_ecef, screening_radius_km,
    estimate_sigma_m, compute_pc, threat_level_from_pc, proximity_severity,
    HAS_NATIVE_MATH, opas_math,
)

log = logging.getLogger("opas")

SAFE_WINDOW_PROXIMITY_KM = 50


def _ecef_dist(ax, ay, az, bx, by, bz):
    dx, dy, dz = ax - bx, ay - by, az - bz
    return sqrt(dx * dx + dy * dy + dz * dz)


def count_threats(candidates, trajectory, target_lat, target_lon, target_alt, t, proximity_km=200):
    count = 0

    traj_ecef = None
    if trajectory:
        traj_ecef = [geodetic_to_ecef(wp["lat"], wp["lon"], wp["alt"]) for wp in trajectory]

    time_varying = trajectory is not None and t is not None and len(trajectory) > 1
    if time_varying:
        steps = len(trajectory) - 1
        r = EARTH_R + target_alt
        period_sec = 2 * pi * sqrt(r ** 3 / 398600.4418)
        stride = max(1, steps // 24)
        sample_indices = list(range(0, steps + 1, stride))
        sample_ecef = [traj_ecef[idx] for idx in sample_indices]
        t_samples = ts.tt_jd([t.tt + period_sec * idx / (steps * 86400.0)
                              for idx in sample_indices])

    target_ecef = geodetic_to_ecef(target_lat, target_lon, target_alt)

    for doc in candidates:
        has_tle = t is not None and doc.get("tle_line1")
        tle_age = tle_epoch_age_days(doc["tle_line1"]) if doc.get("tle_line1") else None
        radius = screening_radius_km(proximity_km, tle_age)

        if time_varying and has_tle:
            sat = get_sat(doc)
            if sat is None:
                continue
            try:
                xyz = sat.at(t_samples).frame_xyz(itrs).km
            except Exception:
                continue

            threat_found = False
            for i, (wx, wy, wz) in enumerate(sample_ecef):
                if _ecef_dist(float(xyz[0][i]), float(xyz[1][i]), float(xyz[2][i]),
                              wx, wy, wz) < radius:
                    threat_found = True
                    break
            if threat_found:
                count += 1

        elif has_tle:
            sat = get_sat(doc)
            if sat is None:
                continue
            try:
                xyz = sat.at(t).frame_xyz(itrs).km
            except Exception:
                continue
            tx, ty, tz = target_ecef
            if _ecef_dist(float(xyz[0]), float(xyz[1]), float(xyz[2]),
                          tx, ty, tz) < radius:
                count += 1

        else:
            coords = doc["location"]["coordinates"]
            d_ecef = geodetic_to_ecef(coords[1], coords[0], doc["altitude_km"])
            if traj_ecef:
                min_dist = float("inf")
                for wx, wy, wz in traj_ecef:
                    d = _ecef_dist(d_ecef[0], d_ecef[1], d_ecef[2], wx, wy, wz)
                    if d < min_dist:
                        min_dist = d
                    if min_dist < proximity_km * 0.25:
                        break
            else:
                tx, ty, tz = target_ecef
                min_dist = _ecef_dist(d_ecef[0], d_ecef[1], d_ecef[2], tx, ty, tz)
            if min_dist < proximity_km:
                count += 1

    return count


def count_threats_fast(scan_items, trajectory, target_alt, t, proximity_km):
    count = 0
    steps = len(trajectory) - 1
    if steps < 1:
        return 0
    r = EARTH_R + target_alt
    period_sec = 2 * pi * sqrt(r ** 3 / 398600.4418)
    step_sec = period_sec / steps
    ascent_steps = min(steps, max(1, round(600 / step_sec)))
    stride = max(1, (steps - ascent_steps) // 12)
    sample_indices = list(range(ascent_steps, steps + 1, stride))
    if not sample_indices:
        sample_indices = [steps]
    sample_wps = [trajectory[idx] for idx in sample_indices]
    sample_ecef = [geodetic_to_ecef(wp["lat"], wp["lon"], wp["alt"]) for wp in sample_wps]
    wp_xs = [e[0] for e in sample_ecef]
    wp_ys = [e[1] for e in sample_ecef]
    wp_zs = [e[2] for e in sample_ecef]
    t_samples = ts.tt_jd([t.tt + period_sec * idx / (steps * 86400.0)
                          for idx in sample_indices])

    for item in scan_items:
        sat, doc = item[0], item[1]
        radius = item[2] if len(item) > 2 else screening_radius_km(
            proximity_km, tle_epoch_age_days(doc["tle_line1"]) if doc.get("tle_line1") else None)

        if sat is not None:
            try:
                xyz = sat.at(t_samples).frame_xyz(itrs).km
            except Exception:
                continue
            if HAS_NATIVE_MATH:
                if opas_math.any_threat_ecef(
                    wp_xs, wp_ys, wp_zs,
                    xyz[0], xyz[1], xyz[2], radius,
                ):
                    count += 1
            else:
                for i, (wx, wy, wz) in enumerate(sample_ecef):
                    d = sqrt((float(xyz[0][i]) - wx) ** 2 + (float(xyz[1][i]) - wy) ** 2 + (float(xyz[2][i]) - wz) ** 2)
                    if d < radius:
                        count += 1
                        break
        else:
            coords = doc["location"]["coordinates"]
            d_ecef = geodetic_to_ecef(coords[1], coords[0], doc["altitude_km"])
            if HAS_NATIVE_MATH:
                if opas_math.any_within_ecef(
                    wp_xs, wp_ys, wp_zs,
                    d_ecef[0], d_ecef[1], d_ecef[2], radius,
                ):
                    count += 1
            else:
                for wx, wy, wz in sample_ecef:
                    d = sqrt((d_ecef[0] - wx) ** 2 + (d_ecef[1] - wy) ** 2 + (d_ecef[2] - wz) ** 2)
                    if d < radius:
                        count += 1
                        break

    return count


def full_check(candidates, trajectory, target_lat, target_lon, target_alt, t,
               launch_dt=None):
    threats = []

    traj_ecef = None
    if trajectory:
        traj_ecef = [geodetic_to_ecef(wp["lat"], wp["lon"], wp["alt"]) for wp in trajectory]
        r = EARTH_R + target_alt
        period_sec = 2 * pi * sqrt(r ** 3 / 398600.4418)
        steps = len(trajectory) - 1

    time_varying = trajectory is not None and t is not None and len(trajectory) > 1
    if time_varying:
        stride = max(1, steps // 24)
        coarse_indices = list(range(0, steps + 1, stride))
        coarse_set = set(coarse_indices)
        coarse_ecef = [traj_ecef[idx] for idx in coarse_indices]
        t_coarse = ts.tt_jd([t.tt + period_sec * idx / (steps * 86400.0)
                             for idx in coarse_indices])

    target_ecef = geodetic_to_ecef(target_lat, target_lon, target_alt)

    for doc in candidates:
        has_tle = t is not None and doc.get("tle_line1")
        tle_age = tle_epoch_age_days(doc["tle_line1"]) if doc.get("tle_line1") else None
        radius = screening_radius_km(200, tle_age)

        if time_varying and has_tle:
            sat = get_sat(doc)
            if sat is None:
                continue
            try:
                xyz = sat.at(t_coarse).frame_xyz(itrs).km
            except Exception:
                continue

            min_dist = float("inf")
            best_ci = 0
            for i, (wx, wy, wz) in enumerate(coarse_ecef):
                d = _ecef_dist(float(xyz[0][i]), float(xyz[1][i]), float(xyz[2][i]),
                               wx, wy, wz)
                if d < min_dist:
                    min_dist = d
                    best_ci = i

            closest_idx = coarse_indices[best_ci]

            if min_dist < 500:
                ref_start = max(0, closest_idx - stride)
                ref_end = min(steps, closest_idx + stride)
                ref_indices = [j for j in range(ref_start, ref_end + 1)
                               if j not in coarse_set]
                if ref_indices:
                    t_ref = ts.tt_jd([t.tt + period_sec * j / (steps * 86400.0)
                                      for j in ref_indices])
                    try:
                        ref_xyz = sat.at(t_ref).frame_xyz(itrs).km
                    except Exception:
                        pass
                    else:
                        for i, ri in enumerate(ref_indices):
                            wp_e = traj_ecef[ri]
                            d = _ecef_dist(float(ref_xyz[0][i]), float(ref_xyz[1][i]), float(ref_xyz[2][i]),
                                           wp_e[0], wp_e[1], wp_e[2])
                            if d < min_dist:
                                min_dist = d
                                closest_idx = ri

            if min_dist >= radius:
                continue

            best_jd = t.tt + period_sec * closest_idx / (steps * 86400.0)
            try:
                sub = sat.at(ts.tt_jd(best_jd)).subpoint()
                d_lat = float(sub.latitude.degrees)
                d_lon = float(sub.longitude.degrees)
                d_alt = float(sub.elevation.km)
            except Exception:
                continue
            alt_ref = trajectory[closest_idx]["alt"]

        elif has_tle:
            sat = get_sat(doc)
            if sat is None:
                continue
            try:
                pos = sat.at(t)
                xyz = pos.frame_xyz(itrs).km
            except Exception:
                continue

            closest_idx = 0
            alt_ref = target_alt
            if traj_ecef:
                min_dist = float("inf")
                for idx, (wx, wy, wz) in enumerate(traj_ecef):
                    d = _ecef_dist(float(xyz[0]), float(xyz[1]), float(xyz[2]),
                                   wx, wy, wz)
                    if d < min_dist:
                        min_dist = d
                        closest_idx = idx
                    if min_dist < 50:
                        break
            else:
                tx, ty, tz = target_ecef
                min_dist = _ecef_dist(float(xyz[0]), float(xyz[1]), float(xyz[2]),
                                      tx, ty, tz)

            if min_dist >= radius:
                continue

            sub = pos.subpoint()
            d_lat = float(sub.latitude.degrees)
            d_lon = float(sub.longitude.degrees)
            d_alt = float(sub.elevation.km)

        else:
            coords = doc["location"]["coordinates"]
            d_lat, d_lon, d_alt = coords[1], coords[0], doc["altitude_km"]
            d_ecef = geodetic_to_ecef(d_lat, d_lon, d_alt)

            closest_idx = 0
            alt_ref = target_alt
            if traj_ecef:
                min_dist = float("inf")
                for idx, (wx, wy, wz) in enumerate(traj_ecef):
                    d = _ecef_dist(d_ecef[0], d_ecef[1], d_ecef[2], wx, wy, wz)
                    if d < min_dist:
                        min_dist = d
                        closest_idx = idx
                    if min_dist < 50:
                        break
            else:
                tx, ty, tz = target_ecef
                min_dist = _ecef_dist(d_ecef[0], d_ecef[1], d_ecef[2], tx, ty, tz)

            if min_dist >= radius:
                continue

        threat = {
            "name": doc["name"],
            "norad_id": doc["norad_id"],
            "altitude_km": round(d_alt, 2),
            "altitude_diff_km": round(abs(d_alt - alt_ref), 2),
            "distance_km": round(min_dist, 3),
            "severity": proximity_severity(min_dist),
            "location": {
                "type": "Point",
                "coordinates": [round(d_lon, 4), round(d_lat, 4)],
            },
        }

        if doc.get("tle_line1"):
            age = tle_epoch_age_days(doc["tle_line1"])
            if age is not None:
                threat["tle_age_days"] = round(age, 1)
                sigma = estimate_sigma_m(age)
                pc = compute_pc(min_dist * 1000, sigma)
                threat["collision_probability"] = pc
                threat["threat_level"] = threat_level_from_pc(pc)
                threat["position_uncertainty_km"] = round(sigma / 1000, 2)

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


def scan_windows(candidates, trajectory, target_lat, target_lon, target_alt,
                 start_dt, end_dt, proximity_km):
    t_total = time.perf_counter()
    coarse_step = timedelta(minutes=10)
    fine_step = timedelta(minutes=2)

    traj_lons = [wp["lon"] for wp in trajectory]
    lon_min, lon_max = min(traj_lons), max(traj_lons)
    lon_pad = 15.0
    wraps = (lon_max - lon_min) > 300

    t0 = time.perf_counter()
    scan_items = []
    tle_count = 0
    geo_skipped = 0
    for doc in candidates:
        sat = get_sat(doc)
        if sat is not None:
            tle_count += 1
            tle_age = tle_epoch_age_days(doc["tle_line1"])
            radius = screening_radius_km(proximity_km, tle_age)
            scan_items.append((sat, doc, radius))
        else:
            coords = doc.get("location", {}).get("coordinates")
            if coords and not wraps:
                d_lon = coords[0]
                if d_lon < lon_min - lon_pad or d_lon > lon_max + lon_pad:
                    geo_skipped += 1
                    continue
            scan_items.append((None, doc, proximity_km))
    log.info("safe-windows | sat build: %.2fs — %d TLE, %d static, %d geo-skipped, %d scan items (cache: %d)",
             time.perf_counter() - t0, tle_count,
             len(scan_items) - tle_count, geo_skipped, len(scan_items), len(_sat_cache))

    time_steps = []
    cursor = start_dt
    while cursor <= end_dt:
        time_steps.append(cursor)
        cursor += coarse_step

    log.info("safe-windows | coarse scan: %d time steps (every %dm over %s → %s)",
             len(time_steps), int(coarse_step.total_seconds() // 60),
             start_dt.strftime("%H:%M"), end_dt.strftime("%H:%M %b %d"))

    def check_time(cursor_time):
        t = ts.from_datetime(cursor_time)
        return (cursor_time, count_threats_fast(scan_items, trajectory, target_alt, t, proximity_km))

    t0 = time.perf_counter()
    with concurrent.futures.ThreadPoolExecutor(max_workers=os.cpu_count() or 4) as executor:
        coarse_results = list(executor.map(check_time, time_steps))
    coarse_elapsed = time.perf_counter() - t0

    threat_steps = sum(1 for _, c in coarse_results if c > 0)
    clear_steps = len(coarse_results) - threat_steps
    log.info("safe-windows | coarse done: %.2fs — %d clear, %d with threats (%.1fms/step)",
             coarse_elapsed, clear_steps, threat_steps,
             (coarse_elapsed / max(len(time_steps), 1)) * 1000)

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

    log.info("safe-windows | raw windows found: %d", len(raw_windows))

    t0 = time.perf_counter()
    refine_calls = 0
    windows = []
    for wi, (raw_start, raw_end) in enumerate(raw_windows[:5]):
        refined_start = raw_start
        check = raw_start - coarse_step
        while check < raw_start:
            check += fine_step
            if check >= raw_start:
                break
            t = ts.from_datetime(check)
            refine_calls += 1
            if count_threats_fast(scan_items, trajectory, target_alt, t, proximity_km) == 0:
                refined_start = check
                break

        refined_end = raw_end
        check = raw_end
        limit = raw_end + coarse_step
        while check < limit:
            t = ts.from_datetime(check)
            refine_calls += 1
            if count_threats_fast(scan_items, trajectory, target_alt, t, proximity_km) > 0:
                break
            refined_end = check
            check += fine_step

        verify_cursor = refined_start + fine_step
        while verify_cursor < refined_end:
            t = ts.from_datetime(verify_cursor)
            refine_calls += 1
            if count_threats_fast(scan_items, trajectory, target_alt, t, proximity_km) > 0:
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
            log.info("safe-windows | window #%d: %s → %s (%dmin)",
                     wi + 1, refined_start.strftime("%H:%M"), refined_end.strftime("%H:%M"), round(duration))

    refine_elapsed = time.perf_counter() - t0
    log.info("safe-windows | refine done: %.2fs — %d calls", refine_elapsed, refine_calls)

    windows.sort(key=lambda w: -w["duration_minutes"])
    total_elapsed = time.perf_counter() - t_total
    log.info("safe-windows | TOTAL: %.2fs — returning %d windows", total_elapsed, len(windows[:5]))
    return windows[:5]
