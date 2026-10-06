from collections import Counter
from datetime import datetime, timedelta, timezone
from itertools import groupby
from pathlib import Path
import sys
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from windows import find_windows, launch_grid


class WindowTests(unittest.TestCase):
    start = datetime(2026, 9, 21, tzinfo=timezone.utc)

    def search(self, clear, minutes):
        return find_windows(lambda t: (t-self.start).total_seconds()/60 not in clear,
                            self.start, self.start+timedelta(minutes=minutes),
                            launch_step_seconds=60)

    def offsets(self, windows):
        return [((datetime.fromisoformat(w['start'])-self.start).total_seconds()/60,
                 (datetime.fromisoformat(w['end'])-self.start).total_seconds()/60)
                for w in windows]

    def test_later_clear_run_survives_early_threat(self):
        windows = self.search({0, 1, 2} | set(range(4, 24)), 40)
        self.assertEqual(self.offsets(windows), [(4, 23)])

    def test_valid_window_after_five_short_candidates(self):
        clear = {m for start in (0, 30, 60, 90, 120) for m in range(start, start+5)}
        clear.update(range(150, 180))
        self.assertEqual(self.offsets(self.search(clear, 190)), [(150, 179)])

    def test_fifteen_minute_run_with_only_one_clear_coarse_marker(self):
        self.assertEqual(self.offsets(self.search(set(range(13, 29)), 40)), [(13, 28)])

    def test_return_five_longest_after_complete_discovery(self):
        clear = set()
        intervals = [(0, 20), (50, 71), (100, 122), (150, 173),
                     (200, 224), (250, 275), (300, 330)]
        for a, b in intervals:
            clear.update(range(a, b))
        self.assertEqual(self.offsets(self.search(clear, 340)),
                         [(a, b-1) for a, b in intervals[:1:-1]])

    def test_no_checks_outside_horizon_and_no_repeated_checks(self):
        seen = Counter()
        end = self.start + timedelta(minutes=35, seconds=30)
        def is_obstructed(t):
            self.assertLessEqual(self.start, t)
            self.assertLessEqual(t, end)
            seen[t] += 1
            return False
        windows = find_windows(is_obstructed, self.start, end)
        self.assertEqual(self.offsets(windows), [(0, 35.5)])
        self.assertTrue(all(n == 1 for n in seen.values()))

    def test_all_obstructed_and_short_runs(self):
        self.assertEqual(self.search(set(), 60), [])
        self.assertEqual(self.search(set(range(14)), 60), [])

    def test_short_or_empty_horizon(self):
        self.assertEqual(self.search(set(range(14)), 13), [])
        self.assertEqual(self.search({0}, 0), [])

    def test_rank_by_actual_duration_before_rounding(self):
        clear = set(range(16)) | set(range(30, 46)) | {45.4}
        windows = self.search(clear, 45.4)
        self.assertEqual(self.offsets(windows), [(30, 45.4), (0, 15)])

    def test_threat_between_clear_minutes_splits_window(self):
        def obstructed(t):
            seconds = (t-self.start).total_seconds()
            return 1190 <= seconds <= 1210
        windows = find_windows(obstructed, self.start, self.start+timedelta(minutes=40))
        self.assertEqual(self.offsets(windows), [(0, 1180/60), (1220/60, 40)])

    def test_start_between_minutes_is_recovered_from_fringe(self):
        def obstructed(t):
            return not 250 <= (t-self.start).total_seconds() <= 1150
        windows = find_windows(obstructed, self.start, self.start+timedelta(minutes=30))
        self.assertEqual(self.offsets(windows), [(250/60, 1150/60)])

    def test_fine_check_rejects_fifteen_minute_bin_without_clear_endpoint(self):
        windows = find_windows(lambda t: (t-self.start).total_seconds() >= 900,
                               self.start, self.start+timedelta(minutes=30))
        self.assertEqual(windows, [])

    def test_shortened_candidate_does_not_hide_later_qualifying_window(self):
        def obstructed(t):
            s = (t-self.start).total_seconds()
            return not (0 <= s <= 1200 or 1800 <= s <= 2880) or s == 600+30
        windows = find_windows(obstructed, self.start, self.start+timedelta(minutes=50))
        self.assertEqual(self.offsets(windows), [(30, 48)])

    def test_launch_grid_is_exact_and_independent_of_flight_spacing(self):
        start = self.start+timedelta(microseconds=811735)
        points = launch_grid(start, start+timedelta(hours=6, seconds=3), 10)
        self.assertEqual([(p-start).total_seconds() for p in points[:-1]],
                         list(range(0, 21601, 10)))
        self.assertEqual(points[-1], start+timedelta(hours=6, seconds=3))
        self.assertEqual(len(points), len(set(points)))

    def test_invalid_grid_spacing(self):
        for step in (0, -10, 7, 90, 10.5, float('inf')):
            with self.subTest(step=step), self.assertRaises(ValueError):
                find_windows(lambda t: False, self.start,
                             self.start+timedelta(minutes=30), launch_step_seconds=step)

    def test_fine_discovery_matches_exhaustive_enumeration(self):
        spans = [(250, 1150), (1810, 2940), (3610, 4880),
                 (5430, 6710), (7210, 8650), (9060, 10580), (11000, 12650)]
        def obstructed(t):
            s = (t-self.start).total_seconds()
            return not any(a <= s <= b for a, b in spans) or s == 8110
        end = self.start+timedelta(seconds=13200)
        expected = []
        for unsafe, group in groupby(launch_grid(self.start, end, 10), key=obstructed):
            points = list(group)
            duration = (points[-1]-points[0]).total_seconds()
            if not unsafe and duration >= 900:
                expected.append({'start': points[0].isoformat(), 'end': points[-1].isoformat(),
                                 'duration_minutes': round(duration/60, 2)})
        expected.sort(key=lambda w: (-(datetime.fromisoformat(w['end'])-
                                      datetime.fromisoformat(w['start'])).total_seconds(), w['start']))
        self.assertEqual(find_windows(obstructed, self.start, end), expected[:5])


if __name__ == '__main__':
    unittest.main()
