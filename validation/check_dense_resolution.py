"""Recalculate six threshold-nearest ISS pairs with direct ~0.2 s propagation.

This is a numerical resolution control for selected pairs, not a finer whole-
catalogue verification or a continuous-time guarantee.
"""
import argparse
from datetime import datetime
import gzip
import hashlib
import json
import math
from pathlib import Path
import time

import numpy as np

from verify_iss_windows import minimum_distances, scanner
from orbital import EARTH_R, generate_trajectory
from proximity import geodetic_to_ecef
from skyfield.framelib import itrs


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--research-root', type=Path, required=True)
    parser.add_argument('--reference', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    started = time.perf_counter()
    reference = json.loads(args.reference.read_text())
    if reference['status'] != 'complete' or reference['phase'] != 'dense':
        raise ValueError('Require a completed independent reference.')
    meta = json.loads((args.research_root/'data/snapshot_meta.json').read_text())
    raw = gzip.decompress((args.research_root/'data'/meta['file']).read_bytes())
    sha = hashlib.sha256(raw).hexdigest()
    if sha != meta['sha256_uncompressed'] or sha != reference['snapshot_sha256']:
        raise ValueError('Snapshot checksum mismatch.')
    documents = {int(doc['norad_id']):doc for line in raw.splitlines() if (doc:=json.loads(line))['norad_id'] is not None}
    selected = []
    for obstructed in [False, True]:
        selected += sorted((entry for entry in reference['launches'] if entry['obstructed'] == obstructed),
                           key=lambda entry:abs(entry['clearance_margin_km']))[:3]
    period = 2*math.pi*math.sqrt((EARTH_R+420)**3/398600.4418)
    steps = round(period/.2)
    trajectory = generate_trajectory(28.573, -80.649, 420, 51.6, steps=steps)
    first = round(600/(period/steps))
    flight = np.arange(first, steps+1)*period/steps
    vehicle = np.array([geodetic_to_ecef(w['lat'], w['lon'], w['alt']) for w in trajectory[first:]])
    production_trajectory = generate_trajectory(28.573, -80.649, 420, 51.6)
    cases = []
    for entry in selected:
        doc = documents[int(entry['closest_norad_id'])]
        sat = scanner.get_sat(doc)
        if sat is None:
            raise ValueError('Satellite construction failed.')
        launch_dt = datetime.fromisoformat(entry['launch_time'])
        launch = scanner.ts.from_datetime(launch_dt)
        xyz = np.asarray(sat.at(scanner.ts.tt_jd(float(launch.tt)+flight/86400)).frame_xyz(itrs).km).T
        if not np.isfinite(xyz).all():
            raise ValueError('Nonfinite directly propagated ephemeris.')
        minimum = float(minimum_distances(xyz[None,:,:], vehicle)[0])
        radius = entry['screening_radius_km']
        fine_obstructed = minimum < radius
        production_pair = bool(scanner.count_threats_fast([(sat,doc,radius)], production_trajectory,
                                                          420, launch, 10, stop_after_first=True))
        cases.append({'launch_time':entry['launch_time'], 'norad_id':doc['norad_id'],
                      'screening_radius_km':radius, 'reference_minimum_distance_km':entry['minimum_distance_km'],
                      'direct_minimum_distance_km':minimum, 'direct_margin_km':minimum-radius,
                      'distance_change_m':1000*(minimum-entry['minimum_distance_km']),
                      'reference_obstructed':entry['obstructed'], 'direct_obstructed':fine_obstructed,
                      'production_pair_obstructed':production_pair})
    report = {'status':'complete', 'snapshot_sha256':sha, 'selected_pairs':len(cases),
              'scope':'Three clear and three obstructed launch/object pairs nearest the threshold; direct propagation at ~0.2s flight spacing.',
              'source_reference':str(args.reference), 'flight_step_s':period/steps, 'flight_scope_start_s':float(flight[0]),
              'classification_changes':sum(case['reference_obstructed'] != case['direct_obstructed'] for case in cases),
              'production_pair_disagreements':sum(case['production_pair_obstructed'] != case['direct_obstructed'] for case in cases),
              'elapsed_seconds':round(time.perf_counter()-started,3), 'cases':cases,
              'source_sha256':hashlib.sha256(Path(__file__).read_bytes()).hexdigest()}
    args.output.write_text(json.dumps(report,indent=2)+'\n')
    print(json.dumps(report,indent=2))


if __name__ == '__main__':
    main()
