# Prediction failure recovery

This revision follows the user's incomplete six-hour, 400 km, 51.6-degree window
request `43b4db87afbc`, starting at `2026-10-06T17:09:47.322041+00:00`.
The supplied diagnostics reported failure on NORAD `69980` before any launch
classification completed. Live MongoDB credentials and the live object's TLE
lines were not available in this workspace.

## Reproduction

[reproduction.json](reproduction.json) records the real archived `69980` TLE at
that request's exact time and flight grid. All 536 post-ascent positions are
non-finite; Skyfield reports SGP4's mean-eccentricity range error. This TLE has
epoch September 20 and yields a valid position at the September 21 snapshot
date. This reproduces the symptom without establishing that the live request
used byte-identical TLE lines or that the satellite physically decayed.

The input is checked into
[`backend/tests/fixtures/stale_prediction.json`](../../../../backend/tests/fixtures/stale_prediction.json).
The fixture identifies the original frozen-catalogue checksum and the fact that
the live TLE was not supplied. The regression test reruns the failure at the
recorded request time; HTTP and stream tests also use the real propagator with
the clock fixed to October 6.

## Recovery behavior

The new targeted refresh command uses Space-Track's GP endpoint, validates
identity and sampled prediction usability, and updates only an existing named
MongoDB object. Missing/decayed records or invalid fresh predictions are retained,
never silently excluded from collision screening. Older epochs and concurrent
updates are rejected. See [runtime recovery instructions](../../RUNTIME_CHECKS.md#recovering-an-invalid-orbital-prediction)
and [Space-Track's API documentation](https://www.space-track.org/documentation).

Focused tests use mocked Space-Track and MongoDB boundaries for refresh behavior,
with real Skyfield propagation. No authenticated Space-Track download or live
MongoDB write was performed; successful recovery on the user's catalogue still
requires running the command locally and repeating the window request.

## Validation records

- [focused_tests.json](focused_tests.json) and its log: the complete backend
  suite, including real API/spawn/SSE execution and the new recovery regressions.
- [archived_pair_replay.json](archived_pair_replay.json) and its log: comparison
  with the original independent ISS, Starlink and SSO encounter minima.
- [manifest.json](manifest.json): source/result hashes, environment, commands,
  test/replay counts and runtime.

The focused suite and pair replay were sequential. Their elapsed times are test
execution times, not full-catalogue API latency or a before/after speedup. There
was no fresh six-hour full-catalogue window reference, frontend code change,
report edit or LaTeX compilation in this revision.

To rerun, with backend development dependencies installed, from the repo root:

```bash
OPENBLAS_NUM_THREADS=1 OMP_NUM_THREADS=1 OPAS_LOG_LEVEL=WARNING python validation/run_focused_tests.py --output /tmp/prediction-focused-tests.json
OPENBLAS_NUM_THREADS=1 OMP_NUM_THREADS=1 python validation/validate_encounters.py --research-root ../OPAS-research/research --output /tmp/prediction-pair-replay.json
```
