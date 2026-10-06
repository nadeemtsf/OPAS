"""HTTP integration: verified responses and incomplete orbital-data failures."""
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import sys
from types import SimpleNamespace
import unittest
from unittest.mock import patch

os.environ['MONGO_URI'] = 'mongodb://localhost:1/?serverSelectionTimeoutMS=1'
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from fastapi.testclient import TestClient
import api
from orbital import generate_trajectory


class WindowApiTests(unittest.TestCase):
    parameters = {'target_lat':28.573, 'target_lon':-80.649, 'target_alt':420,
                  'inclination':51.6, 'search_hours':1}

    def request(self, documents, endpoint='/safe-windows', catalogue_nonempty=True):
        collection = SimpleNamespace(find=lambda query, projection: documents,
                                     find_one=lambda query, projection: {} if catalogue_nonempty else None)
        with patch.object(api, 'collection', collection), TestClient(api.app) as client:
            return client.get(endpoint, params=self.parameters)

    def test_success_uses_the_actual_scanner_and_spawned_workers(self):
        # A stationary polar control cannot approach this 51.6-degree ISS
        # trajectory; unlike an empty candidate list, it exercises the detector.
        response = self.request([{'altitude_km':420,'location':{'coordinates':[0,90]}}])
        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertEqual(data['search_hours'], 1)
        self.assertEqual(data['candidates_checked'], 1)
        self.assertEqual(len(data['windows']), 1)
        window = data['windows'][0]
        seconds = (datetime.fromisoformat(window['end'])-datetime.fromisoformat(window['start'])).total_seconds()
        self.assertEqual(seconds, 3600)
        self.assertEqual(window['duration_minutes'], 60)
        self.assertEqual(window['verification']['status'], 'passed')
        self.assertEqual(window['verification']['checked_launches'], 721)
        self.assertEqual(window['verification']['max_launch_gap_seconds'], 5)
        self.assertEqual(data['diagnostics']['extra_validation_checks'], 360)
        self.assertEqual(data['diagnostics']['status'], 'complete')
        self.assertEqual(response.headers['x-request-id'], data['diagnostics']['request_id'])

    def test_bad_orbital_data_returns_an_error_instead_of_verified_windows(self):
        doc = {'tle_line1':'unavailable TLE', 'altitude_km':420,
               'location':{'coordinates':[180, 0]}}
        response = self.request([doc])
        self.assertEqual(response.status_code, 503)
        self.assertNotIn('windows', response.json())
        self.assertIn('could not load an orbital object', response.json()['detail'])

    def test_verified_obstruction_returns_a_successful_empty_result(self):
        trajectory = generate_trajectory(28.573,-80.649,420,51.6)
        point = trajectory[65]
        doc = {'altitude_km':point['alt'], 'location':{'coordinates':[point['lon'], point['lat']]}}
        response = self.request([doc])
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()['windows'], [])

    def test_empty_catalogue_is_not_a_clear_launch_horizon(self):
        response = self.request([], catalogue_nonempty=False)
        self.assertEqual(response.status_code, 503)
        self.assertIn('catalogue is empty', response.json()['detail'])

    def test_stream_delivers_progress_then_verified_result(self):
        import json
        response = self.request([{'altitude_km':420,'location':{'coordinates':[0,90]}}], endpoint='/safe-windows/stream')
        self.assertEqual(response.status_code, 200)
        self.assertIn('text/event-stream', response.headers['content-type'])
        frames = [frame for frame in response.text.split('\n\n') if frame.startswith('event:')]
        self.assertTrue(frames[0].startswith('event: progress'))
        self.assertTrue(frames[-1].startswith('event: result'))
        result = json.loads(frames[-1].split('\ndata: ', 1)[1])
        self.assertEqual(result['diagnostics']['status'], 'complete')
        self.assertEqual(result['windows'][0]['verification']['max_launch_gap_seconds'], 5)
        self.assertEqual(result['diagnostics']['request_id'], response.headers['x-request-id'])

    def test_stream_error_cannot_be_confused_with_a_successful_empty_result(self):
        response = self.request([], endpoint='/safe-windows/stream', catalogue_nonempty=False)
        self.assertIn('event: error\n', response.text)
        self.assertNotIn('event: result\n', response.text)
        self.assertIn('"status": "incomplete"', response.text)

    def test_real_stale_prediction_has_an_actionable_error_in_both_endpoints(self):
        doc = json.loads((Path(__file__).parent/'fixtures/stale_prediction.json').read_text())['object']
        class FrozenDatetime(datetime):
            @classmethod
            def now(cls, tz=None):
                return datetime(2026, 10, 6, 17, 9, 47, tzinfo=timezone.utc)
        with patch.object(api, 'datetime', FrozenDatetime):
            for endpoint in ['/safe-windows', '/safe-windows/stream']:
                with self.subTest(endpoint=endpoint):
                    response = self.request([doc], endpoint=endpoint)
                    self.assertIn('mean eccentricity is outside the range', response.text)
                    self.assertIn('refresh_catalogue.py --norad-id 69980', response.text)
                    if endpoint.endswith('/stream'):
                        self.assertIn('event: error\n', response.text)
                        self.assertNotIn('event: result\n', response.text)
                    else:
                        self.assertEqual(response.status_code, 503)
                        self.assertNotIn('windows', response.json())

    def test_invalid_mission_parameters_are_rejected_before_search(self):
        with TestClient(api.app) as client:
            for override in [{'target_lat':91}, {'target_lon':181}, {'target_alt':-1},
                             {'target_alt':'nan'}, {'inclination':181}]:
                with self.subTest(override=override):
                    response = client.get('/safe-windows/stream', params={**self.parameters, **override})
                    self.assertEqual(response.status_code, 422)


if __name__=='__main__':
    unittest.main()
