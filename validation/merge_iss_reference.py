"""Merge separately completed minute/fine independent distance calculations."""
import argparse
import json
from pathlib import Path


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--minute', type=Path, required=True)
    parser.add_argument('--fine', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    components = [json.loads(path.read_text()) for path in (args.minute, args.fine)]
    for component in components:
        if component['status'] != 'complete' or component['phase'] != 'dense':
            raise ValueError('Both dense components must be complete.')
    for key in ['snapshot_sha256', 'candidate_count', 'dense_flight_step_s',
                'dense_scope_start_s', 'source_sha256']:
        if components[0][key] != components[1][key]:
            raise ValueError(f'Dense components disagree on {key}.')
    launches = [entry for component in components for entry in component['launches']]
    if len({entry['launch_time'] for entry in launches}) != len(launches):
        raise ValueError('Dense components contain duplicate launches.')
    launches.sort(key=lambda entry: entry['offset_s'])
    report = {key:components[0][key] for key in ['snapshot_sha256', 'candidate_count',
              'dense_flight_step_s', 'dense_scope_start_s', 'source_sha256', 'numerical_caveat']}
    report.update(phase='dense', status='complete', launch_step_seconds=10,
                  scope='Independent minute grid plus all enumerated fine candidate checks; frozen post-ascent model.',
                  launch_count=len(launches), launches=launches,
                  elapsed_seconds=round(sum(component['elapsed_seconds'] for component in components),3),
                  obstructed_launches=sum(entry['obstructed'] for entry in launches),
                  components=[{key:value for key,value in component.items() if key != 'launches'}
                              for component in components])
    args.output.write_text(json.dumps(report, indent=2)+'\n')
    print(json.dumps({'launch_count':len(launches), 'obstructed_launches':report['obstructed_launches'],
                      'elapsed_seconds':report['elapsed_seconds']}, indent=2))


if __name__ == '__main__':
    main()
