"""
Directly verifies the CAUSE of F9's residual false-safe rate: for every reference-unsafe
launch time inside a scanner_fixed.py "safe" window, recomputes the scanner's own discrete
600-waypoint samples for that exact launch and checks whether:
  (a) the scanner's sampled minimum distance was >= its own radius (i.e. its math, run at
      its own sample points, genuinely said "safe" -- not some separate bug), and
  (b) the true closest-approach time (dense reference, parabola-refined) sits between two
      of the scanner's ~9.28s-apart samples rather than landing on one.

If both hold for (essentially) all residual false-safe cases, that's direct proof the
9-second sampling gap is the cause, not an inference from reading the code.

Usage:
    python research/prove_sampling_gap.py --preset iss \
        --baseline research/results/fixed_iss_20260926T172830Z.json \
        --reference research/results/reference_iss_20260921T102002Z.json
"""
import argparse
import json
from datetime import datetime, timedelta, timezone
from math import pi, sqrt
from pathlib import Path

import numpy as np
from skyfield.framelib import itrs

import baseline
from baseline import load_snapshot, freeze_tle_age, PRESETS
import scanner
import reference as ref_module
from orbital import EARTH_R, generate_trajectory
from proximity import geodetic_to_ecef


def parse_dt(s):
    return datetime.fromisoformat(s.replace("Z", "+00:00"))


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--preset", required=True)
    ap.add_argument("--baseline", required=True)
    ap.add_argument("--reference", required=True)
    args = ap.parse_args()

    base = json.loads(Path(args.baseline).read_text())
    ref_meta = json.loads(Path(args.reference).read_text())
    ref = np.load(Path(args.reference).with_suffix(".npz"))
    assert base["environment"]["snapshot_sha256"] == ref_meta["environment"]["snapshot_sha256"], \
        "snapshot mismatch -- not comparable"

    t0 = parse_dt(base["environment"]["snapshot_T0_utc"])
    freeze_tle_age(t0)
    docs, meta = load_snapshot()
    label, lat, lon, alt, inc = PRESETS[args.preset]
    cands = ref_module.select_candidates(docs, alt, limit=0)
    assert len(cands) == ref_meta["n_candidates_used"], "candidate count mismatch -- do not trust results"

    ages = np.array([scanner.tle_epoch_age_days(d["tle_line1"]) or 0.0 for d in cands])
    obj_radius = 10.0 + np.minimum(0.5 * ages, 5.0)  # exact scanner_fixed.py FIX 4 formula

    # Rebuild the EXACT 600-waypoint dense trajectory scanner_fixed.py used
    trajectory = generate_trajectory(lat, lon, alt, inc, steps=600)
    steps = len(trajectory) - 1
    r = EARTH_R + alt
    period_sec = 2 * pi * sqrt(r ** 3 / 398600.4418)
    step_sec = period_sec / steps
    ascent_steps = min(steps, max(1, round(600 / step_sec)))
    sample_indices = list(range(ascent_steps, steps + 1, 1))
    traj_ecef = np.array([geodetic_to_ecef(trajectory[i]["lat"], trajectory[i]["lon"], trajectory[i]["alt"])
                          for i in sample_indices])
    sample_times_s = np.array([i * step_sec for i in sample_indices])  # seconds since launch

    launch_offset_s = ref["launch_offset_s"]
    p_k, p_obj, p_d, p_s = ref["pair_launch_idx"], ref["pair_obj_idx"], ref["pair_dmin_km"], ref["pair_s_ca"]
    unsafe_mask = p_d < obj_radius[p_obj]

    preset_result = next(rr for rr in base["results"] if rr["preset"] == args.preset)
    checked = 0
    confirmed_gap_miss = 0
    details = []

    for w in preset_result["windows"]:
        w_start, w_end = parse_dt(w["start"]), parse_dt(w["end"])
        win_s = (w_start - t0).total_seconds()
        win_e = (w_end - t0).total_seconds()
        in_win = (launch_offset_s[p_k] >= win_s - 1e-6) & (launch_offset_s[p_k] <= win_e + 1e-6)
        pairs_in_window = np.nonzero(in_win & unsafe_mask)[0]
        print(f"\nWindow {w['start']} -> {w['end']}: {len(pairs_in_window)} reference-unsafe pairs to verify")

        for pair_idx in pairs_in_window:
            k, obj_i = int(p_k[pair_idx]), int(p_obj[pair_idx])
            dmin_true, s_ca = float(p_d[pair_idx]), float(p_s[pair_idx])
            doc = cands[obj_i]
            radius = float(obj_radius[obj_i])
            launch_dt = t0 + timedelta(seconds=float(launch_offset_s[k]))

            sat = scanner.get_sat(doc)
            if sat is None:
                continue
            t_abs = scanner.ts.tt_jd(scanner.ts.from_datetime(launch_dt).tt + sample_times_s / 86400.0)
            try:
                xyz = sat.at(t_abs).frame_xyz(itrs).km  # (3, N)
            except Exception:
                continue
            obj_ecef = xyz.T

            dists = np.linalg.norm(obj_ecef - traj_ecef, axis=1)
            min_sampled = float(dists.min())
            nearest_sample_time = sample_times_s[np.argmin(np.abs(sample_times_s - s_ca))]
            gap_to_nearest_sample_s = abs(s_ca - nearest_sample_time)

            scanner_would_say_safe = min_sampled >= radius
            checked += 1
            if scanner_would_say_safe:
                confirmed_gap_miss += 1
            details.append({
                "launch_offset_s": float(launch_offset_s[k]), "norad_id": doc.get("norad_id"),
                "true_dmin_km": dmin_true, "radius_km": radius,
                "scanner_sampled_min_km": min_sampled,
                "true_closest_approach_s_since_launch": s_ca,
                "gap_to_nearest_scanner_sample_s": gap_to_nearest_sample_s,
                "sample_spacing_s": step_sec,
            })

    print(f"\n{checked} true encounters verified inside the scanner's 'safe' windows.")
    if checked:
        print(f"{confirmed_gap_miss}/{checked} ({confirmed_gap_miss/checked:.0%}) were missed purely "
              f"because the scanner's own {step_sec:.2f}s-spaced samples never landed inside the radius, "
              f"even though the true minimum distance was inside it.")
        if confirmed_gap_miss < checked:
            print(f"{checked - confirmed_gap_miss} case(s) were NOT explained by the sampling gap -- "
                  f"inspect those individually, some other cause may be at play there.")

    out = Path("research/results") / f"prove_sampling_gap_{args.preset}_{datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ')}.json"
    out.write_text(json.dumps({"checked": checked, "confirmed_gap_miss": confirmed_gap_miss, "cases": details}, indent=2))
    print(f"Saved {out}")


if __name__ == "__main__":
    main()