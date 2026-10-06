"""Rebuilt encounter tests; frozen gap cases come from the published research."""
from datetime import datetime, timedelta, timezone
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


class ToyTimescale:
    def tt_jd(self, tt):
        return SimpleNamespace(tt=np.asarray(tt))


class ToySatellite:
    def __init__(self, track):
        self.track = track

    def at(self, time):
        xyz = np.asarray(self.track(np.atleast_1d(time.tt)*86400)).T
        return SimpleNamespace(frame_xyz=lambda frame: SimpleNamespace(km=xyz))


class IntervalTests(unittest.TestCase):
    def check(self, positions, vehicle, sat=None, duration=10, radius=1):
        positions, vehicle = np.asarray(positions, float), np.asarray(vehicle, float)
        return has_close_approach(sat, positions, vehicle,
                                 np.linspace(0, duration/86400, len(vehicle)), radius, ToyTimescale())

    def test_crossing_between_clear_endpoints(self):
        self.assertTrue(self.check([[0, 0, 0], [0, 0, 0]], [[-2, 0, 0], [2, 0, 0]]))

    def test_endpoint_encounter(self):
        self.assertTrue(self.check([[0, 0, 0], [4, 0, 0]], np.zeros((2, 3))))

    def test_equal_distance_tracks_are_clear(self):
        self.assertFalse(self.check([[0, 0, 0], [0, 0, 0]], [[2, 0, 0], [2, 0, 0]], duration=1))

    def test_near_miss_is_clear(self):
        self.assertFalse(self.check([[0, 0, 0], [0, 0, 0]], [[-2, 2, 0], [2, 2, 0]]))

    def test_same_spatial_track_at_different_times_is_clear(self):
        vehicle = np.array([[0, 0, 0], [4, 0, 0]])
        positions = vehicle + [2, 0, 0]
        self.assertFalse(self.check(positions, vehicle, duration=1))

    def test_refinement_uses_curved_propagation(self):
        def track(t):
            return np.column_stack((.4*(t-5), .8+.008*(t-5)**2, np.zeros_like(t)))
        sat = ToySatellite(track)
        self.assertTrue(self.check(track(np.array([0., 10.])), np.zeros((2, 3)), sat=sat))

    def test_failed_refinement_is_not_clear(self):
        def fail(t):
            raise RuntimeError('planted propagation failure')
        self.assertTrue(self.check([[-2, 0, 0], [2, 0, 0]], np.zeros((2, 3)), ToySatellite(fail)))

    def test_nonfinite_is_not_clear(self):
        self.assertTrue(self.check([[float('nan'), 0, 0], [2, 0, 0]], np.zeros((2, 3))))

    def test_single_sample(self):
        self.assertTrue(self.check([[0, 0, 0]], [[0, 0, 0]]))
        self.assertFalse(self.check([[2, 0, 0]], [[0, 0, 0]]))


class DocumentedEncounterTests(unittest.TestCase):
    def test_all_ten_research_gap_misses_are_detected(self):
        fixture = json.loads((Path(__file__).parent/'fixtures/gap_cases.json').read_text())
        t0 = datetime.fromisoformat(fixture['t0'])
        presets = {'iss': (28.573, -80.649, 420, 51.6),
                   'starlink': (28.573, -80.649, 550, 53.)}
        self.assertEqual(len(fixture['cases']), 10)
        for entry in fixture['cases']:
            with self.subTest(preset=entry['preset'], norad=entry['object']['norad_id']):
                case, doc = entry['case'], entry['object']
                lat, lon, alt, inc = presets[entry['preset']]
                trajectory = generate_trajectory(lat, lon, alt, inc)
                t = scanner.ts.from_datetime(t0+timedelta(seconds=case['launch_offset_s']))
                items = [(scanner.get_sat(doc), doc, case['radius_km'])]
                self.assertEqual(scanner.count_threats_fast(items, trajectory, alt, t, 10), 1)

    def test_counting_and_first_threat_shortcut(self):
        trajectory = [{'lat': 0, 'lon': 0, 'alt': 420} for _ in range(3)]
        doc = {'location': {'coordinates': [0, 0]}, 'altitude_km': 420}
        t = scanner.ts.from_datetime(datetime(2026, 9, 21, tzinfo=timezone.utc))
        items = [(None, doc, 1), (None, doc, 1)]
        self.assertEqual(scanner.count_threats_fast(items, trajectory, 420, t, 10), 2)
        self.assertEqual(scanner.count_threats_fast(items, trajectory, 420, t, 10, stop_after_first=True), 1)

    def test_initial_propagation_failure_obstructs_scan(self):
        trajectory = [{'lat': 0, 'lon': 0, 'alt': 420} for _ in range(3)]
        class BrokenSatellite:
            def at(self, time):
                raise RuntimeError('planted failure')
        t = scanner.ts.from_datetime(datetime(2026, 9, 21, tzinfo=timezone.utc))
        items = [(BrokenSatellite(), {}, 10)]
        self.assertEqual(scanner.count_threats_fast(items, trajectory, 420, t, 10), 1)

    def test_scan_boundary_clamping_survives(self):
        start = datetime(2026, 9, 21, tzinfo=timezone.utc)
        end = start + timedelta(minutes=30)
        with patch.object(scanner, 'count_threats_fast', return_value=0):
            windows = scanner.scan_windows([], [{'lon': 0}], 0, 0, 420, start, end, 10,
                                           workers=1)
        self.assertEqual(windows, [{'start': start.isoformat(), 'end': end.isoformat(),
                                   'duration_minutes': 30}])

    def test_process_workers_agree_with_single_worker(self):
        start = datetime(2026, 9, 21, tzinfo=timezone.utc)
        end = start+timedelta(minutes=30)
        trajectory = [{'lat': 0, 'lon': 0, 'alt': 420} for _ in range(3)]
        for latitude, expected_count in [(0, 0), (10, 1)]:
            doc = {'location': {'coordinates': [0, latitude]}, 'altitude_km': 420}
            with self.subTest(latitude=latitude):
                single = scanner.scan_windows([doc], trajectory, 0, 0, 420, start, end, 10,
                                              workers=1)
                parallel = scanner.scan_windows([doc], trajectory, 0, 0, 420, start, end, 10,
                                                workers=2)
                self.assertEqual(parallel, single)
                self.assertEqual(len(parallel), expected_count)

    def test_worker_satellite_construction_failure_is_reported(self):
        with patch.object(scanner, 'get_sat', return_value=None):
            scanner._prepare_window_worker([({}, 10, True)], [], 420, 10)
        with self.assertRaises(scanner.WindowVerificationError):
            scanner._window_launch_obstructed(datetime(2026, 9, 21, tzinfo=timezone.utc))

    def test_missing_propagator_cannot_use_a_static_snapshot(self):
        trajectory = [{'lat': 0, 'lon': 0, 'alt': 420} for _ in range(3)]
        t = scanner.ts.from_datetime(datetime(2026, 9, 21, tzinfo=timezone.utc))
        doc = {'tle_line1': 'unavailable TLE', 'location': {'coordinates': [180, 0]},
               'altitude_km': 420}
        for shortcut in [False, True]:
            with self.subTest(stop_after_first=shortcut):
                self.assertEqual(scanner.count_threats_fast([(None, doc, 10)], trajectory, 420, t, 10,
                                                           stop_after_first=shortcut), 1)

    def test_unavailable_tle_is_not_discarded_by_the_static_longitude_filter(self):
        start = datetime(2026, 9, 21, tzinfo=timezone.utc)
        trajectory = [{'lat': 0, 'lon': 0, 'alt': 420} for _ in range(3)]
        for tle in [{'tle_line1': 'unavailable TLE'}, {'tle_line2': 'unavailable TLE'}]:
            for workers in [1, 2]:
                with self.subTest(tle=tle, workers=workers), patch.object(scanner, 'get_sat', return_value=None):
                    doc = {**tle, 'location': {'coordinates': [180, 0]}, 'altitude_km': 420}
                    with self.assertRaises(scanner.WindowVerificationError):
                        scanner.scan_windows([doc], trajectory, 0, 0, 420, start,
                                             start+timedelta(minutes=30), 10, workers=workers)


if __name__ == '__main__':
    unittest.main()
