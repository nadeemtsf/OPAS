"""Observe atomic search progress and retain the discovery/refinement split.

The last minute-only progress timestamp is the phase boundary. A polling miss
is reported explicitly; the total runtime always comes from the search itself.
"""
import argparse
from datetime import datetime, timezone
import json
from pathlib import Path
import time


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--search', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    last_minute = None
    first_fine = None
    trace = {'status': 'running', 'poll_seconds': .1,
             'observer_started_at_utc': datetime.now(timezone.utc).isoformat()}
    while True:
        try:
            search = json.loads(args.search.read_text())
        except (FileNotFoundError, json.JSONDecodeError):
            time.sleep(.1)
            continue
        points = search['launches']
        has_fine = any(entry['offset_s'] % 60 for entry in points)
        if not has_fine and points:
            last_minute = {'checks': len(points),
                           'elapsed_seconds': search['elapsed_seconds_so_far']}
        elif has_fine and first_fine is None:
            first_fine = {'completed_checks': len(points),
                          'elapsed_seconds': search['elapsed_seconds_so_far']}
            trace.update(last_minute_only_progress=last_minute,
                         first_fine_progress=first_fine)
            args.output.write_text(json.dumps(trace, indent=2)+'\n')
        if search['status'] == 'complete':
            exact_boundary = (last_minute is not None and
                              last_minute['checks'] == search['minute_discovery_checks'])
            trace.update(status='complete', phase_boundary_observed=exact_boundary,
                         total_seconds=search['elapsed_seconds'],
                         minute_discovery_checks=search['minute_discovery_checks'],
                         finer_checks=search['finer_checks'])
            if exact_boundary:
                trace['minute_discovery_seconds'] = last_minute['elapsed_seconds']
                trace['finer_checks_seconds'] = round(search['elapsed_seconds']-
                                                     last_minute['elapsed_seconds'], 3)
            else:
                trace['timing_caveat'] = 'Observer did not capture the final minute-only update; no phase durations inferred.'
            args.output.write_text(json.dumps(trace, indent=2)+'\n')
            return
        time.sleep(.1)


if __name__ == '__main__':
    main()
