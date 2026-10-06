"""HTTP integration: verified responses and incomplete orbital-data failures."""
from datetime import datetime
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

    def request(self, documents):
        collection = SimpleNamespace(find=lambda query, projection: documents)
        with patch.object(api, 'collection', collection), TestClient(api.app) as client:
            return client.get('/safe-windows', params=self.parameters)

    def test_success_uses_the_actual_scanner_and_spawned_workers(self):
        response = self.request([])
        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertEqual(data['search_hours'], 1)
        self.assertEqual(data['candidates_checked'], 0)
        self.assertEqual(len(data['windows']), 1)
        window = data['windows'][0]
        seconds = (datetime.fromisoformat(window['end'])-datetime.fromisoformat(window['start'])).total_seconds()
        self.assertEqual(seconds, 3600)
        self.assertEqual(window['duration_minutes'], 60)

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


if __name__=='__main__':
    unittest.main()
