"""Reject failed SGP4 predictions before they can establish clearance."""
import numpy as np
from skyfield.framelib import itrs


def satellite_positions(sat, time):
    """Return ECEF positions, retaining Skyfield's actual propagation error.

    Some SGP4 errors leave finite coordinates, so checking only NaNs is not
    sufficient. Test satellites without Skyfield's message field are supported.
    """
    prediction = sat.at(time)
    messages = getattr(prediction, 'message', None)
    errors = sorted({str(message) for message in np.asarray(messages, dtype=object).ravel()
                     if message})
    if errors:
        raise ValueError('SGP4: ' + '; '.join(errors))
    positions = np.asarray(prediction.frame_xyz(itrs).km, dtype=float).T
    if not np.isfinite(positions).all():
        raise ValueError('Orbital prediction returned non-finite coordinates.')
    return positions
