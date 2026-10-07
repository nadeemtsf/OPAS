# Reproducible scanner profiling and preset validation

The checklist is in [PERFORMANCE_TODO.md](PERFORMANCE_TODO.md). Results and
their limitations are recorded in [performance evidence](results/performance/).
The pre-optimization baseline is commit `85ff387` on the same fix branch.
These tests use the research catalogue, not the fresh Windows catalogue.
Raw evidence logs retain their original whitespace and Windows line endings
so their recorded checksums remain valid; source/document whitespace checks
exclude those archived artifacts.

## Capture a request in the application

Capture is enabled by default. Each window request writes a separate directory
under `backend/run-evidence/`, which Git ignores. It preserves selected objects
and TLEs, mission and trajectory, exact UTC horizon, frozen screening radii,
source/package hashes, every completed launch check and the result. Failed
searches are saved as incomplete, without verified windows. Cancellation saves
the checks that completed before work stopped.

In the sidebar, save **Download check details**, **Download run inputs**, and
**Download launch checks**. The latter two download the captured catalogue and
individual classifications. The backend directory also contains the result
and a manifest with SHA-256 checksums. Keep the entire request directory when
transferring evidence for offline replay; downloading the inputs alone is not
enough to compare classifications. The JSON result includes download URLs.

To choose the storage directory, from the Windows backend directory:

```powershell
$env:OPAS_CAPTURE_DIR = "..\run-evidence"
$env:OPAS_LOG_LEVEL = "DEBUG"
python -m uvicorn api:app --reload --host 0.0.0.0 --port 8000
```

Capture does not change or refresh the database. Saved inputs remain fixed
after a later ingest. The files contain catalogue data, not database or
Space-Track credentials. Storage grows with requests; keep required evidence
and remove other completed request directories when convenient. Set
`OPAS_CAPTURE_RUNS=0` to disable capture. A failed capture is not an exact-input
reproduction.

The final journal is written atomically from all parent-consumed checks; its
count and unique timestamps must match the completed detector diagnostics.
The initial frozen ISS and SSO captures each lacked three append records;
those original artifacts are preserved and identified separately. New captures
are rerun and checked against the complete benchmark records.

The final 5-second pass also checks the fringes of near-qualifying discovery
runs. For example, a clear span from 5 to 905 seconds lasts exactly 15 minutes,
but its 10-second endpoints (10 and 900) span only 890 seconds. The finer pass
recovers the checked endpoints; the returned duration requirement stays 900
seconds. No endpoint is inferred clear without a detector call.

Replay a complete request directory from the repository root:

```bash
python validation/replay_capture.py --capture backend/run-evidence/REQUEST_ID --workers 4 --output replay.json
```

Replay verifies the manifest before loading the input, keeps the stored radii
and trajectory, and compares individual classifications and returned windows.
It records the current source hashes; it does not require MongoDB. An incomplete
original run is not eligible for a claim of complete original-run equivalence.
Package versions in the capture identify the original numerical environment.

To check a captured mission independently across its full launch horizon:

```bash
OPENBLAS_NUM_THREADS=1 OMP_NUM_THREADS=1 python validation/reference_presets.py --capture backend/run-evidence/REQUEST_ID --launch-step-s 5 --workers 4 --output captured_reference.json
```

This uses the captured mission (including a custom 400 km mission), catalogue
and frozen radii. It rejects a different trajectory-model version. The preset
commands below use the separate 420 km ISS research case.

## Controlled frozen-catalogue commands

Create a separate checkout of `research-branch` as `../OPAS-research`. Install
`validation/requirements.txt` for the measured versions. Run scanner workloads
and independent references sequentially with one BLAS/OpenMP thread:

```bash
git worktree add --detach ../OPAS-baseline 85ff387
OPENBLAS_NUM_THREADS=1 OMP_NUM_THREADS=1 python validation/benchmark_scanner.py --backend-root ../OPAS-baseline/backend --research-root ../OPAS-research/research --preset iss --mode profile --output baseline_profile.json
OPENBLAS_NUM_THREADS=1 OMP_NUM_THREADS=1 python validation/benchmark_scanner.py --backend-root ../OPAS-baseline/backend --research-root ../OPAS-research/research --preset iss --mode search --workers 4 --output baseline_iss.json
OPENBLAS_NUM_THREADS=1 OMP_NUM_THREADS=1 python validation/benchmark_scanner.py --research-root ../OPAS-research/research --preset iss --mode search --workers 4 --capture --output optimized_iss.json
OPENBLAS_NUM_THREADS=1 OMP_NUM_THREADS=1 python validation/reference_presets.py --research-root ../OPAS-research/research --preset iss --launch-step-s 5 --workers 4 --output reference_iss.json
```

Repeat with `--preset starlink` and `--preset sso`. ISS is the named 420 km
preset; the supplied Windows run used 400 km according to the conversation.
The reference evaluates the whole six-hour launch horizon, not only spans
selected by production. Its approximately one-second flight grid includes the
production post-ascent endpoint and full flight endpoint. It calls Skyfield
directly and minimizes distances separately from the production interval
detector. It regenerates the nominal vehicle trajectory at finer resolution;
production interpolates its stored waypoints. Near-threshold pairs are
repropagated directly, and selected pairs receive a 0.2-second resolution check.
A sparse flight
prefilter uses maximum measured ephemeris/vehicle displacement to bound the
distance of excluded dense samples. `--prefilter-stride 1` disables that filter
for control runs at exact offsets provided by `--offsets-file`.

The complete suite also runs unfiltered and 0.2-second controls, archived
encounter replay, comparison and capture integrity checks:

```bash
python validation/run_performance_suite.py --research-root ../OPAS-research/research --baseline-root ../OPAS-baseline --results NEW_RESULT_DIR
```

Use a new directory to retain previous evidence. Final comparison rejects
incomplete/mismatched input records and missing launch coverage. Reproduce the
capture integrity audit with `validation/check_capture_integrity.py`; it checks
snapshot selection, trajectory, horizon, frozen radii, recorded classifications,
windows and measured production source hashes without an extra propagation run.

`--mode workers --workers 1` and `--workers 4` measure a four-launch batch,
including process startup, and record compute time inside workers separately
from wall time. The application logs mean detector time and summed compute
seconds across workers; the sum can exceed elapsed wall time because workers
run concurrently. Phase times and counters identify where requests spend time.
The optional `opas_math` module being available does not mean it accelerates
the window scanner: that path uses NumPy and SGP4. Startup now identifies the
SGP4 acceleration mode separately from optional helper availability.

## Evidence map

| File or directory | Contents |
| --- | --- |
| `results/performance/live_run/` | Supplied completed screenshot, partial log and extracted counters/hashes; missing fresh catalogue and completed JSON stated explicitly. |
| `benchmark_scanner.py` | Baseline/current search and cProfile harness; frozen research ages, exact launch instants and source hashes. |
| `reference_presets.py` | Separate dense flight reference across an exact launch grid; measured displacement prefilter and direct threshold checks. |
| `replay_capture.py` | Checksum-verified offline request replay. |
| `compare_presets.py`, `check_capture_integrity.py` | Numerical before/after comparison and exact-input/capture audits. |
| `check_preset_resolution.py` | Selected near-threshold 0.2-second pair controls. |
| `backend/batch_prediction.py`, `backend/scan_plan.py` | Exact SGP4 batching, shared Skyfield transforms, fixed geometry and the existing broad-screen expressions. |
| `backend/encounters.py`, `backend/windows.py` | Existing closest-approach refinement and discovery/5-second coverage audit. |
| `backend/evidence.py` | Request input/check/result capture and checksums. |

Agreement concerns sampled launches under the nominal post-ascent model and
existing altitude filter. It is not a proof of continuous launch-time or
physical safety. The supplied 849 clear Windows launch samples cannot be
independently checked without that run's exact catalogue and completed JSON.
