import time
import logging
import os
from concurrent.futures import ProcessPoolExecutor
from multiprocessing import get_context
from math import pi, sqrt
from datetime import timedelta

import numpy as np

from skyfield.framelib import itrs

from encounters import has_close_approach
from windows import LAUNCH_STEP_SECONDS, find_windows, WindowVerificationError

from db import ts, get_sat, _sat_cache
from orbital import EARTH_R, tle_epoch_age_days
from proximity import (
    geodetic_to_ecef, screening_radius_km,
    estimate_sigma_m, compute_pc, threat_level_from_pc, proximity_severity,
)

log = logging.getLogger("opas")

def safe_window_proximity_km(alt_km):
    """10 km for LEO (alt < 2000 km), 50 km for higher orbits."""
    return 10.0 if alt_km < 2000 else 50.0

SAFE_WINDOW_PROXIMITY_KM = 50  # legacy default, used by count_threats


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


def count_threats_fast(scan_items, trajectory, target_alt, t, proximity_km,
                       stop_after_first=False, strict=False):
    count = 0
    steps = len(trajectory) - 1
    if steps < 1:
        if strict:
            raise WindowVerificationError('The flight trajectory has no intervals to verify.')
        return 0
    r = EARTH_R + target_alt
    period_sec = 2 * pi * sqrt(r ** 3 / 398600.4418)
    step_sec = period_sec / steps
    ascent_steps = min(steps, max(1, round(600 / step_sec)))
    stride = 1  # evaluate every waypoint for dense coverage
    sample_indices = list(range(ascent_steps, steps + 1, stride))
    if not sample_indices:
        sample_indices = [steps]
    sample_wps = [trajectory[idx] for idx in sample_indices]
    sample_ecef = [geodetic_to_ecef(wp["lat"], wp["lon"], wp["alt"]) for wp in sample_wps]
    sample_ecef = np.asarray(sample_ecef)
    t_samples = ts.tt_jd([t.tt + period_sec * idx / (steps * 86400.0)
                          for idx in sample_indices])

    for item in scan_items:
        sat, doc = item[0], item[1]
        radius = item[2] if len(item) > 2 else screening_radius_km(
            proximity_km, tle_epoch_age_days(doc["tle_line1"]) if doc.get("tle_line1") else None)
        if not np.isfinite(radius) or radius <= 0:
            raise WindowVerificationError('An object has an invalid screening radius.')

        if sat is not None:
            try:
                xyz = np.asarray(sat.at(t_samples).frame_xyz(itrs).km).T
            except Exception:
                if strict:
                    raise WindowVerificationError(
                        f"Orbital prediction failed for object {doc.get('norad_id', 'unknown')}.")
                # A failed prediction cannot establish a clear launch time.
                count += 1
                if stop_after_first:
                    return count
                continue
        else:
            if doc.get("tle_line1") or doc.get("tle_line2"):
                if strict:
                    raise WindowVerificationError('An orbital propagator is unavailable.')
                # A missing propagator is not evidence of a stationary object.
                count += 1
                if stop_after_first:
                    return count
                continue
            coords = doc["location"]["coordinates"]
            position = geodetic_to_ecef(coords[1], coords[0], doc["altitude_km"])
            xyz = np.broadcast_to(position, sample_ecef.shape)
        try:
            obstructed = has_close_approach(sat, xyz, sample_ecef, t_samples.tt, radius, ts,
                                            strict=strict)
        except ValueError as error:
            raise WindowVerificationError(
                f"Flight prediction or refinement failed for object {doc.get('norad_id', 'unknown')}.") from error
        if obstructed:
            count += 1
            if stop_after_first:
                return count

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


def _prepare_window_worker(documents, trajectory, target_alt, proximity_km):
    """Build process-local Skyfield objects once; pass frozen radii from parent."""
    global _window_worker_state
    items = [(get_sat(doc) if has_sat else None, doc, radius)
             for doc, radius, has_sat in documents]
    failed = any(has_sat and item[0] is None
                 for item, (_, _, has_sat) in zip(items, documents))
    _window_worker_state = items, trajectory, target_alt, proximity_km, failed


def _window_launch_obstructed(launch_dt):
    items, trajectory, alt, proximity, failed = _window_worker_state
    if failed:
        raise WindowVerificationError("The window search could not load an orbital object. Refresh the catalogue and retry.")
    return count_threats_fast(items, trajectory, alt, ts.from_datetime(launch_dt),
                             proximity, stop_after_first=True, strict=True) > 0


def scan_windows(candidates, trajectory, target_lat, target_lon, target_alt,
                 start_dt, end_dt, proximity_km, launch_step_seconds=LAUNCH_STEP_SECONDS,
                 workers=None, verification_step_seconds=None, progress=None, diagnostics=None):
    t_total = time.perf_counter()
    traj_lons = [wp["lon"] for wp in trajectory]
    lon_min, lon_max = min(traj_lons), max(traj_lons)
    lon_pad = 15.0
    wraps = (lon_max - lon_min) > 300

    t0 = time.perf_counter()
    scan_items = []
    tle_count = 0
    geo_skipped = 0
    ages = []
    for doc in candidates:
        sat = get_sat(doc)
        if sat is not None:
            tle_count += 1
            tle_age = tle_epoch_age_days(doc["tle_line1"])
            if tle_age is not None:
                ages.append(tle_age)
            radius = screening_radius_km(proximity_km, tle_age)
            scan_items.append((sat, doc, radius))
        else:
            if doc.get("tle_line1") or doc.get("tle_line2"):
                raise WindowVerificationError("The window search could not load an orbital object. Refresh the catalogue and retry.")
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
    if diagnostics is not None:
        diagnostics.update(tle_objects=tle_count, static_objects=len(scan_items)-tle_count,
                           static_objects_excluded=geo_skipped, scan_items=len(scan_items),
                           radius_min_km=min((item[2] for item in scan_items), default=None),
                           radius_max_km=max((item[2] for item in scan_items), default=None),
                           oldest_tle_age_days=round(max(ages), 3) if ages else None,
                           future_epoch_objects=sum(age < 0 for age in ages))

    def is_obstructed(launch_dt):
        t = ts.from_datetime(launch_dt)
        return count_threats_fast(scan_items, trajectory, target_alt, t, proximity_km,
                                  stop_after_first=True, strict=True) > 0

    workers = min(os.cpu_count() or 4, 4) if workers is None else workers
    options = dict(launch_step_seconds=launch_step_seconds,
                   verification_step_seconds=verification_step_seconds,
                   progress=progress, diagnostics=diagnostics)
    if diagnostics is not None:
        diagnostics['workers'] = workers
    if progress:
        progress({'phase': 'orbital_data_ready', **(diagnostics or {})})
    if workers == 1:
        windows = find_windows(is_obstructed, start_dt, end_dt, workers=1,
                               **options)
    else:
        documents = [(doc, radius, sat is not None) for sat, doc, radius in scan_items]
        # Spawn works on Windows too and avoids inheriting thread/BLAS state.
        with ProcessPoolExecutor(max_workers=workers, mp_context=get_context('spawn'),
                                 initializer=_prepare_window_worker,
                                 initargs=(documents, trajectory, target_alt, proximity_km)) as executor:
            windows = find_windows(is_obstructed, start_dt, end_dt, workers=1,
                                   **options,
                                   check_many=lambda points: executor.map(_window_launch_obstructed, points))
    log.info("safe-windows | TOTAL: %.2fs — returning %d windows",
             time.perf_counter() - t_total, len(windows))
    return windows
