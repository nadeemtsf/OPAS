"""
A fixed version of OPAS's scanning algorithm, designed to correct the 100% false-safe 
rate measured in LEO environments.

This script implements three specific fixes:
1. Realistic Radius Cap: Shrinks the LEO proximity radius from 50 km to 10.0 km.
2. Dense Native Sampling: Overrides the default trajectory generator to produce 600
   waypoints (roughly every 9 seconds) and forces the inner scanner to evaluate ALL 
   of them, preventing fast-moving crossing objects from slipping between samples.
3. Boundary Clamping: Strictly bounds returned windows to [start_dt, end_dt] (fixes F1).

Usage:
    python research/scanner_fixed.py --preset iss
"""
import argparse
import concurrent.futures
import json
import logging
import os
import platform
import sys
import time
from datetime import datetime, timedelta, timezone
from math import pi, sqrt
from pathlib import Path

import numpy
import skyfield
from skyfield.framelib import itrs

# Ensure backend logic is accessible
RESEARCH = Path(__file__).resolve().parent
REPO = RESEARCH.parent
sys.path.insert(0, str(REPO / "backend"))

import baseline
from db import ts, get_sat, _sat_cache
from orbital import EARTH_R, tle_epoch_age_days, generate_trajectory
from proximity import geodetic_to_ecef, screening_radius_km, HAS_NATIVE_MATH, opas_math

log = logging.getLogger("opas")

# FIX 1: Realistic Screening Radius (10 km for LEO, 50 km for GEO)
def get_base_proximity(alt_km):
    return 10.0 if alt_km < 2000 else 50.0

def count_threats_dense(scan_items, trajectory, target_alt, t, proximity_km):
    count = 0
    steps = len(trajectory) - 1
    if steps < 1:
        return 0
        
    r = EARTH_R + target_alt
    period_sec = 2 * pi * sqrt(r ** 3 / 398600.4418)
    step_sec = period_sec / steps
    ascent_steps = min(steps, max(1, round(600 / step_sec)))
    
    # FIX 2: Evaluate ALL waypoints in the dense 600-step trajectory (stride = 1)
    sample_indices = list(range(ascent_steps, steps + 1, 1))
    if not sample_indices:
        sample_indices = [steps]
        
    sample_wps = [trajectory[idx] for idx in sample_indices]
    sample_ecef = [geodetic_to_ecef(wp["lat"], wp["lon"], wp["alt"]) for wp in sample_wps]
    wp_xs = [e[0] for e in sample_ecef]
    wp_ys = [e[1] for e in sample_ecef]
    wp_zs = [e[2] for e in sample_ecef]
    
    t_samples = ts.tt_jd([t.tt + period_sec * idx / (steps * 86400.0) for idx in sample_indices])

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
                if opas_math.any_threat_ecef(wp_xs, wp_ys, wp_zs, xyz[0], xyz[1], xyz[2], radius):
                    count += 1
            else:
                for i, (wx, wy, wz) in enumerate(sample_ecef):
                    d = sqrt((float(xyz[0][i]) - wx)**2 + (float(xyz[1][i]) - wy)**2 + (float(xyz[2][i]) - wz)**2)
                    if d < radius:
                        count += 1
                        break
        else:
            coords = doc["location"]["coordinates"]
            d_ecef = geodetic_to_ecef(coords[1], coords[0], doc["altitude_km"])
            if HAS_NATIVE_MATH:
                if opas_math.any_within_ecef(wp_xs, wp_ys, wp_zs, d_ecef[0], d_ecef[1], d_ecef[2], radius):
                    count += 1
            else:
                for wx, wy, wz in sample_ecef:
                    d = sqrt((d_ecef[0] - wx)**2 + (d_ecef[1] - wy)**2 + (d_ecef[2] - wz)**2)
                    if d < radius:
                        count += 1
                        break
    return count

def scan_windows_fixed(candidates, target_lat, target_lon, target_alt, target_inc, start_dt, end_dt):
    proximity_km = get_base_proximity(target_alt)
    
    # Generate DENSE trajectory (600 steps)
    trajectory = generate_trajectory(target_lat, target_lon, target_alt, target_inc, steps=600)
    
    coarse_step = timedelta(minutes=10)
    fine_step = timedelta(minutes=1)
    
    traj_lons = [wp["lon"] for wp in trajectory]
    lon_min, lon_max = min(traj_lons), max(traj_lons)
    lon_pad = 15.0
    wraps = (lon_max - lon_min) > 300

    scan_items = []
    for doc in candidates:
        sat = get_sat(doc)
        if sat is not None:
            tle_age = tle_epoch_age_days(doc["tle_line1"])
            # FIX 4: Kill the exponential 200km inflation. 
            # SGP4 errors grow linearly, so cap the age penalty at 5.0 km max.
            age_penalty = min(0.5 * (tle_age if tle_age else 0), 5.0)
            radius = proximity_km + age_penalty
            scan_items.append((sat, doc, radius))
        else:
            coords = doc.get("location", {}).get("coordinates")
            if coords and not wraps:
                d_lon = coords[0]
                if d_lon < lon_min - lon_pad or d_lon > lon_max + lon_pad:
                    continue
            scan_items.append((None, doc, proximity_km))

    time_steps = []
    cursor = start_dt
    while cursor <= end_dt:
        time_steps.append(cursor)
        cursor += coarse_step

    def check_time(cursor_time):
        t = ts.from_datetime(cursor_time)
        return (cursor_time, count_threats_dense(scan_items, trajectory, target_alt, t, proximity_km))

    with concurrent.futures.ThreadPoolExecutor(max_workers=os.cpu_count() or 4) as executor:
        coarse_results = list(executor.map(check_time, time_steps))

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
            if count_threats_dense(scan_items, trajectory, target_alt, t, proximity_km) == 0:
                refined_start = check
                break

        refined_end = raw_end
        check = raw_end
        limit = raw_end + coarse_step
        while check < limit:
            t = ts.from_datetime(check)
            if count_threats_dense(scan_items, trajectory, target_alt, t, proximity_km) > 0:
                break
            refined_end = check
            check += fine_step

        verify_cursor = refined_start + fine_step
        while verify_cursor < refined_end:
            t = ts.from_datetime(verify_cursor)
            if count_threats_dense(scan_items, trajectory, target_alt, t, proximity_km) > 0:
                refined_end = verify_cursor
                break
            verify_cursor += fine_step
            
        # FIX 3: Strictly clamp boundaries to requested range
        final_start = max(refined_start, start_dt)
        final_end = min(refined_end, end_dt)

        duration = (final_end - final_start).total_seconds() / 60
        if duration >= 15:
            windows.append({
                "start": final_start.isoformat(),
                "end": final_end.isoformat(),
                "duration_minutes": round(duration),
            })

    windows.sort(key=lambda w: -w["duration_minutes"])
    return windows[:5]

def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--preset", required=True, choices=list(baseline.PRESETS.keys()))
    parser.add_argument("--hours", type=int, default=6)
    args = parser.parse_args()

    docs, meta = baseline.load_snapshot()
    t0 = datetime.fromisoformat(meta["exported_at_utc"])
    baseline.freeze_tle_age(t0)

    label, lat, lon, alt, inc = baseline.PRESETS[args.preset]
    candidates = [d for d in docs
                  if isinstance(d.get("altitude_km"), (int, float))
                  and alt - baseline.ALT_BAND_KM <= d["altitude_km"] <= alt + baseline.ALT_BAND_KM]
    
    end = t0 + timedelta(hours=args.hours)
    
    print(f"Running FIXED scanner for {args.preset} (alt: {alt} km)...")
    t_start = time.perf_counter()
    windows = scan_windows_fixed(candidates, lat, lon, alt, inc, t0, end)
    elapsed = time.perf_counter() - t_start
    
    print(f"Done in {elapsed:.1f}s. Returned {len(windows)} windows:")
    for w in windows:
        print(f"  {w['start']} -> {w['end']} ({w['duration_minutes']} min)")

    res = {
        "preset": args.preset,
        "horizon_hours": args.hours,
        "windows": windows
    }
    
    out_path = baseline.RESULTS_DIR / f"fixed_{args.preset}_{datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ')}.json"
    out_path.write_text(json.dumps({
        "environment": baseline.environment(meta),
        "results": [res]
    }, indent=2))
    print(f"Saved {out_path}")

if __name__ == "__main__":
    main()