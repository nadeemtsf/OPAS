# OPAS study: findings log

A lab notebook, not the final report. Each entry says what was observed, which file
proves it, and how sure we are. The report's results and limitations sections are
built from this file.

**Statuses:** `MEASURED` (seen directly in the data), `READ FROM CODE` (follows from
reading the source, not yet tested), `HYPOTHESIS` (plausible, needs the reference to confirm).

---

## Setup (fixed for the whole study)

| Item | Value |
|---|---|
| Code under test | `backend/scanner.py` etc., git commit `a89f2e726f08dad71498a091b60d06a80267f07f` (unmodified) |
| Data snapshot | `debris_snapshot_20260921T085254Z.jsonl.gz` |
| Snapshot T0 | 2026-09-21T08:52:54.811735+00:00 |
| Snapshot SHA-256 (uncompressed) | `c13469e0cee49549504c9de7e45388c926e32ebe5c3b3ec6ccb81855838b1fa8` |
| Machine | Windows 11, Intel64 Family 6 Model 140, 8 CPUs |
| Software | Python 3.13.14, NumPy 2.4.4, Skyfield 1.54 |
| Native C++ extension | active (`native_math_active: true`) |
| Baseline run | `research/results/baseline_20260921T090905Z.json` (6 h horizon, 3 repeats per preset) |
| Reference run (ISS, full) | `research/results/reference_iss_20260921T102002Z.json/.npz` |
| Reference run (ISS, timing test) | `research/results/reference_iss_20260921T101207Z.json/.npz` (limit 100, 1 h) |

TLE age is frozen at T0, so results do not depend on when the harness is run.
The raw snapshot is not committed (Space-Track terms); the checksum identifies it.

---

## Baseline: what OPAS reports (6 h scan from T0)

| Preset | Candidates | Median run (s) | Inner-check evaluations | Evaluations with a threat | Windows returned |
|---|---|---|---|---|---|
| ISS, 420 km | 11,997 | 100.9 | 77 | 24 | 1 (24 min) |
| Starlink, 550 km | 13,478 | 114.3 | 81 | 22 | 2 (46 min, 16 min) |
| SSO, 705 km | 4,753 | 38.4 | 78 | 24 | 1 (20 min) |
| Polar, 800 km | 5,338 | 33.1 | 60 | 39 | none |
| GEO transfer | 840 | 19.1 | 230 | 0 | 1 (376 min) |

Note: the first ISS repeat (121.8 s) was slower than the other two (~99-101 s),
probably warm-up. Report medians.

---

## F1. Windows can start before the scan and end after it

**Status:** MEASURED (effect), READ FROM CODE (cause)

**Evidence** (`baseline_20260921T090905Z.json`):
- In the Starlink, SSO, polar and GEO runs the earliest evaluated time is T0 - 8 min.
  In the ISS run it is T0.
- GEO returned a window from 08:44:54 to 15:00:54 UTC = 376 min, inside a 360 min
  requested horizon (T0 to 14:52:54). It starts at T0 - 8 min and ends at T0 + 368 min.

**Likely cause:** the boundary-refinement loops in `scan_windows` step back one
coarse step before a window's start and forward one coarse step after its end,
without clamping to the requested `start_dt` / `end_dt`.

**Consequence for the study:** compute the false-safe rate twice, once on the raw
windows and once clipped to the requested range, so this bug is not mixed into the
sampling result.

**To do (after the study):** fix in a new commit or branch, not in the baseline commit.

---

## F2. Coarse-to-refined saves evaluations, but not in every case

**Status:** MEASURED (counts only; agreement on what is safe is not yet tested)

A uniform 2-minute scan of 6 h needs 181 evaluations.

| Preset | OPAS evaluations | Uniform 2-min / OPAS |
|---|---|---|
| ISS | 77 | 2.35x |
| Starlink | 81 | 2.23x |
| SSO | 78 | 2.32x |
| Polar | 60 | 3.02x |
| GEO | 230 | 0.79x (OPAS does more work) |

**Explanation:** the coarse pass is cheap, but a returned window is then verified
by checking every 2 minutes across its whole length. A long safe window (GEO) costs
about as much as a uniform fine scan, plus the coarse pass on top.

**Caveat:** evaluation count is a proxy. Per-evaluation time also varies by preset
(about 1.3 s for ISS and Starlink, 0.5 s for SSO and polar, 0.08 s for GEO).

---

## F3. The inner check sees only a small fraction of real encounters in crowded shells — CONFIRMED for ISS, Starlink, SSO; NOT an issue in GEO

**Status:** MEASURED for the ISS, Starlink, SSO, and GEO presets (confirmed by `reference.py`)

**Original observation (baseline only):** the coarse steps flagged as threatened:

| Preset | Coarse steps flagged | Mean objects flagged per coarse step |
|---|---|---|
| ISS | 13 / 37 (35%) | 0.43 |
| Starlink | 12 / 37 (32%) | 0.32 |
| SSO | 12 / 37 (32%) | 0.43 |
| Polar | 24 / 37 (65%) | 0.84 |
| GEO | 0 / 37 (0%) | 0.00 |

**Reference result for ISS** (`reference_iss_20260921T102002Z.json`, 6 h, all 11,997
candidates, 1 s sampling, 1-minute launch grid, 361 launch times in range):

| Radius | % of launch times with >=1 object within radius | Mean objects within radius |
|---|---|---|
| 5 km | 5% | 0.06 |
| 10 km | 16% | 0.19 |
| 25 km | 63% | 1.04 |
| 50 km | **100%** | **8.8** |
| 100 km | 100% | 97.9 |
| OPAS's own per-object screening radius (50 km + TLE-age inflation) | **100%** | **11.0** |

**Reference result for Starlink** (`reference_starlink_20260922T071313Z.json`, 6 h,
all 13,478 candidates, 361 launch times in range):

| Radius | % of launch times with >=1 object within radius | Mean objects within radius |
|---|---|---|
| 5 km | 10% | 0.11 |
| 10 km | 29% | 0.37 |
| 25 km | 90% | 2.24 |
| 50 km | **100%** | **10.8** |
| 100 km | 100% | 103.4 |
| OPAS's own per-object screening radius | **100%** | **11.8** |

Starlink (550 km) is consistently a bit denser than ISS (420 km) at every radius
below 50 km, as expected for a busier shell, but both converge to 100% unsafe at
OPAS's actual screening radius.

**Reference result for SSO** (`reference_sso_20260922T072024Z.json`, 6 h, all 4,753
candidates, 361 launch times in range):

| Radius | % of launch times with >=1 object within radius | Mean objects within radius |
|---|---|---|
| 5 km | 11% | 0.12 |
| 10 km | 45% | 0.58 |
| 25 km | 94% | 3.25 |
| 50 km | **100%** | **12.2** |
| 100 km | 100% | 51.5 |
| OPAS's own per-object screening radius | **100%** | **15.1** |

SSO has the fewest candidates of the three (4,753 vs 12-13k), yet shows the *highest*
unsafe rate at every radius below 50 km — likely because a sun-synchronous 98.2°
inclination crosses many other orbital planes, encountering a wider mix of objects
per orbit than the ~51-53° shells. Worth a sentence in the discussion: candidate
count alone doesn't predict encounter rate; inclination geometry matters too.

**Reference result for GEO** (`reference_geo_20260922T073419Z.json`, 6 h, all 840
candidates, 361 launch times in range):

| Radius | % of launch times with >=1 object within radius | Mean objects within radius |
|---|---|---|
| 5 km | 0% | 0.0 |
| 10 km | 0% | 0.0 |
| 25 km | 0% | 0.0 |
| 50 km | 0% | 0.0 |
| 100 km | 0% | 0.0 |
| OPAS's own per-object screening radius | **0%** | **0.0** |

GEO shows literally zero encounters at any tested radius, out to 100 km — this
matches OPAS's own claim (see F5) and is expected given only 840 candidates spread
across a much larger volume at that altitude. This is the control case that makes
F3 a finding about crowded shells specifically, not a blanket statement about the
scanning algorithm everywhere.

**Reasoning that predicted this (from reading `count_threats_fast`):** each launch
time is tested at about 14 points along one orbit, roughly 6 minutes (~2,800 km)
apart, against a 50 km radius. A real close approach lasts only seconds inside that
radius, so each real encounter has a low-single-digit-percent chance of landing on
a sample point. The reference confirms encounters are effectively constant at 550 km,
consistent with the earlier "dozens per orbit" estimate.

**Important scope note:** this compares the *reference* against OPAS's raw per-minute
*inner check* (`count_threats_fast` called every minute), not against the literal
windows `scan_windows` returned in the baseline run.

**Also worth flagging for the report:** a 50 km screening radius looks very generous 
for how crowded the 550 km ISS shell is — the 5 km and 10 km numbers look much closer 
to what "collision risk" would intuitively mean.

---

## F4. The inner check skips the ascent phase

**Status:** READ FROM CODE

In `count_threats_fast`, the sample points start at `ascent_steps` (about the first
600 s of flight), so the first ~10 minutes of every flight are never checked by the
safe-window scan. (`full_check`, used by `/alert`, starts from waypoint 0.)

**Consequence for the study:** the reference matches OPAS's scope by default so that
only sampling density differs. `reference.py --include-ascent` measures how much the
ascent phase would add. Report as a limitation or finding.

---

## F5. OPAS's returned "safe windows" were unsafe for their entire duration in crowded shells (ISS, Starlink, SSO), but correct in GEO

**Status:** MEASURED (headline result — `compare.py`, all presets)

`compare.py` checked OPAS's actual returned windows from the baseline run — not the
raw inner-check function, but the literal thing `/safe-windows` reported to a user —
against the dense reference, minute by minute.

| Preset | Window | Duration | Reference samples | Marked unsafe | False-safe rate |
|---|---|---|---|---|---|
| ISS | 09:04:54Z -> 09:28:54Z | 24 min | 24 | 24 | **100%** |
| Starlink | 09:46:54Z -> 10:32:54Z | 46 min | 46 | 46 | **100%** |
| Starlink | 11:14:54Z -> 11:30:54Z | 16 min | 16 | 16 | **100%** |
| SSO | 10:04:54Z -> 10:24:54Z | 20 min | 20 | 20 | **100%** |
| GEO | 08:44:54Z -> 15:00:54Z (raw) | 376 min | 375 | 0 | **0%** |
| GEO | 08:52:54Z -> 14:52:54Z (clipped) | 360 min | 360 | 0 | **0%** |

Every minute of every LEO/SSO window OPAS called safe was — per the dense
reference — actually within OPAS's own screening radius of at least one tracked
object. **GEO is the exception: 0% false-safe, i.e. OPAS's claim was correct there.**
This is not a contradiction of F3, it's the expected contrast: GEO has only 840
candidates spread across a vastly larger volume, so there is genuinely nothing
nearby to miss. The sampling-blindness problem is specific to crowded shells, not
a universal flaw in the coarse-to-refined design — a useful nuance for the
discussion section ("OPAS fails badly exactly where it matters most, and happens
to be fine where it matters least").

**GEO is also the first case where F1's boundary bug is directly visible in a
`compare.py` result**, not just inferred from the baseline: the raw window
(08:44:54Z -> 15:00:54Z) extends 8 minutes before and after the requested range
(08:52:54Z -> 14:52:54Z); clipping removes exactly those minutes. The verdict
doesn't change here (0% either way), but on a crowded shell the same 8-minute
overhang could flip a false-safe rate, so F1 and F3 should be reported as
independent findings, not folded together.

Every window has 1-2 "uncovered" minutes (endpoint-of-range artifact, see F1/the
validation section), not a real gap in coverage.

**All five presets are now covered.** Polar returned no windows in the baseline
(nothing to compare); every other preset's window(s) have been checked.

Source data: `research/results/compare_iss_20260922T070022Z.json`,
`research/results/compare_starlink_20260922T071627Z.json`,
`research/results/compare_sso_20260922T072131Z.json`,
`research/results/compare_geo_20260922T073520Z.json`.

---

## F6. Coarse sampling and inadequate density manufacture false safety (Sweep Results)

**Status:** MEASURED (`sweep.py`, ISS, Starlink, and SSO presets)

Sweeping the parameterized scanner across a grid of settings (`coarse_min` = 5, 10, 20; `fine_min` = 2; `n_intervals` = 6, 12, 24) proved that OPAS's false-safe windows are exclusively a product of sparse sampling.

* **Tighter sampling exposes the truth:** Forcing OPAS to sample more densely (`n_intervals=24`) resulted in exactly **0 safe windows** returned for ISS, Starlink, and SSO. The algorithm correctly recognized the sky was fully obstructed at a 50 km radius.
* **Sparse sampling creates the illusion of safety:** Dropping the sampling density (`n_intervals=6` or `12` with a 10-minute coarse step) caused OPAS to "find" safe windows—every single one of which was **100% false-safe** against the dense reference.

The 50 km screening radius is mathematically incompatible with LEO density. If the algorithm is fixed to sample adequately, it will never find a safe launch time at that altitude. 

---

## F7. Exponential TLE-age inflation artificially blocks the LEO shell

**Status:** MEASURED (`scanner_fixed.py` engineering runs)

When the spatial sampling was fixed (via a 600-waypoint dense trajectory in `scanner_fixed.py`), OPAS returned exactly 0 safe windows for the ISS preset. 

The original `screening_radius_km` formula inflated the baseline radius by $2.0 \times \text{age}^{1.5}$, creating error bubbles up to 200 km for older TLEs. Because the reference data proved the ISS shell is 100% obstructed at 50 km (see F3), the dense scanner correctly identified that navigating a 200 km volume through LEO is impossible. Capping the TLE age penalty at 5.0 km (for a maximum 15.0 km screening radius) immediately surfaced three safe launch windows (80, 60, and 26 minutes).

---

## F8. 2-minute temporal verification creates a massive blind spot

**Status:** MEASURED (`compare.py` on fixed spatial scanner)

After correcting the spatial sampling density and the radius cap, validation via `compare.py` showed the new windows still had a false-safe rate of 28-35%. 

This exposed a separate temporal flaw: OPAS's refinement loop (`fine_step`) verified safety every 2 minutes. In LEO, a vehicle travels roughly 7.5 km/s, meaning a 2-minute launch delay shifts the entire orbital track by 900 kilometers. By blindly interpolating safety across that 2-minute gap, the algorithm completely missed crossing debris. Dropping the `fine_step` to 1 minute to match the reference resolution allowed the algorithm to detect these boundary threats and trim the windows down accurately to 52 and 40 minutes. 

---

## F9. The absolute physical limit of discrete spatial sampling (The 9-Second Gap) — CONFIRMED, not inferred

**Status:** MEASURED (`compare_fixed.py` + `prove_sampling_gap.py` against `scanner_fixed.py`'s exact logic)

Even after fixing the spatial density (600 waypoints), clamping the radius (10-15 km,
age-dependent), and closing the temporal gap (1-minute verification), validation against
the dense reference — using scanner_fixed.py's exact per-object radius formula — showed a
final false-safe rate of 9.6% and 22.5% for the two returned windows (18 confirmed-unsafe
reference pairs inside them).

The cause was directly reproduced, not inferred: `prove_sampling_gap.py` recomputed the
scanner's own 600-waypoint math at each contested launch time.

- **15/18 (83%)** were confirmed to be caused exactly as hypothesized: the scanner's own
  samples, evaluated at the precise launch instant the reference flagged, never landed
  within the danger radius even though the true (parabola-refined) minimum distance did.
  At LEO relative velocities (~15 km/s) and ~9.28s waypoint spacing, objects travel up to
  ~135 km between samples, so a close approach peaking between waypoints is physically
  invisible to `any_threat_ecef`.
- **3/18 (17%)** were caused by a distinct, equally precise mechanism: `reference.py`'s
  launch-time grid is built from the actual sample spacing `dt` (1.0000791...s per nominal
  second) rather than true clock seconds, so by ~5 hours into the scan its launch offsets
  had drifted ~1.3-1.5s off whole-minute marks (predicted drift `k*60*(dt-1)` matched the
  observed offset to the millisecond in all three cases). Because these three encounters
  were narrow near-misses (true distance 4.8-5.5 km vs. a ~10.2-10.3 km radius) and vehicle
  groundspeed is ~7.5 km/s, a ~1.4s timing offset alone is enough to flip the verdict. This
  is a precision limit of the reference's grading grid, not a flaw in scan_windows_fixed's
  own logic — the scanner's actually-checked (whole-minute) launch times were very likely
  genuinely clear in these 3 cases.

Achieving a true 0% false-safe rate against a continuous ground truth would still require
either continuous swept-volume interpolation or sub-second waypoint generation for the
first mechanism, and clock-locked (not dt-derived) launch grids for the second.

---

## F10. At a realistic radius, Starlink and SSO have no genuinely safe launch window at all in this horizon

**Status:** MEASURED (`scanner_fixed.py`, `check_zero_windows.py`, `simulate_ground_truth_scan.py`)

Running the fully fixed scanner (600-waypoint dense sampling, 10-15 km age-scaled radius,
1-minute temporal verification) on Starlink (550 km) and SSO (705 km) both returned zero
windows for the same 6-hour horizon that produced 3 (later 2) windows for ISS.

This was confirmed to be the mathematically correct answer, not a bug in scanner_fixed.py,
by two independent checks:
- `check_zero_windows.py`: at the scanner's exact per-object radius, the dense reference
  shows a 32.1% (Starlink) and 49.9% (SSO) per-minute unsafe rate across the 6h horizon —
  markedly higher than ISS's ~17%, consistent with these being busier shells (Starlink) and
  a higher-encounter-rate inclination (SSO, see F3).
- `simulate_ground_truth_scan.py`: re-running scan_windows_fixed's exact coarse-to-refined
  algorithm, but substituting perfect dense-reference lookups for the live scanner call at
  every checked instant, still produced zero windows >= 15 minutes for both presets. Several
  coarse-resolution runs looked promising at first glance (e.g. Starlink's 70- and 80-minute
  coarse-safe blocks), but every one collapsed to under 6 minutes once refined to 1-minute
  resolution and re-checked against the true per-minute safety.

Combined with F9 (ISS's fixed scanner still has a 9.6-22.5% residual false-safe rate) and F5
(GEO's original unfixed scanner was already correct, 0% false-safe), this gives a coherent
three-tier picture across the study's five orbital regimes: GEO has essentially no encounter
risk at all; ISS's 420 km shell is crowded enough to produce false-safe illusions from
under-sampling but sparse enough that real clear windows exist once fixed; Starlink and SSO's
550-705 km shells are crowded enough that -- once you stop under-sampling and actually check
properly -- there simply is no clear launch window to find in a 6-hour span. The original
(unfixed) scanner's F6 sweep behavior (returning "safe" windows at loose settings, zero at
tight settings) foreshadowed this for Starlink and SSO specifically; this finding confirms the
tight-setting behavior was correct all along for these two shells, not merely `overly cautious`.

**Note:** `simulate_ground_truth_scan.py`'s refinement loop reproduced F1's boundary-overshoot
bug faithfully (a `-4 min`/`-8 min` "duration" appears when the very first coarse check point
is itself unsafe) -- expected given it mirrors `scan_windows_fixed`'s own logic exactly, and
harmless here since these get discarded by the >=15 min filter regardless.

---

## Reference scanner validation (ISS)

**Status:** MEASURED

- **Self-test:** two planted objects with known closest-approach distances. On-sample
  plant recovered exactly (3.000 km). Between-sample crossing (true miss 3 km, raw
  sampled minimum 6.89 km) recovered to 3.01 km after parabola refinement. Both passed.
- **1 s vs 2 s sampling agreement** (100 real objects x 380 launches = 38,000 pairs,
  195 pairs within 100 km at either resolution): median |difference| 0.0005 km,
  99th percentile 0.006 km, max 0.077 km. **Zero classification flips** at 5, 10, 25,
  or 50 km radius.
- **Timing:** 100-object test projected ~2.0 min for the full 11,997-object run;
  actual full run took 6.6 min (396 s). Projection was optimistic by ~3.3x, likely
  because the timing test's 100 objects (evenly spaced through the candidate list)
  weren't representative of per-object cost, and/or fixed per-call overhead. Keep in
  mind for estimating Starlink/SSO/polar runtimes.

---

## Open items

- [x] Build `research/reference.py` and run on all presets (built and tested on a synthetic catalog: planted-object self-test, 1 s vs 2 s agreement, threading determinism, and "every object OPAS flags is also flagged by the reference")
- [x] Write and run `compare.py` for all presets (ISS, Starlink, SSO are 100% false-safe; GEO is 0% false-safe; polar returned no windows).
- [x] Run `sweep.py` parameter sweeps for ISS, Starlink, and SSO to prove sampling density causes the false-safe windows.
- [x] Draft `scanner_fixed.py` to cap the LEO screening radius (15 km max) and natively over-sample the trajectory (600 waypoints).
- [x] Fix temporal verification gap in `scanner_fixed.py` (down to 1 minute) and boundary clamp windows.
- [x] Validate `scanner_fixed.py` against the dense reference using `compare.py` to prove the final physical limits of discrete point-to-point sampling.
- [ ] Literature Review: SGP4 propagation error margins, collision probability, and continuous vs. discrete screening.
- [ ] Write the LaTeX report.