"""Off-Pi tests for backend/startup.py: the startup phase clock and its summary
line, and reading the system uptime.

    python3 -m unittest tests.test_startup
"""

import unittest
from unittest import mock

from backend.startup import StartupClock, since_boot


class FakeNow:
    """A monotonic clock the test moves by hand, in seconds."""

    def __init__(self, t=100.0):
        self.t = t

    def __call__(self):
        return self.t


def no_uptime():
    return None


class MarkTest(unittest.TestCase):
    def test_marks_keep_order_and_ms_since_creation(self):
        now = FakeNow(100.0)
        clock = StartupClock(now=now, uptime=no_uptime)
        now.t = 100.412
        clock.mark("imports")
        now.t = 100.655
        clock.mark("backends")
        self.assertEqual(clock._marks, [("imports", 412), ("backends", 655)])

    def test_mark_is_rounded_to_whole_ms(self):
        now = FakeNow(0.0)
        clock = StartupClock(now=now, uptime=no_uptime)
        now.t = 0.0014
        clock.mark("a")
        now.t = 0.0016
        clock.mark("b")
        self.assertEqual(clock._marks, [("a", 1), ("b", 2)])

    def test_duplicate_mark_keeps_the_first_time(self):
        now = FakeNow(0.0)
        clock = StartupClock(now=now, uptime=no_uptime)
        now.t = 1.0
        clock.mark("qml")
        now.t = 5.0
        clock.mark("qml")
        self.assertEqual(clock._marks, [("qml", 1000)])


class SummaryTest(unittest.TestCase):
    def test_summary_lists_marks_in_order(self):
        now = FakeNow(0.0)
        clock = StartupClock(now=now, uptime=no_uptime)
        for t, name in [(0.412, "imports"), (0.655, "backends"), (1.840, "qml"),
                        (2.105, "first frame"), (2.190, "started")]:
            now.t = t
            clock.mark(name)
        self.assertEqual(clock.summary(),
                         "Startup: imports 412 ms, backends 655 ms, qml 1840 ms, "
                         "first frame 2105 ms, started 2190 ms")

    def test_summary_adds_system_uptime_when_known(self):
        now = FakeNow(0.0)
        clock = StartupClock(now=now, uptime=lambda: 14.23)
        now.t = 0.5
        clock.mark("started")
        self.assertEqual(clock.summary(), "Startup: started 500 ms (system up 14.2 s)")

    def test_summary_without_uptime_has_no_suffix(self):
        now = FakeNow(0.0)
        clock = StartupClock(now=now, uptime=no_uptime)
        now.t = 0.5
        clock.mark("started")
        self.assertEqual(clock.summary(), "Startup: started 500 ms")

    def test_summary_with_no_marks_is_still_one_line(self):
        clock = StartupClock(now=FakeNow(), uptime=no_uptime)
        self.assertEqual(clock.summary(), "Startup: ")

    def test_default_clock_reads_real_time_without_error(self):
        clock = StartupClock()
        clock.mark("imports")
        self.assertTrue(clock.summary().startswith("Startup: imports "))


class SinceBootTest(unittest.TestCase):
    def test_reads_seconds_from_proc_uptime(self):
        with mock.patch("builtins.open", mock.mock_open(read_data="14.25 40.10\n")):
            self.assertAlmostEqual(since_boot(), 14.25)

    def test_none_when_proc_uptime_is_missing(self):
        with mock.patch("builtins.open", side_effect=FileNotFoundError):
            self.assertIsNone(since_boot())

    def test_none_when_proc_uptime_is_garbage(self):
        with mock.patch("builtins.open", mock.mock_open(read_data="")):
            self.assertIsNone(since_boot())
        with mock.patch("builtins.open", mock.mock_open(read_data="soon\n")):
            self.assertIsNone(since_boot())


if __name__ == "__main__":
    unittest.main()
