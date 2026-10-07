"""Worker-local fixed flight geometry and bounded exact orbital batches."""
from math import pi, sqrt
import numpy as np
from sgp4.api import SatrecArray
from skyfield.api import EarthSatellite

from batch_prediction import batch_positions, error_message, frame_rotations
from encounters import (has_close_approach, RELATIVE_ACCELERATION_KM_S2,
                        WAYPOINT_ALLOWANCE_KM)
from orbital import EARTH_R
from prediction import satellite_positions
from proximity import geodetic_to_ecef


class ScanPlan:
    BATCH_SIZE = 128

    def __init__(self, items, trajectory, target_alt):
        self.items = items
        self.steps = len(trajectory)-1
        self.batches = []
        if self.steps < 1:
            return
        period = 2*pi*sqrt((EARTH_R+target_alt)**3/398600.4418)
        first = min(self.steps, max(1, round(600/(period/self.steps))))
        indices = range(first, self.steps+1)
        self.vehicle = np.asarray([geodetic_to_ecef(trajectory[i]['lat'],
                            trajectory[i]['lon'], trajectory[i]['alt']) for i in indices])
        self.vehicle_valid = bool(np.isfinite(self.vehicle).all())
        self.offset_days = np.array([period*i/(self.steps*86400.) for i in indices])
        # Contiguous batches retain catalogue order and first-threat behavior.
        begin = 0
        while begin < len(items):
            sat = items[begin][0]
            if isinstance(sat, EarthSatellite):
                end = begin+1
                while end < min(begin+self.BATCH_SIZE, len(items)) and (
                        isinstance(items[end][0], EarthSatellite)):
                    end += 1
                models = SatrecArray([item[0].model for item in items[begin:end]])
            else:
                end, models = begin+1, None
            self.batches.append((begin, end, models))
            begin = end

    def predictions(self, t, timescale):
        samples = timescale.tt_jd(t.tt+self.offset_days)
        rotations = None
        for begin, end, models in self.batches:
            if models is None:
                sat, doc = self.items[begin][:2]
                try:
                    if sat is not None:
                        xyz = satellite_positions(sat, samples)
                    elif doc.get('tle_line1') or doc.get('tle_line2'):
                        raise ValueError('An orbital propagator is unavailable.')
                    else:
                        coords = doc['location']['coordinates']
                        xyz = np.broadcast_to(geodetic_to_ecef(coords[1], coords[0],
                                                    doc['altitude_km']), self.vehicle.shape)
                    yield begin, xyz, None, True, samples
                except Exception as error:
                    yield begin, None, error, True, samples
                continue
            try:
                if rotations is None:
                    rotations = frame_rotations(samples)
                xyz, codes = batch_positions(models, samples, rotations)
            except Exception as error:
                for index in range(begin, end):
                    yield index, None, error, True, samples
                continue
            # Same vertex and interval-chord broad pass as has_close_approach,
            # evaluated over an object dimension. Only potential rows need the
            # original narrow pass. Invalid rows are handled in catalogue order.
            relative = xyz-self.vehicle
            delta = np.diff(relative, axis=1)
            speed2 = np.einsum('nij,nij->ni', delta, delta)
            fraction = np.divide(-np.einsum('nij,nij->ni', relative[:, :-1], delta),
                                 speed2, out=np.zeros_like(speed2), where=speed2 > 0)
            closest = relative[:, :-1]+np.clip(fraction, 0, 1)[:, :, None]*delta
            allowance = (RELATIVE_ACCELERATION_KM_S2*(np.diff(samples.tt)*86400)**2/8
                         + WAYPOINT_ALLOWANCE_KM)
            radii = np.asarray([item[2] for item in self.items[begin:end]])
            vertex2 = np.einsum('nij,nij->ni', relative, relative)
            chord2 = np.einsum('nij,nij->ni', closest, closest)
            thresholds = radii[:, None]+allowance
            potential_rows = (np.any(vertex2 < radii[:, None]**2, axis=1) |
                              np.any(chord2 < thresholds**2, axis=1))
            # Batched einsum can round a few ulps differently. Re-run the
            # original Skyfield path near either broad-pass decision boundary.
            guard = 1e-8  # km, comfortably above measured frame differences
            boundary_rows = (np.any(np.abs(vertex2-radii[:, None]**2) <=
                                    guard*(2*radii[:, None]+guard), axis=1) |
                             np.any(np.abs(chord2-thresholds**2) <=
                                    guard*(2*thresholds+guard), axis=1))
            finite_rows = np.isfinite(xyz).all(axis=(1, 2))
            valid_times = bool(np.isfinite(samples.tt).all())
            for row, index in enumerate(range(begin, end)):
                error = None
                if np.any(codes[row]):
                    error = ValueError(error_message(codes[row]))
                elif not finite_rows[row]:
                    error = ValueError('Non-finite orbital prediction.')
                potential = not self.vehicle_valid or not valid_times or bool(potential_rows[row])
                if error is None and boundary_rows[row]:
                    try:
                        xyz[row] = satellite_positions(self.items[index][0], samples)
                        potential = True
                    except Exception as failure:
                        error = failure
                yield index, xyz[row], error, potential, samples
