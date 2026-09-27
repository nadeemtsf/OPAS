"""
Compare what OPAS's scan_windows() actually RETURNED (from a baseline.py run) against
the dense reference (from reference.py), to answer the real question: of the minutes
OPAS reported as a safe window, how many does the dense reference say were unsafe?

This is different from the "OPAS inner check vs reference" comparison already printed
by reference.py. That one compares against OPAS's per-minute inner check function.
This script compares against the literal windows scan_windows() returned to the user,
which is what actually matters -- those are the times a person could act on.

Because the reference's launch-time grid (1-minute steps, from generate_trajectory)
does not necessarily land exactly on OPAS's own minute grid, "unsafe" is decided by
nearest reference launch time within half the reference's launch step; a gap larger
than that is reported separately rather than silently guessed at.

Usage (from the repo root, after both baseline.py and reference.py have been run
for the SAME preset and the SAME snapshot):

    python research/compare.py \\
        --baseline research/results/baseline_20260921T090905Z.json \\
        --reference research/results/reference_iss_20260921T102002Z.json \\
        --preset iss

Prints, for every window scan_windows() returned for that preset:
  - the window as reported (start, end, duration)
  - the window clipped to the originally requested [start_dt, end_dt] range (see F1)
  - for both the raw and the clipped window: how many of its minutes the reference
    marks unsafe at OPAS's own per-object radius, i.e. the false-safe rate
Also saves a JSON with the full per-minute breakdown for the report's figures.
"""
import argparse
import json
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

import numpy as np

RESEARCH = Path(__file__).resolve().parent
RESULTS_DIR = RESEARCH / "results"


def load(path):
    return json.loads(Path(path).read_text())


def parse_dt(s):
    return datetime.fromisoformat(s.replace("Z", "+00:00"))


def false_safe_rate(win_start, win_end, launch_offset_s, t0, unsafe_mask, step_s, max_gap_s):
    """
    For every reference launch time inside [win_start, win_end], look up whether the
    reference marked it unsafe. Returns (n_covered, n_unsafe, n_uncovered, minutes).
    n_uncovered counts window-minutes with no reference launch time within max_gap_s.
    """
    win_s = (win_start - t0).total_seconds()
    win_e = (win_end - t0).total_seconds()
    if win_e <= win_s:
        return 0, 0, 0, []
    in_win = (launch_offset_s >= win_s - 1e-6) & (launch_offset_s <= win_e + 1e-6)
    covered_offsets = launch_offset_s[in_win]
    covered_unsafe = unsafe_mask[in_win]

    # Flag any part of the window further from a reference sample than half the
    # reference's own launch step -- i.e. genuinely uncovered, not just off-grid.
    grid = np.arange(win_s, win_e + 1e-6, 60.0)  # report per-minute, regardless of ref step
    if len(covered_offsets):
        nearest_gap = np.min(np.abs(grid[:, None] - covered_offsets[None, :]), axis=1)
    else:
        nearest_gap = np.full(len(grid), np.inf)
    uncovered = nearest_gap > max_gap_s
    n_uncovered = int(uncovered.sum())

    return len(covered_offsets), int(covered_unsafe.sum()), n_uncovered, {
        "window_minutes_total": len(grid),
        "reference_samples_in_window": len(covered_offsets),
    }


def clip(win_start, win_end, req_start, req_end):
    s = max(win_start, req_start)
    e = min(win_end, req_end)
    return (s, e) if e > s else (None, None)


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--baseline", required=True, help="baseline_*.json from baseline.py")
    ap.add_argument("--reference", required=True, help="reference_<preset>_*.json from reference.py")
    ap.add_argument("--preset", required=True, help="which preset's result to pull from the baseline file")
    args = ap.parse_args()

    base = load(args.baseline)
    ref_meta = load(args.reference)
    ref_npz_path = Path(args.reference).with_suffix(".npz")
    if not ref_npz_path.exists():
        sys.exit(f"Expected the matching .npz next to {args.reference} (at {ref_npz_path}), not found.")
    ref = np.load(ref_npz_path)

    if base["environment"]["snapshot_sha256"] != ref_meta["environment"]["snapshot_sha256"]:
        sys.exit("baseline and reference were run on DIFFERENT snapshots (sha256 mismatch) "
                 "-- results are not comparable. Re-run both against the same snapshot.")
    if ref_meta["args"]["preset"] != args.preset:
        sys.exit(f"--preset {args.preset} does not match the reference file's preset "
                 f"({ref_meta['args']['preset']}).")

    preset_result = next((r for r in base["results"] if r["preset"] == args.preset), None)
    if preset_result is None:
        sys.exit(f"No results for preset '{args.preset}' in {args.baseline}. "
                 f"Available: {[r['preset'] for r in base['results']]}")

    t0 = parse_dt(base["environment"]["snapshot_T0_utc"])
    req_start = t0
    req_end = t0 + timedelta(hours=preset_result["horizon_hours"])
    windows = preset_result["windows"]
    if not windows:
        print(f"OPAS returned no safe windows for '{args.preset}' in this baseline run. Nothing to compare.")
        return

    launch_offset_s = ref["launch_offset_s"]
    p_k, p_obj, p_d = ref["pair_launch_idx"], ref["pair_obj_idx"], ref["pair_dmin_km"]
    obj_radius = ref["obj_radius_km"]
    K = len(launch_offset_s)
    unsafe_per_launch = np.zeros(K, dtype=bool)
    # Validate against the new strict 10.0 km maximum radius
    within_radius = p_d < 10.0
    unsafe_per_launch[np.unique(p_k[within_radius])] = True

    grid_step_s = np.min(np.diff(np.sort(launch_offset_s)))
    max_gap_s = grid_step_s / 2.0 + 1.0
    print(f"Preset: {args.preset}  |  requested range: {req_start.isoformat()} -> {req_end.isoformat()}")
    print(f"Reference: {K} launch times, every {grid_step_s:.0f} s, "
          f"OPAS-radius unsafe rate overall: {unsafe_per_launch.mean():.1%}\n")

    report = []
    for i, w in enumerate(windows):
        w_start, w_end = parse_dt(w["start"]), parse_dt(w["end"])
        print(f"Window {i + 1}: {w_start.isoformat()} -> {w_end.isoformat()} "
              f"({w['duration_minutes']} min as reported)")

        entry = {"window": w, "raw": None, "clipped": None}
        for label, (s, e) in (("raw", (w_start, w_end)),
                              ("clipped_to_requested_range", clip(w_start, w_end, req_start, req_end))):
            if s is None:
                print(f"    {label}: entirely outside the requested range, skipped")
                entry[label] = {"skipped": True}
                continue
            n_cov, n_unsafe, n_uncov, meta = false_safe_rate(
                s, e, launch_offset_s, t0, unsafe_per_launch, grid_step_s, max_gap_s)
            rate = n_unsafe / n_cov if n_cov else float("nan")
            print(f"    {label}: {s.isoformat()} -> {e.isoformat()}")
            print(f"      reference samples in this span: {n_cov}  |  marked unsafe: {n_unsafe} "
                  f"({rate:.0%})  |  minutes with no nearby reference sample: {n_uncov}")
            if n_uncov:
                print(f"      NOTE: {n_uncov} of {meta['window_minutes_total']} minutes had no reference "
                      f"sample within {max_gap_s:.0f}s -- likely outside the reference's own margin "
                      f"(see reference.py --margin-min) or a launch-grid misalignment. Not counted "
                      f"as safe or unsafe; investigate before quoting this rate.")
            entry[label] = {"start": s.isoformat(), "end": e.isoformat(), "reference_samples": n_cov,
                            "marked_unsafe": n_unsafe, "false_safe_rate": rate,
                            "uncovered_minutes": n_uncov, **meta}
        report.append(entry)
        print()

    out = RESULTS_DIR / f"compare_{args.preset}_{datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ')}.json"
    out.write_text(json.dumps({
        "baseline_file": args.baseline, "reference_file": args.reference,
        "preset": args.preset, "requested_range": [req_start.isoformat(), req_end.isoformat()],
        "reference_overall_unsafe_rate_at_opas_radius": float(unsafe_per_launch.mean()),
        "windows": report,
    }, indent=2))
    print(f"Saved {out}")


if __name__ == "__main__":
    main()
