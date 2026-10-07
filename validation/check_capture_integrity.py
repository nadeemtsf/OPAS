"""Verify preserved preset inputs, checks and source against their measurements."""
import argparse
from datetime import datetime
import gzip
import hashlib
import json
import os
from pathlib import Path
import sys

from replay_capture import load_capture


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--research-root', type=Path, required=True)
    parser.add_argument('--results', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    backend = Path(__file__).resolve().parents[1]/'backend'
    os.environ['MONGO_URI'] = 'mongodb://localhost:1/?serverSelectionTimeoutMS=1'
    sys.path.insert(0, str(backend))
    from orbital import generate_trajectory
    from proximity import screening_radius_km
    from datetime import timedelta
    meta = json.loads((args.research_root/'data/snapshot_meta.json').read_text())
    raw = gzip.decompress((args.research_root/'data'/meta['file']).read_bytes())
    if hashlib.sha256(raw).hexdigest() != meta['sha256_uncompressed']:
        raise ValueError('Research snapshot checksum mismatch.')
    catalogue = [json.loads(line) for line in raw.splitlines()]
    result = {'status': 'complete', 'scope': 'Capture integrity and matching recorded inputs/checks; not an additional propagation rerun.', 'presets': {}}
    for preset in ['iss', 'starlink', 'sso']:
        report = json.loads((args.results/f'optimized_{preset}.json').read_text())
        directory = args.results/report['capture_directory']
        inputs = load_capture(directory)
        parameters = report['parameters']
        alt = parameters['alt_km']
        docs = [d for d in catalogue if alt-100 <= d['altitude_km'] <= alt+100]
        if docs != inputs['catalogue']:
            raise ValueError(f'{preset}: selected catalogue mismatch.')
        if inputs['search_start_utc'] != report['t0'] or report['snapshot_sha256'] != meta['sha256_uncompressed']:
            raise ValueError(f'{preset}: horizon/snapshot mismatch.')
        expected_params = dict(target_lat=parameters['lat'], target_lon=parameters['lon'],
                               target_alt=alt, inclination=parameters['inclination'],
                               search_hours=parameters['hours'])
        if inputs['parameters'] != expected_params:
            raise ValueError(f'{preset}: mission mismatch.')
        start = datetime.fromisoformat(report['t0'])
        if inputs['search_end_utc'] != (start+timedelta(hours=parameters['hours'])).isoformat():
            raise ValueError(f'{preset}: end mismatch.')
        trajectory = generate_trajectory(parameters['lat'], parameters['lon'], alt, parameters['inclination'])
        if inputs['trajectory'] != trajectory:
            raise ValueError(f'{preset}: trajectory mismatch.')
        radii = []
        for doc in docs:
            line = doc['tle_line1']; year = int(line[18:20])
            epoch = datetime(year+(1900 if year>=57 else 2000), 1, 1, tzinfo=start.tzinfo)+timedelta(days=float(line[20:32])-1)
            radii.append(screening_radius_km(10, (start-epoch).total_seconds()/86400))
        if radii != inputs['frozen_radii_km']:
            raise ValueError(f'{preset}: frozen radii mismatch.')
        checks = [json.loads(line) for line in (directory/'launches.jsonl').read_text().splitlines()]
        original = {e['launch_time']: e['obstructed'] for e in report['launches']}
        if len(checks) != len(original) or len({e['launch_time'] for e in checks}) != len(checks) or any(original[e['launch_time']] != e['obstructed'] for e in checks):
            raise ValueError(f'{preset}: classification mismatch.')
        captured_result = json.loads((directory/'result.json').read_text())
        if captured_result['status'] != 'complete' or captured_result['windows'] != report['returned_windows']:
            raise ValueError(f'{preset}: result mismatch.')
        for name, expected in report['source_sha256'].items():
            if hashlib.sha256((backend/name).read_bytes()).hexdigest() != expected or inputs['source_sha256'][name] != expected:
                raise ValueError(f'{preset}: measured production source changed: {name}')
        result['presets'][preset] = {'capture_directory': report['capture_directory'],
            'objects': len(docs), 'checks': len(checks), 'manifest_verified': True,
            'catalogue_trajectory_horizon_radii_equal': True, 'classifications_windows_equal': True,
            'measured_production_sources_equal': True}
    args.output.write_text(json.dumps(result, indent=2)+'\n')
    print(json.dumps(result, indent=2))


if __name__ == '__main__':
    main()
