"""Independent dense flight reference over an entire exact launch-time grid.

Skyfield is used directly, not the production batching or interval detector.
One-second ephemerides are shared between launches. A sparse flight prefilter
uses measured maximum one-second displacement and the triangle inequality to
exclude distant pairs from the dense calculation. Threshold-near pairs are
repropagated directly. This is numerical validation of the nominal model.
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

import numpy as np

os.environ['MONGO_URI'] = 'mongodb://localhost:1/?serverSelectionTimeoutMS=1'
sys.path.insert(0, str(Path(__file__).resolve().parents[1]/'backend'))
import scanner
from orbital import EARTH_R, generate_trajectory
from proximity import geodetic_to_ecef, screening_radius_km
from skyfield.framelib import itrs
from benchmark_scanner import PRESETS
from verify_iss_windows import minimum_distances
from windows import launch_grid
from replay_capture import load_capture


def direct(sat, t):
    prediction = sat.at(t)
    errors = {str(e) for e in np.asarray(prediction.message, dtype=object).ravel() if e}
    if errors:
        raise ValueError(f'Independent SGP4 failure: {sorted(errors)}')
    xyz = np.asarray(prediction.frame_xyz(itrs).km).T
    if not np.isfinite(xyz).all():
        raise ValueError('Independent non-finite orbital prediction.')
    return xyz


def sparse_candidates(xyz, lower, fraction, vehicle, radius, stride, flight_step):
    indices = np.unique(np.r_[np.arange(0, len(vehicle), stride), len(vehicle)-1])
    sat_step = np.linalg.norm(np.diff(xyz, axis=0), axis=1).max(initial=0)
    vehicle_step = np.linalg.norm(np.diff(vehicle, axis=0), axis=1).max(initial=0)
    # Every dense vertex is at most stride/2 indices from a sparse vertex.
    # Linear ephemeris interpolation is Lipschitz with the measured max step.
    # Two extra steps also cover between-sample minimum refinement and rounding.
    allowance = (sat_step*flight_step+vehicle_step)*(stride/2+2)+.02
    minima = np.full(len(lower), np.inf)
    for begin in range(0, len(lower), 64):
        rows = slice(begin, begin+64)
        lo, u = lower[rows][:, indices], fraction[rows][:, indices]
        positions = xyz[lo]*(1-u) + xyz[lo+1]*u
        rel = positions-vehicle[indices]
        minima[rows] = np.sqrt(np.einsum('kij,kij->ki', rel, rel).min(axis=1))
    return np.flatnonzero(minima <= radius+allowance), minima-allowance


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    source = ap.add_mutually_exclusive_group(required=True)
    source.add_argument('--research-root', type=Path)
    source.add_argument('--capture', type=Path)
    ap.add_argument('--preset', choices=PRESETS)
    ap.add_argument('--output', type=Path, required=True)
    ap.add_argument('--hours', type=float, default=6)
    ap.add_argument('--launch-step-s', type=int, default=5)
    ap.add_argument('--workers', type=int, default=4)
    ap.add_argument('--prefilter-stride', type=int, default=30)
    ap.add_argument('--offsets-file', type=Path, help='control: check only recorded exact launch offsets')
    args = ap.parse_args()
    if args.prefilter_stride < 1 or args.workers < 1 or args.hours <= 0 or args.launch_step_s <= 0:
        ap.error('positive strides, workers and horizon required')
    started = time.perf_counter()
    captured = None
    if args.capture:
        captured = load_capture(args.capture)
        expected = captured['source_sha256']['orbital.py']
        if hashlib.sha256(Path('backend/orbital.py').read_bytes()).hexdigest() != expected:
            raise ValueError('Captured trajectory model version differs; use its recorded orbital source.')
        params = captured['parameters']
        lat, lon, alt, inc = [params[k] for k in ['target_lat','target_lon','target_alt','inclination']]
        t0 = datetime.fromisoformat(captured['search_start_utc'])
        args.hours = (datetime.fromisoformat(captured['search_end_utc'])-t0).total_seconds()/3600
        selected = [(doc, r) for doc, r in zip(captured['catalogue'],captured['frozen_radii_km']) if r is not None]
        docs = [doc for doc, _ in selected]
        radii = np.array([r for _, r in selected])
        args.preset = 'captured'
        meta = {'sha256_uncompressed':captured['catalogue_sha256']}
    else:
        if not args.preset: ap.error('--preset is required with --research-root')
        meta = json.loads((args.research_root/'data/snapshot_meta.json').read_text())
        raw = gzip.decompress((args.research_root/'data'/meta['file']).read_bytes())
        if hashlib.sha256(raw).hexdigest() != meta['sha256_uncompressed']:
            raise ValueError('Snapshot checksum mismatch.')
        lat, lon, alt, inc = PRESETS[args.preset]
        docs = [json.loads(line) for line in raw.splitlines()]
        docs = [d for d in docs if alt-100 <= d['altitude_km'] <= alt+100]
        t0 = datetime.fromisoformat(meta['exported_at_utc'])
    def age(line):
        year = int(line[18:20]); year += 1900 if year >= 57 else 2000
        epoch = datetime(year, 1, 1, tzinfo=t0.tzinfo)+timedelta(days=float(line[20:32])-1)
        return (t0-epoch).total_seconds()/86400
    if not captured:
        radii = np.array([screening_radius_km(10, age(d['tle_line1'])) for d in docs])
    if not np.isfinite(radii).all() or np.any(radii <= 0):
        raise ValueError('Invalid frozen screening radius.')
    offsets = (np.array(json.loads(args.offsets_file.read_text())['offsets_s'], dtype=float)
               if args.offsets_file else np.array([(t-t0).total_seconds() for t in
                    launch_grid(t0, t0+timedelta(hours=args.hours), args.launch_step_s)]))
    period = 2*math.pi*math.sqrt((EARTH_R+alt)**3/398600.4418)
    steps = round(period)
    trajectory = generate_trajectory(lat, lon, alt, inc, steps=steps)
    production = generate_trajectory(lat, lon, alt, inc)
    if captured and production != captured['trajectory']:
        raise ValueError('Captured trajectory does not match this nominal mission model.')
    scope_start = round(600/(period/600))*period/600
    first = int(math.floor(scope_start/(period/steps)))+1
    flight = np.r_[scope_start, np.arange(first, steps+1)*period/steps]
    start_wp = production[round(600/(period/600))]
    vehicle = np.array([geodetic_to_ecef(start_wp['lat'], start_wp['lon'], start_wp['alt'])]+
                       [geodetic_to_ecef(w['lat'], w['lon'], w['alt']) for w in trajectory[first:]])
    target = offsets[:, None]+flight[None, :]
    lower = np.floor(target).astype(int)
    fraction = (target-lower)[:, :, None]
    origin = int(lower.min()); lower -= origin
    times = scanner.ts.tt_jd(float(scanner.ts.from_datetime(t0).tt)+
                            np.arange(origin, int(np.ceil(target.max()))+2)/86400)
    launch_tt = np.array([float(scanner.ts.from_datetime(
                  t0+timedelta(seconds=float(offset))).tt) for offset in offsets])
    unsafe = np.zeros(len(offsets), dtype=bool)
    margins = np.full(len(offsets), np.inf)
    lower_margins = np.full(len(offsets), np.inf)
    launches = [{'offset_s':float(offset), 'launch_time':(t0+timedelta(seconds=float(offset))).isoformat()}
                for offset in offsets]
    report = {'status':'running', 'phase':'dense', 'preset':args.preset,
              'snapshot_sha256':meta['sha256_uncompressed'], 't0':t0.isoformat(),
              'parameters':dict(lat=lat,lon=lon,alt_km=alt,inclination=inc,hours=args.hours),
              'candidate_count':len(docs), 'launch_count':len(offsets), 'workers':args.workers,
              'launch_step_seconds':args.launch_step_s, 'dense_flight_step_s':period/steps,
              'flight_start_seconds':scope_start, 'flight_end_seconds':period,
              'prefilter_stride':args.prefilter_stride,
              'scope':'Whole horizon at exact launch grid; nominal post-ascent model. Recorded distances concern dense-checked pairs; distant pairs excluded by measured displacement bounds.',
              'source_sha256':{name:hashlib.sha256(Path(name).read_bytes()).hexdigest()
                               for name in ['validation/reference_presets.py','validation/verify_iss_windows.py','backend/orbital.py','backend/proximity.py']}}
    if captured:
        report['request_id'] = captured['request_id']
    args.output.parent.mkdir(parents=True, exist_ok=True)
    def save():
        temporary=args.output.with_suffix('.tmp');temporary.write_text(json.dumps(report,indent=2)+'\n');temporary.replace(args.output)
    save()
    def check(item):
        doc, radius = item
        sat = scanner.get_sat(doc)
        if sat is None:
            if doc.get('tle_line1') or doc.get('tle_line2'):
                raise ValueError('Independent satellite construction failed.')
            coords = doc['location']['coordinates']
            position = geodetic_to_ecef(coords[1],coords[0],doc['altitude_km'])
            xyz = np.broadcast_to(position,(len(times.tt),3))
        else:
            xyz = direct(sat, times)
        if args.prefilter_stride == 1:
            selected = np.arange(len(offsets)); bounds = np.full(len(offsets), -np.inf)
        else:
            selected, bounds = sparse_candidates(xyz, lower, fraction, vehicle,
                                                   radius, args.prefilter_stride, period/steps)
        distances = np.full(len(offsets), np.inf)
        for begin in range(0, len(selected), 32):
            rows = selected[begin:begin+32]
            positions = xyz[lower[rows]]*(1-fraction[rows])+xyz[lower[rows]+1]*fraction[rows]
            distances[rows] = minimum_distances(positions, vehicle)
        near = np.flatnonzero(distances <= radius+.02)
        for row in near:
            exact = (direct(sat, scanner.ts.tt_jd(launch_tt[row]+flight/86400))
                     if sat is not None else np.broadcast_to(position,vehicle.shape))
            distances[row] = minimum_distances(exact[None, :, :], vehicle)[0]
        bounds[selected] = distances[selected]
        return distances, bounds, len(selected), len(near)
    # Initialize Skyfield's shared Earth-orientation cache once. Otherwise the
    # first worker threads can allocate the same large nutation arrays together.
    _ = times.M, times.gast
    dense_pairs = direct_pairs = 0
    with ThreadPoolExecutor(max_workers=args.workers) as executor:
        for index, (doc, radius, (distances, bounds, n_dense, n_direct)) in enumerate(
                zip(docs, radii, executor.map(check, zip(docs, radii)))):
            dense_pairs += n_dense; direct_pairs += n_direct
            better = np.flatnonzero(distances-radius < margins)
            for row in better:
                launches[row].update(closest_norad_id=doc.get('norad_id'),
                                     minimum_distance_km=float(distances[row]), screening_radius_km=float(radius),
                                     clearance_margin_km=float(distances[row]-radius))
            margins = np.minimum(margins, distances-radius)
            lower_margins = np.minimum(lower_margins, bounds-radius)
            unsafe |= distances < radius
            if (index+1)%200 == 0 or index+1==len(docs):
                report.update(completed_objects=index+1, obstructed_so_far=int(unsafe.sum()),
                              elapsed_seconds_so_far=time.perf_counter()-started)
                save(); print(args.preset,index+1,len(docs),round(time.perf_counter()-started,2),flush=True)
    for row, entry in enumerate(launches):
        entry['obstructed'] = bool(unsafe[row])
        entry['clearance_margin_lower_bound_km'] = (float(lower_margins[row])
                if np.isfinite(lower_margins[row]) else None)
    report.update(status='complete', launches=launches, elapsed_seconds=time.perf_counter()-started,
                  dense_pairs=dense_pairs, direct_near_threshold_pairs=direct_pairs,
                  clear=int((~unsafe).sum()), obstructed=int(unsafe.sum()))
    save(); print(args.preset,'complete',report['elapsed_seconds'],flush=True)

if __name__ == '__main__': main()
