# OPAS scanner changes ready for review

The scanner now refines close approaches between flight waypoints and checks candidate launch times every 10 seconds. Unsafe samples split windows, both endpoints are checked clear, and all candidates are evaluated before selecting the five longest spans of at least 15 minutes.

The measured scanner version is local commit `19548cdbc9486f1b990fd2ad881544e6482d02d3` on `fix/refine-close-approaches`, based on `fix/scanner-accuracy` at `50fb28f61a2fef1a1f29ea1d92e2089333fb24cc`. Its staged sources match every checksum in the [six-hour verification manifest](results/rerun_20261006T115728Z/manifest.json).

The following integration fixes preserve that interval and launch-grid algorithm:

- An unavailable TLE propagator cannot be substituted with the object's static snapshot or excluded by the static longitude filter. Unavailable construction in the parent or a spawned worker raises a verification error; `/safe-windows` returns HTTP 503. The UI displays an incomplete search separately from a verified result with no windows.
- Clicking a window preserves the exact checked ISO timestamp, including seconds and sub-millisecond precision. For example, `12:26:54.811735` is no longer converted to `12:26:00`. The launch-time field represents UTC, as its label states, across browser timezones. Editing the field clears the selected checked timestamp.

| Verification | Result |
| --- | --- |
| Final backend suite, including real HTTP/scanner/spawn integration | 38 passed in 6.789 s |
| Frontend timestamp tests across UTC, Jerusalem and New York | 9 passed |
| Frontend production build | Passed |
| Frontend lint | Passed |
| Fresh archived ISS, Starlink and SSO replay on final detector | 451 unsafe pairs detected; 3089 nearby clear pairs retained; zero disagreements; 83.949 s |
| Frozen ISS snapshot compatibility | All 11,997 orbital objects construct; new failure guards are not reached |

The earlier full six-hour run verified 691/691 production classifications against 736 independent launch samples, with 0/565 observed false-safe samples. It took 18.44 minutes for the instrumented production search and 15.82 minutes for the independent calculation. Finer sampling exposed 52 unsafe launches inside the two apparent minute-grid windows, leaving no qualifying 15-minute ISS window in that snapshot. See [report.md](results/rerun_20261006T115728Z/report.md).

The full six-hour run was performed on the measured scanner commit above, before the integration fixes. Its results retain their original source checksums. The final integration suite and archived-pair replay were rerun afterward; their sources and results are in [the handoff manifest](results/handoff_20261006T140107Z/manifest.json). Interval mathematics, flight generation and window discovery remain byte-identical to the measured version. The full search was not retimed after the integration fixes.

The numerical agreement covers sampled launch times in the frozen post-ascent model. Continuous launch-time clearance, ascent, objects outside the altitude filter and physical trajectory/propagation uncertainty remain outside that validation. The measured search is still expensive for a synchronous API request; this patch does not establish faster production latency.

Reproduce the focused checks with `pip install -r backend/requirements-dev.txt`, then run `python validation/run_focused_tests.py --output /tmp/opas-focused-tests.json`. Run `npm ci`, `npm test`, `npm run build` and `npm run lint` in `frontend/`. Detailed independent replay commands are in [README.md](README.md).
