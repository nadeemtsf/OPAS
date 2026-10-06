"""Check ISS launches at exact clock instants, independently of flight spacing.

Run production and dense phases separately. Dense uses one-second object
ephemerides shared between launches, linear interpolation onto the ~one-second
vehicle grid, and parabolic minimum refinement. Any pair within 20 m of the
threshold is repropagated at the exact flight times before classification.
This verifies sampled launch times in the frozen model, not continuous safety.
"""
import argparse
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta
import gzip
import hashlib
import json
import math
import os
from pathlib import Path
import sys
import time
from threading import Lock
from unittest.mock import patch

import numpy as np

os.environ['MONGO_URI'] = 'mongodb://localhost:1/?serverSelectionTimeoutMS=1'
sys.path.insert(0, str(Path(__file__).resolve().parents[1]/'backend'))
import scanner
from orbital import EARTH_R, generate_trajectory
from proximity import geodetic_to_ecef, screening_radius_km
from skyfield.framelib import itrs
from windows import find_windows, launch_grid


def minimum_distances(positions, vehicle):
    delta = positions - vehicle[None, :, :]
    d2 = np.einsum('kij,kij->ki', delta, delta)
    rows = np.arange(len(d2))
    cols = d2.argmin(axis=1)
    minimum = d2[rows, cols].copy()
    interior = (cols > 0) & (cols < d2.shape[1]-1)
    r, c = rows[interior], cols[interior]
    a, b, z = d2[r, c-1], d2[r, c], d2[r, c+1]
    curvature = a - 2*b + z
    good = curvature > 1e-12
    shift = np.zeros(len(r))
    shift[good] = (a[good]-z[good])/(2*curvature[good])
    good &= np.abs(shift) <= 1
    refined = b.copy()
    refined[good] -= (z[good]-a[good])**2/(8*curvature[good])
    minimum[r] = np.maximum(refined, 0)
    return np.sqrt(minimum)


def save(path, report):
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix('.tmp')
    temporary.write_text(json.dumps(report, indent=2)+'\n')
    temporary.replace(path)


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument('--research-root', type=Path, required=True)
    ap.add_argument('--phase', choices=['production', 'dense', 'search'], required=True)
    ap.add_argument('--output', type=Path, required=True)
    ap.add_argument('--launch-step-s', type=int, default=60)
    ap.add_argument('--horizon-hours', type=float,
                    help='sample the complete horizon from the snapshot epoch')
    ap.add_argument('--windows-file', type=Path, default=Path('validation/results/window_replay.json'))
    ap.add_argument('--launches-file', type=Path,
                    help='verify the exact launch instants recorded by a completed search')
    ap.add_argument('--workers', type=int, default=4)
    args = ap.parse_args()
    if args.launch_step_s <= 0 or 60 % args.launch_step_s:
        ap.error('launch step must be a positive divisor of 60 seconds')
    if args.workers < 1 or (args.horizon_hours is not None and args.horizon_hours <= 0):
        ap.error('workers and horizon must be positive')
    root = args.research_root
    meta = json.loads((root/'data/snapshot_meta.json').read_text())
    raw = gzip.decompress((root/'data'/meta['file']).read_bytes())
    if hashlib.sha256(raw).hexdigest() != meta['sha256_uncompressed']:
        raise ValueError('snapshot checksum mismatch')
    docs = [json.loads(line) for line in raw.splitlines()]
    candidates = [d for d in docs if isinstance(d.get('altitude_km'), (int, float))
                  and 320 <= d['altitude_km'] <= 520]
    if len(candidates) != 11997:
        raise ValueError('ISS candidate count mismatch')
    t0 = datetime.fromisoformat(meta['exported_at_utc'])
    t0_tt = float(scanner.ts.from_datetime(t0).tt)
    def age(line):
        yr = int(line[18:20])
        epoch = datetime(yr+(1900 if yr >= 57 else 2000), 1, 1, tzinfo=t0.tzinfo)
        epoch += timedelta(days=float(line[20:32])-1)
        return (t0-epoch).total_seconds()/86400
    scanner.tle_epoch_age_days = age
    radii = np.array([screening_radius_km(10, age(d['tle_line1'])) for d in candidates])
    windows = []
    launches = []
    if args.phase == 'search':
        if args.launches_file:
            ap.error('search cannot use a launches file')
        scope = 'actual full-horizon production window search with exact minute discovery and finer candidate checks'
    elif args.launches_file:
        previous = json.loads(args.launches_file.read_text())
        if previous['status'] != 'complete' or previous['snapshot_sha256'] != meta['sha256_uncompressed']:
            raise ValueError('launches must come from a completed check on the same snapshot')
        for entry in previous['launches']:
            launch_dt = datetime.fromisoformat(entry['launch_time'])
            offset = (launch_dt-t0).total_seconds()
            if abs(offset-entry['offset_s']) > 1e-6:
                raise ValueError('launch timestamp and recorded offset disagree')
            launches.append({'launch_time': launch_dt.isoformat(), 'offset_s': offset})
        windows = previous.get('returned_windows', previous.get('candidate_windows', []))
        scope = 'independent verification at every exact launch instant checked by production; frozen post-ascent model'
    elif args.horizon_hours:
        scope = 'exact clock launch grid across the complete horizon; frozen post-ascent model'
        launches = [{'launch_time': cursor.isoformat(), 'offset_s': (cursor-t0).total_seconds()}
                    for cursor in launch_grid(t0, t0+timedelta(hours=args.horizon_hours), args.launch_step_s)]
    else:
        data = json.loads(args.windows_file.read_text())
        windows = data['presets']['iss']['windows'] if 'presets' in data else data['verified_subset_windows']
        scope = 'exact clock launch samples inside candidate windows; frozen post-ascent model'
        for i, window in enumerate(windows):
            first, end = datetime.fromisoformat(window['start']), datetime.fromisoformat(window['end'])
            for cursor in launch_grid(first, end, args.launch_step_s):
                if cursor < end:
                    launches.append({'window_index': i, 'launch_time': cursor.isoformat(),
                                     'offset_s': (cursor-t0).total_seconds()})
    offsets = np.array([entry['offset_s'] for entry in launches])
    report = {'phase': args.phase, 'status': 'running', 'snapshot_sha256': meta['sha256_uncompressed'],
              'candidate_count': len(candidates), 'launch_count': len(launches),
              'scope': scope, 'launch_step_seconds': args.launch_step_s,
              'candidate_windows': windows, 'workers': args.workers, 'launches': launches}
    report['source_sha256'] = {name: hashlib.sha256(Path(name).read_bytes()).hexdigest()
                               for name in ['backend/scanner.py', 'backend/encounters.py', 'backend/windows.py',
                                            'backend/orbital.py', 'validation/verify_iss_windows.py']}
    started = time.perf_counter()
    if args.phase == 'search':
        trajectory = generate_trajectory(28.573, -80.649, 420, 51.6)
        lock = Lock()
        def measured_search(is_obstructed, start, end, **kwargs):
            def record(launch_dt, obstructed, elapsed=None):
                with lock:
                    launches.append({'launch_time': launch_dt.isoformat(),
                                     'offset_s': (launch_dt-t0).total_seconds(),
                                     'obstructed': obstructed,
                                     'check_seconds': round(elapsed, 3) if elapsed is not None else None})
                    report['completed_launches'] = len(launches)
                    report['elapsed_seconds_so_far'] = round(time.perf_counter()-started, 3)
                    save(args.output, report)
                    print(f"search {len(launches)}: offset={launches[-1]['offset_s']:.0f}s "
                          f"obstructed={obstructed}", flush=True)
                return obstructed
            def check(launch_dt):
                before = time.perf_counter()
                return record(launch_dt, bool(is_obstructed(launch_dt)), time.perf_counter()-before)
            batch_check = kwargs.get('check_many')
            if batch_check:
                def measured_batch(points):
                    for launch_dt, obstructed in zip(points, batch_check(points)):
                        yield record(launch_dt, bool(obstructed))
                kwargs['check_many'] = measured_batch
            kwargs['workers'] = args.workers
            return find_windows(check, start, end, **kwargs)
        with patch.object(scanner, 'find_windows', side_effect=measured_search):
            report['returned_windows'] = scanner.scan_windows(
                candidates, trajectory, 28.573, -80.649, 420, t0,
                t0+timedelta(hours=args.horizon_hours or 6), 10,
                launch_step_seconds=args.launch_step_s, workers=args.workers)
        launches.sort(key=lambda entry: entry['offset_s'])
        report['launch_count'] = len(launches)
        report['minute_discovery_checks'] = sum(entry['offset_s'] % 60 == 0 for entry in launches)
        report['finer_checks'] = len(launches)-report['minute_discovery_checks']
    elif args.phase == 'production':
        trajectory = generate_trajectory(28.573, -80.649, 420, 51.6)
        items = [(scanner.get_sat(d), d, radius) for d, radius in zip(candidates, radii)]
        if any(sat is None for sat, _, _ in items):
            raise ValueError('satellite construction failed')
        def production_check(entry):
            before = time.perf_counter()
            t = scanner.ts.from_datetime(datetime.fromisoformat(entry['launch_time']))
            return (bool(scanner.count_threats_fast(items, trajectory, 420, t, 10,
                                                    stop_after_first=True)), time.perf_counter()-before)
        with ThreadPoolExecutor(max_workers=args.workers) as executor:
            results = executor.map(production_check, launches)
            for index, (entry, (obstructed, elapsed)) in enumerate(zip(launches, results)):
                entry['obstructed'] = obstructed
                entry['check_seconds'] = round(elapsed, 3)
                report['completed_launches'] = index+1
                save(args.output, report)
                print(f"production {index+1}/{len(launches)}: {entry['launch_time']} obstructed={obstructed}", flush=True)
    else:
        period = 2*math.pi*math.sqrt((EARTH_R+420)**3/398600.4418)
        steps = round(period)
        trajectory = generate_trajectory(28.573, -80.649, 420, 51.6, steps=steps)
        first = round(600/(period/steps))
        flight = np.arange(first, steps+1)*period/steps
        vehicle = np.array([geodetic_to_ecef(w['lat'], w['lon'], w['alt'])
                            for w in trajectory[first:]])
        target_seconds = offsets[:, None] + flight[None, :]
        lower = np.floor(target_seconds).astype(int)
        fraction = (target_seconds-lower)[:, :, None]
        origin = int(math.floor(target_seconds.min()))
        lower -= origin
        uniform_seconds = np.arange(origin, int(math.ceil(target_seconds.max()))+2)
        uniform_time = scanner.ts.tt_jd(t0_tt + uniform_seconds/86400)
        margins = np.full(len(launches), np.inf)
        unsafe = np.zeros(len(launches), dtype=bool)
        direct_pairs = 0
        def dense_check(item):
            doc, radius = item
            sat = scanner.get_sat(doc)
            if sat is None:
                raise ValueError('satellite construction failed')
            xyz = np.asarray(sat.at(uniform_time).frame_xyz(itrs).km).T
            if not np.isfinite(xyz).all():
                raise ValueError(f"non-finite dense ephemeris: {doc['norad_id']}")
            distances = np.empty(len(launches))
            # Bound memory when verifying many fine-grid launches together.
            for first_launch in range(0, len(launches), 32):
                batch = slice(first_launch, first_launch+32)
                positions = xyz[lower[batch]]*(1-fraction[batch]) + xyz[lower[batch]+1]*fraction[batch]
                distances[batch] = minimum_distances(positions, vehicle)
            close = np.flatnonzero(distances <= radius+.02)
            for k in close:
                exact = sat.at(scanner.ts.tt_jd(t0_tt+target_seconds[k]/86400)).frame_xyz(itrs).km.T
                if not np.isfinite(exact).all():
                    raise ValueError('non-finite exact repropagation')
                distances[k] = minimum_distances(exact[None, :, :], vehicle)[0]
            return distances, len(close)
        with ThreadPoolExecutor(max_workers=args.workers) as executor:
            results = executor.map(dense_check, zip(candidates, radii))
            for index, (doc, radius, (distances, n_direct)) in enumerate(zip(candidates, radii, results)):
                direct_pairs += n_direct
                for k in np.flatnonzero(distances-radius < margins):
                    launches[k]['closest_norad_id'] = doc['norad_id']
                    launches[k]['minimum_distance_km'] = float(distances[k])
                    launches[k]['screening_radius_km'] = float(radius)
                    launches[k]['clearance_margin_km'] = float(distances[k]-radius)
                margins = np.minimum(margins, distances-radius)
                unsafe |= distances < radius
                if (index+1) % 100 == 0 or index+1 == len(candidates):
                    report['completed_objects'] = index+1
                    report['unsafe_launches_so_far'] = int(unsafe.sum())
                    save(args.output, report)
                    print(f"dense {index+1}/{len(candidates)} objects: unsafe_launches={unsafe.sum()}", flush=True)
        for entry, obstructed in zip(launches, unsafe):
            entry['obstructed'] = bool(obstructed)
        report['direct_near_threshold_pairs'] = direct_pairs
        report['dense_flight_step_s'] = period/steps
        report['dense_scope_start_s'] = float(flight[0])
        report['numerical_caveat'] = '1s object ephemeris interpolation; <=radius+20m pairs directly repropagated; dense parabola remains approximate'
    report['status'] = 'complete'
    report['elapsed_seconds'] = round(time.perf_counter()-started, 3)
    report['obstructed_launches'] = sum(entry['obstructed'] for entry in launches)
    save(args.output, report)
    print(json.dumps({k:v for k,v in report.items() if k != 'launches'}, indent=2), flush=True)


if __name__ == '__main__':
    main()
