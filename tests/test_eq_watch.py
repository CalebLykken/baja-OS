"""Off-Pi tests for how often backend/eq.py looks for the PipeWire filter: every
CHECK_EVERY_MS while it is missing, and only every FOUND_CHECK_MS once it is
running (a PipeWire restart is the only thing that can change that). No
threads are started and pw-cli is never called.

    python3 -m unittest tests.test_eq_watch
"""

import unittest
from unittest import mock

try:
    from PyQt6.QtCore import QCoreApplication

    from backend import eq
    from backend.eq import CHECK_EVERY_MS, FOUND_CHECK_MS, Equalizer
except ImportError as e:
    raise unittest.SkipTest(f"PyQt6 isn't installed ({e})")

app = QCoreApplication.instance() or QCoreApplication([])


class FakeSettings:
    def __init__(self):
        self.d = {}

    def get(self, k, default=None):
        return self.d.get(k, default)

    def set(self, k, v):
        self.d[k] = v


def make():
    s = FakeSettings()
    s.d["eq"] = "4,2,0,2,3"
    with mock.patch("backend.eq.shutil.which", return_value="/usr/bin/pw-cli"):
        return Equalizer(s)


class WatchPaceTests(unittest.TestCase):
    def test_fresh_timer_looks_every_check_interval(self):
        e = make()
        self.assertEqual(e._timer.interval(), CHECK_EVERY_MS)

    def test_found_slows_to_found_interval(self):
        e = make()
        e._on_found((57, 1000))
        self.assertEqual(e._timer.interval(), FOUND_CHECK_MS)

    def test_missing_again_speeds_back_up(self):
        e = make()
        e._on_found((57, 1000))
        e._on_found(None)
        self.assertEqual(e._timer.interval(), CHECK_EVERY_MS)

    def test_repeat_found_keeps_interval_and_does_not_push_again(self):
        e = make()
        e._on_found((57, 1000))
        with mock.patch.object(e, "_push") as push:
            e._on_found((57, 1000))
        self.assertEqual(e._timer.interval(), FOUND_CHECK_MS)
        push.assert_not_called()

    def test_restart_under_new_serial_pushes_gains(self):
        e = make()
        e._on_found((57, 1000))
        with mock.patch.object(e, "_push") as push:
            e._on_found((57, 1001))
        self.assertEqual(e._timer.interval(), FOUND_CHECK_MS)
        push.assert_called_once()


class RestartTests(unittest.TestCase):
    """A restarted filter must get its gains back without waiting out the
    slow found-interval: its sink reappearing triggers a check."""

    def test_output_list_change_triggers_a_check(self):
        e = make()
        e._on_found((57, 1000))            # slow-watch mode
        with mock.patch("backend.eq.threading.Thread"), \
                mock.patch("backend.eq.QMediaDevices") as devices:
            e.start()
            slot = devices.return_value.audioOutputsChanged.connect.call_args[0][0]
        with mock.patch("backend.eq.threading.Thread") as thread:
            slot()
        thread.assert_called_once_with(target=e._find, daemon=True)
        thread.return_value.start.assert_called_once()

    def test_restart_seen_by_that_check_pushes_gains(self):
        e = make()
        e._on_found((57, 1000))
        with mock.patch.object(e, "_push") as push:
            e._on_found((58, 1001))        # what _find reports after the restart
        push.assert_called_once()


if __name__ == "__main__":
    unittest.main()
