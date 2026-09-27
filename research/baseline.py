"""
Baseline harness: run OPAS's *unmodified* safe-window scan on a frozen snapshot
and record how long it takes and what it returns.

This is step 1 of the study. Nothing here changes OPAS's behaviour; we only
(a) load the catalog from the snapshot instead of MongoDB, (b) freeze "now" so
TLE ages are reproducible, and (c) count how many times the scanner's inner
check is evaluated (the number we will compare against a dense reference).

Run from the repo root, after export_snapshot.py:

    python research/baseline.py                    # all presets, 6 h horizon, 3 repeats
    python research/baseline.py --preset iss --hours 3 --repeats 1   # quick test
    python research/baseline.py --verbose          # show OPAS's own scan logs
"""
import argparse
import gzip
import hashlib
import json
import logging
import os
import platform
import statistics
import subprocess
import sys
import threading
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path

RESEARCH = Path(__file__).resolve().parent
REPO = RESEARCH.parent
DATA_DIR = RESEARCH / "data"
RESULTS_DIR = RESEARCH / "results"

# --- Offline setup: must happen BEFORE importing anything from backend/ ------
# backend/db.py creates a MongoClient at import time. Point it at a dead address
# so this harness can never touch (or wait on) the real database.
os.environ["MONGO_URI"] = "mongodb://localhost:1/?serverSelectionTimeoutMS=1"
logging.getLogger("opas").setLevel(logging.ERROR)  # hide the expected "MongoDB connection check failed"
sys.path.insert(0, str(REPO / "backend"))

import numpy  # noqa: E402
import skyfield  # noqa: E402

import scanner  # noqa: E402
from orbital import generate_trajectory  # noqa: E402
import proximity  # noqa: E402

# Copied from frontend/src/constants.ts (index 0, "Custom", omitted).
PRESETS = {
    "iss":      ("ISS Resupply (Cape Canaveral)",   28.573,  -80.649,   420, 51.6),
    "starlink": ("Starlink Deploy (Cape Canaveral)", 28.573,  -80.649,   550, 53.0),
    "sso":      ("Sun-Sync SSO (Vandenberg)",        34.632, -120.611,   705, 98.2),
    "polar":    ("Polar Orbit (Vandenberg)",         34.632, -120.611,   800, 90.0),
    "geo":      ("GEO Transfer (Kourou)",             5.236,  -52.768, 35786,  6.0),
}

# scan_windows-side candidate filter, copied from backend/api.py (/safe-windows).
ALT_BAND_KM = 100


def load_snapshot():
    meta = json.loads((DATA_DIR / "snapshot_meta.json").read_text())
    hasher = hashlib.sha256()
    docs = []
    with gzip.open(DATA_DIR / meta["file"], "rb") as f:
        for line in f:
            hasher.update(line)
            docs.append(json.loads(line))
    if hasher.hexdigest() != meta["sha256_uncompressed"]:
        sys.exit("Snapshot checksum mismatch - the data file was modified or corrupted.")
    return docs, meta


def freeze_tle_age(t0):
    """Make TLE age relative to the snapshot time T0 instead of the wall clock."""
    def age(tle_line1):
        try:
            yr2 = int(tle_line1[18:20])
            day_frac = float(tle_line1[20:32])
            year = yr2 + (1900 if yr2 >= 57 else 2000)
            epoch = datetime(year, 1, 1, tzinfo=timezone.utc) + timedelta(days=day_frac - 1)
            return (t0 - epoch).total_seconds() / 86400.0
        except Exception:
            return None
    # scanner.py did `from orbital import tle_epoch_age_days`, so patch its own reference.
    scanner.tle_epoch_age_days = age


class EvalTracer:
    """Wraps scanner.count_threats_fast to record every evaluation (thread-safe)."""

    def __init__(self, fn, t0_tt):
        self.fn = fn
        self.t0_tt = t0_tt
        self.lock = threading.Lock()
        self.trace = []  # (minutes since T0, number of threatening objects)

    def __call__(self, scan_items, trajectory, target_alt, t, proximity_km):
        n = self.fn(scan_items, trajectory, target_alt, t, proximity_km)
        with self.lock:
            self.trace.append((round((float(t.tt) - self.t0_tt) * 1440.0, 3), n))
        return n

    def reset(self):
        with self.lock:
            self.trace = []


def git_commit():
    try:
        return subprocess.check_output(
            ["git", "rev-parse", "HEAD"], cwd=REPO, stderr=subprocess.DEVNULL, text=True
        ).strip()
    except Exception:
        return None


def environment(meta):
    return {
        "python": sys.version.split()[0],
        "platform": platform.platform(),
        "processor": platform.processor(),
        "cpu_count": os.cpu_count(),
        "numpy": numpy.__version__,
        "skyfield": skyfield.__version__,
        "native_math_active": proximity.HAS_NATIVE_MATH,
        "repo_git_commit": git_commit(),
        "snapshot_file": meta["file"],
        "snapshot_sha256": meta["sha256_uncompressed"],
        "snapshot_T0_utc": meta["exported_at_utc"],
    }


def run_preset(key, docs, t0, hours, repeats, tracer):
    label, lat, lon, alt, inc = PRESETS[key]
    candidates = [d for d in docs
                  if isinstance(d.get("altitude_km"), (int, float))
                  and alt - ALT_BAND_KM <= d["altitude_km"] <= alt + ALT_BAND_KM]
    n_tle = sum(1 for d in candidates if d.get("tle_line1") and d.get("tle_line2"))
    trajectory = generate_trajectory(lat, lon, alt, inc)
    end = t0 + timedelta(hours=hours)

    # Build satellite objects once (cold), so timed runs measure scanning only.
    t_build = time.perf_counter()
    for d in candidates:
        scanner.get_sat(d)
    build_s = time.perf_counter() - t_build

    runs, windows, first_trace = [], None, None
    for r in range(repeats):
        tracer.reset()
        t_start = time.perf_counter()
        w = scanner.scan_windows(candidates, trajectory, lat, lon, alt, t0, end,
                                 scanner.SAFE_WINDOW_PROXIMITY_KM)
        runs.append(time.perf_counter() - t_start)
        if r == 0:
            windows, first_trace = w, list(tracer.trace)

    threat_evals = sum(1 for _, n in first_trace if n > 0)
    return {
        "preset": key, "label": label,
        "lat": lat, "lon": lon, "alt_km": alt, "inc_deg": inc,
        "horizon_hours": hours,
        "n_candidates": len(candidates), "n_with_tle": n_tle,
        "sat_build_seconds": round(build_s, 3),
        "run_seconds": [round(x, 3) for x in runs],
        "median_seconds": round(statistics.median(runs), 3),
        "n_evaluations": len(first_trace),
        "n_evaluations_with_threat": threat_evals,
        "windows": windows,
        "trace_minutes_since_T0_and_threat_count": sorted(first_trace),
    }


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--preset", choices=list(PRESETS) + ["all"], default="all")
    ap.add_argument("--hours", type=int, default=6, help="scan horizon (default 6)")
    ap.add_argument("--repeats", type=int, default=3, help="timed repeats per preset (default 3)")
    ap.add_argument("--verbose", action="store_true", help="show OPAS scan logs")
    args = ap.parse_args()

    if args.verbose:
        logging.basicConfig(level=logging.INFO, format="%(levelname)s | %(message)s")
        logging.getLogger("opas").setLevel(logging.INFO)

    docs, meta = load_snapshot()
    t0 = datetime.fromisoformat(meta["exported_at_utc"])
    freeze_tle_age(t0)
    t0_tt = scanner.ts.from_datetime(t0).tt
    tracer = EvalTracer(scanner.count_threats_fast, t0_tt)
    scanner.count_threats_fast = tracer  # scan_windows looks this name up in scanner's globals

    print(f"Snapshot: {meta['n_objects']} objects, T0 = {meta['exported_at_utc']}")
    print(f"Native C++ math active: {proximity.HAS_NATIVE_MATH} | CPUs: {os.cpu_count()}")

    keys = list(PRESETS) if args.preset == "all" else [args.preset]
    results = []
    for k in keys:
        print(f"\n[{k}] scanning {args.hours} h, {args.repeats} repeat(s) ...", flush=True)
        res = run_preset(k, docs, t0, args.hours, args.repeats, tracer)
        results.append(res)
        wins = ", ".join(f"{w['duration_minutes']} min" for w in res["windows"]) or "none"
        print(f"  candidates={res['n_candidates']} (TLE={res['n_with_tle']})  "
              f"median={res['median_seconds']} s  evals={res['n_evaluations']} "
              f"(with threat: {res['n_evaluations_with_threat']})  windows: {wins}")

    RESULTS_DIR.mkdir(parents=True, exist_ok=True)
    out = RESULTS_DIR / f"baseline_{datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ')}.json"
    out.write_text(json.dumps({"environment": environment(meta), "args": vars(args),
                               "results": results}, indent=2))
    print(f"\nSaved {out}")


if __name__ == "__main__":
    main()
