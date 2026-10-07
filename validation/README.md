# Focused scanner verification

Looking for the files behind a report result? Start with the
[report evidence index](EVIDENCE.md), which maps each table and supplementary
check to its exact records. The commands below reproduce the follow-up checks;
the index also links the historical research and corrected duration recount.
The [performance guide](PERFORMANCE.md) covers exact-input capture, offline
replay and controlled before/after ISS, Starlink and SSO comparisons.

For live application diagnostics, request logs and the finer final validation
pass, see [runtime checks](RUNTIME_CHECKS.md). The research benchmark commands
below retain their documented 10-second comparison protocol. The HTTP API now
also checks qualifying spans at 5 seconds; do not label its runtime or result
as the earlier six-hour measurement without a fresh matched reference run.

Run the detector and window-finder tests from the repository root:

```bash
OPENBLAS_NUM_THREADS=1 OMP_NUM_THREADS=1 python -m unittest discover -s backend/tests -v
```

Install `backend/requirements-dev.txt` for the HTTP integration tests. To save a
complete JSON result and test log, use `validation/run_focused_tests.py --output
PATH.json` with the same thread settings. Frontend checks run with `npm test`,
`npm run build` and `npm run lint` from `frontend/`.

The frozen data and original independent research references are in the
`research-branch`. Create a separate checkout of that branch and pass its
`research` directory to the validation scripts. Install the backend dependencies
and `skyfield==1.55`. The scripts disable the MongoDB connection; no live
catalogue or database writes are required.

For a fresh six-hour ISS verification, create a new result directory and run
the actual production search and the independent minute reference. Both use
exact clock launch offsets, independent of the flight discretization.

```bash
OPENBLAS_NUM_THREADS=1 OMP_NUM_THREADS=1 python validation/verify_iss_windows.py --research-root ../OPAS-research/research --phase search --horizon-hours 6 --launch-step-s 10 --workers 4 --output RESULT_DIR/iss_search.json
OPENBLAS_NUM_THREADS=1 OMP_NUM_THREADS=1 python validation/verify_iss_windows.py --research-root ../OPAS-research/research --phase dense --horizon-hours 6 --launch-step-s 60 --workers 3 --output RESULT_DIR/iss_minute_reference.json
```

After the minute reference completes, enumerate the extra fine launch times,
calculate their independent distances, and combine the completed references.
The enumeration classifies no launches. The final comparison rejects incomplete
reports, snapshot/source mismatches, duplicate timestamps, and any production
launch lacking independent coverage.

```bash
python validation/plan_fine_launches.py --minute-reference RESULT_DIR/iss_minute_reference.json --output RESULT_DIR/fine_plan.json
OPENBLAS_NUM_THREADS=1 OMP_NUM_THREADS=1 python validation/verify_iss_windows.py --research-root ../OPAS-research/research --phase dense --launches-file RESULT_DIR/fine_plan.json --launch-step-s 10 --workers 4 --output RESULT_DIR/iss_fine_reference.json
python validation/merge_iss_reference.py --minute RESULT_DIR/iss_minute_reference.json --fine RESULT_DIR/iss_fine_reference.json --output RESULT_DIR/iss_reference.json
python validation/compare_iss_verification.py --production RESULT_DIR/iss_search.json --dense RESULT_DIR/iss_reference.json --output RESULT_DIR/summary.json
python validation/compare_launch_sampling.py --minute RESULT_DIR/iss_minute_reference.json --reference RESULT_DIR/iss_reference.json --production RESULT_DIR/iss_search.json --output RESULT_DIR/launch_sampling.json
OPENBLAS_NUM_THREADS=1 OMP_NUM_THREADS=1 python validation/check_dense_resolution.py --research-root ../OPAS-research/research --reference RESULT_DIR/iss_reference.json --output RESULT_DIR/resolution_control.json
OPENBLAS_NUM_THREADS=1 OMP_NUM_THREADS=1 python validation/validate_encounters.py --research-root ../OPAS-research/research --output RESULT_DIR/archived_pair_replay.json
```

Use `trace_search_runtime.py` alongside a running search to capture the minute
discovery/fine refinement timing boundary. Total runtimes come from the measured
phases; overlapping calculations share CPU resources. Each completed result
records the snapshot and source checksums. Run reports under `results/` describe
the exact environment, recovery provenance, measurements, and limitations.

The independent calculation shares the vehicle and SGP4 physics but uses a
separate dense flight grid and distance minimization. Agreement is evidence for
sampled launch times within this frozen model. It is not continuous-time or
real-world safety certification.

The six-hour report records the code tested in that run. Later integration fixes
add explicit errors for unavailable satellite construction and preserve the
exact timestamp when a window is selected. Their tests and fresh archived pair
replay are recorded separately under `results/handoff_*/`, so previous
measurements keep their original source checksums.
