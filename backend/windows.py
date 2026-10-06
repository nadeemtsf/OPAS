"""Discover candidate launch windows, then check their intervening launch times."""
from concurrent.futures import ThreadPoolExecutor
from datetime import timedelta
import logging
from math import ceil, isfinite

log = logging.getLogger('opas')
LAUNCH_STEP_SECONDS = 10
MIN_WINDOW_SECONDS = 15 * 60


def launch_grid(start_dt, end_dt, step_seconds):
    """Exact clock offsets from start, including a clipped final endpoint.

    Launch spacing is independent of the flight's numerical sample spacing.
    Multiplication by an integer index avoids accumulated floating-point drift.
    """
    if not isfinite(step_seconds) or step_seconds <= 0:
        raise ValueError('launch step must be positive and finite')
    seconds = (end_dt - start_dt).total_seconds()
    if seconds < 0:
        return []
    return [start_dt + timedelta(seconds=min(i * step_seconds, seconds))
            for i in range(ceil(seconds / step_seconds) + 1)]


def find_windows(is_obstructed, start_dt, end_dt, workers=4,
                 launch_step_seconds=LAUNCH_STEP_SECONDS, check_many=None):
    """Return the five longest >=15-minute spans of checked clear launches.

    A minute-grid discovery pass checks regions around every clear 10-minute
    marker. Every qualifying clear span contains such a marker. Every candidate
    is then checked at launch_step_seconds spacing before selecting the longest
    five. Unsafe samples split runs; endpoints are checked clear launches, with
    no extrapolation into the gap preceding an unsafe or unchecked launch.

    This improves sampled clearance; it does not certify continuous time.
    """
    if (not isinstance(launch_step_seconds, int) or launch_step_seconds <= 0
            or 60 % launch_step_seconds):
        raise ValueError('launch step must be a positive integer divisor of 60 seconds')
    if (end_dt - start_dt).total_seconds() < MIN_WINDOW_SECONDS:
        return []
    times = launch_grid(start_dt, end_dt, 60)
    last = len(times) - 1
    coarse_indices = list(range(0, last + 1, 10))
    if coarse_indices[-1] != last:
        coarse_indices.append(last)
    checked = {}
    windows = []

    with ThreadPoolExecutor(max_workers=workers) as executor:
        def check_all(points):
            missing = [time for time in points if time not in checked]
            states = check_many(missing) if check_many else executor.map(is_obstructed, missing)
            checked.update(zip(missing, states))

        coarse = [times[i] for i in coarse_indices]
        check_all(coarse)
        regions = []
        for index in coarse_indices:
            if checked[times[index]]:
                continue
            lo, hi = max(0, index - 10), min(last, index + 10)
            if regions and lo <= regions[-1][1] + 1:
                regions[-1] = (regions[-1][0], max(hi, regions[-1][1]))
            else:
                regions.append((lo, hi))

        candidates = []

        def candidate(first_index, end_index):
            # A fine-grid run can begin just after the preceding unsafe minute.
            # Include that fringe so refinement can recover the earlier start.
            first = times[max(0, first_index - 1)]
            end = times[end_index]
            if (end - first).total_seconds() >= MIN_WINDOW_SECONDS:
                candidates.append((first, end))

        for lo, hi in regions:
            points = times[lo:hi + 1]
            check_all(points)
            first = None
            for index in range(lo, hi + 1):
                time = times[index]
                if checked[time]:
                    if first is not None:
                        candidate(first, index)
                        first = None
                elif first is None:
                    first = index
            if first is not None:
                candidate(first, hi)

        minute_checks = len(checked)

        def finish(first, last_clear):
            seconds = (last_clear - first).total_seconds()
            if seconds >= MIN_WINDOW_SECONDS:
                windows.append((seconds, {
                    'start': first.isoformat(), 'end': last_clear.isoformat(),
                    'duration_minutes': round(seconds / 60, 2),
                }))

        for first, end in candidates:
            points = launch_grid(first, end, launch_step_seconds)
            check_all(points)
            run_start = last_clear = None
            for time in points:
                if checked[time]:
                    if run_start is not None:
                        finish(run_start, last_clear)
                        run_start = last_clear = None
                else:
                    if run_start is None:
                        run_start = time
                    last_clear = time
            if run_start is not None:
                finish(run_start, last_clear)

    windows.sort(key=lambda w: (-w[0], w[1]['start']))
    log.info('safe-windows | %d minute discovery checks + %d finer checks (%ds); '
             '%d candidates, %d qualifying spans', minute_checks,
             len(checked) - minute_checks, launch_step_seconds,
             len(candidates), len(windows))
    return [window for _, window in windows[:5]]
