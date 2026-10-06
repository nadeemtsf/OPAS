"""Compare complete classifications by exact launch timestamp, with coverage checks."""
import argparse
from datetime import datetime, timedelta
import json
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]/'backend'))
from windows import find_windows, launch_grid


def unique_launches(report):
    entries = report['launches']
    result = {entry['launch_time']: entry for entry in entries}
    if len(result) != len(entries):
        raise ValueError('Duplicate launch timestamps.')
    if any(type(entry.get('obstructed')) is not bool for entry in entries):
        raise ValueError('Every launch must have a boolean classification.')
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--production', type=Path, required=True)
    parser.add_argument('--dense', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    production, dense = [json.loads(path.read_text()) for path in (args.production, args.dense)]
    if any(report['status'] != 'complete' for report in [production, dense]):
        raise ValueError('Both reports must be complete.')
    if production['phase'] != 'search' or dense['phase'] != 'dense':
        raise ValueError('Expected actual production search and independent dense calculation.')
    for key in ['snapshot_sha256', 'candidate_count', 'source_sha256']:
        if production[key] != dense[key]:
            raise ValueError(f'Reports disagree on {key}.')
    p, d = unique_launches(production), unique_launches(dense)
    missing = sorted(p.keys()-d.keys())
    if missing:
        raise ValueError(f'{len(missing)} production launches lack independent verification.')
    false_safe = [d[key] for key,entry in p.items() if not entry['obstructed'] and d[key]['obstructed']]
    false_alarm = [d[key] for key,entry in p.items() if entry['obstructed'] and not d[key]['obstructed']]
    clear_count = sum(not entry['obstructed'] for entry in p.values())
    first = min(p.values(), key=lambda entry: entry['offset_s'])
    t0 = datetime.fromisoformat(first['launch_time'])-timedelta(seconds=first['offset_s'])
    end = max(datetime.fromisoformat(entry['launch_time']) for entry in p.values())

    def conservatively_obstructed(launch):
        key = launch.isoformat()
        return key not in p or p[key]['obstructed'] or d[key]['obstructed']

    verified_windows = find_windows(conservatively_obstructed, t0, end, workers=1,
                                   launch_step_seconds=production['launch_step_seconds'])
    returned_window_checks = []
    for window in production['returned_windows']:
        points = launch_grid(datetime.fromisoformat(window['start']), datetime.fromisoformat(window['end']),
                             production['launch_step_seconds'])
        entries = [p.get(point.isoformat()) for point in points]
        if not entries or any(entry is None for entry in entries):
            raise ValueError('Returned window includes unchecked grid launches.')
        unsafe = [point.isoformat() for point in points if d[point.isoformat()]['obstructed']]
        returned_window_checks.append({'window':window, 'checked_samples':len(points),
                                       'independently_unsafe_samples':unsafe})
    report = {
        'status':'complete', 'snapshot_sha256':production['snapshot_sha256'],
        'candidate_count':production['candidate_count'], 'checked_launch_samples':len(p),
        'independent_reference_samples':len(d), 'additional_reference_samples':len(d)-len(p),
        'missing_reference_samples':0, 'production_clear_samples':clear_count,
        'production_unsafe_samples':len(p)-clear_count,
        'dense_unsafe_samples':sum(d[key]['obstructed'] for key in p),
        'false_safe_samples':len(false_safe), 'false_alarm_samples':len(false_alarm),
        'observed_false_safe_percentage':100*len(false_safe)/clear_count if clear_count else None,
        'false_safe_cases':false_safe, 'false_alarm_cases':false_alarm,
        'classification_agreement_percentage':100*(len(p)-len(false_safe)-len(false_alarm))/len(p),
        'verified_subset_windows':verified_windows, 'returned_window_checks':returned_window_checks,
        'returned_windows':production['returned_windows'],
        'minute_discovery_checks':production['minute_discovery_checks'], 'finer_checks':production['finer_checks'],
        'production_search_seconds':production['elapsed_seconds'],
        'dense_verification_seconds':dense['elapsed_seconds'],
        'dense_flight_step_s':dense['dense_flight_step_s'], 'dense_scope_start_s':dense['dense_scope_start_s'],
        'production_source':str(args.production), 'independent_source':str(args.dense),
        'scope':'Agreement at sampled launch times in the frozen post-ascent model; no continuous-time or real-world safety certification.'
    }
    args.output.write_text(json.dumps(report, indent=2)+'\n')
    print(json.dumps(report, indent=2))


if __name__ == '__main__':
    main()
