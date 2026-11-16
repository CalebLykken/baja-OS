"""Off-Pi tests for backend/errorlog.py: the first few of each distinct error
are logged in full, repeats are counted and summarised, every one counts, and
logging never raises.

    python3 -m unittest tests.test_errorlog
"""

import io
import json
import unittest

from backend.errorlog import ErrorLog, QtMessages
from PyQt6.QtCore import QtMsgType


class FakeTimer:
    started = []

    def __init__(self, interval, function):
        self.interval, self.function, self.daemon = interval, function, False

    def start(self):
        FakeTimer.started.append(self)


def raised(exc, where=0):
    """(type, value, traceback) of exc raised from one of two places."""
    def a():
        raise exc

    def b():
        raise exc
    try:
        (a, b)[where]()
    except Exception as e:
        return type(e), e, e.__traceback__


class ErrorLogTest(unittest.TestCase):
    def setUp(self):
        FakeTimer.started = []
        self.out = io.StringIO()
        self.log = ErrorLog(out=self.out, full=3, every=60, timer=FakeTimer)

    def test_the_first_few_are_logged_in_full_then_only_counted(self):
        for _ in range(10):
            self.log.report(*raised(KeyError("k")))
        self.assertEqual(self.out.getvalue().count("Traceback"), 3)
        self.assertEqual(self.log.count(), 10)

    def test_a_summary_says_how_many_more(self):
        for _ in range(1243):
            self.log.report(*raised(KeyError("k")))
        self.log.flush()
        self.assertIn("Same error 1,240 more times in the last 60s: KeyError at", self.out.getvalue())

    def test_a_summary_counts_only_since_the_last_one(self):
        for _ in range(5):
            self.log.report(*raised(KeyError("k")))
        self.log.flush()
        self.log.report(*raised(KeyError("k")))
        self.log.flush()
        text = self.out.getvalue()
        self.assertIn("Same error 2 more times", text)
        self.assertIn("Same error 1 more times", text)
        self.log.flush()
        self.assertEqual(text, self.out.getvalue())          # nothing new: nothing written

    def test_one_timer_makes_sure_the_summary_comes_even_if_errors_stop(self):
        for _ in range(8):
            self.log.report(*raised(KeyError("k")))
        self.assertEqual(len(FakeTimer.started), 1)
        self.assertTrue(FakeTimer.started[0].daemon)
        FakeTimer.started[0].function()
        self.assertIn("Same error 5 more times", self.out.getvalue())
        self.log.report(*raised(KeyError("k")))              # a new quiet spell: a new timer
        self.assertEqual(len(FakeTimer.started), 2)

    def test_different_places_and_types_are_counted_apart(self):
        for where in (0, 1):
            for _ in range(5):
                self.log.report(*raised(KeyError("k"), where))
        for _ in range(5):
            self.log.report(*raised(ValueError("v")))
        self.assertEqual(self.out.getvalue().count("Traceback"), 9)
        self.assertEqual(self.log.count(), 15)

    def test_the_same_error_with_a_different_message_is_the_same_error(self):
        for i in range(6):
            self.log.report(*raised(KeyError(i)))
        self.assertEqual(self.out.getvalue().count("Traceback"), 3)

    def test_a_thread_label_is_used(self):
        self.log.report(*raised(KeyError("k")), label="Thread poller stopped on an error:")
        self.assertIn("Thread poller stopped on an error:", self.out.getvalue())

    def test_logging_never_raises(self):
        class Broken:
            def write(self, _):
                raise OSError("stderr is gone")

            def flush(self):
                raise OSError("stderr is gone")
        log = ErrorLog(out=Broken(), timer=FakeTimer)
        for _ in range(6):
            log.report(*raised(KeyError("k")))
        log.flush()
        log.report(None, None, None)
        self.assertEqual(log.count(), 7)

    def test_a_timer_that_cant_start_is_not_an_error(self):
        def no_threads(*_):
            raise RuntimeError("can't start new thread")
        log = ErrorLog(out=self.out, full=1, timer=no_threads)
        for _ in range(3):
            log.report(*raised(KeyError("k")))
        self.assertEqual(log.count(), 3)

    def test_distinct_errors_are_bounded(self):
        for i in range(300):
            exc = type(f"E{i}", (Exception,), {})("x")
            self.log.report(*raised(exc))
        self.assertLessEqual(len(self.log._kinds), 201)
        self.assertEqual(self.log.count(), 300)

    def test_a_stdlib_error_from_two_project_functions_is_two_errors(self):
        for fn in (self._parse_a, self._parse_b):
            for _ in range(5):
                self.log.report(*fn())
        self.assertEqual(self.out.getvalue().count("Traceback"), 6)

    def test_a_stdlib_error_from_one_project_function_is_one_error(self):
        for _ in range(10):
            self.log.report(*self._parse_a())
        self.assertEqual(self.out.getvalue().count("Traceback"), 3)

    def test_the_label_tells_otherwise_identical_errors_apart(self):
        for label in ("GPS: reader error, retrying:", "Knob: read error, retrying:"):
            for _ in range(5):
                self.log.report(*raised(KeyError("k")), label=label)
        self.assertEqual(self.out.getvalue().count("Traceback"), 6)
        self.log.flush()
        self.assertIn("Same error 2 more times in the last 60s: KeyError at", self.out.getvalue())

    def test_key_of_a_project_frame_error_is_unchanged(self):
        kind, where = ErrorLog.key(*raised(KeyError("k"))[::2])
        self.assertEqual(kind, "KeyError")
        self.assertRegex(where, r"^test_errorlog\.py:\d+ in [ab]$")

    def test_key_of_a_stdlib_error_names_the_project_frame_first(self):
        kind, where = ErrorLog.key(*self._parse_a()[::2])
        self.assertEqual(kind, "JSONDecodeError")
        self.assertRegex(where, r"^test_errorlog\.py:\d+ in _parse_a > decoder\.py:\d+ in raw_decode$")

    def test_a_relative_filename_is_still_found_in_the_project(self):
        import os
        rel = os.path.relpath(os.path.join(os.path.dirname(__file__), "rel_demo.py"))
        ns = {"json": json}
        exec(compile("def f():\n    json.loads('{')\n", rel, "exec"), ns)
        try:
            ns["f"]()
        except ValueError as e:
            where = ErrorLog.key(type(e), e.__traceback__)[1]
        self.assertRegex(where, r"^rel_demo\.py:\d+ in f > decoder\.py:\d+ in raw_decode$")

    @staticmethod
    def _parse_a():
        try:
            json.loads("{")
        except ValueError as e:
            return type(e), e, e.__traceback__

    @staticmethod
    def _parse_b():
        try:
            json.loads("{")
        except ValueError as e:
            return type(e), e, e.__traceback__


class QtMessagesTest(unittest.TestCase):
    def setUp(self):
        FakeTimer.started = []
        self.out = io.StringIO()
        self.qt = QtMessages(out=self.out, full=3, every=60, timer=FakeTimer)
        self.ctx = None

    def test_repeats_print_three_then_one_summary(self):
        msg = "qrc:/Gauge.qml:12: TypeError: Cannot read property 'x' of null"
        for _ in range(500):
            self.qt.handle(QtMsgType.QtWarningMsg, self.ctx, msg)
        self.assertEqual(self.out.getvalue().count(msg), 3)
        self.assertEqual(len(FakeTimer.started), 1)
        self.qt.flush()
        self.assertIn("Same message 497 more times", self.out.getvalue())

    def test_distinct_messages_each_print(self):
        for i in range(5):
            self.qt.handle(QtMsgType.QtWarningMsg, self.ctx, f"warning {i}")
        for i in range(5):
            self.assertIn(f"warning {i}", self.out.getvalue())

    def test_a_fatal_message_always_prints(self):
        for _ in range(6):
            self.qt.handle(QtMsgType.QtFatalMsg, self.ctx, "fatal thing")
        self.assertEqual(self.out.getvalue().count("fatal thing"), 6)

    def test_a_broken_stderr_does_not_raise(self):
        class Broken:
            def write(self, *_):
                raise OSError("closed")
            flush = write
        qt = QtMessages(out=Broken(), timer=FakeTimer)
        for _ in range(10):
            qt.handle(QtMsgType.QtWarningMsg, self.ctx, "x")
        qt.flush()


if __name__ == "__main__":
    unittest.main()
