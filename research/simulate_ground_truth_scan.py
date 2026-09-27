"""
Reproduces scan_windows_fixed.py's EXACT window-forming algorithm (coarse pass, boundary
refinement, interior 1-min verification, final >=15min filter) but replaces the live
per-instant scanner call with a direct lookup against the dense reference at the scanner's
exact per-object radius. If this ALSO returns zero windows, scanner_fixed.py's 0-window
result is correct (a coarser-grid version of the same sampling-gap problem as F9). If it
finds real windows, scanner_fixed.py has an actual bug worth chasing down.

Usage:
    python research/simulate_ground_truth_scan.py --preset starlink --reference research/results/reference_starlink_20260922T071313Z.json
"""
import argparse
import json
from datetime import datetime, timedelta
from pathlib import Path

import numpy as np

import baseline
from baseline import load_snapshot, freeze_tle_age, PRESETS
import scanner
import reference as ref_module


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--preset", required=True)
    ap.add_argument("--reference", required=True)
    ap.add_argument("--hours", type=float, default=6.0)
    ap.add_argument("--coarse-min", type=float, default=10.0)
    ap.add_argument("--fine-min", type=float, default=1.0)
    args = ap.parse_args()

    ref_meta = json.loads(Path(args.reference).read_text())
    ref = np.load(Path(args.reference).with_suffix(".npz"))
    if ref_meta["args"].get("limit"):
        raise SystemExit("Reference used --limit; need a full run.")

    t0 = datetime.fromisoformat(ref_meta["environment"]["snapshot_T0_utc"])
    freeze_tle_age(t0)
    docs, meta = load_snapshot()
    if meta["sha256_uncompressed"] != ref_meta["environment"]["snapshot_sha256"]:
        raise SystemExit("Snapshot mismatch.")
    _, lat, lon, alt, inc = PRESETS[args.preset]
    cands = ref_module.select_candidates(docs, alt, limit=0)
    assert len(cands) == ref_meta["n_candidates_used"], "candidate mismatch"

    ages = np.array([scanner.tle_epoch_age_days(d["tle_line1"]) or 0.0 for d in cands])
    obj_radius = 10.0 + np.minimum(0.5 * ages, 5.0)

    launch_offset_s = ref["launch_offset_s"]
    p_k, p_obj, p_d = ref["pair_launch_idx"], ref["pair_obj_idx"], ref["pair_dmin_km"]
    K = len(launch_offset_s)
    unsafe = np.zeros(K, dtype=bool)
    unsafe[np.unique(p_k[p_d < obj_radius[p_obj]])] = True

    def unsafe_at(cursor_dt):
        off = (cursor_dt - t0).total_seconds()
        idx = int(np.argmin(np.abs(launch_offset_s - off)))
        return bool(unsafe[idx])

    coarse_step = timedelta(minutes=args.coarse_min)
    fine_step = timedelta(minutes=args.fine_min)
    start_dt = t0
    end_dt = t0 + timedelta(hours=args.hours)

    time_steps = []
    cursor = start_dt
    while cursor <= end_dt:
        time_steps.append(cursor)
        cursor += coarse_step
    coarse_results = [(c, 1 if unsafe_at(c) else 0) for c in time_steps]

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

    print(f"[{args.preset}] {len(raw_windows)} raw coarse-safe run(s) found before refinement:")
    for s, e in raw_windows:
        print(f"  {s.isoformat()} -> {e.isoformat()}  ({(e-s).total_seconds()/60:.0f} min at coarse resolution)")

    windows = []
    for raw_start, raw_end in raw_windows[:5]:
        refined_start = raw_start
        check = raw_start - coarse_step
        while check < raw_start:
            check += fine_step
            if check >= raw_start:
                break
            if not unsafe_at(check):
                refined_start = check
                break

        refined_end = raw_end
        check = raw_end
        limit = raw_end + coarse_step
        while check < limit:
            if unsafe_at(check):
                break
            refined_end = check
            check += fine_step

        verify_cursor = refined_start + fine_step
        while verify_cursor < refined_end:
            if unsafe_at(verify_cursor):
                refined_end = verify_cursor
                break
            verify_cursor += fine_step

        final_start = max(refined_start, start_dt)
        final_end = min(refined_end, end_dt)
        duration = (final_end - final_start).total_seconds() / 60
        print(f"  after refinement: {final_start.isoformat()} -> {final_end.isoformat()} ({duration:.1f} min)"
              + ("  [KEPT]" if duration >= 15 else "  [discarded, <15min]"))
        if duration >= 15:
            windows.append({"start": final_start.isoformat(), "end": final_end.isoformat(),
                            "duration_minutes": round(duration)})

    print(f"\nGround-truth-simulated scan_windows_fixed result: {len(windows)} window(s) >= 15 min.")
    if windows:
        print("-> scanner_fixed.py's actual 0-window output does NOT match what the true data "
              "supports. This points to a real bug -- worth inspecting count_threats_dense.")
    else:
        print("-> Even with perfect (dense-reference) knowledge, no >=15 min safe window exists "
              "in this horizon at scan_windows_fixed's own coarse/fine grid. 0 windows is correct.")


if __name__ == "__main__":
    main()