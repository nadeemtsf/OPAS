import argparse, json
from datetime import datetime
from pathlib import Path
import numpy as np

import baseline
from baseline import load_snapshot, freeze_tle_age, PRESETS
import scanner
import reference as ref_module

ap = argparse.ArgumentParser()
ap.add_argument("--preset", required=True)
ap.add_argument("--reference", required=True)
ap.add_argument("--hours", type=float, default=6.0)
args = ap.parse_args()

ref_meta = json.loads(Path(args.reference).read_text())
ref = np.load(Path(args.reference).with_suffix(".npz"))
t0 = datetime.fromisoformat(ref_meta["environment"]["snapshot_T0_utc"])
freeze_tle_age(t0)
docs, meta = load_snapshot()
assert meta["sha256_uncompressed"] == ref_meta["environment"]["snapshot_sha256"], "snapshot mismatch"
_, lat, lon, alt, inc = PRESETS[args.preset]
cands = ref_module.select_candidates(docs, alt, limit=0)
assert len(cands) == ref_meta["n_candidates_used"], "candidate mismatch"

ages = np.array([scanner.tle_epoch_age_days(d["tle_line1"]) or 0.0 for d in cands])
radius = 10.0 + np.minimum(0.5 * ages, 5.0)

off = ref["launch_offset_s"]
p_k, p_obj, p_d = ref["pair_launch_idx"], ref["pair_obj_idx"], ref["pair_dmin_km"]
unsafe = np.zeros(len(off), dtype=bool)
unsafe[np.unique(p_k[p_d < radius[p_obj]])] = True

idx = np.nonzero((off >= -1.0) & (off <= args.hours * 3600 + 3.0))[0]
runs, start = [], None
for j, i in enumerate(idx):
    if not unsafe[i] and start is None:
        start = i
    if start is not None and (unsafe[i] or j == len(idx) - 1):
        end = i - 1 if unsafe[i] else i
        runs.append((start, end))
        start = None

lengths = [(off[e] - off[s]) / 60.0 + 1 for s, e in runs]
print(f"[{args.preset}] {len(runs)} clear runs; {sum(l >= 15 for l in lengths)} of them >= 15 min")
print(f"longest clear run: {max(lengths) if lengths else 0:.0f} min")
for (s, e), l in sorted(zip(runs, lengths), key=lambda x: -x[1])[:5]:
    print(f"  {l:5.0f} min  t0+{off[s]/60:6.1f} -> t0+{off[e]/60:6.1f} min")