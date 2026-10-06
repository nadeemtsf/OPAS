"""Enumerate fine launch instants from a completed exact-minute reference.

Fine points are deliberately unclassified here. Treating them as obstructed
only during this replay enumerates every requested point: the window finder
creates all candidates before fine classification. The production/reference
comparison later requires coverage of every actual production check.
"""
import argparse
from datetime import datetime, timedelta
import hashlib
import json
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]/'backend'))
from windows import find_windows


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--minute-reference', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    reference = json.loads(args.minute_reference.read_text())
    if (reference['status'] != 'complete' or reference['phase'] != 'dense' or
            reference['launch_step_seconds'] != 60):
        raise ValueError('Require a completed exact-minute dense reference.')
    points = reference['launches']
    by_time = {entry['launch_time']: entry for entry in points}
    if len(by_time) != len(points):
        raise ValueError('Duplicate minute reference timestamps.')
    t0 = datetime.fromisoformat(points[0]['launch_time'])-timedelta(seconds=points[0]['offset_s'])
    end = max(datetime.fromisoformat(entry['launch_time']) for entry in points)
    fine = []
    minute_checks = []

    def check(launch):
        key = launch.isoformat()
        if key in by_time:
            minute_checks.append(key)
            return by_time[key]['obstructed']
        offset = (launch-t0).total_seconds()
        if offset % 60 == 0:
            raise ValueError('Incomplete minute reference.')
        fine.append({'launch_time': key, 'offset_s': offset})
        return True

    find_windows(check, t0, end, workers=1, launch_step_seconds=10)
    fine.sort(key=lambda entry: entry['offset_s'])
    report = {'phase': 'sample_plan', 'status': 'complete',
              'scope': 'Enumeration only; no fine safety classifications.',
              'snapshot_sha256': reference['snapshot_sha256'],
              'candidate_count': reference['candidate_count'],
              'launch_step_seconds': 10, 'launch_count': len(fine),
              'planned_minute_checks': len(minute_checks), 'launches': fine,
              'minute_reference': str(args.minute_reference),
              'windows_sha256': hashlib.sha256((Path(__file__).resolve().parents[1]/
                                               'backend/windows.py').read_bytes()).hexdigest()}
    args.output.write_text(json.dumps(report, indent=2)+'\n')
    print(json.dumps({key:value for key,value in report.items() if key != 'launches'}, indent=2))


if __name__ == '__main__':
    main()
