from collections import Counter
from datetime import datetime, timedelta, timezone
from itertools import groupby
from pathlib import Path
import sys
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from windows import find_windows, launch_grid, verify_window_coverage, WindowVerificationError


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

    def test_five_second_validation_finds_threat_between_ten_second_checks(self):
        end = self.start+timedelta(minutes=40)
        def obstructed(point):
            return (point-self.start).total_seconds() == 1205
        baseline = find_windows(obstructed, self.start, end)
        diagnostics, events = {}, []
        verified = find_windows(obstructed, self.start, end, verification_step_seconds=5,
                                diagnostics=diagnostics, progress=events.append)
        self.assertEqual(self.offsets(baseline), [(0, 40)])
        self.assertEqual(self.offsets(verified), [(0, 20), (1210/60, 40)])
        self.assertEqual(diagnostics['validation_obstructed_samples'], 1)
        self.assertEqual(diagnostics['extra_validation_checks'], 240)
        self.assertEqual(events[-1]['status'], 'complete')
        self.assertTrue(any(e['phase']=='window_validation' for e in events))
        self.assertEqual(diagnostics['checked_launch_samples'],
                         diagnostics['clear_launch_samples']+diagnostics['obstructed_launch_samples'])
        for window in verified:
            self.assertEqual(window['verification']['status'], 'passed')
            self.assertLessEqual(window['verification']['max_launch_gap_seconds'], 5)

    def test_incomplete_extra_or_invalid_batch_results_fail_verification(self):
        for values in [[], [False]*10, [None]*4, [0]*4, [float('nan')]*4]:
            with self.subTest(values=values), self.assertRaises(WindowVerificationError):
                find_windows(lambda t: False, self.start, self.start+timedelta(minutes=30),
                             check_many=lambda points: iter(values))

    def test_final_audit_rejects_missing_unsafe_and_outside_horizon_samples(self):
        end = self.start+timedelta(minutes=15)
        points = launch_grid(self.start, end, 5)
        window = {'start':self.start, 'end':end}
        clear = dict.fromkeys(points, False)
        self.assertEqual(verify_window_coverage(window, clear, self.start, end, 5)['checked_launches'],181)
        missing = dict(clear); missing.pop(points[50])
        unsafe = {**clear, points[50]: True}
        for checked in [missing, unsafe]:
            with self.assertRaises(WindowVerificationError):
                verify_window_coverage(window, checked, self.start, end, 5)
        with self.assertRaises(WindowVerificationError):
            verify_window_coverage(window, clear, self.start+timedelta(seconds=1), end, 5)

    def test_final_audit_rejects_obstruction_off_the_required_grid(self):
        end = self.start+timedelta(minutes=15)
        checked = dict.fromkeys(launch_grid(self.start,end,5), False)
        checked[self.start+timedelta(seconds=2)] = True
        with self.assertRaises(WindowVerificationError):
            verify_window_coverage({'start':self.start,'end':end},checked,self.start,end,5)

    def test_final_validation_ranks_all_spans_before_five_window_limit(self):
        spans = [(0,1200),(1800,3060),(3600,4920),(5400,6780),(7200,8640),(9000,10800)]
        def obstructed(point):
            s=(point-self.start).total_seconds()
            return not any(a<=s<=b for a,b in spans) or s==9605
        windows=find_windows(obstructed,self.start,self.start+timedelta(seconds=11400),
                             verification_step_seconds=5)
        # The longest original candidate splits into shorter runs at 9605;
        # validating only the first five selected windows would lose (0,1200).
        self.assertEqual(self.offsets(windows),[(120,144),(90,113),(60,82),(30,51),(0,20)])

    def test_final_windows_agree_with_exhaustive_five_second_enumeration(self):
        spans=[(250,1150),(1810,2940),(3610,4880),(5430,6710),(7210,8650),(9060,10580),(11000,12650)]
        def obstructed(point):
            seconds=(point-self.start).total_seconds()
            return not any(a<=seconds<=b for a,b in spans) or seconds==8115
        end=self.start+timedelta(seconds=13200)
        expected=[]
        for unsafe,group in groupby(launch_grid(self.start,end,5),key=obstructed):
            points=list(group)
            seconds=(points[-1]-points[0]).total_seconds()
            if not unsafe and seconds>=900:
                expected.append({'start':points[0].isoformat(),'end':points[-1].isoformat(),
                                 'duration_minutes':round(seconds/60,2)})
        expected.sort(key=lambda w:(-(datetime.fromisoformat(w['end'])-datetime.fromisoformat(w['start'])).total_seconds(),w['start']))
        self.assertEqual(find_windows(obstructed,self.start,end,verification_step_seconds=5),expected[:5])

    def test_final_grid_recovers_fifteen_minutes_with_both_endpoints_between_discovery_samples(self):
        def obstructed(point):
            seconds = (point-self.start).total_seconds()
            return not 5 <= seconds <= 905
        end = self.start+timedelta(minutes=30)
        self.assertEqual(find_windows(obstructed,self.start,end), [])
        verified = find_windows(obstructed,self.start,end,verification_step_seconds=5)
        self.assertEqual(self.offsets(verified),[(5/60,905/60)])
        self.assertEqual(verified[0]['duration_minutes'],15)

    def test_launch_debug_logs_identify_their_request(self):
        with self.assertLogs('opas',level='DEBUG') as captured:
            find_windows(lambda point:False,self.start,self.start+timedelta(minutes=15),
                         diagnostics={'request_id':'trace-control'},workers=1)
        launches=[line for line in captured.output if 'launch=' in line]
        self.assertTrue(launches)
        self.assertTrue(all('request=trace-control' in line and 'classification=clear' in line for line in launches))


if __name__ == '__main__':
    unittest.main()
