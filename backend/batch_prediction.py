"""Exact SGP4 arrays in the same ITRS frame as Skyfield's EarthSatellite.

Skyfield supplies UTC fractions, precession/nutation and polar motion. Reuse
its two rotations across objects; do not interpolate orbital positions.
"""
import numpy as np
from sgp4.api import SatrecArray, SGP4_ERRORS
from skyfield.constants import AU_KM, DAY_S
from skyfield.framelib import itrs
from skyfield.sgp4lib import TEME


def frame_rotations(t):
    return TEME.rotation_at(t), itrs.rotation_at(t)


def batch_positions(models, t, rotations):
    errors, positions, _ = models.sgp4(
        np.ascontiguousarray(t.whole),
        np.ascontiguousarray(t.tai_fraction-t._leap_seconds()/DAY_S))
    teme, terrestrial = rotations
    # Preserve Skyfield's sequence, including its AU scaling. Combining the
    # rotations would change floating-point rounding at a screening threshold.
    celestial = np.einsum('jit,ntj->nti', teme, positions/AU_KM)
    xyz = np.einsum('ijt,ntj->nti', terrestrial, celestial)*AU_KM
    return xyz, errors


def error_message(codes):
    return 'SGP4: ' + '; '.join(sorted({SGP4_ERRORS.get(int(c), f'error {c}')
                                      for c in codes if c}))
