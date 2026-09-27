"""
When scanner_fixed.py returns ZERO windows for a preset, this checks whether that's the
mathematically correct answer -- i.e. whether the dense reference agrees that, at the
scanner's exact per-object radius (10.0 + min(0.5*age, 5.0)), literally every coarse
launch time in the horizon has a threat somewhere across the full flight -- rather than
silently masking a bug (an exception being swallowed, the longitude-wrap prefilter
discarding too many candidates, etc.).

Usage:
    python research/check_zero_windows.py --preset starlink --reference research/results/reference_starlink_20260922T071313Z.json
"""
import argparse
import json
from pathlib import Path

import numpy as np

import baseline
from baseline import load_snapshot, freeze_tle_age, PRESETS
import scanner
import reference as ref_module
from datetime import datetime


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--preset", required=True)
    ap.add_argument("--reference", required=True)
    args = ap.parse_args()

    ref_meta = json.loads(Path(args.reference).read_text())
    ref = np.load(Path(args.reference).with_suffix(".npz"))
    if ref_meta["args"].get("limit"):
        raise SystemExit("This reference run used --limit; use a full run.")

    t0 = datetime.fromisoformat(ref_meta["environment"]["snapshot_T0_utc"])
    freeze_tle_age(t0)
    docs, meta = load_snapshot()
    if meta["sha256_uncompressed"] != ref_meta["environment"]["snapshot_sha256"]:
        raise SystemExit("Snapshot mismatch.")
    _, lat, lon, alt, inc = PRESETS[args.preset]
    cands = ref_module.select_candidates(docs, alt, limit=0)
    assert len(cands) == ref_meta["n_candidates_used"], "candidate count mismatch"

    ages = np.array([scanner.tle_epoch_age_days(d["tle_line1"]) or 0.0 for d in cands])
    obj_radius = 10.0 + np.minimum(0.5 * ages, 5.0)
    print(f"[{args.preset}] {len(cands)} candidates | TLE age median={np.median(ages):.1f}d "
          f"max={ages.max():.1f}d | {(ages >= 10).mean():.0%} saturated at 15km")

    launch_offset_s = ref["launch_offset_s"]
    p_k, p_obj, p_d = ref["pair_launch_idx"], ref["pair_obj_idx"], ref["pair_dmin_km"]
    K = len(launch_offset_s)

    unsafe = np.zeros(K, dtype=bool)
    unsafe[np.unique(p_k[p_d < obj_radius[p_obj]])] = True

    # Restrict to the requested 6h horizon (launch_offset_s=0 is T0), matching scan_windows_fixed's scope
    in_horizon = (launch_offset_s >= -1.0) & (launch_offset_s <= 6 * 3600 + 3.0)
    rate = unsafe[in_horizon].mean()
    n_clear = (~unsafe[in_horizon]).sum()
    print(f"Reference-confirmed unsafe rate across {in_horizon.sum()} launch times in the 6h horizon: {rate:.1%}")
    print(f"Launch times with NO reference-confirmed threat anywhere in the full flight: {n_clear}")
    if n_clear == 0:
        print("-> Zero windows is the mathematically correct answer: not one launch time in "
              "this horizon has a fully clear flight at this radius. Not a bug.")
    else:
        print(f"-> {n_clear} launch time(s) SHOULD have been clear. scanner_fixed.py returning "
              "0 windows may indicate a bug worth investigating (check for a swallowed exception, "
              "the longitude-wrap prefilter, or an ascent/scope mismatch).")


if __name__ == "__main__":
    main()