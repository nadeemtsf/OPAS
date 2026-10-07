"""Batching must preserve frames, interval decisions and ordered failures."""
from datetime import datetime, timedelta
import json
import os
from pathlib import Path
import sys
import unittest
from unittest.mock import patch

import numpy as np

os.environ['MONGO_URI'] = 'mongodb://localhost:1/?serverSelectionTimeoutMS=1'
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from batch_prediction import batch_positions, frame_rotations
from prediction import satellite_positions
from scan_plan import ScanPlan
from sgp4.api import SatrecArray
import scanner
from orbital import generate_trajectory


class BatchTests(unittest.TestCase):
    def setUp(self):
        self.fixture = json.loads((Path(__file__).parent/'fixtures/gap_cases.json').read_text())
        self.t0 = datetime.fromisoformat(self.fixture['t0'])
        self.docs = [case['object'] for case in self.fixture['cases']]
        self.sats = [scanner.get_sat(d) for d in self.docs]

    def test_matches_skyfield_for_multiple_objects_times_and_polar_motion(self):
        from skyfield.api import load
        for polar in [False, True]:
            ts = load.timescale()
            if polar:
                jd = float(ts.from_datetime(self.t0).tt)
                ts.polar_motion_table = (np.array([jd-1, jd+1]),
                                        np.array([.1, .2]), np.array([.2, .3]))
            t = ts.from_datetimes([self.t0+timedelta(seconds=s) for s in [0, .125, 600, 4000]])
            xyz, codes = batch_positions(SatrecArray([s.model for s in self.sats]), t, frame_rotations(t))
            self.assertFalse(codes.any())
            for i, sat in enumerate(self.sats):
                np.testing.assert_allclose(xyz[i], satellite_positions(sat, t), rtol=0, atol=2e-11)

    def test_real_gaps_are_detected_with_batches_and_different_chunk_boundaries(self):
        for size in [1, 3, 128]:
            with patch.object(ScanPlan, 'BATCH_SIZE', size):
                for entry in self.fixture['cases']:
                    preset = entry['preset']; alt, inc = (420, 51.6) if preset == 'iss' else (550, 53)
                    trajectory = generate_trajectory(28.573, -80.649, alt, inc)
                    t = scanner.ts.from_datetime(self.t0+timedelta(seconds=entry['case']['launch_offset_s']))
                    sat = scanner.get_sat(entry['object'])
                    self.assertEqual(scanner.count_threats_fast([(sat, entry['object'], entry['case']['radius_km'])],
                                                              trajectory, alt, t, 10, strict=True), 1)

    def test_failure_later_in_batch_does_not_override_first_obstruction(self):
        bad = json.loads((Path(__file__).parent/'fixtures/stale_prediction.json').read_text())
        t = scanner.ts.from_datetime(datetime.fromisoformat(bad['launch_utc']))
        sat = self.sats[0]
        trajectory = generate_trajectory(28.573, -80.649, 400, 51.6)
        items = [(sat, self.docs[0], 1e9), (scanner.get_sat(bad['object']), bad['object'], 15)]
        self.assertEqual(scanner.count_threats_fast(items, trajectory, 400, t, 10,
                                                  stop_after_first=True, strict=True), 1)
        with self.assertRaises(scanner.WindowVerificationError):
            scanner.count_threats_fast(items, trajectory, 400, t, 10, strict=True)

    def test_batch_nonfinite_vehicle_cannot_be_clear(self):
        trajectory = generate_trajectory(28.573, -80.649, 420, 51.6)
        trajectory[100]['lat'] = float('nan')
        with self.assertRaises(scanner.WindowVerificationError):
            scanner.count_threats_fast([(self.sats[0], self.docs[0], 10)], trajectory, 420,
                                      scanner.ts.from_datetime(self.t0), 10, strict=True)

    def test_real_decay_code_with_finite_batch_coordinates_is_rejected(self):
        fixture=json.loads((Path(__file__).parent/'fixtures/decayed_prediction.json').read_text())
        doc=fixture['object'];sat=scanner.get_sat(doc)
        t=scanner.ts.from_datetime(datetime.fromisoformat(fixture['launch_utc']))
        trajectory=generate_trajectory(28.573,-80.649,400,51.6)
        plan=ScanPlan([(sat,doc,15)],trajectory,400)
        _, xyz, error, _, _ = next(plan.predictions(t,scanner.ts))
        self.assertTrue(np.isfinite(xyz).all())
        self.assertIn('satellite has decayed',str(error))
        with self.assertRaisesRegex(scanner.WindowVerificationError,'34861.*satellite has decayed'):
            scanner.count_threats_fast(plan.items,trajectory,400,t,10,strict=True,prepared=plan)
        self.assertEqual(scanner.count_threats_fast(plan.items,trajectory,400,t,10,prepared=plan),1)

if __name__ == '__main__': unittest.main()
