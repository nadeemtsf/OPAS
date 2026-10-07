# Scanner performance and numerical validation

Work stays on `fix/refine-close-approaches`. No PR, merge or LaTeX compilation.
Baseline: `85ff387975254cf827076c6171b61e7204726c3c`.

## 1. Preserve evidence and exact inputs
- [x] Preserve the supplied 40-minute screenshot/log and record their hashes.
- [x] Identify missing inputs: the completed check-details JSON and fresh catalogue were not attached; the older incomplete JSON is a different request.
- [x] Add per-request capture of selected catalogue, frozen screening radii, mission, trajectory, horizon, launch classifications and source/environment hashes.
- [x] Add checksum-verified offline replay; document capture and transfer from Windows.
- [x] Exercise successful and incomplete captures with HTTP tests.

## 2. Measure the existing scanner
- [x] Profile clear and obstructed launches on the checksum-verified research catalogue.
- [x] Separate propagation/frame transforms, interval screening, fixed mission setup and worker overhead.
- [x] Record baseline preset searches and execution environment; run timings sequentially.
- [x] State which findings explain the cloud workload and which remain unmeasured on the user's Windows run.

## 3. Optimize measured costs
- [x] Reuse fixed mission geometry and flight offsets within each worker.
- [x] Batch exact orbital propagation and broad screening where profiling supports it.
- [x] Retain strict SGP4 errors, object ordering, screening radii and narrow interval refinement.
- [x] Test batch equivalence, coordinate transforms, static objects and failure handling.

## 4. Independent comparison
- [x] Compare baseline and optimized classifications at identical launch instants.
- [x] Independently check both clear and obstructed launches on a dense flight grid.
- [x] Check the full launch horizon for missed qualifying spans; explicitly record grid resolution.
- [x] Compare the zero-window catalogue cases with the reference; verify positive endpoints/duration/5-second coverage with planted regressions and inspect threshold-sensitive pairs.
- [x] Record discrepancies, numerical margins and limitations without claiming continuous or physical safety.

## 5. Presets, documentation and publication
- [x] Measure ISS, Starlink and SSO: candidate counts, classifications, windows, runtime and reference agreement.
- [x] Run appropriate backend/frontend checks and archived encounter regressions.
- [x] Update validation guides with commands and a file/evidence map.
- [x] Update report only where these measurements warrant it; never compile it.
- [x] Commit and push to the same branch, verifying the published tree.

Exact reproduction of the fresh Windows run remains dependent on its missing
completed JSON/catalogue. Frozen-catalogue measurements cannot verify that run's
849 clear launch samples.
