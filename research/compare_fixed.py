"""
Validates a scanner_fixed.py run against the dense reference, using the EXACT
per-object screening radius formula scanner_fixed.py's FIX 4 applies:
    radius_km = 10.0 + min(0.5 * tle_age_days, 5.0)   # ranges 10-15 km
This replaces the flat p_d < 10.0 / p_d < 15.0 guesses used earlier, which
didn't match the scanner's actual per-object radius and skewed the false-safe
rate (most TLEs in this catalog are old enough to saturate at 15 km, so a flat
10.0 threshold undercounts unsafe minutes).

Usage:
    python research/compare_fixed.py \
        --baseline research/results/fixed_iss_20260926T172830Z.json \
        --reference research/results/reference_iss_20260921T102002Z.json \
        --preset iss
"""
import argparse
import json
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

import numpy as np

RESEARCH = Path(__file__).resolve().parent
RESULTS_DIR = RESEARCH / "results"

import baseline
from baseline import load_snapshot, freeze_tle_age, PRESETS
import scanner              # gives us the frozen tle_epoch_age_days after freeze_tle_age()
import reference as ref_module  # reuse select_candidates() so object order matches exactly


def load(path):
    return json.loads(Path(path).read_text())


def parse_dt(s):
    return datetime.fromisoformat(s.replace("Z", "+00:00"))


def false_safe_rate(win_start, win_end, launch_offset_s, t0, unsafe_mask, max_gap_s):
    win_s = (win_start - t0).total_seconds()
    win_e = (win_end - t0).total_seconds()
    if win_e <= win_s:
        return 0, 0, 0, {}
    in_win = (launch_offset_s >= win_s - 1e-6) & (launch_offset_s <= win_e + 1e-6)
    covered_offsets = launch_offset_s[in_win]
    covered_unsafe = unsafe_mask[in_win]
    grid = np.arange(win_s, win_e + 1e-6, 60.0)
    if len(covered_offsets):
        nearest_gap = np.min(np.abs(grid[:, None] - covered_offsets[None, :]), axis=1)
    else:
        nearest_gap = np.full(len(grid), np.inf)
    n_uncovered = int((nearest_gap > max_gap_s).sum())
    return len(covered_offsets), int(covered_unsafe.sum()), n_uncovered, {
        "window_minutes_total": len(grid),
        "reference_samples_in_window": len(covered_offsets),
    }


def clip(win_start, win_end, req_start, req_end):
    s = max(win_start, req_start)
    e = min(win_end, req_end)
    return (s, e) if e > s else (None, None)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--baseline", required=True, help="fixed_<preset>_*.json from scanner_fixed.py")
    ap.add_argument("--reference", required=True, help="reference_<preset>_*.json from reference.py")
    ap.add_argument("--preset", required=True)
    args = ap.parse_args()

    base = load(args.baseline)
    ref_meta = load(args.reference)
    ref_npz_path = Path(args.reference).with_suffix(".npz")
    if not ref_npz_path.exists():
        sys.exit(f"Missing {ref_npz_path}")
    ref = np.load(ref_npz_path)

    if base["environment"]["snapshot_sha256"] != ref_meta["environment"]["snapshot_sha256"]:
        sys.exit("baseline and reference snapshots differ -- not comparable.")
    if ref_meta["args"]["preset"] != args.preset:
        sys.exit(f"--preset {args.preset} != reference's preset {ref_meta['args']['preset']}")
    if ref_meta["args"].get("limit"):
        sys.exit("This reference run used --limit; use a full (no --limit) reference run so "
                 "object indices line up with a fresh candidate rebuild.")

    preset_result = next((r for r in base["results"] if r["preset"] == args.preset), None)
    if preset_result is None:
        sys.exit(f"No results for preset '{args.preset}' in {args.baseline}.")

    t0 = parse_dt(base["environment"]["snapshot_T0_utc"])
    req_start = t0
    req_end = t0 + timedelta(hours=preset_result["horizon_hours"])
    windows = preset_result["windows"]
    if not windows:
        print("No windows in this fixed-scanner run. Nothing to compare.")
        return

    # --- Rebuild the EXACT candidate list reference.py used, so p_obj indices line up ---
    docs, meta = load_snapshot()
    if meta["sha256_uncompressed"] != base["environment"]["snapshot_sha256"]:
        sys.exit("Locally loaded snapshot doesn't match the baseline/reference sha256.")
    freeze_tle_age(t0)  # patches scanner.tle_epoch_age_days to be frozen at T0, same as every other script
    _, lat, lon, alt, inc = PRESETS[args.preset]
    cands = ref_module.select_candidates(docs, alt, limit=0)
    print(f"Rebuilt {len(cands)} candidates (reference used {ref_meta['n_candidates_used']})")
    if len(cands) != ref_meta["n_candidates_used"]:
        sys.exit("Candidate count mismatch -- do not trust results until this matches exactly.")

    # --- The EXACT radius formula from scanner_fixed.py's FIX 4 ---
    ages = np.array([scanner.tle_epoch_age_days(d["tle_line1"]) or 0.0 for d in cands])
    obj_radius_fixed = 10.0 + np.minimum(0.5 * ages, 5.0)  # 10..15 km, matches FIX 4 exactly
    print(f"TLE age stats (days): min={ages.min():.1f} median={np.median(ages):.1f} max={ages.max():.1f}")
    print(f"-> {(ages >= 10).mean():.0%} of candidates are old enough to be saturated at 15 km\n")

    launch_offset_s = ref["launch_offset_s"]
    p_k, p_obj, p_d = ref["pair_launch_idx"], ref["pair_obj_idx"], ref["pair_dmin_km"]
    K = len(launch_offset_s)

    unsafe_per_launch = np.zeros(K, dtype=bool)
    within_radius = p_d < obj_radius_fixed[p_obj]
    unsafe_per_launch[np.unique(p_k[within_radius])] = True

    grid_step_s = np.min(np.diff(np.sort(launch_offset_s)))
    max_gap_s = grid_step_s / 2.0 + 1.0

    print(f"Preset: {args.preset}  |  requested range: {req_start.isoformat()} -> {req_end.isoformat()}")
    print("Radius formula: 10.0 + min(0.5*age_days, 5.0) km  (matches scanner_fixed.py FIX 4 exactly)")
    print(f"Reference overall unsafe rate at this exact radius: {unsafe_per_launch.mean():.1%}\n")

    report = []
    for i, w in enumerate(windows):
        w_start, w_end = parse_dt(w["start"]), parse_dt(w["end"])
        print(f"Window {i + 1}: {w_start.isoformat()} -> {w_end.isoformat()} ({w['duration_minutes']} min as reported)")
        entry = {"window": w}
        for label, (s, e) in (("raw", (w_start, w_end)),
                              ("clipped_to_requested_range", clip(w_start, w_end, req_start, req_end))):
            if s is None:
                print(f"    {label}: entirely outside requested range, skipped")
                entry[label] = {"skipped": True}
                continue
            n_cov, n_unsafe, n_uncov, meta_d = false_safe_rate(s, e, launch_offset_s, t0, unsafe_per_launch, max_gap_s)
            rate = n_unsafe / n_cov if n_cov else float("nan")
            print(f"    {label}: reference samples {n_cov} | marked unsafe {n_unsafe} ({rate:.1%}) | uncovered {n_uncov}")
            entry[label] = {"start": s.isoformat(), "end": e.isoformat(), "reference_samples": n_cov,
                            "marked_unsafe": n_unsafe, "false_safe_rate": rate,
                            "uncovered_minutes": n_uncov, **meta_d}
        report.append(entry)
        print()

    out = RESULTS_DIR / f"compare_fixed_{args.preset}_{datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ')}.json"
    out.write_text(json.dumps({
        "baseline_file": args.baseline, "reference_file": args.reference, "preset": args.preset,
        "radius_formula": "10.0 + min(0.5*age_days, 5.0)",
        "reference_overall_unsafe_rate_at_exact_radius": float(unsafe_per_launch.mean()),
        "windows": report,
    }, indent=2))
    print(f"Saved {out}")


if __name__ == "__main__":
    main()