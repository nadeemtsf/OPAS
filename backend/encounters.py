"""Interval screening for OPAS's sampled, post-ascent vehicle trajectory.

The broad pass bounds departure from a straight relative-motion segment using
an assumed relative ECEF acceleration ceiling. This is an engineering bound for
ordinary Earth orbits, not a guarantee for arbitrary trajectories or bad TLEs.
The narrow pass propagates the satellite again and minimizes distance to a cubic
interpolant of the vehicle waypoints. It does not change SGP4 or the vehicle model.
"""
import numpy as np

from skyfield.framelib import itrs

RELATIVE_ACCELERATION_KM_S2 = 0.05
WAYPOINT_ALLOWANCE_KM = 0.02  # rounded coordinates and vehicle interpolation
REFINEMENT_ITERATIONS = 20


def vehicle_positions(points, indices, fractions):
    """Cubic Hermite interpolation; no longitude wrap discontinuities in ECEF."""
    last = len(points) - 1
    right = indices + 1
    left_slope = (points[np.minimum(indices + 1, last)] -
                  points[np.maximum(indices - 1, 0)]) / np.where(indices == 0, 1, 2)[:, None]
    right_slope = (points[np.minimum(right + 1, last)] -
                   points[np.maximum(right - 1, 0)]) / np.where(right == last, 1, 2)[:, None]
    u = fractions[:, None]
    return ((2*u**3 - 3*u**2 + 1) * points[indices] +
            (u**3 - 2*u**2 + u) * left_slope +
            (-2*u**3 + 3*u**2) * points[right] +
            (u**3 - u**2) * right_slope)


def has_close_approach(sat, satellite_positions, vehicle, sample_tt, radius_km,
                       timescale):
    """Screen every interval, then refine potential minima with real propagation.

    Invalid/failed propagation is treated as obstructed, never as evidence of
    clearance. Static objects use the same interval checks without propagation.
    """
    satellite_positions = np.asarray(satellite_positions, dtype=float)
    vehicle = np.asarray(vehicle, dtype=float)
    sample_tt = np.asarray(sample_tt, dtype=float)
    if (not np.isfinite(satellite_positions).all() or
            not np.isfinite(vehicle).all() or not np.isfinite(sample_tt).all()):
        return True
    relative = satellite_positions - vehicle
    radius2 = radius_km ** 2
    if np.any(np.einsum('ij,ij->i', relative, relative) < radius2):
        return True
    if len(vehicle) < 2:
        return False

    delta = np.diff(relative, axis=0)
    speed2 = np.einsum('ij,ij->i', delta, delta)
    fraction = np.divide(-np.einsum('ij,ij->i', relative[:-1], delta), speed2,
                         out=np.zeros_like(speed2), where=speed2 > 0)
    fraction = np.clip(fraction, 0, 1)
    closest = relative[:-1] + fraction[:, None] * delta
    dt = np.diff(sample_tt) * 86400
    allowance = RELATIVE_ACCELERATION_KM_S2 * dt**2 / 8 + WAYPOINT_ALLOWANCE_KM
    indices = np.flatnonzero(np.einsum('ij,ij->i', closest, closest) <
                             (radius_km + allowance)**2)
    if not len(indices):
        return False

    def distances(fractions):
        wp = vehicle_positions(vehicle, indices, fractions)
        if sat is None:
            pos = satellite_positions[indices]
        else:
            tt = sample_tt[indices] + fractions * np.diff(sample_tt)[indices]
            pos = np.asarray(sat.at(timescale.tt_jd(tt)).frame_xyz(itrs).km).T
        if not np.isfinite(pos).all():
            raise ValueError('non-finite propagated position')
        diff = pos - wp
        return np.einsum('ij,ij->i', diff, diff)

    # Golden-section search avoids assuming that a chord's minimum is the
    # curved orbit's minimum. All selected intervals are evaluated in one batch.
    lo = np.zeros(len(indices))
    hi = np.ones(len(indices))
    ratio = (np.sqrt(5) - 1) / 2
    x1, x2 = hi - ratio*(hi-lo), lo + ratio*(hi-lo)
    try:
        f1, f2 = distances(x1), distances(x2)
        for _ in range(REFINEMENT_ITERATIONS):
            if np.any(np.minimum(f1, f2) < radius2):
                return True
            left = f1 < f2
            hi = np.where(left, x2, hi)
            lo = np.where(left, lo, x1)
            x1, x2 = (np.where(left, hi - ratio*(hi-lo), x2),
                      np.where(left, x1, lo + ratio*(hi-lo)))
            new_values = distances(np.where(left, x1, x2))
            f1, f2 = np.where(left, new_values, f2), np.where(left, f1, new_values)
        return bool(np.any(np.minimum(f1, f2) < radius2))
    except Exception:
        return True
