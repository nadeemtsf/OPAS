# research/results/ — file map

Every file follows `<type>_<preset>_<timestamp>.<ext>`. This maps each file to the
script that produced it and the study phase it belongs to. Superseded files are kept
for the audit trail (see the chat log for why) — nothing here should be deleted.

## Phase 1 — Snapshot + Baseline

| File | Produced by | Notes |
|---|---|---|
| *(not listed here — `.jsonl.gz` in `research/data/`)* | `export_snapshot.py` | The frozen catalog everything else reads from |
| `baseline_20260921T090905Z.json` | `baseline.py` | Unmodified OPAS, all 5 presets, 6h horizon. Source for F1–F2, F5's baseline windows. |

## Phase 2 — Dense reference (ground truth)

| File | Produced by | Notes |
|---|---|---|
| `reference_iss_20260921T101207Z.json` / `.npz` | `reference.py --preset iss --limit 100 --hours 1` | Timing test only (100 objects, 1h). Not used in any real finding — kept for the runtime-projection note in the "Reference scanner validation" section. |
| `reference_iss_20260921T102002Z.json` / `.npz` | `reference.py --preset iss` | **Full ISS reference.** Backs F3, F5, F9, F10-adjacent, and every `compare*_iss_*` file. |
| `reference_starlink_20260922T071313Z.json` / `.npz` | `reference.py --preset starlink` | Full Starlink reference. Backs F3, F5, F6, F10. |
| `reference_sso_20260922T072024Z.json` / `.npz` | `reference.py --preset sso` | Full SSO reference. Backs F3, F5, F6, F10. |
| `reference_geo_20260922T073419Z.json` / `.npz` | `reference.py --preset geo` | Full GEO reference. Backs F3, F5. |

## Phase 3 — Validate the original (unfixed) baseline windows → F5

| File | Produced by | Validates | Result |
|---|---|---|---|
| `compare_iss_20260922T070022Z.json` | `compare.py` | `baseline_*.json` (ISS) vs `reference_iss_20260921T102002Z` | 24 min window, 100% false-safe |
| `compare_starlink_20260922T071627Z.json` | `compare.py` | `baseline_*.json` (Starlink) vs `reference_starlink_*` | 46+16 min windows, 100% false-safe |
| `compare_sso_20260922T072131Z.json` | `compare.py` | `baseline_*.json` (SSO) vs `reference_sso_*` | 20 min window, 100% false-safe |
| `compare_geo_20260922T073520Z.json` | `compare.py` | `baseline_*.json` (GEO) vs `reference_geo_*` | 376 min window, 0% false-safe (control case) |

**These four are final, not superseded** — F5's cited numbers.

## Phase 4 — Parameter sweep (original scanner) → F6

| File | Produced by | Notes |
|---|---|---|
| `sweep_iss_20260922T141430Z.jsonl` | `sweep.py` (drives `scanner_param.py` internally — no separate output files from that script) | Coarse/fine/n_intervals grid, ISS |
| `sweep_starlink_20260922T150409Z.jsonl` | `sweep.py` | Same grid, Starlink |
| `sweep_sso_20260922T151644Z.jsonl` | `sweep.py` | Same grid, SSO |

## Phase 5 — Fixed scanner raw output

| File | Produced by | Notes |
|---|---|---|
| `fixed_iss_20260922T160812Z.json` | `scanner_fixed.py --preset iss` | **Superseded.** First attempt, before FIX 4 — 0 windows (blocked by the old exponential TLE-age radius inflation). Kept as evidence for F7. |
| `fixed_iss_20260924T184134Z.json` | `scanner_fixed.py --preset iss` | **Superseded.** After FIX 4, `fine_step` still 2 min — 3 windows (80/60/26 min). Kept as evidence for F7/F8. |
| `fixed_iss_20260926T172830Z.json` | `scanner_fixed.py --preset iss` | **Final, authoritative ISS fixed run** — FIX 4 + 1-min `fine_step` — 2 windows (52/40 min). Everything in Phase 7/8 validates *this* file. |
| `fixed_starlink_20260927T071252Z.json` | `scanner_fixed.py --preset starlink` | 0 windows — confirmed correct, F10 |
| `fixed_sso_20260927T071644Z.json` | `scanner_fixed.py --preset sso` | 0 windows — confirmed correct, F10 |

## Phase 6/7 — Validating the fixed ISS windows → F9

| File | Produced by | Threshold used | Result | Status |
|---|---|---|---|---|
| `compare_iss_20260926T162655Z.json` | `compare.py` (edited: flat `p_d < 15.0`) | flat 15.0 km | 28%/35% false-safe | **Superseded** — overcounts unsafe for fresh-TLE objects whose real radius was only 10km |
| `compare_iss_20260926T174323Z.json` | `compare.py` (edited: flat `p_d < 10.0`) | flat 10.0 km | 9.6%/22.5% false-safe | **Superseded** — an approximation, numerically identical to the correct answer only because this catalog's TLEs happened to be fresh, not because it was the right method |
| `compare_fixed_iss_20260927T064155Z.json` | `compare_fixed.py` | exact per-object `10.0 + min(0.5×age, 5.0)` | 9.6%/22.5% false-safe (overall unsafe rate 17.1%) | **Authoritative — this is what F9 cites** |

## Phase 8 — Proof of causation → F9's mechanism

| File | Produced by | Notes |
|---|---|---|
| `prove_sampling_gap_iss_20260927T065053Z.json` | `prove_sampling_gap.py` | 18 residual false-safe cases traced individually: 15/18 confirmed as the 9-second waypoint gap, 3/18 traced to a distinct reference-grid clock-drift artifact |

## Phase 9 — Confirming F10's zero-window result wasn't a bug (Starlink, SSO)

None of these three scripts write output on their own — the terminal transcripts were archived
directly as `.txt` files instead of being re-run.

| File | Produced by | Notes |
|---|---|---|
| `check_zero_windows_starlink_sso_20260927.txt` | `check_zero_windows.py` | First pass: confirms the dense reference shows a much higher per-minute unsafe rate for these two shells (32.1% Starlink, 49.9% SSO) than ISS's ~17% — consistent with, but not yet proof of, zero windows being correct. Flags "possible bug" at this stage — see next file. |
| `check_coarse_grid_starlink_sso_20260927.txt` | `check_coarse_grid.py` | Second pass: checks the *exact* 10-minute coarse-grid instants `scan_windows_fixed` samples. Still flags "possible bug," because most on-grid 10-minute points look clear — misleading, since the real algorithm refines to 1-minute resolution before accepting a window. Superseded by the next file. |
| `simulate_ground_truth_scan_starlink_sso_20260927.txt` | `simulate_ground_truth_scan.py` | **Decisive.** Reproduces `scan_windows_fixed`'s exact coarse-to-refined algorithm fed perfect dense-reference lookups instead of live scanner calls. Every candidate coarse-safe run (up to 80 min at coarse resolution) collapses below the 15-minute cutoff once refined to 1-minute checks. Confirms 0 windows is mathematically correct for both presets, not a bug. **This is F10's cited evidence.** |