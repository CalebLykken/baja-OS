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
from backend.roadinfo import TRACE_EVERY_S, RoadInfo

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

    def test_status_updates_add_nothing(self):
        self.fix(0)
        for report in ({"gpsd": True}, {"receiver": True}, {"sats": 6, "view": 12},
                       {"sats": 7, "view": 12}, {"gpsd": False}):
            self.now += 0.9
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
                     b"<html>", OSError("refused")):
            with self.subTest(body=body):
                self.assertEqual(self.match(body), (50, "Main St"))

    def test_a_name_that_isnt_text(self):
        self.assertEqual(self.match(b'{"edges": [{"speed_limit": 30, "names": [null]}]}'), (30, "None"))


if __name__ == "__main__":
    unittest.main()
