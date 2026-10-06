# OPAS focused verification rerun — rerun_20261006T115728Z

The detector agreed with the independent distance calculation on **691/691 exact launch timestamps (100.00%)**. Observed false-safe samples: **0/565 (0.00%)**. Observed false alarms: **0**. Every production check had an independent reference result; the reference included 45 additional minute-grid samples.

| Run | Coverage | Elapsed runtime |
| --- | --- | --- |
| Focused tests | 33 passed | 3.120 s (0.05 min) |
| Actual six-hour ISS window search | 691 launch checks | 1106.109 s (18.44 min) |
| Independent ISS reference | 736 launch checks | 948.989 s (15.82 min) |
| Archived research pair replay | 451 unsafe + 3089 nearby clear | 90.911 s (1.52 min) |
| Direct ~0.2 s resolution control | 6 selected pairs | 7.230 s (0.12 min) |

Minute discovery used 316 checks and took 516.460 s; the 375 intervening checks took another 589.649 s. The runtime observer captured the final minute-only update.

The minute-only grid produced apparent windows of 33.0 minutes, 23.0 minutes. The finer reference found **52 unsafe launches among 280 additional samples** inside those windows (18.57%). The final 10-second candidate refinement returned **0 qualifying windows of at least 15 minutes**. This between-minute unsafe fraction is a measurement of minute-only sampling, separate from the final scanner's observed false-safe rate.

The archived ISS, Starlink and SSO replay found 0 missed unsafe pairs and 0 incorrectly flagged clear pairs. This fresh replay uses exact recorded offsets inside the six-hour horizon, frozen screening radii, and clear controls within radius + 20 km. It excludes 6 nearby pairs whose archived closest approach is before the production flight scope. It is a comparison with archived research minima. The full ISS reference above was recomputed during this run.

Direct propagation at 0.200001 s spacing changed 0 classifications in the 6 selected threshold-nearest pairs and disagreed with the production pair detector on 0 pairs. This checks numerical resolution for those six pairs; it does not repeat the entire catalogue at 0.2 seconds.

The tested launch horizon is **2026-09-21T08:52:54.811735+00:00 through 2026-09-21T14:52:54.811735+00:00**, from the archived snapshot. The snapshot contains 11,997 ISS altitude-filtered objects, with SHA-256 `c13469e0cee49549504c9de7e45388c926e32ebe5c3b3ec6ccb81855838b1fa8`. The independent reference regenerates the vehicle path at 1.000079 s spacing and uses separate squared-distance/parabolic minimization. Its one-second satellite ephemerides are interpolated onto that grid; pairs within 20 m of the threshold are directly repropagated. Both methods share the frozen TLE/SGP4 and vehicle models.

The production ISS flight check begins at about 603.356 s; the dense reference begins at 600.047470 s. These measurements establish agreement at tested launch times in the frozen post-ascent model. They do not establish real-world safety, ascent safety, coverage of objects outside the altitude filter, or safety at every instant between 10-second launch samples.

Instrumented production search (4 spawned processes) and dense minute reference (3 threads) overlap; the supplementary archived pair replay also ran for 90.911s during them. Fine reference uses 4 threads. CPU quota is 8 cores; BLAS/OMP use one thread. Elapsed timings describe this shared-load run, not isolated latency. Reported elapsed_seconds starts after snapshot input setup and ends after phase classification; command startup and final report serialization are excluded.

The previous scratch checkout was unavailable. `backend/encounters.py` and `backend/windows.py` were reconstructed and matched their recorded previous SHA-256 values byte for byte. The scanner patches were reapplied to `50fb28f61a2fef1a1f29ea1d92e2089333fb24cc`; its prior full checksum was unavailable. Eighteen focused tests were reproduced from recorded source and fifteen encounter/scanner tests were rebuilt from recorded descriptions. All numbers in this report are fresh measurements; historical runtimes and classifications were not reused.

Detailed evidence: [summary.json](summary.json), [manifest.json](manifest.json), [focused_tests.log](focused_tests.log), [archived_pair_replay.json](archived_pair_replay.json), [launch_sampling.json](launch_sampling.json), [resolution_control.json](resolution_control.json), [search_phase_runtime.json](search_phase_runtime.json), [iss_search.json](iss_search.json), [iss_reference.json](iss_reference.json).
