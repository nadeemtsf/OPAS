"""
Sweep scan_windows_param over a grid of (coarse_step, fine_step, n_intervals) and
score each configuration's returned windows against the DENSE REFERENCE you already
collected with reference.py. Does not re-run reference.py -- the ground truth (which
launch times are actually unsafe) doesn't depend on OPAS's scan settings, only the
windows being tested do.

For each configuration, prints and records:
  - wall-clock time and evaluation count (cost)
  - the windows it returned
  - the false-safe rate of those windows: what fraction of their minutes the
    reference marks unsafe at OPAS's own screening radius (accuracy)

This directly answers the tradeoff question from the study design: does a smaller
coarse step / more inner samples actually buy fewer false-safe minutes, and at what
cost in evaluations?

Requires: scanner_param.py has already passed --validate for this preset (run that
first -- this script does not re-check correctness, only sweeps).

Usage (from the repo root):

    python research/sweep.py --preset iss \\
        --reference research/results/reference_iss_20260921T102002Z.json \\
        --baseline research/results/baseline_20260921T090905Z.json

    # override the default grid (see --help for the defaults):
    python research/sweep.py --preset sso --reference ... --baseline ... \\
        --coarse-min 2,5,10,20,30 --fine-min 0.5,1,2,4 --n-intervals 6,12,24,48

Results are appended to research/results/sweep_<preset>_<stamp>.jsonl as they
complete (one JSON line per configuration), so a long sweep can be interrupted
(Ctrl+C) without losing finished configurations, and resumed later by re-running
with a narrower grid.
"""
import argparse
import itertools
import json
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path

import numpy as np

import baseline
from baseline import PRESETS, load_snapshot, freeze_tle_age, RESULTS_DIR
import scanner_param


def parse_dt(s):
    return datetime.fromisoformat(s.replace("Z", "+00:00"))


def parse_list(s, cast):
    return [cast(x) for x in s.split(",")]


def load_reference(reference_path):
    ref_meta = json.loads(Path(reference_path).read_text())
    ref = np.load(Path(reference_path).with_suffix(".npz"))
    launch_offset_s = ref["launch_offset_s"]
    p_k, p_obj, p_d = ref["pair_launch_idx"], ref["pair_obj_idx"], ref["pair_dmin_km"]
    obj_radius = ref["obj_radius_km"]
    unsafe = np.zeros(len(launch_offset_s), dtype=bool)
    within = p_d < obj_radius[p_obj]
    unsafe[np.unique(p_k[within])] = True
    grid_step_s = float(np.min(np.diff(np.sort(launch_offset_s))))
    return ref_meta, launch_offset_s, unsafe, grid_step_s


def window_false_safe(win_start_iso, win_end_iso, t0, launch_offset_s, unsafe, grid_step_s):
    """Same logic as compare.py's false_safe_rate, inlined so this script is standalone."""
    s = (parse_dt(win_start_iso) - t0).total_seconds()
    e = (parse_dt(win_end_iso) - t0).total_seconds()
    if e <= s:
        return {"reference_samples": 0, "marked_unsafe": 0, "false_safe_rate": None, "uncovered_minutes": 0}
    max_gap_s = grid_step_s / 2.0 + 1.0
    in_win = (launch_offset_s >= s - 1e-6) & (launch_offset_s <= e + 1e-6)
    cov_offsets = launch_offset_s[in_win]
    cov_unsafe = unsafe[in_win]
    grid = np.arange(s, e + 1e-6, 60.0)
    if len(cov_offsets):
        gap = np.min(np.abs(grid[:, None] - cov_offsets[None, :]), axis=1)
    else:
        gap = np.full(len(grid), np.inf)
    n_uncovered = int((gap > max_gap_s).sum())
    n_cov = len(cov_offsets)
    n_unsafe = int(cov_unsafe.sum())
    return {"reference_samples": n_cov, "marked_unsafe": n_unsafe,
            "false_safe_rate": (n_unsafe / n_cov) if n_cov else None,
            "uncovered_minutes": n_uncovered}


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--preset", required=True, choices=list(PRESETS))
    ap.add_argument("--reference", required=True, help="reference_<preset>_*.json from reference.py")
    ap.add_argument("--baseline", required=True, help="baseline_*.json from baseline.py (for hours/snapshot check)")
    ap.add_argument("--coarse-min", default="5,10,20", help="comma-separated coarse step minutes (default matches OPAS's 10 plus one smaller, one larger)")
    ap.add_argument("--fine-min", default="2", help="comma-separated fine step minutes (default: OPAS's own 2)")
    ap.add_argument("--n-intervals", default="6,12,24", help="comma-separated inner sample counts (default 12 = OPAS's own)")
    args = ap.parse_args()

    base = json.loads(Path(args.baseline).read_text())
    ref_meta, launch_offset_s, unsafe, grid_step_s = load_reference(args.reference)
    if base["environment"]["snapshot_sha256"] != ref_meta["environment"]["snapshot_sha256"]:
        raise SystemExit("baseline and reference were run on different snapshots -- not comparable.")
    if ref_meta["args"]["preset"] != args.preset:
        raise SystemExit(f"--preset {args.preset} doesn't match the reference file's preset "
                         f"({ref_meta['args']['preset']}).")
    preset_result = next((r for r in base["results"] if r["preset"] == args.preset), None)
    if preset_result is None:
        raise SystemExit(f"No baseline result for preset '{args.preset}'.")
    hours = preset_result["horizon_hours"]

    docs, meta = load_snapshot()
    t0 = datetime.fromisoformat(meta["exported_at_utc"])
    freeze_tle_age(t0)

    coarse_list = parse_list(args.coarse_min, float)
    fine_list = parse_list(args.fine_min, float)
    ni_list = parse_list(args.n_intervals, int)
    grid = list(itertools.product(coarse_list, fine_list, ni_list))
    print(f"Sweeping {len(grid)} configuration(s) for '{args.preset}': "
          f"coarse={coarse_list} min, fine={fine_list} min, n_intervals={ni_list}")
    print(f"Reference overall unsafe rate at OPAS's radius: {unsafe.mean():.1%} "
          f"({len(launch_offset_s)} launch times)\n")

    RESULTS_DIR.mkdir(parents=True, exist_ok=True)
    out_path = RESULTS_DIR / f"sweep_{args.preset}_{datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ')}.jsonl"

    with open(out_path, "a") as out_f:
        for i, (coarse_min, fine_min, n_intervals) in enumerate(grid, 1):
            t_start = time.perf_counter()
            windows, n_eval, elapsed, n_cand = scanner_param.run_preset(
                args.preset, docs, t0, hours,
                timedelta(minutes=coarse_min), timedelta(minutes=fine_min), n_intervals)

            win_results = []
            total_safe_claimed_min = 0
            total_false_safe_min = 0
            for w in windows:
                fs = window_false_safe(w["start"], w["end"], t0, launch_offset_s, unsafe, grid_step_s)
                win_results.append({**w, **fs})
                total_safe_claimed_min += w["duration_minutes"]
                if fs["false_safe_rate"] is not None:
                    total_false_safe_min += fs["false_safe_rate"] * fs["reference_samples"]

            record = {
                "coarse_min": coarse_min, "fine_min": fine_min, "n_intervals": n_intervals,
                "n_evaluations": n_eval, "wall_seconds": round(elapsed, 2), "n_candidates": n_cand,
                "n_windows": len(windows), "total_safe_claimed_minutes": total_safe_claimed_min,
                "total_false_safe_minutes_est": round(total_false_safe_min, 1),
                "windows": win_results,
            }
            out_f.write(json.dumps(record) + "\n")
            out_f.flush()

            prefix = (f"[{i}/{len(grid)}] coarse={coarse_min}min fine={fine_min}min "
                     f"n_intervals={n_intervals}  evals={n_eval}  time={elapsed:.1f}s  windows={len(windows)}")
            if total_safe_claimed_min:
                rate = total_false_safe_min / total_safe_claimed_min
                print(f"{prefix}  claimed_safe={total_safe_claimed_min}min  "
                      f"~false_safe={total_false_safe_min:.0f}min ({rate:.0%})")
            else:
                print(f"{prefix}  no windows returned")

    print(f"\nSaved {out_path} ({len(grid)} configurations, one JSON line each)")


if __name__ == "__main__":
    main()
