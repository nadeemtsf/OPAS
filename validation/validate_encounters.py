"""Replay archived ISS/Starlink/SSO near-threshold pairs through the detector.

Uses each archive's exact recorded launch offset, never a nominal minute label.
Screening radii are frozen at the snapshot epoch. The archive's ~1 s minima are
an independent reference; comparisons outside the production post-ascent scope
are reported as excluded rather than scored as detector misses.
"""
import argparse
from datetime import datetime, timedelta
import gzip
import hashlib
import json
import math
from pathlib import Path
import time

import numpy as np

from verify_iss_windows import scanner
from orbital import EARTH_R, generate_trajectory
from proximity import screening_radius_km


PRESETS = {'iss':(28.573,-80.649,420,51.6,'20260921T102002Z'),
           'starlink':(28.573,-80.649,550,53,'20260922T071313Z'),
           'sso':(34.632,-120.611,705,98.2,'20260922T072024Z')}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--research-root',type=Path,required=True)
    parser.add_argument('--output',type=Path,required=True)
    args = parser.parse_args()
    started = time.perf_counter()
    meta = json.loads((args.research_root/'data/snapshot_meta.json').read_text())
    raw = gzip.decompress((args.research_root/'data'/meta['file']).read_bytes())
    sha = hashlib.sha256(raw).hexdigest()
    if sha != meta['sha256_uncompressed']:
        raise ValueError('Snapshot checksum mismatch.')
    documents = {int(doc['norad_id']):doc for line in raw.splitlines() if (doc:=json.loads(line))['norad_id'] is not None}
    t0 = datetime.fromisoformat(meta['exported_at_utc'])

    def frozen_age(line):
        year = int(line[18:20])
        epoch = datetime(year+(1900 if year>=57 else 2000),1,1,tzinfo=t0.tzinfo)+timedelta(days=float(line[20:32])-1)
        return (t0-epoch).total_seconds()/86400

    outcomes = {}
    for name,(lat,lon,alt,inc,stamp) in PRESETS.items():
        before = time.perf_counter()
        path = args.research_root/f'results/reference_{name}_{stamp}.npz'
        reference_meta = json.loads(path.with_suffix('.json').read_text())
        if reference_meta['environment']['snapshot_sha256'] != sha:
            raise ValueError('Archived reference snapshot mismatch.')
        data = np.load(path)
        trajectory = generate_trajectory(lat,lon,alt,inc)
        period = 2*math.pi*math.sqrt((EARTH_R+alt)**3/398600.4418)
        production_start = round(600/(period/600))*(period/600)
        radii = np.array([screening_radius_km(10,frozen_age(documents[int(norad)]['tle_line1']))
                          for norad in data['obj_norad']])
        radius = radii[data['pair_obj_idx']]
        offsets = data['launch_offset_s'][data['pair_launch_idx']]
        in_horizon = (offsets>=0)&(offsets<=6*3600)
        covered = data['pair_s_ca']>=production_start
        near = data['pair_dmin_km']<radius+20
        selected = np.flatnonzero(in_horizon&covered&near)
        cases = []
        unsafe_count = clear_count = misses = false_alarms = 0
        for index in selected:
            doc = documents[int(data['obj_norad'][data['pair_obj_idx'][index]])]
            sat = scanner.get_sat(doc)
            if sat is None:
                raise ValueError('Satellite construction failed.')
            launch_offset = float(offsets[index])
            launch = scanner.ts.from_datetime(t0+timedelta(seconds=launch_offset))
            expected = bool(data['pair_dmin_km'][index]<radius[index])
            actual = bool(scanner.count_threats_fast([(sat,doc,float(radius[index]))],trajectory,
                                                     alt,launch,10,stop_after_first=True))
            unsafe_count += expected
            clear_count += not expected
            misses += expected and not actual
            false_alarms += actual and not expected
            if expected != actual:
                cases.append({'norad_id':doc['norad_id'], 'launch_offset_s':launch_offset,
                              'radius_km':float(radius[index]), 'reference_minimum_km':float(data['pair_dmin_km'][index]),
                              'reference_obstructed':expected,'production_obstructed':actual})
        outcomes[name] = {'unsafe_pairs':unsafe_count,'clear_pairs':clear_count,'missed_unsafe_pairs':misses,
                          'false_alarm_pairs':false_alarms,'disagreements':cases,
                          'excluded_outside_production_scope':int((in_horizon&~covered&near).sum()),
                          'production_scope_start_s':production_start,
                          'reference_npz_sha256':hashlib.sha256(path.read_bytes()).hexdigest(),
                          'elapsed_seconds':round(time.perf_counter()-before,3)}
        print(json.dumps({name:outcomes[name]}),flush=True)
    report = {'status':'complete','snapshot_sha256':sha,'presets':outcomes,
              'unsafe_pairs':sum(result['unsafe_pairs'] for result in outcomes.values()),
              'clear_pairs':sum(result['clear_pairs'] for result in outcomes.values()),
              'missed_unsafe_pairs':sum(result['missed_unsafe_pairs'] for result in outcomes.values()),
              'false_alarm_pairs':sum(result['false_alarm_pairs'] for result in outcomes.values()),
              'scope':'Archived independent ~1s reference pairs inside the 6h horizon and production post-ascent scope; clear controls within radius+20km.',
              'elapsed_seconds':round(time.perf_counter()-started,3),
              'source_sha256':hashlib.sha256(Path(__file__).read_bytes()).hexdigest()}
    args.output.write_text(json.dumps(report,indent=2)+'\n')
    print(json.dumps(report,indent=2),flush=True)


if __name__ == '__main__':
    main()
