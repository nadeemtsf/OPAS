"""Replay a captured HTTP search offline, rejecting altered inputs first."""
import argparse
from datetime import datetime
import gzip
import hashlib
import json
import os
from pathlib import Path
import sys
import time


def load_capture(directory):
    manifest = json.loads((directory/'manifest.json').read_text())
    if not {'inputs.json.gz', 'launches.jsonl', 'result.json'}.issubset(manifest['files']):
        raise ValueError('Capture manifest does not cover all replay files.')
    for name, expected in manifest['files'].items():
        if Path(name).name != name or hashlib.sha256((directory/name).read_bytes()).hexdigest() != expected:
            raise ValueError(f'Capture checksum mismatch: {name}')
    inputs = json.loads(gzip.decompress((directory/'inputs.json.gz').read_bytes()))
    if inputs['schema_version'] != 1 or 'frozen_radii_km' not in inputs:
        raise ValueError('Capture did not finish preparing orbital data; cannot replay classification.')
    if len(inputs['catalogue']) != len(inputs['frozen_radii_km']):
        raise ValueError('Frozen radii do not cover the catalogue.')
    return inputs


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--capture', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--workers', type=int, default=4)
    args = parser.parse_args()
    inputs = load_capture(args.capture)
    os.environ['MONGO_URI'] = 'mongodb://localhost:1/?serverSelectionTimeoutMS=1'
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]/'backend'))
    import scanner
    parameters = inputs['parameters']
    checks = []
    start = time.perf_counter()
    diagnostics = {}
    windows = scanner.scan_windows(inputs['catalogue'], inputs['trajectory'],
        parameters['target_lat'], parameters['target_lon'], parameters['target_alt'],
        datetime.fromisoformat(inputs['search_start_utc']),
        datetime.fromisoformat(inputs['search_end_utc']), inputs['proximity_km'],
        launch_step_seconds=inputs['launch_step_seconds'],
        verification_step_seconds=inputs['verification_step_seconds'],
        frozen_radii=inputs['frozen_radii_km'], workers=args.workers,
        diagnostics=diagnostics, record_check=lambda dt, state, phase:
            checks.append(dict(launch_time=dt.isoformat(), obstructed=state, phase=phase)))
    original = [json.loads(line) for line in (args.capture/'launches.jsonl').read_text().splitlines()]
    original_result = json.loads((args.capture/'result.json').read_text())
    report = {'status': 'complete', 'elapsed_seconds': time.perf_counter()-start,
              'original_status': original_result.get('status', original_result.get('diagnostics', {}).get('status')),
              'classifications_equal': checks == original,
              'windows_equal': windows == original_result.get('windows'),
              'windows': windows, 'diagnostics': diagnostics, 'launches': checks,
              'source_sha256': {p.name: hashlib.sha256(p.read_bytes()).hexdigest()
                               for p in (Path(__file__).resolve().parents[1]/'backend').glob('*.py')}}
    args.output.write_text(json.dumps(report, indent=2)+'\n')
    print(json.dumps({k:v for k,v in report.items() if k not in ['launches','source_sha256']}))
    return 0 if (report['original_status'] == 'complete' and
                 report['classifications_equal'] and report['windows_equal']) else 1

if __name__ == '__main__':
    raise SystemExit(main())
