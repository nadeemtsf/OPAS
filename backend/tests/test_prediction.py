"""Failed SGP4 output and the specific archived live-run failure stay incomplete."""
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import sys
from types import SimpleNamespace
import unittest
from unittest.mock import patch

import numpy as np

os.environ['MONGO_URI'] = 'mongodb://localhost:1/?serverSelectionTimeoutMS=1'
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import scanner
from encounters import has_close_approach
from orbital import generate_trajectory
from prediction import satellite_positions
from refresh_catalogue import fetch_latest, refresh_object, validated_document


FIXTURE = Path(__file__).parent/'fixtures/stale_prediction.json'


class PredictionTests(unittest.TestCase):
    def test_finite_coordinates_with_a_reported_sgp4_error_are_rejected(self):
        prediction = SimpleNamespace(message=['mrt is less than 1.0 which indicates the satellite has decayed'],
                                     frame_xyz=lambda frame: SimpleNamespace(km=np.ones((3, 2))))
        sat = SimpleNamespace(at=lambda time: prediction)
        with self.assertRaisesRegex(ValueError, 'satellite has decayed'):
            satellite_positions(sat, None)

    def test_valid_output_is_unchanged(self):
        xyz = np.arange(6.).reshape(3, 2)
        prediction = SimpleNamespace(message=[None, None], frame_xyz=lambda frame: SimpleNamespace(km=xyz))
        np.testing.assert_array_equal(satellite_positions(SimpleNamespace(at=lambda time: prediction), None), xyz.T)

    def test_real_archived_object_fails_at_the_users_exact_launch_time(self):
        fixture = json.loads(FIXTURE.read_text())
        document = fixture['object']
        t = scanner.ts.from_datetime(datetime.fromisoformat(fixture['launch_utc']))
        trajectory = generate_trajectory(28.573, -80.649, 400, 51.6)
        items = [(scanner.get_sat(document), document, 15)]
        with self.assertRaises(scanner.WindowVerificationError) as caught:
            scanner.count_threats_fast(items, trajectory, 400, t, 10, strict=True)
        detail = str(caught.exception)
        self.assertIn('69980', detail)
        self.assertIn('mean eccentricity is outside the range', detail)
        self.assertIn('2026-10-06T17:09:47Z', detail)
        self.assertIn('refresh_catalogue.py --norad-id 69980', detail)
        # Legacy conservative handling must still count failure as obstruction.
        self.assertEqual(scanner.count_threats_fast(items, trajectory, 400, t, 10), 1)

    def test_refinement_error_retains_its_cause(self):
        class FailedSatellite:
            def at(self, time):
                raise RuntimeError('planted narrow-pass failure')
        with self.assertRaisesRegex(ValueError, 'planted narrow-pass failure'):
            has_close_approach(FailedSatellite(), np.array([[-2,0,0],[2,0,0]]),
                               np.zeros((2,3)), np.array([0.,10/86400]), 1,
                               scanner.ts, strict=True)


class RefreshTests(unittest.TestCase):
    def setUp(self):
        self.doc = json.loads(FIXTURE.read_text())['object']
        self.record = {'NORAD_CAT_ID': str(self.doc['norad_id']), 'OBJECT_NAME': self.doc['name'],
                       'TLE_LINE1': self.doc['tle_line1'], 'TLE_LINE2': self.doc['tle_line2'],
                       'DECAY_DATE': None}
        self.valid_time = datetime(2026, 9, 21, tzinfo=timezone.utc)
        self.current = {**self.doc, '_id': 'test-object', 'research_metadata': 'preserved'}
        self.collection = unittest.mock.Mock()
        self.collection.find_one.return_value = self.current
        self.collection.update_one.return_value = SimpleNamespace(matched_count=1, modified_count=1)
        self.session = unittest.mock.Mock()
        self.session.get.return_value.json.return_value = [self.record]

    def test_invalid_prediction_never_updates_or_deletes_database_objects(self):
        with self.assertRaisesRegex(ValueError, 'mean eccentricity'):
            refresh_object(self.collection, self.session, scanner.ts, 69980,
                           datetime(2026, 10, 6, tzinfo=timezone.utc))
        self.collection.update_one.assert_not_called()
        self.collection.delete_many.assert_not_called()

    def test_refresh_updates_only_the_requested_existing_object(self):
        self.assertEqual(refresh_object(self.collection, self.session, scanner.ts, 69980,
                                        self.valid_time), 'updated')
        args, kwargs = self.collection.update_one.call_args
        self.assertEqual(args[0], {'_id': 'test-object', 'tle_line1': self.doc['tle_line1'],
                                  'tle_line2': self.doc['tle_line2']})
        self.assertEqual(args[1]['$set']['norad_id'], 69980)
        self.assertNotIn('research_metadata', args[1]['$set'])
        self.assertFalse(kwargs['upsert'])
        self.collection.delete_many.assert_not_called()

    def test_dry_run_makes_no_database_change(self):
        status = refresh_object(self.collection, self.session, scanner.ts, 69980, self.valid_time, dry_run=True)
        self.assertIn('dry run', status)
        self.collection.update_one.assert_not_called()

    def test_missing_or_decayed_space_track_record_is_retained(self):
        for records in [[], [{**self.record, 'DECAY_DATE': '2026-10-01'}]]:
            with self.subTest(records=records):
                self.session.get.return_value.json.return_value = records
                with self.assertRaises(ValueError):
                    refresh_object(self.collection, self.session, scanner.ts, 69980, self.valid_time)
                self.collection.update_one.assert_not_called()
                self.collection.delete_many.assert_not_called()

    def test_wrong_norad_record_or_tle_cannot_update_the_object(self):
        self.session.get.return_value.json.return_value = [{**self.record, 'NORAD_CAT_ID': '1'}]
        with self.assertRaises(ValueError):
            fetch_latest(self.session, 69980)
        with self.assertRaisesRegex(ValueError, 'TLE lines do not match'):
            validated_document({**self.record, 'NORAD_CAT_ID': '1'}, scanner.ts, self.valid_time)

    def test_concurrent_change_does_not_force_an_update(self):
        self.collection.update_one.return_value = SimpleNamespace(matched_count=0, modified_count=0)
        with self.assertRaisesRegex(ValueError, 'changed during refresh'):
            refresh_object(self.collection, self.session, scanner.ts, 69980, self.valid_time)

    def test_older_space_track_tle_cannot_replace_a_newer_stored_epoch(self):
        self.collection.find_one.return_value = {**self.current,
            'tle_line1': self.doc['tle_line1'][:18]+'26264'+self.doc['tle_line1'][23:]}
        with self.assertRaisesRegex(ValueError, 'older TLE'):
            refresh_object(self.collection, self.session, scanner.ts, 69980, self.valid_time)
        self.collection.update_one.assert_not_called()


if __name__ == '__main__':
    unittest.main()
