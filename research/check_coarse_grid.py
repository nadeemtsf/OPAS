"""
Investigates WHY scanner_fixed.py returned 0 windows for a preset despite the dense
reference showing many launch times (at the scanner's exact radius) should be clear.

Checks the EXACT set of coarse-grid launch times scan_windows_fixed.py actually samples
(t0, t0+10min, t0+20min, ... every coarse_step across the horizon) against the reference's
per-launch unsafe verdict at the scanner's exact radius. If every one of those coarse-grid
instants is reference-confirmed unsafe -- even though many OFF-grid minutes are clear --
that proves the outer 10-minute coarse grid is aliasing past every safe minute (a distinct,
separate sampling-gap finding from F9's within-orbit 9-second gap). If some coarse-grid
instants SHOULD be safe but scanner_fixed.py still returned 0 windows, that points to an
actual bug in count_threats_dense/scan_windows_fixed rather than a sampling limitation.

Usage:
    python research/check_coarse_grid.py --preset starlink --reference research/results/reference_starlink_20260922T071313Z.json
"""
import argparse
import json
from datetime import datetime
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
    ap.add_argument("--coarse-min", type=float, default=10.0)
    ap.add_argument("--hours", type=float, default=6.0)
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

    grid_step_s = float(np.min(np.diff(np.sort(launch_offset_s))))
    max_gap_s = grid_step_s / 2.0 + 1.0

    # Exact coarse grid scan_windows_fixed samples: t0, t0+coarse, ... <= t0+hours
    coarse_s = args.coarse_min * 60.0
    n_steps = int(args.hours * 3600 // coarse_s) + 1
    coarse_offsets = np.arange(n_steps) * coarse_s

    print(f"[{args.preset}] checking {len(coarse_offsets)} coarse-grid launch times "
          f"(every {args.coarse_min:.0f} min) against the reference\n")

    results = []
    for off in coarse_offsets:
        idx = np.argmin(np.abs(launch_offset_s - off))
        gap = abs(launch_offset_s[idx] - off)
        verdict = "UNSAFE" if unsafe[idx] else "safe"
        flag = "" if gap <= max_gap_s else "  (no close reference sample!)"
        results.append((off, verdict, gap))
        print(f"  t0+{off/60:>6.1f} min -> nearest reference sample {gap:.2f}s away: {verdict}{flag}")

    n_unsafe = sum(1 for _, v, _ in results if v == "UNSAFE")
    print(f"\n{n_unsafe}/{len(results)} coarse-grid instants are reference-confirmed unsafe.")
    if n_unsafe == len(results):
        print("-> Every coarse-grid instant scan_windows_fixed actually tests is unsafe, even "
              "though many OFF-grid minutes are clear. Zero windows is the CORRECT output given "
              "this 10-minute coarse grid -- the coarse grid itself is aliasing past every clear "
              "minute. This is a genuine, separate sampling-gap finding, not a bug.")
    else:
        print("-> At least one coarse-grid instant SHOULD have been safe. scanner_fixed.py "
              "returning 0 windows here likely indicates an actual bug -- worth inspecting "
              "count_threats_dense for that specific instant.")


if __name__ == "__main__":
    main()