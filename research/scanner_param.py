"""
A parameterized COPY of backend/scanner.py's scan_windows / count_threats_fast.

backend/scanner.py itself is never imported for its scan_windows/count_threats_fast
(only for shared helpers: ts, get_sat, _sat_cache, SAFE_WINDOW_PROXIMITY_KM). The two
functions below are separate, editable copies, because the real ones hardcode:
  - coarse_step = 10 min, fine_step = 2 min          (inside scan_windows)
  - the inner sample count via `steps // 12`          (inside count_threats_fast)
Here those three become function arguments: coarse_step, fine_step, n_intervals
(n_intervals=12 reproduces the original's sample count exactly).

Everything else -- the window-merging logic, the boundary refinement, the TLE-age
screening radius, the candidate/scan_items construction -- is copied verbatim from
the real scan_windows/count_threats_fast, so a run at the defaults (coarse=10min,
fine=2min, n_intervals=12) should reproduce your baseline.py output exactly. That
reproduction is checked automatically by --validate below; if it does not match,
the sweep results are not trustworthy and the mismatch must be fixed first.

Usage (from the repo root, after export_snapshot.py and baseline.py):

    python research/scanner_param.py --validate                    # all 5 presets
    python research/scanner_param.py --validate --preset iss        # one preset

    # one-off run, for spot checks (sweep.py drives this in bulk):
    python research/scanner_param.py --preset iss --coarse-min 5 --fine-min 1 --n-intervals 12
"""
import argparse
import concurrent.futures
import os
import time
from datetime import timedelta
from math import pi, sqrt

from skyfield.framelib import itrs

import baseline
from baseline import PRESETS, load_snapshot, freeze_tle_age, ALT_BAND_KM
import scanner  # for ts, get_sat, _sat_cache, SAFE_WINDOW_PROXIMITY_KM (shared, unmodified)
from orbital import EARTH_R, tle_epoch_age_days, generate_trajectory
from proximity import geodetic_to_ecef, screening_radius_km, HAS_NATIVE_MATH, opas_math


def _ecef_dist(ax, ay, az, bx, by, bz):
    dx, dy, dz = ax - bx, ay - by, az - bz
    return sqrt(dx * dx + dy * dy + dz * dz)


def count_threats_fast_param(scan_items, trajectory, target_alt, t, proximity_km, n_intervals):
    """Verbatim copy of scanner.count_threats_fast, with the hardcoded '12' as n_intervals."""
    count = 0
    steps = len(trajectory) - 1
    if steps < 1:
        return 0
    r = EARTH_R + target_alt
    period_sec = 2 * pi * sqrt(r ** 3 / 398600.4418)
    step_sec = period_sec / steps
    ascent_steps = min(steps, max(1, round(600 / step_sec)))
    stride = max(1, (steps - ascent_steps) // n_intervals)
    sample_indices = list(range(ascent_steps, steps + 1, stride))
    if not sample_indices:
        sample_indices = [steps]
    sample_wps = [trajectory[idx] for idx in sample_indices]
    sample_ecef = [geodetic_to_ecef(wp["lat"], wp["lon"], wp["alt"]) for wp in sample_wps]
    wp_xs = [e[0] for e in sample_ecef]
    wp_ys = [e[1] for e in sample_ecef]
    wp_zs = [e[2] for e in sample_ecef]
    t_samples = scanner.ts.tt_jd([t.tt + period_sec * idx / (steps * 86400.0)
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
                if opas_math.any_threat_ecef(wp_xs, wp_ys, wp_zs, xyz[0], xyz[1], xyz[2], radius):
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
                if opas_math.any_within_ecef(wp_xs, wp_ys, wp_zs, d_ecef[0], d_ecef[1], d_ecef[2], radius):
                    count += 1
            else:
                for wx, wy, wz in sample_ecef:
                    d = sqrt((d_ecef[0] - wx) ** 2 + (d_ecef[1] - wy) ** 2 + (d_ecef[2] - wz) ** 2)
                    if d < radius:
                        count += 1
                        break
    return count


def scan_windows_param(candidates, trajectory, target_lat, target_lon, target_alt,
                       start_dt, end_dt, proximity_km, coarse_step, fine_step, n_intervals):
    """
    Verbatim copy of scanner.scan_windows, with coarse_step/fine_step (timedeltas) and
    n_intervals (int) as parameters instead of the hardcoded 10 min / 2 min / 12.
    Returns (windows, n_evaluations) -- n_evaluations added for the sweep's cost metric
    (the real scan_windows doesn't return this; baseline.py gets it via a tracer wrapper
    instead, but counting it inline here is simpler since this is already a private copy).
    """
    traj_lons = [wp["lon"] for wp in trajectory]
    lon_min, lon_max = min(traj_lons), max(traj_lons)
    lon_pad = 15.0
    wraps = (lon_max - lon_min) > 300

    scan_items = []
    for doc in candidates:
        sat = scanner.get_sat(doc)
        if sat is not None:
            tle_age = tle_epoch_age_days(doc["tle_line1"])
            radius = screening_radius_km(proximity_km, tle_age)
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

    n_eval = 0

    def check_time(cursor_time):
        t = scanner.ts.from_datetime(cursor_time)
        return (cursor_time, count_threats_fast_param(scan_items, trajectory, target_alt, t,
                                                       proximity_km, n_intervals))

    with concurrent.futures.ThreadPoolExecutor(max_workers=os.cpu_count() or 4) as executor:
        coarse_results = list(executor.map(check_time, time_steps))
    n_eval = len(coarse_results)  # one evaluation per coarse time step

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
            t = scanner.ts.from_datetime(check)
            n_eval += 1
            if count_threats_fast_param(scan_items, trajectory, target_alt, t, proximity_km, n_intervals) == 0:
                refined_start = check
                break

        refined_end = raw_end
        check = raw_end
        limit = raw_end + coarse_step
        while check < limit:
            t = scanner.ts.from_datetime(check)
            n_eval += 1
            if count_threats_fast_param(scan_items, trajectory, target_alt, t, proximity_km, n_intervals) > 0:
                break
            refined_end = check
            check += fine_step

        verify_cursor = refined_start + fine_step
        while verify_cursor < refined_end:
            t = scanner.ts.from_datetime(verify_cursor)
            n_eval += 1
            if count_threats_fast_param(scan_items, trajectory, target_alt, t, proximity_km, n_intervals) > 0:
                refined_end = verify_cursor
                break
            verify_cursor += fine_step

        duration = (refined_end - refined_start).total_seconds() / 60
        if duration >= 15:
            windows.append({"start": refined_start.isoformat(), "end": refined_end.isoformat(),
                            "duration_minutes": round(duration)})

    windows.sort(key=lambda w: -w["duration_minutes"])
    return windows[:5], n_eval


def run_preset(key, docs, t0, hours, coarse_step, fine_step, n_intervals):
    label, lat, lon, alt, inc = PRESETS[key]
    candidates = [d for d in docs
                  if isinstance(d.get("altitude_km"), (int, float))
                  and alt - ALT_BAND_KM <= d["altitude_km"] <= alt + ALT_BAND_KM]
    trajectory = generate_trajectory(lat, lon, alt, inc)
    end = t0 + timedelta(hours=hours)
    t_start = time.perf_counter()
    windows, n_eval = scan_windows_param(candidates, trajectory, lat, lon, alt, t0, end,
                                         scanner.SAFE_WINDOW_PROXIMITY_KM,
                                         coarse_step, fine_step, n_intervals)
    elapsed = time.perf_counter() - t_start
    return windows, n_eval, elapsed, len(candidates)


def validate(preset_filter=None):
    import json
    baseline_path = None
    from pathlib import Path
    cands = sorted((baseline.RESULTS_DIR).glob("baseline_*.json"))
    if not cands:
        raise SystemExit("No baseline_*.json found in research/results/. Run baseline.py first.")
    baseline_path = cands[-1]
    print(f"Validating against {baseline_path}")
    base = json.loads(baseline_path.read_text())

    docs, meta = load_snapshot()
    if base["environment"]["snapshot_sha256"] != meta["sha256_uncompressed"]:
        raise SystemExit("Baseline and current snapshot differ (sha256 mismatch) -- "
                         "re-run baseline.py against research/data's current snapshot first.")
    t0 = __import__("datetime").datetime.fromisoformat(meta["exported_at_utc"])
    freeze_tle_age(t0)

    all_ok = True
    for r in base["results"]:
        key = r["preset"]
        if preset_filter and key != preset_filter:
            continue
        windows, n_eval, elapsed, n_cand = run_preset(
            key, docs, t0, r["horizon_hours"],
            coarse_step=timedelta(minutes=10), fine_step=timedelta(minutes=2), n_intervals=12)
        base_windows = [{"start": w["start"], "end": w["end"], "duration_minutes": w["duration_minutes"]}
                        for w in r["windows"]]
        match = windows == base_windows
        eval_match = n_eval == r["n_evaluations"]
        status = "OK" if (match and eval_match) else "MISMATCH"
        if not (match and eval_match):
            all_ok = False
        print(f"[{key}] {status}  windows_match={match}  evaluations: got {n_eval}, "
              f"baseline {r['n_evaluations']} (match={eval_match})  time={elapsed:.1f}s")
        if not match:
            print(f"    baseline windows: {base_windows}")
            print(f"    got windows:      {windows}")

    print("\nAll presets matched the baseline exactly." if all_ok else
          "\nMISMATCH -- scanner_param.py does not faithfully reproduce scan_windows. "
          "Do not trust sweep.py results until this is fixed.")
    return all_ok


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--validate", action="store_true",
                    help="run at default settings and diff against the latest baseline_*.json")
    ap.add_argument("--preset", choices=list(PRESETS), default=None)
    ap.add_argument("--coarse-min", type=float, default=10.0)
    ap.add_argument("--fine-min", type=float, default=2.0)
    ap.add_argument("--n-intervals", type=int, default=12)
    ap.add_argument("--hours", type=float, default=6.0)
    args = ap.parse_args()

    if args.validate:
        ok = validate(args.preset)
        raise SystemExit(0 if ok else 1)

    if not args.preset:
        raise SystemExit("Specify --preset (or use --validate to check all presets from the baseline).")

    docs, meta = load_snapshot()
    from datetime import datetime
    t0 = datetime.fromisoformat(meta["exported_at_utc"])
    freeze_tle_age(t0)
    windows, n_eval, elapsed, n_cand = run_preset(
        args.preset, docs, t0, args.hours,
        timedelta(minutes=args.coarse_min), timedelta(minutes=args.fine_min), args.n_intervals)
    print(f"[{args.preset}] coarse={args.coarse_min}min fine={args.fine_min}min "
          f"n_intervals={args.n_intervals}  candidates={n_cand}  time={elapsed:.1f}s  "
          f"evaluations={n_eval}")
    for w in windows:
        print(f"  window: {w['start']} -> {w['end']} ({w['duration_minutes']} min)")
    if not windows:
        print("  no windows returned")


if __name__ == "__main__":
    main()
