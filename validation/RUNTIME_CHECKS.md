# Runtime checks and request diagnostics

The application now reports what it checked during each window request and
audits every returned span. Use this guide when testing
`fix/refine-close-approaches`; the [report evidence index](EVIDENCE.md) identifies
the earlier research measurements separately.

## Testing in the app

1. Start the backend and frontend as described in the repository README. The
   backend logs its native-math mode, process count, model checking policy and
   each incoming request. Database connection failures are logged explicitly.
2. Select a mission and choose **1 hour (quick test)** for an initial request.
   Window searches are available without first receiving an alert. The UI also
   offers a six-hour test; its default search selection is six hours.
3. Open the browser developer console. Ordinary debris/alert requests log their
   URL, parameters, HTTP result, elapsed time and request ID. Window requests log
   phase changes and the completed verification response.
4. While scanning, the sidebar shows the current phase, elapsed time, screened
   object count, clear/obstructed launch counts, candidate spans, extra five-second
   checks and newly found obstructions. A group's progress is not a global ETA:
   later phases depend on how many candidates discovery finds.
5. Each returned window shows its exact checked start, duration/end, number of
   clear launch checks and maximum gap. Request/model details give the screening
   radius and actual post-ascent flight range. **Download check details** saves
   the diagnostics, window audits and any error as JSON.
6. Match the request ID to the backend log when investigating a result. Mission
   inputs and overlapping actions are locked during a request. **Cancel search**
   clears acceptance of a result and stops further work between check batches;
   predictions already running may take time to finish.

For every launch classification, enable debug logging before starting the API:

```bash
OPAS_LOG_LEVEL=DEBUG python -m uvicorn api:app --reload --host 0.0.0.0 --port 8000
```

PowerShell, from the backend directory:

```powershell
$env:OPAS_LOG_LEVEL = "DEBUG"
python -m uvicorn api:app --reload --host 0.0.0.0 --port 8000
```

`INFO` is the default and logs phase changes plus periodic count updates.
`DEBUG` can produce large logs over long horizons; neither mode logs catalogue
TLE contents or credentials. The backend's per-launch debug lines identify the
request ID, checked UTC instant, phase and classification.
MongoDB heartbeat/topology debug traffic is suppressed; database warnings and
errors remain visible.

## Recovering an invalid orbital prediction

An incomplete search is not evidence that no safe windows exist. A failed SGP4
prediction must not be ignored or converted into a successful empty result.
Errors now include the NORAD ID, launch time and underlying propagation/refinement
cause. Both non-finite positions and explicit Skyfield/SGP4 error messages reject
the window search, including reported errors whose coordinates happen to be finite.

For the observed object `69980`, the archived September 20 TLE reproduces the
October 6 request's failure: SGP4 reports that mean eccentricity is outside its
valid range. This is a reproduction using archived data, not proof that the
live database contained identical TLE lines. Age alone is not a decay diagnosis.

From the backend directory, with the Python environment active:

```powershell
python refresh_catalogue.py --norad-id 69980
```

The existing `.env` must contain `MONGO_URI`, `SPACE_TRACK_USER` and
`SPACE_TRACK_PASS`. The command obtains the latest Space-Track GP record for
that object, checks its identity/TLE lines and predictions, and updates only
that existing document. It retains unrelated metadata, refuses an older epoch,
and detects concurrent changes. Use `--dry-run` to validate without writing;
repeat `--norad-id` to refresh multiple objects.

Default prediction validation spans eight hours at one-minute samples: a
six-hour launch horizon plus two hours of LEO flight. Increase
`--validation-hours` for longer launch horizons/flights. This tests prediction
usability at those samples, not clearance or continuous-time validity. Runtime
checks still verify each modeled flight and its refinement times.

Rerun the window search after a successful refresh. Workers rebuild their
propagators from the request's current TLE lines; a backend restart is not needed
for the data update itself. If another ID fails, refresh that ID as well. Missing
Space-Track records, reported decay, invalid fresh predictions and unavailable
credentials stop the refresh and retain the object. Confirm catalogue status
separately rather than silently excluding it. `python ingest.py` deletes and
repopulates the whole catalogue, so it is not the targeted recovery command.
The archived reproduction and regression/replay results are recorded in
[prediction recovery evidence](results/prediction_recovery/).

## What has to pass before a window is returned

| Check | Behavior |
| --- | --- |
| Orbital data available | Database failures, an empty catalogue and unavailable TLE propagators make the search incomplete. Zero objects in the altitude filter is distinct from an empty whole catalogue and is reported explicitly. |
| Valid predictions | Failed/non-finite satellite predictions or closest-approach refinement cannot count as clear. A window search uses strict error handling and refuses completion. |
| Complete detector output | Every requested launch needs exactly one boolean result. Missing, extra or invalid results reject the search. |
| Initial candidate refinement | Candidate regions are checked at exact 10-second launch offsets using interval encounter refinement during the modeled flight. |
| Additional launch validation | All qualifying spans are checked at 5-second spacing before choosing the five longest. Previously checked timestamps are reused; new midpoints require detector calls. New obstructions split spans, and spans under 15 minutes are dropped. This pass does not extrapolate beyond the original candidate endpoints. |
| Returned-span audit | Both endpoints are clear; duration is at least 900 seconds; endpoints lie within the requested horizon; every required launch sample is present; no checked obstruction lies inside; maximum sampled gap is at most five seconds. |
| Browser acceptance | The frontend requires a completed response, consistent launch counts and a passing audit for each window. An error, truncated stream, missing audit or inconsistent duration/coverage prevents window selection. |
| Current orbital elements | The satellite cache matches both TLE lines. A changed second line rebuilds the propagator instead of reusing an older orbit. |

The guards use the production detector and its existing physical assumptions.
They are **not an independent dense numerical reference**. Launches between
five-second samples remain unchecked, and flight interpolation/refinement has
its existing engineering assumptions. The altitude filter, post-ascent scope,
TLE prediction errors and simplified vehicle model still limit the meaning of
clearance. The separate `/alert` risk model is not certified by these checks.

## API and diagnostic fields

`GET /safe-windows` returns the final JSON response, including `diagnostics` and
each window's `verification`. `GET /safe-windows/stream` accepts the same query
parameters and streams the same search:

- `progress`: phase, counters, model metadata and elapsed time as they become
  available. Heartbeat comments every ten seconds keep the connection active
  during slower prediction work.
- `result`: the completed response, including all returned-window audits.
- `error`: an incomplete request with its request ID and explanation. It is
  not a completed empty search, even when the already opened stream has HTTP 200.

All API responses expose `X-Request-ID`. Diagnostic JSON includes the exact UTC
horizon, request parameters, selected-catalogue SHA-256, altitude filter,
screening radius range, TLE-age summary, trajectory waypoint count, actual flight
start/end, worker count, launch classification counts, additional-validation
counts and per-window audit flags. The catalogue fingerprint identifies the
selected request data, not the uncompressed archived research snapshot checksum.

No positive returned window means no qualifying span passed these sampled
checks; it does not mean every checked launch was obstructed. No returned-window
case is validated by merely receiving a successful empty result.

## Verification and performance

Focused checks cover real HTTP/scanner/spawn execution, progress/result/error
events, disconnected-stream cancellation, invalid inputs, incomplete detector
output, a planted obstruction between clear ten-second launches, exhaustive
five-second toy enumeration, later candidates after the five-window limit,
window coverage audits and TLE cache updates. Frontend tests cover fragmented
streams, truncated/error responses and acceptance guards, alongside the existing
exact UTC timestamp tests.

Recorded checks for this change are in [runtime_diagnostics](results/runtime_diagnostics/).
The archived pair replay is a detector comparison with existing independent
research minima, not a fresh full-catalogue five-second window reference. The
full six-hour numerical benchmark documented in the research report was not
repeated for this revision. Its counts and timings retain their earlier versions.

Final five-second checking adds work when qualifying spans exist; it adds no
launch checks when none qualify after ten-second refinement. Diagnostic
collection, batching, streaming and stricter error handling can also change
runtime. The earlier 18.44-minute timing is not a latency claim for this revision.
