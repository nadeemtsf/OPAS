"""Discover candidate launch windows, then check their intervening launch times."""
from concurrent.futures import ThreadPoolExecutor
from datetime import timedelta
import logging
from math import ceil, isfinite
import time

log = logging.getLogger('opas')
LAUNCH_STEP_SECONDS = 10
MIN_WINDOW_SECONDS = 15 * 60


class WindowVerificationError(RuntimeError):
    """Incomplete or invalid checks cannot establish a clear window."""


def verify_window_coverage(window, checked, horizon_start, horizon_end, step_seconds):
    """Audit exact endpoints and every required launch sample before returning."""
    first = window['start']
    last = window['end']
    seconds = (last - first).total_seconds()
    if not horizon_start <= first < last <= horizon_end or seconds < MIN_WINDOW_SECONDS:
        raise WindowVerificationError('A window failed its endpoint or duration checks.')
    required = launch_grid(first, last, step_seconds)
    if any(point not in checked for point in required):
        raise WindowVerificationError('A window is missing required launch checks.')
    samples = sorted(point for point in checked if first <= point <= last)
    if any(checked[point] is not False for point in samples):
        raise WindowVerificationError('A window contains an obstructed or invalid launch check.')
    maximum_gap = max((b-a).total_seconds() for a, b in zip(samples, samples[1:]))
    if maximum_gap > step_seconds:
        raise WindowVerificationError('A window contains an unchecked launch-time gap.')
    return {'status': 'passed', 'checked_launches': len(samples),
            'max_launch_gap_seconds': maximum_gap, 'unsafe_launches': 0,
            'duration_seconds': seconds,
            'endpoints_checked': True, 'horizon_checked': True,
            'duration_checked': True, 'coverage_checked': True}


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
                 launch_step_seconds=LAUNCH_STEP_SECONDS, check_many=None,
                 verification_step_seconds=None, progress=None, diagnostics=None):
    """Return the five longest >=15-minute spans of checked clear launches.

    A minute-grid discovery pass checks regions around every clear 10-minute
    marker. Every qualifying clear span contains such a marker. Every candidate
    is then checked at launch_step_seconds spacing before selecting the longest
    five. Unsafe samples split runs; endpoints are checked clear launches, with
    no extrapolation into the gap preceding an unsafe or unchecked launch.

    An optional finer final pass splits qualifying spans at new obstructions.
    Every returned span then passes a coverage audit. These checks use the same
    detector, not an independent reference, and do not certify continuous time.
    """
    if (not isinstance(launch_step_seconds, int) or launch_step_seconds <= 0
            or 60 % launch_step_seconds):
        raise ValueError('launch step must be a positive integer divisor of 60 seconds')
    if verification_step_seconds is not None and (
            not isinstance(verification_step_seconds, int) or verification_step_seconds <= 0
            or launch_step_seconds % verification_step_seconds):
        raise ValueError('verification step must divide the launch step')
    started = time.perf_counter()
    metrics = {'checked_launch_samples': 0, 'clear_launch_samples': 0,
               'obstructed_launch_samples': 0, 'candidate_spans': 0,
               'qualifying_spans': 0, 'returned_windows': 0,
               'launch_step_seconds': launch_step_seconds,
               'verification_step_seconds': verification_step_seconds or launch_step_seconds,
               'extra_validation_checks': 0, 'validation_obstructed_samples': 0,
               'independent_reference': False}

    def report(phase, **details):
        metrics.update(phase=phase, elapsed_seconds=round(time.perf_counter()-started, 3), **details)
        if diagnostics is not None:
            diagnostics.update(metrics)
        if progress:
            progress(dict(metrics))

    if (end_dt - start_dt).total_seconds() < MIN_WINDOW_SECONDS:
        report('complete', status='complete', window_checks=[])
        return []
    times = launch_grid(start_dt, end_dt, 60)
    last = len(times) - 1
    coarse_indices = list(range(0, last + 1, 10))
    if coarse_indices[-1] != last:
        coarse_indices.append(last)
    checked = {}
    windows = []

    with ThreadPoolExecutor(max_workers=workers) as executor:
        def check_all(points, phase):
            missing = list(dict.fromkeys(point for point in points if point not in checked))
            completed = 0
            report(phase, phase_completed=0, phase_total=len(missing))
            # Bound queued work so progress and disconnected requests are handled
            # between small batches rather than after a whole multi-day scan.
            for offset in range(0, len(missing), 16):
                batch = missing[offset:offset+16]
                states = iter(check_many(batch) if check_many else executor.map(is_obstructed, batch))
                for point in batch:
                    try:
                        state = next(states)
                    except StopIteration as error:
                        raise WindowVerificationError('The detector returned incomplete launch checks.') from error
                    if type(state) is not bool:
                        raise WindowVerificationError('The detector returned an invalid launch classification.')
                    checked[point] = state
                    metrics['checked_launch_samples'] += 1
                    metrics['obstructed_launch_samples' if state else 'clear_launch_samples'] += 1
                    if phase == 'window_validation':
                        metrics['extra_validation_checks'] += 1
                        metrics['validation_obstructed_samples'] += int(state)
                    completed += 1
                    log.debug('request=%s | safe-windows launch=%s phase=%s classification=%s',
                              (diagnostics or {}).get('request_id', '-'),
                              point.isoformat(), phase, 'obstructed' if state else 'clear')
                sentinel = object()
                if next(states, sentinel) is not sentinel:
                    raise WindowVerificationError('The detector returned extra launch classifications.')
                report(phase, phase_completed=completed, phase_total=len(missing),
                       last_launch_checked=batch[-1].isoformat())

        coarse = [times[i] for i in coarse_indices]
        check_all(coarse, 'coarse_discovery')
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
            check_all(points, 'minute_discovery')
            first = None
            for index in range(lo, hi + 1):
                point = times[index]
                if checked[point]:
                    if first is not None:
                        candidate(first, index)
                        first = None
                elif first is None:
                    first = index
            if first is not None:
                candidate(first, hi)

        minute_checks = len(checked)
        report('fine_verification', candidate_spans=len(candidates))

        def finish(first, last_clear, destination):
            seconds = (last_clear - first).total_seconds()
            if seconds >= MIN_WINDOW_SECONDS:
                destination.append((seconds, {'start': first, 'end': last_clear}))

        def split_runs(points, destination):
            run_start = last_clear = None
            for point in points:
                if checked[point]:
                    if run_start is not None:
                        finish(run_start, last_clear, destination)
                        run_start = last_clear = None
                else:
                    if run_start is None:
                        run_start = point
                    last_clear = point
            if run_start is not None:
                finish(run_start, last_clear, destination)

        for first, end in candidates:
            points = launch_grid(first, end, launch_step_seconds)
            check_all(points, 'fine_verification')
            split_runs(points, windows)

        fine_checks = len(checked) - minute_checks
        if verification_step_seconds is not None:
            verified = []
            report('window_validation', qualifying_spans=len(windows))
            for _, window in windows:
                points = launch_grid(window['start'], window['end'], verification_step_seconds)
                check_all(points, 'window_validation')
                split_runs(points, verified)
            windows = verified

    windows.sort(key=lambda w: (-w[0], w[1]['start']))
    result, audits = [], []
    for seconds, window in windows[:5]:
        audit = verify_window_coverage(window, checked, start_dt, end_dt,
                                       verification_step_seconds or launch_step_seconds)
        item = {'start': window['start'].isoformat(), 'end': window['end'].isoformat(),
                'duration_minutes': round(seconds/60, 2)}
        audits.append({'start': item['start'], 'end': item['end'], **audit})
        if diagnostics is not None:
            item['verification'] = audit
        result.append(item)
    log.info('safe-windows | %d minute discovery checks + %d finer checks (%ds); '
             '%d candidates, %d qualifying spans; %d additional validation checks', minute_checks,
             fine_checks, launch_step_seconds,
             len(candidates), len(windows), metrics['extra_validation_checks'])
    report('complete', status='complete', minute_discovery_checks=minute_checks,
           fine_verification_checks=fine_checks, qualifying_spans=len(windows),
           returned_windows=len(result), window_checks=audits)
    return result
