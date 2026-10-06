from pathlib import Path
import sys
import unittest

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parents[2]/'validation'))
from verify_iss_windows import minimum_distances


class DenseVerificationTests(unittest.TestCase):
    def test_planted_encounter_between_one_second_samples(self):
        t = np.arange(6.)
        positions = np.stack((3*(t-2.5), np.full(6, 2.), np.zeros(6)), axis=1)
        np.testing.assert_allclose(minimum_distances(positions[None, :, :],
                                                    np.zeros((6, 3))), [2.])

    def test_endpoints_are_not_extrapolated(self):
        positions = np.array([[[2., 0, 0], [3., 0, 0], [4., 0, 0]],
                              [[4., 0, 0], [3., 0, 0], [2., 0, 0]]])
        np.testing.assert_allclose(minimum_distances(positions, np.zeros((3, 3))), [2., 2.])

    def test_constant_relative_position(self):
        positions = np.tile([3., 4., 0.], (1, 5, 1))
        np.testing.assert_allclose(minimum_distances(positions, np.zeros((5, 3))), [5.])


if __name__ == '__main__':
    unittest.main()
