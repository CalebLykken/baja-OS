"""Off-Pi tests for the road-match trace (backend/roadinfo.py): one entry per
GPS fix, none for status updates, and about one a second however often the
receiver reports, with a clock that's just a number.

    python3 -m unittest tests.test_roadinfo
"""

import io
import json
import unittest
from types import SimpleNamespace
from unittest import mock

from PyQt6.QtCore import QCoreApplication

from backend.gps import Gps
from backend.roadinfo import GAP_S, HELD_MAX_S, TRACE_EVERY_S, RoadInfo, parse_match

app = QCoreApplication.instance() or QCoreApplication([])


def real(n):
    """The n-th position reported: lat says which one it was."""
    return {"lat": 47.0 + n / 1000, "lon": -122.0, "speed": 20.0, "heading": 90.0, "source": "gps"}


class TraceTest(unittest.TestCase):
    def setUp(self):
        self.now = 100.0
        # Gps (is the fix fresh?) and RoadInfo (how long since the last one?) both read the clock.
        clock = mock.patch("backend.roadinfo.time.monotonic", lambda: self.now)
        clock.start()
        self.addCleanup(clock.stop)
        self.gps = Gps()
        self.info = RoadInfo(self.gps)

    def fix(self, n, after=1.0):
        self.now += after
        self.gps._apply(real(n))

    def trace(self):
        """Which positions are in the trace, as the n each was reported with."""
        return [round((lat - 47.0) * 1000) for lat, _ in self.info._fixes]

    def test_one_entry_per_fix(self):
        for n in range(3):
            self.fix(n)
        self.assertEqual(self.trace(), [0, 1, 2])

    def test_a_fix_after_a_gap_starts_the_trace_again(self):
        for n in range(3):
            self.fix(n)
        self.fix(3, after=GAP_S + 1)
        self.assertEqual(self.trace(), [3])

    def test_a_gap_just_under_the_limit_keeps_the_old_points(self):
        for n in range(3):
            self.fix(n)
        self.fix(3, after=GAP_S - 0.5)
        self.assertEqual(self.trace(), [0, 1, 2, 3])

    def test_status_updates_add_nothing(self):
        self.fix(0)
        for report in ({"gpsd": True}, {"receiver": True}, {"sats": 6, "view": 12},
                       {"sats": 7, "view": 12}, {"gpsd": False}):
            self.now += 0.5                       # 2.5 s in all: well inside the gap, so the trace stays
            self.gps._apply(report)
        self.assertEqual(self.trace(), [0])
        self.fix(1)
        self.assertEqual(self.trace(), [0, 1])

    def test_about_one_entry_a_second_at_a_higher_receiver_rate(self):
        for n in range(60):                       # 12 s of fixes, 5 a second
            self.fix(n, after=0.2)
        trace = self.trace()
        self.assertEqual(len(trace), 10)
        gaps = [b - a for a, b in zip(trace, trace[1:])]
        self.assertTrue(all(4 <= g <= 5 for g in gaps), gaps)   # 0.8 to 1 s apart
        self.assertGreaterEqual((trace[-1] - trace[0]) * 0.2, 7)  # still about 10 s of driving

    def test_a_fix_less_than_the_spacing_after_the_last_is_skipped(self):
        self.fix(0)
        self.fix(1, after=TRACE_EVERY_S - 0.2)
        self.assertEqual(self.trace(), [0])
        self.fix(2, after=0.3)                    # 0.9 s since the one that was kept
        self.assertEqual(self.trace(), [0, 2])

    def test_a_stale_position_is_not_added(self):
        self.fix(0)
        self.now += 11                            # the fix is old now
        self.assertTrue(self.gps.stale)
        self.info._on_fix()
        self.assertEqual(self.trace(), [0])


class InlineThread:
    """Stands in for threading.Thread: start() runs the work on the spot."""

    def __init__(self, target=None, name=None, daemon=None):
        self.target = target

    def start(self):
        self.target()


class MatchTest(unittest.TestCase):
    """Whatever the router answers, the match comes back, so the next one
    can be asked for (a stuck _busy meant no speed limit until a restart)."""

    def setUp(self):
        inline = mock.patch("backend.roadinfo.threading", SimpleNamespace(Thread=InlineThread))
        inline.start()
        self.addCleanup(inline.stop)
        self.now = 100.0
        clock = mock.patch("backend.roadinfo.time.monotonic", lambda: self.now)
        clock.start()
        self.addCleanup(clock.stop)
        self.gps = Gps()
        self.info = RoadInfo(self.gps)
        for n in range(4):
            self.now += 1.0
            self.gps._apply(real(n))

    def match(self, body):
        def urlopen(req, timeout):
            if isinstance(body, Exception):
                raise body
            return io.BytesIO(body)
        with mock.patch("backend.roadinfo.urllib.request.urlopen", urlopen):
            self.info._check()
        self.assertFalse(self.info._busy)
        return self.info.speedLimit, self.info.roadName

    def test_a_match(self):
        edges = {"edges": [{"speed_limit": 50, "names": ["Main St"]}]}
        self.assertEqual(self.match(json.dumps(edges).encode()), (50, "Main St"))

    def test_answers_that_arent_the_usual_shape_keep_the_last_match(self):
        self.match(json.dumps({"edges": [{"speed_limit": 50, "names": ["Main St"]}]}).encode())
        for body in (b"[1]", b'"x"', b"null", b'{"edges": [5]}', b'{"edges": {"a": 1}}',
                     b'{"edges": [{"speed_limit": "fast"}]}', b'{"edges": [{"names": {"a": 1}}]}',
                     b'{"edges": [{"speed_limit": Infinity}]}', b'{"edges": [{"speed_limit": NaN}]}',
                     b'{"edges": [{"speed_limit": 1e400}]}', b'{"edges": [{"speed_limit": true}]}',
                     b'{"edges": [{"speed_limit": -5}]}', b'{"edges": [{"speed_limit": 1000000000000}]}',
                     b"<html>", OSError("refused")):
            with self.subTest(body=body):
                self.assertEqual(self.match(body), (50, "Main St"))

    def test_an_infinite_limit_does_not_reach_the_error_log(self):
        self.match(json.dumps({"edges": [{"speed_limit": 50, "names": ["Main St"]}]}).encode())
        with mock.patch("threading.excepthook") as excepthook:
            self.assertEqual(self.match(b'{"edges": [{"speed_limit": Infinity}]}'), (50, "Main St"))
        excepthook.assert_not_called()

    def test_a_name_that_isnt_text(self):
        self.assertEqual(self.match(b'{"edges": [{"speed_limit": 30, "names": [null]}]}'), (30, ""))

    def test_an_empty_name_list(self):
        self.assertEqual(self.match(b'{"edges": [{"speed_limit": 30, "names": []}]}'), (30, ""))

    def test_a_fractional_limit_is_rounded(self):
        self.assertEqual(self.match(b'{"edges": [{"speed_limit": 49.6}]}'), (50, ""))

    def test_a_numeric_string_limit(self):
        self.assertEqual(self.match(b'{"edges": [{"speed_limit": "50"}]}'), (50, ""))


class ParseMatchTest(unittest.TestCase):
    def edge(self, **fields):
        return {"edges": [fields]}

    def test_the_usual_shape(self):
        self.assertEqual(parse_match(self.edge(speed_limit=50, names=["Main St", "Route 9"])), (50, "Main St"))

    def test_the_last_edge_is_the_road_now(self):
        answer = {"edges": [{"speed_limit": 30, "names": ["Old"]}, {"speed_limit": 80, "names": ["New"]}]}
        self.assertEqual(parse_match(answer), (80, "New"))

    def test_no_limit_or_no_name_is_zero_or_empty(self):
        self.assertEqual(parse_match(self.edge()), (0, ""))
        self.assertEqual(parse_match(self.edge(speed_limit=None, names=None)), (0, ""))
        self.assertEqual(parse_match(self.edge(speed_limit=0, names=[])), (0, ""))

    def test_limits_that_are_not_sane_are_no_match(self):
        for value in (float("nan"), float("inf"), -1, 201, 10 ** 400, True, False, "fast", "inf", "nan", "", [50]):
            with self.subTest(value=value):
                self.assertIsNone(parse_match(self.edge(speed_limit=value)))

    def test_names_that_are_not_a_list_of_text_are_no_match_or_empty(self):
        self.assertIsNone(parse_match(self.edge(speed_limit=30, names={"a": 1})))
        self.assertEqual(parse_match(self.edge(speed_limit=30, names=[None])), (30, ""))
        self.assertEqual(parse_match(self.edge(speed_limit=30, names=[7, "Main St"])), (30, ""))

    def test_answers_that_are_not_the_usual_shape(self):
        for answer in ([1], "x", None, {}, {"edges": []}, {"edges": {"a": 1}}, {"edges": [5]}, {"edges": [None]}):
            with self.subTest(answer=answer):
                self.assertIsNone(parse_match(answer))


class HeldLimitTest(unittest.TestCase):
    """A red light must not lose the limit sign, and a parked truck runs no timer."""

    def setUp(self):
        inline = mock.patch("backend.roadinfo.threading", SimpleNamespace(Thread=InlineThread))
        inline.start()
        self.addCleanup(inline.stop)
        self.now = 100.0
        clock = mock.patch("backend.roadinfo.time.monotonic", lambda: self.now)
        clock.start()
        self.addCleanup(clock.stop)
        self.gps = Gps()
        self.info = RoadInfo(self.gps)
        self.assertFalse(self.info._timer.isActive())
        for n in range(4):
            self.now += 1.0
            self.gps._apply(real(n))
        self.assertTrue(self.info._timer.isActive())
        self.check(b'{"edges": [{"speed_limit": 50, "names": ["Main St"]}]}')
        self.assertEqual((self.info.speedLimit, self.info.roadName), (50, "Main St"))

    def check(self, body):
        with mock.patch("backend.roadinfo.urllib.request.urlopen",
                        lambda req, timeout: io.BytesIO(body)):
            self.info._check()

    def stop_at(self, n, speed=0.0):
        self.gps._apply(dict(real(n), speed=speed))

    def test_a_long_red_light_keeps_the_limit(self):
        self.stop_at(3)
        self.now += 60
        self.info._check()
        self.assertEqual((self.info.speedLimit, self.info.roadName), (50, "Main St"))

    def test_driving_on_without_a_match_clears_it(self):
        self.now += 60
        self.gps._apply(real(4))
        self.info._busy = True        # no new answer yet
        self.info._check()
        self.assertEqual((self.info.speedLimit, self.info.roadName), (0, ""))

    def test_stopped_but_far_from_the_match_clears_it(self):
        self.now += 60
        self.stop_at(3 + 200)         # 0.001 degree of latitude is about 111 m
        self.info._check()
        self.assertEqual(self.info.speedLimit, 0)

    def test_timer_stops_once_parked_with_nothing_held(self):
        self.stop_at(3)
        self.now += 60
        self.info._check()
        self.assertTrue(self.info._timer.isActive())    # still holding the limit
        self.stop_at(3 + 200)
        self.info._check()
        self.assertFalse(self.info._timer.isActive())
        self.gps._apply(real(300))
        self.assertTrue(self.info._timer.isActive())

    def test_a_parked_truck_drifting_a_little_drops_the_limit_in_the_end(self):
        self.gps._apply(dict(real(3), lat=47.0033, speed=0.0))   # about 33 m of drift, under HELD_AWAY_M
        self.now += HELD_MAX_S - 10
        self.info._check()
        self.assertEqual(self.info.speedLimit, 50)
        self.assertTrue(self.info._timer.isActive())
        self.now += 20
        self.info._check()
        self.assertEqual(self.info.speedLimit, 0)
        self.assertFalse(self.info._timer.isActive())


if __name__ == "__main__":
    unittest.main()
