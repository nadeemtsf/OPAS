# Runtime diagnostics verification

The request progress and final five-second checks passed **54 backend tests**
in 8.133 seconds and **25 frontend tests**, with a successful
production build and lint. Backend cases exercise real HTTP and spawned scan
workers, clear polar-static controls, prediction/data failures, exact launch
coverage, a new obstruction at a five-second midpoint, exhaustive toy-grid
comparison, request-correlated debug output and stream cancellation.

The fresh archived ISS, Starlink and SSO detector replay found **zero disagreements**
across 451 unsafe pairs and 3,089 nearby clear controls in 80.218
seconds. Six pairs whose archived minima precede the production flight scope
remain excluded. This replay compares with archived independent research minima;
it is not a full-catalogue five-second window-finder validation.

The full six-hour benchmark was not repeated for this revision. Positive window
cases here are controlled tests, not a new real ISS safe-window certificate.

Evidence: [focused tests](focused_tests.json), [test log](focused_tests.log),
[frontend checks](frontend_checks.json), [build log](frontend_build.log),
[archived pair replay](archived_pair_replay.json), [source/environment manifest](manifest.json).

Use [runtime checks](../../RUNTIME_CHECKS.md) for live testing and scope, and
[the report evidence index](../../EVIDENCE.md) for historical measured results.
