# research/results/ — File Map & Pipeline

> **Rule of thumb:** if it lives at the top level of this directory, it's **authoritative — cite it**.
> If it's inside `_stale_unfrozen_age/`, it's **invalidated — do NOT cite**.

---

## Pipeline overview: which script produces what, and where it feeds

```
 DATA PREPARATION
 ════════════════
 export_snapshot.py
       │
       ▼
 data/debris_snapshot_*.jsonl.gz  ◄── frozen catalog, 32,517 objects at T0
       │
       │  (every script below reads from this snapshot)
       │
 ══════╪════════════════════════════════════════════════════════════════════
 PHASE │  SCRIPT                    OUTPUT FILE(s)                 FINDING
 ══════╪════════════════════════════════════════════════════════════════════
       │
  1    │  baseline.py ──────────►  baseline_20260921T090905Z.json   F1,F2
       │       │                   (all 5 presets, 6h horizon)
       │       │
  2    │  reference.py ─────────►  reference_<preset>_*.json/.npz   F3
       │       │                   (1s-sampled ground truth)
       │       │
       │       │  ┌─ compare.py reads baseline + reference ─┐
  3    │       ▼  ▼                                         │
       │  compare.py ───────────►  compare_<preset>_*.json ─┼──►   F5
       │                           ISS   → 100% false-safe  │    TABLE 1
       │                           SLink → 100% false-safe  │
       │                           SSO   → 100% false-safe  │
       │                           GEO   →   0% false-safe  │
       │                                                    │
  4    │  scanner_param.py ◄─── (used internally by sweep)  │
       │       │                                            │
       │  sweep.py ─────────────►  sweep_<preset>_*.jsonl ──┼──►   F6
       │                           n_intervals=24 → 0 wins  │
       │                           loose settings → 100%    │
       │                                                    │
  5    │  scanner_fixed.py ─────►  fixed_<preset>_*.json ───┤
       │       │                   ISS   → 1 win (52 min)   │
       │       │                   SLink → 1 win (19 min)   │
       │       │                   SSO   → 0 wins           │
       │       │                                            │
       │       │  ┌─ compare_fixed reads fixed + reference ─┤
  6    │       ▼  ▼                                         │
       │  compare_fixed.py ─────►  compare_fixed_*.json ────┼──►   F9
       │                           ISS   →  9.6% false-safe │    TABLE 2
       │                           SLink → 21.1% false-safe │
       │                                                    │
  7    │  prove_sampling_gap.py ►  prove_sampling_gap_*.json┼──►   F9
       │                           ISS   5/5 = waypoint gap │   mechanism
       │                           SLink 5/5 = waypoint gap │
       │                                                    │
  8    │  longest_clear_runs.py    (terminal output only) ──┼──►   F10
       │  simulate_ground_truth    (terminal output only) ──┘
       │  _scan.py
       │
 ══════╧════════════════════════════════════════════════════════════════════
```

---

## Complete file inventory (authoritative, top-level)

### Phase 1 — Baseline (unmodified OPAS)

| File | Script | Purpose |
|------|--------|---------|
| `baseline_20260921T090905Z.json` | `baseline.py` | Raw OPAS output for all 5 presets, 6h horizon. Source for Table 1 window durations. |

### Phase 2 — Dense reference (ground truth)

| File | Script | Purpose |
|------|--------|---------|
| `reference_iss_20260921T101207Z.json/.npz` | `reference.py --preset iss --limit 100 --hours 1` | Timing test only. Not used in any finding. |
| `reference_iss_20260921T102002Z.json/.npz` | `reference.py --preset iss` | **Full ISS ground truth.** Every compare/fixed/prove file for ISS validates against this. |
| `reference_starlink_20260922T071313Z.json/.npz` | `reference.py --preset starlink` | Full Starlink ground truth. |
| `reference_sso_20260922T072024Z.json/.npz` | `reference.py --preset sso` | Full SSO ground truth. |
| `reference_geo_20260922T073419Z.json/.npz` | `reference.py --preset geo` | Full GEO ground truth (control case — 0% encounters). |

### Phase 3 — Baseline validation → **Table 1 / F5**

| File | Script | Result |
|------|--------|--------|
| `compare_iss_20260922T070022Z.json` | `compare.py` | ISS 24 min → **100% false-safe** |
| `compare_starlink_20260922T071627Z.json` | `compare.py` | Starlink 46+16 min → **100% false-safe** |
| `compare_sso_20260922T072131Z.json` | `compare.py` | SSO 20 min → **100% false-safe** |
| `compare_geo_20260922T073520Z.json` | `compare.py` | GEO 376 min → **0% false-safe** ✓ |

### Phase 4 — Parameter sweep → **F6**

| File | Script | Result |
|------|--------|--------|
| `sweep_iss_20260928T192528Z.jsonl` | `sweep.py` | n_intervals=24 → 0 windows (all coarse steps) |
| `sweep_starlink_20260928T190843Z.jsonl` | `sweep.py` | Same pattern |
| `sweep_sso_20260928T185956Z.jsonl` | `sweep.py` | Same pattern |

### Phase 5 — Fixed scanner output → **Table 2**

| File | Script | Result |
|------|--------|--------|
| `fixed_iss_20260928T125736Z.json` | `scanner_fixed.py` | 1 window, 10:33–11:25 (**52 min**) |
| `fixed_starlink_20260928T124617Z.json` | `scanner_fixed.py` | 1 window, 10:03–10:22 (**19 min**) |
| `fixed_sso_20260928T123422Z.json` | `scanner_fixed.py` | **0 windows** |

### Phase 6 — Fixed scanner validation → **Table 2 / F9**

| File | Script | Result |
|------|--------|--------|
| `compare_fixed_iss_20260928T185703Z.json` | `compare_fixed.py` | 52 samples, 5 unsafe → **9.6% false-safe** |
| `compare_fixed_starlink_20260928T185705Z.json` | `compare_fixed.py` | 19 samples, 4 unsafe → **21.1% false-safe** |

### Phase 7 — Root cause proof → **F9 mechanism**

| File | Script | Result |
|------|--------|--------|
| `prove_sampling_gap_iss_20260928T185708Z.json` | `prove_sampling_gap.py` | 5/5 = **100% waypoint-gap cause** |
| `prove_sampling_gap_starlink_20260928T185711Z.json` | `prove_sampling_gap.py` | 5/5 = **100% waypoint-gap cause** |

### Phase 8 — Zero-window verification → **F10**

These scripts write to **terminal only** (no output files):

| Script | What it confirms |
|--------|------------------|
| `longest_clear_runs.py` | ISS: 5 clear runs ≥15 min (longest 19 min). Starlink: longest 14 min (<15). SSO: longest 6 min. |
| `simulate_ground_truth_scan.py` | 0 windows for Starlink/SSO is mathematically correct, not a bug. |

---

## `_stale_unfrozen_age/` — invalidated files (audit trail only)

**Why they're stale:** `scanner_param.py` and `scanner_fixed.py` computed TLE
age from wall-clock time instead of frozen T0 for all runs 09-22 through 09-27.
This inflated ages by 3–8 days (true median = 0.8 days). Bug discovered 09-28,
fixed via `patch_age.py`, everything re-run.

| Stale file | Why it's wrong |
|------------|----------------|
| `fixed_iss_20260922T160812Z.json` | Pre-FIX4 (old radius formula, separate issue) |
| `fixed_iss_20260924T184134Z.json` | FIX4 applied but TLE age unfrozen |
| `fixed_iss_20260926T172830Z.json` | Showed phantom 2nd window (40 min) that doesn't exist |
| `fixed_starlink_20260927T071252Z.json` | Showed 0 windows; corrected = 1 window |
| `fixed_sso_20260927T071644Z.json` | Showed 0 windows; coincidentally matches (lucky) |
| `compare_fixed_iss_20260927T064155Z.json` | Wrong age → wrong false-safe breakdown |
| `prove_sampling_gap_iss_20260927T065053Z.json` | 3/18 "drift" cases = stale-run artifact, not real |
| `compare_iss_20260926T162655Z.json` | Flat 15km threshold experiment, superseded |
| `compare_iss_20260926T174323Z.json` | Flat 10km threshold experiment, superseded |
| `sweep_*_20260922T*.jsonl` | Original stale sweeps |
| `*.txt` files | Stale terminal captures (script logic fine, age was wrong) |