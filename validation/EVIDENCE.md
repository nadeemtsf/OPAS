# Report evidence index

Use this index to locate the records behind the revised **OPAS safe-window
scanner audit**, dated 6 October 2026. Report descriptions and table numbers
map to the exact files below; long filenames do not need to be repeated in the
paper. See [the validation guide](README.md) for reproduction commands and
[the handoff](HANDOFF.md) for the final implementation checks.

The revised [Overleaf source](opas_audit_report.tex) is included without a newly
compiled PDF. [Runtime checks](RUNTIME_CHECKS.md) describe the later application
diagnostics and 5-second final validation; the historical tables below retain
their measured code versions.

## Code versions and where to look

| Stage | Code version | Evidence location |
| --- | --- | --- |
| Original scanner | `a89f2e726f08dad71498a091b60d06a80267f07f` | Historical research checkout below |
| Corrected four-fix research and archived references | Research checkout `8fef312648e542060256b94fef2cbce49be4e161`; production counterpart `fix/scanner-accuracy` at `50fb28f61a2fef1a1f29ea1d92e2089333fb24cc` | `research/` on `research-branch` |
| Full follow-up ISS numerical search | `19548cdbc9486f1b990fd2ad881544e6482d02d3` | `validation/results/rerun_20261006T115728Z/` |
| Final integration checks and fresh pair replay | `9637985` | `validation/results/handoff_20261006T140107Z/` |
| Duration recount for the revised report | Derived from the archived research distances; no new propagation run | `validation/results/report_evidence/historical_run_recount.json` |

The historical links below pin the research checkout instead of following a
moving branch. Follow-up records and this index belong to
`fix/refine-close-approaches`; they are not evidence for the repository's
default branch. Read the guides and follow-up files from a checkout of this
branch containing them; the historical links identify their own code versions.

## Frozen input

The launch horizon is `2026-09-21T08:52:54.811735+00:00` through
`2026-09-21T14:52:54.811735+00:00`. The collection contains 32,517 objects;
the follow-up ISS filter selects 11,997.

- [Snapshot metadata](https://github.com/nadeemtsf/OPAS/blob/8fef312648e542060256b94fef2cbce49be4e161/research/data/snapshot_meta.json): `research/data/snapshot_meta.json`.
- [Compressed catalogue](https://github.com/nadeemtsf/OPAS/blob/8fef312648e542060256b94fef2cbce49be4e161/research/data/debris_snapshot_20260921T085254Z.jsonl.gz): `research/data/debris_snapshot_20260921T085254Z.jsonl.gz`.
- SHA-256 of the **uncompressed** snapshot: `c13469e0cee49549504c9de7e45388c926e32ebe5c3b3ec6ccb81855838b1fa8`.

## Historical report results

These paths are relative to `research/results/` in the pinned research checkout.
The [historical inventory](https://github.com/nadeemtsf/OPAS/blob/8fef312648e542060256b94fef2cbce49be4e161/research/results/README.md)
also explains the producing scripts and invalidated runs.

| Report result | Exact evidence files |
| --- | --- |
| Table 1: original returned windows and boundary defect | [baseline_20260921T090905Z.json](https://github.com/nadeemtsf/OPAS/blob/8fef312648e542060256b94fef2cbce49be4e161/research/results/baseline_20260921T090905Z.json) |
| Table 1: original sampled false-safe rates | [compare_iss_20260922T070022Z.json](https://github.com/nadeemtsf/OPAS/blob/8fef312648e542060256b94fef2cbce49be4e161/research/results/compare_iss_20260922T070022Z.json), [compare_starlink_20260922T071627Z.json](https://github.com/nadeemtsf/OPAS/blob/8fef312648e542060256b94fef2cbce49be4e161/research/results/compare_starlink_20260922T071627Z.json), [compare_sso_20260922T072131Z.json](https://github.com/nadeemtsf/OPAS/blob/8fef312648e542060256b94fef2cbce49be4e161/research/results/compare_sso_20260922T072131Z.json), [compare_geo_20260922T073520Z.json](https://github.com/nadeemtsf/OPAS/blob/8fef312648e542060256b94fef2cbce49be4e161/research/results/compare_geo_20260922T073520Z.json) |
| Sampling sweep: 24 inner intervals produce no ISS, Starlink or SSO windows at the tested coarse steps | [sweep_iss_20260928T192528Z.jsonl](https://github.com/nadeemtsf/OPAS/blob/8fef312648e542060256b94fef2cbce49be4e161/research/results/sweep_iss_20260928T192528Z.jsonl), [sweep_starlink_20260928T190843Z.jsonl](https://github.com/nadeemtsf/OPAS/blob/8fef312648e542060256b94fef2cbce49be4e161/research/results/sweep_starlink_20260928T190843Z.jsonl), [sweep_sso_20260928T185956Z.jsonl](https://github.com/nadeemtsf/OPAS/blob/8fef312648e542060256b94fef2cbce49be4e161/research/results/sweep_sso_20260928T185956Z.jsonl) |
| Table 2: corrected four-fix windows, 5/52 ISS and 4/19 Starlink unsafe samples | [compare_fixed_iss_20260928T185703Z.json](https://github.com/nadeemtsf/OPAS/blob/8fef312648e542060256b94fef2cbce49be4e161/research/results/compare_fixed_iss_20260928T185703Z.json), [compare_fixed_starlink_20260928T185705Z.json](https://github.com/nadeemtsf/OPAS/blob/8fef312648e542060256b94fef2cbce49be4e161/research/results/compare_fixed_starlink_20260928T185705Z.json) |
| Four-fix scanner raw output, including the SSO zero-window case | [fixed_iss_20260928T125736Z.json](https://github.com/nadeemtsf/OPAS/blob/8fef312648e542060256b94fef2cbce49be4e161/research/results/fixed_iss_20260928T125736Z.json), [fixed_starlink_20260928T124617Z.json](https://github.com/nadeemtsf/OPAS/blob/8fef312648e542060256b94fef2cbce49be4e161/research/results/fixed_starlink_20260928T124617Z.json), [fixed_sso_20260928T123422Z.json](https://github.com/nadeemtsf/OPAS/blob/8fef312648e542060256b94fef2cbce49be4e161/research/results/fixed_sso_20260928T123422Z.json) |
| Residual waypoint misses: five ISS and five Starlink object-launch pairs | [prove_sampling_gap_iss_20260928T185708Z.json](https://github.com/nadeemtsf/OPAS/blob/8fef312648e542060256b94fef2cbce49be4e161/research/results/prove_sampling_gap_iss_20260928T185708Z.json), [prove_sampling_gap_starlink_20260928T185711Z.json](https://github.com/nadeemtsf/OPAS/blob/8fef312648e542060256b94fef2cbce49be4e161/research/results/prove_sampling_gap_starlink_20260928T185711Z.json) |

The dense reference archives are:

| Preset | Metadata | Stored distances and launch offsets |
| --- | --- | --- |
| ISS | [reference_iss_20260921T102002Z.json](https://github.com/nadeemtsf/OPAS/blob/8fef312648e542060256b94fef2cbce49be4e161/research/results/reference_iss_20260921T102002Z.json) | [reference_iss_20260921T102002Z.npz](https://github.com/nadeemtsf/OPAS/blob/8fef312648e542060256b94fef2cbce49be4e161/research/results/reference_iss_20260921T102002Z.npz) |
| Starlink | [reference_starlink_20260922T071313Z.json](https://github.com/nadeemtsf/OPAS/blob/8fef312648e542060256b94fef2cbce49be4e161/research/results/reference_starlink_20260922T071313Z.json) | [reference_starlink_20260922T071313Z.npz](https://github.com/nadeemtsf/OPAS/blob/8fef312648e542060256b94fef2cbce49be4e161/research/results/reference_starlink_20260922T071313Z.npz) |
| SSO | [reference_sso_20260922T072024Z.json](https://github.com/nadeemtsf/OPAS/blob/8fef312648e542060256b94fef2cbce49be4e161/research/results/reference_sso_20260922T072024Z.json) | [reference_sso_20260922T072024Z.npz](https://github.com/nadeemtsf/OPAS/blob/8fef312648e542060256b94fef2cbce49be4e161/research/results/reference_sso_20260922T072024Z.npz) |
| GEO control | [reference_geo_20260922T073419Z.json](https://github.com/nadeemtsf/OPAS/blob/8fef312648e542060256b94fef2cbce49be4e161/research/results/reference_geo_20260922T073419Z.json) | [reference_geo_20260922T073419Z.npz](https://github.com/nadeemtsf/OPAS/blob/8fef312648e542060256b94fef2cbce49be4e161/research/results/reference_geo_20260922T073419Z.npz) |

### Table 3: corrected duration recount

Use [historical_run_recount.json](results/report_evidence/historical_run_recount.json)
for the saved endpoint-span recount and its input/method details. It preserves
the already computed recount; publishing this record did not rerun propagation.
The original enumeration added one minute to `last offset - first offset`.
Its five ISS runs labelled 15–19 minutes contain 15–19 samples; only **two**
have endpoints at least 15 minutes apart. The longest endpoint spans are
18.0014 minutes for ISS, 13.0003 for Starlink and 4.9997 for SSO.

The historical inventory and enumeration script retain the older duration
convention. Use this recount for Table 3 rather than copying their five-run
claim. These are sampled clear runs, not continuous clearance certificates.
Research outputs under `_stale_unfrozen_age/` remain invalidated and must not
be used for the report's corrected four-fix results.

## Follow-up ISS search and supplementary checks

The following files are in `validation/results/rerun_20261006T115728Z/`.

| Report result | Exact evidence |
| --- | --- |
| Table 4: 691/691 agreement, 0/565 observed false-safe launch samples, no qualifying window | [summary.json](results/rerun_20261006T115728Z/summary.json); individual production checks in [iss_search.json](results/rerun_20261006T115728Z/iss_search.json), matched independent checks in [iss_reference.json](results/rerun_20261006T115728Z/iss_reference.json) |
| Independent coverage: 361 minute launches and 375 finer launches | [iss_minute_reference.json](results/rerun_20261006T115728Z/iss_minute_reference.json), [iss_fine_reference.json](results/rerun_20261006T115728Z/iss_fine_reference.json); requested extra timestamps in [fine_plan.json](results/rerun_20261006T115728Z/fine_plan.json) |
| Table 5: 52 unsafe intervening launches among 280 checks inside the 33- and 23-minute apparent spans | [launch_sampling.json](results/rerun_20261006T115728Z/launch_sampling.json), together with the minute and merged references above |
| Numerical resolution: six selected ISS pairs checked at approximately 0.2 seconds | [resolution_control.json](results/rerun_20261006T115728Z/resolution_control.json) |
| Measured search/reference runtime, environment, source hashes and recovery provenance | [manifest.json](results/rerun_20261006T115728Z/manifest.json), [search_phase_runtime.json](results/rerun_20261006T115728Z/search_phase_runtime.json), [report.md](results/rerun_20261006T115728Z/report.md) |

The minute-grid spans were generated by the new independent reference; they
are not the historical four-fix scanner's returned windows. The unsafe
fraction inside them is separate from the final scanner's false-safe rate.

## Final integration evidence

These files are in `validation/results/handoff_20261006T140107Z/`.

| Report result | Exact evidence |
| --- | --- |
| Final detector replay: 451 unsafe pairs detected and 3,089 nearby clear controls retained, zero disagreements | [archived_pair_replay.json](results/handoff_20261006T140107Z/archived_pair_replay.json); per-preset counts and six scope exclusions are recorded here |
| Backend: 38 tests passed in 6.789 seconds | [focused_tests.json](results/handoff_20261006T140107Z/focused_tests.json), [focused_tests.log](results/handoff_20261006T140107Z/focused_tests.log) |
| Frontend: nine timestamp tests, successful build and lint | [frontend_tests.xml](results/handoff_20261006T140107Z/frontend_tests.xml), [frontend_build.log](results/handoff_20261006T140107Z/frontend_build.log), [frontend_lint.log](results/handoff_20261006T140107Z/frontend_lint.log) |
| All 11,997 ISS objects construct; encounter, window and vehicle modules unchanged | [snapshot_compatibility.json](results/handoff_20261006T140107Z/snapshot_compatibility.json) |
| Final environment, commands, source and artifact checksums | [manifest.json](results/handoff_20261006T140107Z/manifest.json) |

The full six-hour numerical search preceded these integration changes and was
not repeated or retimed afterward. Pair replay is not a full Starlink or SSO
window search. All numerical agreement concerns sampled launches in the frozen
post-ascent model; it does not certify intervening launch times, ascent or
physical launch safety. The report's literature claims have their own
bibliographic citations and are not established by these result files.
