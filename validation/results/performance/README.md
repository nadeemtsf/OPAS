# Matched scanner performance and independent validation

These are six-hour searches on the preserved research catalogue, measured on
6–7 October 2026. The baseline is commit `85ff387`; current reports identify the
measured production source by SHA-256. The detailed checklist is
[../../PERFORMANCE_TODO.md](../../PERFORMANCE_TODO.md); reproduction commands
and the code map are in [../../PERFORMANCE.md](../../PERFORMANCE.md).

## Search measurements

| Mission | Selected objects | Checks (clear/unsafe) | Before (s) | After (s) | Speedup | Returned windows |
| --- | ---: | ---: | ---: | ---: | ---: | ---: |
| ISS (420 km) | 11,997 | 691 (565/126) | 1292.461 | 707.157 | 1.83× | 0 |
| Starlink (550 km) | 13,478 | 418 (281/137) | 708.826 | 436.498 | 1.62× | 0 |
| SSO (705 km) | 4,753 | 271 (144/127) | 163.709 | 99.228 | 1.65× | 0 |

All 1,380 checked classifications match before and after: 990 clear and 390
obstructed. All searches return zero qualifying windows. The final ISS and SSO
measurements rerun the captures after journal finalization was hardened; their
initial measurements and unchanged original capture artifacts are retained
under `initial_capture_journal_gaps/`. The initial Starlink journal was complete. The interrupted SSO rerun is
retained under `interrupted_capture_rerun/`, explicitly marked incomplete.
Final capture reruns resumed on 7 October after the workspace reconnected;
the initial series ran on 6 October. Resource quota and package versions match,
but these timings should not be treated as repeated same-host statistics.

Times include scanner preparation, spawning/initializing four workers, search
and (for optimized runs) exact evidence capture; snapshot reading and nominal
trajectory generation are excluded. Main scanner and reference workloads ran
sequentially. Small software/synthetic controls ran during parts of the initial
search series within the same eight-core quota. These are individual observed
runs, not repeated statistics or a Windows latency prediction.

## Independent numerical comparison

| Mission | Full reference launch grid | Reference clear/unsafe | Reference (s) | Observed false-safe checks | Longest clear sampled span (s) |
| --- | ---: | ---: | ---: | ---: | ---: |
| ISS (420 km) | 4,321 | 3473/848 | 509.237 | 0/565 | 250 |
| Starlink (550 km) | 4,321 | 2876/1445 | 609.438 | 0/281 | 85 |
| SSO (705 km) | 4,321 | 2309/2012 | 324.308 | 0/144 | 70 |

Each reference covers the entire horizon at exact five-second launch spacing:
4,321 launches per preset, 12,963 in total. There are zero production/reference
classification disagreements, including zero false obstructions. No reference
span reaches 900 seconds, so no qualifying sampled window was missed in these
cases. No positive returned window from the real catalogue was available to
validate. Planted window tests cover positive spans, five-second coverage and
the endpoint case that looked too short on the ten-second discovery grid.

The reference propagates through Skyfield directly, independently interpolates
its approximately one-second flight ephemeris, and uses a separate parabolic
distance minimization. A sparse flight prefilter bounds excluded dense samples
using maximum measured vehicle/object displacement; it does not reuse the
production detector's broad pass or acceleration allowance. Near-threshold
pairs receive direct propagation at the actual launch TT. Unfiltered
full-catalogue controls cover 14 launches per preset (42 total), with zero
disagreements. Direct approximately 0.2-second controls cover six selected pairs
per preset (18 total), with zero classification changes or production pair
mismatches. They are not a full-catalogue 0.2-second evaluation.

Both calculations share SGP4 and the nominal vehicle model. The reference
regenerates that vehicle at finer resolution; production interpolates its
stored waypoints. Their starts align to the production post-ascent endpoint.
Agreement applies to this snapshot, altitude selection, frozen screening radii
and sampled launch grid. It does not establish a universal false-safe rate,
continuous launch-time clearance, ascent coverage or physical safety.

## What profiling found

The three-launch ISS profile (two clear, one obstructed) took 21.440 seconds
before and 12.562 after. The original orbital-position path accounted for
17.690 cumulative seconds, including 9.166 seconds of raw SGP4. These nested
costs must not be added. The optimized raw SGP4 cost remained 9.433 seconds:
the savings come chiefly from removing repeated frame construction and scalar
broad-screen work. Exact SGP4 propagation is batched in groups of 128 objects;
Skyfield time conversion and rotations are shared per launch. Fixed mission
geometry is reused per worker. Close-approach refinement, radii, altitude
selection and strict propagation errors remain unchanged.

The four-launch worker experiment took 26.380 → 16.915 seconds with one worker,
and 11.227 → 8.002 with four. Wall time minus serial compute sum/parallel
largest check was about 1.1/3.9 seconds, respectively. That residual includes
initialization, serialization and scheduling, not only startup. It cannot
explain a forty-minute workload by itself on this host. Optional `opas_math`
helper availability is separate from the SGP4 C++ acceleration actually used
by this scanner; startup diagnostics now state both accurately.

## Capture integrity and software checks

All final preset bundles pass manifest checks and match the benchmark's selected
catalogue, exact trajectory/horizon, frozen radii, individual classifications,
windows and measured production source. Journals contain 691 ISS, 418 Starlink
and 271 SSO checks. The initial ISS/SSO append journals each lacked three checks;
their causes were not established, and those files were preserved without
silently filling them from benchmark records. Finalization now writes all
parent-consumed checks atomically and rejects a completed result whose count or
unique timestamps do not agree. The replacement runs passed that audit.

A separate synthetic 400 km one-hour request verifies capture/replay and
independent-reference handling of a custom mission; it is not live-catalogue
accuracy evidence. Failed/cancelled captures retain incomplete status and do
not contain verified windows. Manifest validation precedes offline replay;
replay exits unsuccessfully on incomplete originals or differing results.

Backend: 77 tests passed, no failures/errors/skips. The same suite
passed with optional native helpers importable; window geometry uses the same
NumPy/Skyfield/SGP4 path in both modes. Frontend: 25 tests, build and lint passed.
Archived encounter replay detected 451 unsafe pairs and retained 3,089 clear
controls with zero disagreements; six cases outside the flight scope were
excluded.

## Environment and evidence limits

Linux x86-64; Python 3.12.14; Skyfield 1.55; sgp4 2.27; NumPy 2.3.5.
Eight-core CPU quota, four production workers, 8 GiB RAM,
`OPENBLAS_NUM_THREADS=1`, `OMP_NUM_THREADS=1`. Horizon:
`2026-09-21T08:52:54.811735+00:00` to `2026-09-21T14:52:54.811735+00:00`.
Uncompressed research snapshot SHA-256:
`c13469e0cee49549504c9de7e45388c926e32ebe5c3b3ec6ccb81855838b1fa8`.
The full 32,517-object snapshot is pinned on `research-branch`; each current
capture preserves its selected objects and frozen radii for standalone replay.

`live_run/` preserves the supplied screenshot and partial log: request
`3812000cee87`, 2,436 seconds, 11,672 selected objects, 957 checks, 849 clear,
108 obstructed, zero windows. The completed JSON, exact fresh catalogue,
search start and frozen radii were not supplied. Those 849 clear samples and
that exact Windows bottleneck remain unverified. The frozen 420 km ISS preset
is separate from the conversation's 400 km mission.

`comparison.json` contains the comparison, `capture_integrity.json` the capture
audit, and `manifest.json` the source/environment/artifact checksums. Logs and
individual reports remain available beside them. The evidence index maps report
tables to these records without putting lengthy filenames in the paper.
