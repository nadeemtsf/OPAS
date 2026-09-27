"""
Dense reference scanner: the "ground truth" that OPAS's scan is compared against.

For every launch time on a 1-minute grid (with a margin before and after the
requested range) and every candidate object, this computes the MINIMUM DISTANCE
between the launched vehicle and the object over the whole flight, sampling
positions every ~1 second and then refining the closest approach with a
parabola fit (exact for locally straight-line relative motion).

It uses exactly the same model as OPAS - same snapshot, same candidate filter,
same TLE propagation (Skyfield/SGP4, ITRS frame), same simplified vehicle path
(backend/orbital.py generate_trajectory), same per-object screening radius,
and the same scope (OPAS's inner check ignores the ~10 min ascent, so by default
so do we). Only the sampling density differs, so any disagreement with OPAS is
caused by sampling and nothing else.

Usage (from the repo root, after export_snapshot.py):

    python research/reference.py --selftest                     # no data needed, ~seconds
    python research/reference.py --preset iss --limit 100 --hours 1   # timing test
    python research/reference.py --preset iss --validate 100    # 1 s vs 2 s agreement check
    python research/reference.py --preset iss                   # full 6 h run

Output (research/results/): reference_<preset>_<stamp>.npz (arrays) and .json (summary).
"""
import argparse
import concurrent.futures as cf
import json
import math
import os
import sys
import time
from datetime import datetime, timedelta, timezone

import numpy as np
from numpy.lib.stride_tricks import sliding_window_view

import baseline  # noqa: F401  (sets offline env, puts backend/ on sys.path, imports OPAS)
from baseline import (ALT_BAND_KM, PRESETS, RESULTS_DIR, environment, freeze_tle_age,
                      load_snapshot)
import proximity
import scanner
from orbital import EARTH_R, generate_trajectory
from skyfield.framelib import itrs

RADII_KM = (5, 10, 25, 50, 100)  # radii reported in the summary


# ----------------------------------------------------------------------------
# Vehicle path
# ----------------------------------------------------------------------------
def build_vehicle(lat, lon, alt, inc, dt_s, include_ascent):
    """Vehicle path in ECEF at ~dt_s spacing, using OPAS's own generate_trajectory."""
    r = EARTH_R + alt
    period_s = 2 * math.pi * math.sqrt(r ** 3 / 398600.4418)
    n = int(round(period_s / dt_s))
    traj = generate_trajectory(lat, lon, alt, inc, steps=n)
    dt = period_s / n  # actual sample spacing (slightly different from dt_s)
    ascent_steps = min(n, max(1, round(600 / dt)))  # same rule as OPAS's inner check
    i0 = 0 if include_ascent else ascent_steps
    V = np.array([proximity.geodetic_to_ecef(w["lat"], w["lon"], w["alt"]) for w in traj])
    return {"period_s": period_s, "n": n, "dt": dt, "i0": i0, "V": V}


# ----------------------------------------------------------------------------
# Core numerical routine (pure numpy, no OPAS / Skyfield dependence -> unit-testable)
# ----------------------------------------------------------------------------
def min_dist_table(D, V, i0, stride, K):
    """
    D: (J,3) object track on the sample grid.  V: (n+1,3) vehicle path on the same grid.
    Launch k flies V[i] at the same time the object is at D[k*stride + i], for i = i0..n.
    Returns (dmin_km (K,), s_ca (K,)) : refined minimum distance and the closest-approach
    time in *samples since launch* (fractional).
    """
    Vs = V[i0:]
    M = Vs.shape[0]
    win = sliding_window_view(D, M, axis=0)          # (J-M+1, 3, M), a view, no copy
    sel = win[i0::stride][:K]                        # (K, 3, M)
    diff = sel - Vs.T[None, :, :]
    d2 = np.einsum("kcm,kcm->km", diff, diff)        # squared distances
    kk = np.arange(d2.shape[0])
    m = d2.argmin(axis=1)
    b = d2[kk, m]
    d2min = b.copy()
    delta = np.zeros(len(kk))
    interior = (m > 0) & (m < M - 1)
    if interior.any():
        ki, mi = kk[interior], m[interior]
        a, bb, c = d2[ki, mi - 1], d2[ki, mi], d2[ki, mi + 1]
        denom = a - 2 * bb + c
        ok = denom > 1e-12
        dl = np.zeros(len(ki))
        dref = bb.copy()
        dl[ok] = np.clip((a[ok] - c[ok]) / (2 * denom[ok]), -1.0, 1.0)
        dref[ok] = bb[ok] - (c[ok] - a[ok]) ** 2 / (8 * denom[ok])
        d2min[ki] = np.maximum(dref, 0.0)
        delta[ki] = dl
    return np.sqrt(d2min), i0 + m + delta


# ----------------------------------------------------------------------------
# Self-test: planted objects with known answers
# ----------------------------------------------------------------------------
def selftest():
    print("Self-test: planted objects with known closest approach")
    veh = build_vehicle(*PRESETS["iss"][1:], dt_s=1.0, include_ascent=False)
    V, n, i0, dt = veh["V"], veh["n"], veh["i0"], veh["dt"]
    stride, K = 60, 40
    J = (K - 1) * stride + n + 1
    far = np.tile(np.array([[1e5, 0.0, 0.0]]), (J, 1))
    k_star = 12
    fails = 0

    # Test 1: object exactly 3 km (radially offset) from the vehicle on a sample point.
    D = far.copy()
    rad = V / np.linalg.norm(V, axis=1, keepdims=True)
    D[k_star * stride + i0: k_star * stride + n + 1] = V[i0:] + 3.0 * rad[i0:]
    dmin, _ = min_dist_table(D, V, i0, stride, K)
    err = abs(dmin[k_star] - 3.0)
    others = np.delete(dmin, k_star).min()
    ok = err < 1e-6 and others > 50
    fails += not ok
    print(f"  [{'PASS' if ok else 'FAIL'}] on-sample plant: dmin={dmin[k_star]:.6f} km (want 3), "
          f"nearest other launch={others:.0f} km (want >50)")

    # Test 2: a crossing object whose closest approach falls BETWEEN two samples.
    # It passes the vehicle at a true miss distance of 3 km (radial), moving across the
    # track at 10 km/s, at time i_c + 0.5 samples. Sampling alone overestimates the miss
    # distance (the two nearest samples are each ~half a sample of relative motion away);
    # the parabola refinement must recover ~3 km.
    i_c = i0 + 2000
    tau = i_c + 0.5
    Vc = 0.5 * (V[i_c] + V[i_c + 1])
    rhat = Vc / np.linalg.norm(Vc)
    vhat = (V[i_c + 1] - V[i_c]) / np.linalg.norm(V[i_c + 1] - V[i_c])
    what = np.cross(rhat, vhat)
    D = far.copy()
    for i in range(i_c - 20, i_c + 22):
        D[k_star * stride + i] = Vc + 3.0 * rhat + 10.0 * dt * what * (i - tau)
    dmin, _ = min_dist_table(D, V, i0, stride, K)
    raw = np.linalg.norm(D[k_star * stride + i0: k_star * stride + n + 1] - V[i0:], axis=1).min()
    err = abs(dmin[k_star] - 3.0)
    ok = err < 0.05 and raw > 5.0
    fails += not ok
    print(f"  [{'PASS' if ok else 'FAIL'}] between-sample crossing: refined dmin={dmin[k_star]:.4f} km "
          f"(want ~3); raw sampled minimum would have been {raw:.2f} km")

    print("Self-test", "FAILED" if fails else "passed")
    return fails == 0


# ----------------------------------------------------------------------------
# Real objects
# ----------------------------------------------------------------------------
def object_track(sat, tgrid):
    xyz = sat.at(tgrid).frame_xyz(itrs).km          # (3, J), same call OPAS uses
    return np.ascontiguousarray(xyz.T)


def select_candidates(docs, alt, limit):
    cand = [d for d in docs
            if isinstance(d.get("altitude_km"), (int, float))
            and alt - ALT_BAND_KM <= d["altitude_km"] <= alt + ALT_BAND_KM
            and d.get("tle_line1") and d.get("tle_line2")]
    if limit and limit < len(cand):
        step = len(cand) / limit
        cand = [cand[int(i * step)] for i in range(limit)]
    return cand


def make_grid(t0, hours, margin_min, veh, launch_step_s):
    dt, n = veh["dt"], veh["n"]
    stride = max(1, int(round(launch_step_s / dt)))
    q0 = -int(round(margin_min * 60 / dt))
    K = int(((hours * 3600 + 2 * margin_min * 60) / dt) // stride) + 1
    J = (K - 1) * stride + n + 1
    t0_tt = scanner.ts.from_datetime(t0).tt
    tgrid = scanner.ts.tt_jd(t0_tt + (q0 + np.arange(J)) * dt / 86400.0)
    launch_offset_s = (q0 + np.arange(K) * stride) * dt
    return stride, K, J, tgrid, launch_offset_s


def process_object(doc, tgrid, veh, stride, K, store_km):
    """Returns (status, pairs) where pairs = list of (k, dmin, s_ca_seconds)."""
    sat = scanner.get_sat(doc)
    if sat is None:
        return "no_sat", []
    try:
        D = object_track(sat, tgrid)
    except Exception:
        return "propagation_error", []
    if not np.isfinite(D).all():
        D = np.where(np.isfinite(D), D, 1e9)     # bad samples = "far away"
    V, i0 = veh["V"], veh["i0"]
    # Cheap prefilter: if the object's distance-from-Earth-centre range never comes
    # within store_km of the vehicle's, no launch can bring them within store_km.
    r = np.linalg.norm(D, axis=1)
    rv = np.linalg.norm(V[i0:], axis=1)
    if r.max() < rv.min() - store_km or r.min() > rv.max() + store_km:
        return "pruned", []
    dmin, s_ca = min_dist_table(D, V, i0, stride, K)
    hit = np.nonzero(dmin < store_km)[0]
    return "ok", [(int(k), float(dmin[k]), float(s_ca[k] * veh["dt"])) for k in hit]


# ----------------------------------------------------------------------------
# 1 s vs 2 s agreement check
# ----------------------------------------------------------------------------
def validate(cands, tgrid, veh, stride, K, n_obj):
    if stride % 2:
        print(f"Warning: launch stride {stride} is odd; dropping to {stride - 1} for validation")
        stride -= 1
    V, i0, n = veh["V"], veh["i0"], veh["n"]
    V2, i0_2, stride2 = V[::2], (i0 + 1) // 2, stride // 2
    diffs, flips = [], {R: 0 for R in (5, 10, 25, 50)}
    used = pairs_total = 0
    for doc in cands:
        sat = scanner.get_sat(doc)
        if sat is None:
            continue
        D = object_track(sat, tgrid)
        if not np.isfinite(D).all():
            continue
        d1, _ = min_dist_table(D, V, i0, stride, K)
        d2, _ = min_dist_table(D[::2], V2, i0_2, stride2, K)
        near = (d1 < 100) | (d2 < 100)
        if near.any():
            diffs.extend(np.abs(d1[near] - d2[near]).tolist())
        for R in flips:
            flips[R] += int(((d1 < R) != (d2 < R)).sum())
        pairs_total += K
        used += 1
        if used >= n_obj:
            break
    diffs = np.array(diffs) if diffs else np.array([0.0])
    print(f"Validation on {used} objects x {K} launches = {pairs_total} (object, launch) pairs")
    print(f"  pairs within 100 km at either resolution: {len(diffs)}; "
          f"|d(1s) - d(2s)|: median {np.median(diffs):.4f} km, 99th pct {np.percentile(diffs, 99):.3f} km, "
          f"max {diffs.max():.3f} km")
    for R, f in flips.items():
        print(f"  classification flips at {R:>3} km: {f}")
    return {"objects": used, "pairs": pairs_total, "pairs_within_100km": len(diffs),
            "median_abs_diff_km": float(np.median(diffs)), "p99_abs_diff_km": float(np.percentile(diffs, 99)),
            "max_abs_diff_km": float(diffs.max()), "flips": flips}


# ----------------------------------------------------------------------------
# Summary
# ----------------------------------------------------------------------------
def summarise(K, launch_offset_s, hours, p_k, p_obj, p_d, obj_radius):
    in_range = (launch_offset_s >= -1.0) & (launch_offset_s <= hours * 3600 + 3.0)
    n_in = int(in_range.sum())
    out = {"launches_in_range": n_in, "by_radius_km": {}, "opas_radius": None}
    for R in RADII_KM:
        m = p_d < R
        cnt = np.bincount(p_k[m], minlength=K)[in_range]
        out["by_radius_km"][str(R)] = {"frac_launch_times_unsafe": float((cnt > 0).mean()),
                                       "mean_objects_within_R_per_launch": float(cnt.mean())}
    m = p_d < obj_radius[p_obj]
    cnt = np.bincount(p_k[m], minlength=K)[in_range]
    out["opas_radius"] = {"frac_launch_times_unsafe": float((cnt > 0).mean()),
                          "mean_objects_within_radius_per_launch": float(cnt.mean())}
    return out


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--preset", choices=list(PRESETS), default="iss")
    ap.add_argument("--hours", type=float, default=6.0, help="requested launch range (default 6)")
    ap.add_argument("--margin-min", type=float, default=10.0, help="extra minutes each side (default 10)")
    ap.add_argument("--dt-s", type=float, default=1.0, help="target sample spacing in s (use ~10 for GEO)")
    ap.add_argument("--launch-step-s", type=float, default=60.0, help="launch-time grid step (default 60)")
    ap.add_argument("--store-km", type=float, default=200.0, help="store pairs closer than this (default 200)")
    ap.add_argument("--limit", type=int, default=0, help="use only N evenly spaced candidates (timing test)")
    ap.add_argument("--workers", type=int, default=os.cpu_count() or 4)
    ap.add_argument("--include-ascent", action="store_true", help="also cover the first ~10 min (OPAS's check skips it)")
    ap.add_argument("--validate", type=int, default=0, metavar="N", help="1 s vs 2 s check on N objects, then exit")
    ap.add_argument("--selftest", action="store_true", help="planted-object unit tests, then exit")
    args = ap.parse_args()

    if args.selftest:
        sys.exit(0 if selftest() else 1)

    docs, meta = load_snapshot()
    t0 = datetime.fromisoformat(meta["exported_at_utc"])
    freeze_tle_age(t0)
    label, lat, lon, alt, inc = PRESETS[args.preset]

    veh = build_vehicle(lat, lon, alt, inc, args.dt_s, args.include_ascent)
    stride, K, J, tgrid, launch_offset_s = make_grid(t0, args.hours, args.margin_min, veh, args.launch_step_s)
    cands = select_candidates(docs, alt, args.limit)
    total_cands = len(select_candidates(docs, alt, 0))
    print(f"[{args.preset}] {label}: period {veh['period_s']:.0f} s, sample spacing {veh['dt']:.5f} s, "
          f"flight scope from {veh['i0'] * veh['dt']:.0f} s, launches {K} (every {stride * veh['dt']:.2f} s), "
          f"grid {J} samples/object, candidates {len(cands)} of {total_cands}", flush=True)

    if args.validate:
        res = validate(cands, tgrid, veh, stride, K, args.validate)
        return

    # Warm-up in the main thread so shared Skyfield caches are built before threading.
    process_object(cands[0], tgrid, veh, stride, K, args.store_km)

    t_start = time.perf_counter()
    statuses = {}
    pk, pobj, pd, ps = [], [], [], []
    with cf.ThreadPoolExecutor(max_workers=args.workers) as ex:
        futs = {ex.submit(process_object, d, tgrid, veh, stride, K, args.store_km): i
                for i, d in enumerate(cands)}
        done = 0
        for fut in cf.as_completed(futs):
            i = futs[fut]
            status, pairs = fut.result()
            statuses[status] = statuses.get(status, 0) + 1
            for k, dm, s in pairs:
                pk.append(k); pobj.append(i); pd.append(dm); ps.append(s)
            done += 1
            if done % max(1, len(cands) // 10) == 0:
                el = time.perf_counter() - t_start
                print(f"  {done}/{len(cands)} objects, {el:.0f} s elapsed, ~{el / done * (len(cands) - done):.0f} s left",
                      flush=True)
    elapsed = time.perf_counter() - t_start

    per_obj = elapsed / len(cands)
    print(f"Done in {elapsed:.1f} s ({per_obj * 1000:.0f} ms/object wall, {args.workers} workers). Status: {statuses}")
    if args.limit:
        print(f"Projected full run for {total_cands} candidates: ~{per_obj * total_cands / 60:.1f} min")

    p_k, p_obj = np.array(pk, dtype=np.int32), np.array(pobj, dtype=np.int32)
    p_d, p_s = np.array(pd), np.array(ps)
    obj_radius = np.array([proximity.screening_radius_km(scanner.SAFE_WINDOW_PROXIMITY_KM,
                                                        scanner.tle_epoch_age_days(d["tle_line1"]))
                           for d in cands])
    summary = summarise(K, launch_offset_s, args.hours, p_k, p_obj, p_d, obj_radius)

    print(f"\nReference results ({summary['launches_in_range']} launch times in the requested {args.hours:g} h):")
    for R in RADII_KM:
        s = summary["by_radius_km"][str(R)]
        print(f"  radius {R:>3} km: {s['frac_launch_times_unsafe']:.0%} of launch times have >=1 object; "
              f"mean {s['mean_objects_within_R_per_launch']:.1f} objects per launch")
    o = summary["opas_radius"]
    print(f"  OPAS per-object radius: {o['frac_launch_times_unsafe']:.0%} unsafe; "
          f"mean {o['mean_objects_within_radius_per_launch']:.1f} objects per launch")

    RESULTS_DIR.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    base = RESULTS_DIR / f"reference_{args.preset}_{stamp}"
    np.savez_compressed(f"{base}.npz", launch_offset_s=launch_offset_s, pair_launch_idx=p_k,
                        pair_obj_idx=p_obj, pair_dmin_km=p_d, pair_s_ca=p_s,
                        obj_norad=np.array([d["norad_id"] for d in cands]), obj_radius_km=obj_radius)
    with open(f"{base}.json", "w") as f:
        json.dump({"environment": environment(meta), "args": vars(args),
                   "grid": {"K": K, "J": J, "stride": stride, "dt_s": veh["dt"], "period_s": veh["period_s"],
                            "flight_scope_start_s": veh["i0"] * veh["dt"]},
                   "n_candidates_used": len(cands), "n_candidates_total": total_cands,
                   "statuses": statuses, "elapsed_seconds": round(elapsed, 2),
                   "n_pairs_stored": int(len(p_d)), "summary": summary}, f, indent=2)
    print(f"\nSaved {base}.npz and .json")


if __name__ == "__main__":
    main()
