# OPAS Independent Audit — Research Directory

> **Author:** Nadim Baboun, Al-Quds University
> **Branch:** `research-branch` (never merged into `main`)
> **Backend commit under test:** `a89f2e72` (unmodified — this study only _reads_ from the backend)

This directory contains all code, data, and results for an independent study
auditing the false-safe rate of OPAS's `/safe-windows` collision-screening
endpoint. The companion report is in `Code.tex` / `opas_audit_report.pdf`.

---

## Quick start — reproducing the results

```bash
# 1. Make sure backend/ dependencies are installed (see repo root README).
# 2. From the repo root:
python research/baseline.py          # run OPAS's unmodified scanner
python research/reference.py --preset iss   # build dense ground truth
python research/compare.py --preset iss     # validate baseline windows → Table 1
python research/scanner_fixed.py --preset iss  # run the improved scanner
python research/compare_fixed.py --preset iss  # validate fixed windows → Table 2
```

All scripts read from the frozen snapshot in `data/`; no live database is
needed after the initial export.

---

## Directory layout

```
research/
├── README.md                ← you are here
├── FINDINGS.md              ← lab notebook: every finding with evidence links
├── Code.tex                 ← LaTeX source for the report
├── opas_audit_report.pdf    ← compiled report
│
├── data/
│   ├── debris_snapshot_*.jsonl.gz   ← frozen catalog (32,517 objects at T0)
│   └── snapshot_meta.json           ← T0 timestamp + SHA-256 checksum
│
├── results/                 ← authoritative result files (post-fix, 2026-09-28)
│   ├── _stale_unfrozen_age/ ← pre-fix results kept for audit trail (DO NOT CITE)
│   └── …                    ← see results/README.md for the full file map
│
└── *.py                     ← scripts (described below)
```

---

## Script-by-script guide

### Data preparation

| Script | What it does |
|--------|-------------|
| **`export_snapshot.py`** | Connects to the live MongoDB database and dumps every debris object into a single compressed file (`data/*.jsonl.gz`). Records the exact timestamp (T0) and a SHA-256 checksum so every subsequent experiment runs on bit-identical data. You only run this once. |

### Measuring the original system (Phase 1–3)

| Script | What it does |
|--------|-------------|
| **`baseline.py`** | Runs OPAS's _unmodified_ `scan_windows()` on all five orbital presets (ISS, Starlink, SSO, Polar, GEO) for a 6-hour horizon starting at T0. Patches TLE-age computation to use frozen T0 instead of wall-clock time (via `freeze_tle_age`). Produces the baseline windows cited in Table 1. |
| **`reference.py`** | Builds a dense "ground truth" by sampling every candidate object's distance to the vehicle once per second, across every 1-minute launch offset in the 6-hour horizon. Uses parabola interpolation to find the true closest-approach distance. This is the yardstick everything else is measured against. |
| **`compare.py`** | Takes a baseline window (from `baseline.py`) and checks every minute of it against the dense reference: was there actually a debris object within OPAS's own screening radius at that launch time? Produces the false-safe rates for Table 1 (100% for ISS/Starlink/SSO, 0% for GEO). |

### Diagnosing why (Phase 4)

| Script | What it does |
|--------|-------------|
| **`scanner_param.py`** | A copy of OPAS's `scan_windows()` with the coarse step, fine step, and number of trajectory waypoints exposed as command-line arguments. Lets you test "what happens if we change one parameter?" Has a `--validate` flag that checks its output matches the baseline exactly. Used internally by `sweep.py`. |
| **`sweep.py`** | Runs `scanner_param.py` across a grid of parameter combinations (coarse step × fine step × waypoints) and records how many windows each setting produces and their false-safe rates. Proves that sampling density is the root cause: tight settings → 0 windows, loose settings → 100% false-safe windows (Finding F6). |

### Building and testing the fix (Phase 5–8)

| Script | What it does |
|--------|-------------|
| **`scanner_fixed.py`** | The improved scanner. Four changes from the original: (1) 600 trajectory waypoints instead of ~12, (2) screening radius capped at 10–15 km instead of 50–200 km, (3) 1-minute fine-step instead of 2 minutes, (4) window boundaries clamped to the requested time range. Produces the fixed windows cited in Table 2. |
| **`compare_fixed.py`** | Like `compare.py`, but validates `scanner_fixed.py`'s windows using the exact per-object radius formula (not a flat approximation). Produces the residual false-safe rates for Table 2 (ISS 9.6%, Starlink 21.1%). |
| **`prove_sampling_gap.py`** | For every remaining false-safe minute inside a fixed window, recomputes the scanner's own 600-waypoint distances at that exact launch time. Proves the cause: the true closest approach falls _between_ two waypoints (~9.3 s apart), so the scanner literally never checks the dangerous moment. 10/10 confirmed cases = waypoint gap. |

### Verifying the zero-window results (Phase 9)

| Script | What it does |
|--------|-------------|
| **`longest_clear_runs.py`** | Reads the dense reference directly and lists every contiguous stretch of "clear" minutes (no debris within radius) across the full 6-hour horizon, with _no algorithm cap_. Definitively answers "does a genuinely safe window even exist?" independently of `scan_windows`. |
| **`simulate_ground_truth_scan.py`** | Replays `scanner_fixed.py`'s exact algorithm (coarse pass → refine → 15-min filter → 5-run cap) but substitutes perfect reference data for the live scanner calls. Proves that zero windows for Starlink/SSO is the mathematically correct answer, not a bug. |
| **`check_zero_windows.py`** | Earlier, coarser check: prints the per-minute unsafe rate from the reference for each preset. Superseded by `simulate_ground_truth_scan.py` but kept for completeness. |
| **`check_coarse_grid.py`** | Checks only the coarse-grid instants the scanner would sample. Superseded by `simulate_ground_truth_scan.py`. |

### Bug discovery & repair utilities

| Script | What it does |
|--------|-------------|
| **`check_age_patch.py`** | Diagnostic one-liner: prints the TLE-epoch age as seen by `scanner`, `scanner_param`, and `scanner_fixed` for a single TLE. Used to discover that `scanner_param` and `scanner_fixed` were computing age from wall-clock time instead of frozen T0. |
| **`patch_age.py`** | One-time automated patch that rewired `scanner_param.py` and `scanner_fixed.py` to call `scanner.tle_epoch_age_days()` (which respects the freeze) instead of importing directly from `orbital`. Already applied; kept for the audit trail. |

### Report verification

| Script | What it does |
|--------|-------------|
| **`verify_report_numbers.py`** | Reads the authoritative result JSONs and prints every specific number cited in the LaTeX report, so you can eyeball-diff the paper against the data before submitting. |

---

## The TLE-age-freeze bug (methodology note)

`baseline.py` freezes TLE-epoch age at T0 by patching the `scanner` module's
`tle_epoch_age_days` attribute. The original `backend/scanner.py` calls this
function unqualified, so the patch works correctly. However, `scanner_param.py`
and `scanner_fixed.py` imported `tle_epoch_age_days` directly from `orbital`,
creating a private binding that was _never_ patched — they computed TLE age from
wall-clock time for all runs between 09-22 and 09-27.

**Consequence:** every `scanner_fixed` / `sweep` / `compare_fixed` /
`prove_sampling_gap` result dated before 2026-09-28 used the wrong age (~3–8
days too old). These are archived in `results/_stale_unfrozen_age/` and must
**not** be cited. All results were re-run on 09-28 after the fix.

Table 1 / F1–F5 (the `baseline.py` + `compare.py` + `reference.py` path) were
**never affected** — the bug was isolated to the two research scanner scripts.

---

## Key findings at a glance

| # | Finding | Source |
|---|---------|--------|
| F5 | Every ISS/Starlink/SSO baseline "safe window" was 100% false-safe; GEO was 0% (correct) | `compare.py` → Table 1 |
| F6 | Tight sampling → 0 windows; loose sampling → 100% false-safe (proves sampling is the cause) | `sweep.py` |
| F9 | Fixed scanner: ISS 52 min / 9.6% false-safe, Starlink 19 min / 21.1% — residual cause is the 9-second waypoint gap | `scanner_fixed.py` + `compare_fixed.py` + `prove_sampling_gap.py` → Table 2 |
| F10 | Starlink and SSO have _no_ genuinely safe window in this 6-hour horizon at realistic radii | `longest_clear_runs.py` + `simulate_ground_truth_scan.py` |
