"""Off-Pi tests that a crashing Bluetooth poll (backend/bluetooth.py) is logged
once, frees the busy flag, keeps the last state, and lets the next poll run.
BlueZ is faked, and the worker thread runs right where it's started.

    python3 -m unittest tests.test_bluetooth
"""

import json
import subprocess
import unittest
from types import SimpleNamespace
from unittest import mock

from PyQt6.QtCore import QCoreApplication

from backend.bluetooth import BluetoothAudio

app = QCoreApplication.instance() or QCoreApplication([])


class InlineThread:
    """Stands in for threading.Thread: start() runs the work on the spot."""

    def __init__(self, target=None, daemon=None):
        self.target = target

    def start(self):
        self.target()


INLINE = mock.patch("backend.bluetooth.threading", SimpleNamespace(Thread=InlineThread))


def phone(alias, paired=True, trusted=True):
    """What busctl says about an adapter and one connected phone."""
    def v(kind, data):
        return {"type": kind, "data": data}
    return {
        "/org/bluez/hci0": {"org.bluez.Adapter1": {"Discoverable": v("b", False)}},
        "/org/bluez/hci0/dev_AA": {"org.bluez.Device1": {
            "Alias": v("s", alias), "Paired": v("b", paired), "Trusted": v("b", trusted),
            "Connected": v("b", True)}},
    }


def busctl_says(objects):
    out = json.dumps({"type": "a{oa{sa{sv}}}", "data": [objects]})
    return subprocess.CompletedProcess(["busctl"], 0, out, "")


def logged(printed):
    return [c.args[0] for c in printed.call_args_list if c.args and "Bluetooth" in str(c.args[0])]


class PollFailureTest(unittest.TestCase):
    def setUp(self):
        self.bt = BluetoothAudio()
        INLINE.start()
        self.printed = mock.patch("builtins.print").start()
        self.addCleanup(mock.patch.stopall)

    def poll(self, objects):
        with mock.patch("backend.bluetooth._busctl", return_value=busctl_says(objects)):
            self.bt._tick()

    def test_two_crashing_polls_log_once_and_keep_the_state(self):
        self.poll(phone("Pixel"))
        self.assertEqual(self.bt.deviceName, "Pixel")
        with mock.patch("backend.bluetooth.parse_objects", side_effect=TypeError("bad data")):
            for _ in range(2):
                self.poll(phone("Pixel"))
                self.assertFalse(self.bt._busy)           # the next poll can run
                self.assertEqual(self.bt.deviceName, "Pixel")
        lines = logged(self.printed)
        self.assertEqual(len(lines), 1)
        self.assertIn("TypeError: bad data", lines[0])
        self.assertIn("Traceback", lines[0])              # an unexpected kind of error

    def test_the_next_poll_after_a_crash_applies_good_data(self):
        self.poll(phone("Pixel"))
        with mock.patch("backend.bluetooth.parse_objects", side_effect=AttributeError("nope")):
            self.poll(phone("Pixel"))
        self.poll(phone("Pixel 9"))
        self.assertEqual(self.bt.deviceName, "Pixel 9")
        self.assertFalse(self.bt._busy)
        lines = logged(self.printed)
        self.assertEqual(len(lines), 2)
        self.assertIn("working again", lines[1])

    def test_a_different_error_is_logged_again(self):
        with mock.patch("backend.bluetooth.parse_objects", side_effect=TypeError("one")):
            self.poll({})
        with mock.patch("backend.bluetooth.parse_objects", side_effect=KeyError("two")):
            self.poll({})
        self.assertEqual(len(logged(self.printed)), 2)

    def test_junk_json_from_busctl_is_a_crash_not_a_blank_state(self):
        self.poll(phone("Pixel"))
        bad = subprocess.CompletedProcess(["busctl"], 0, json.dumps({"data": 5}), "")
        with mock.patch("backend.bluetooth._busctl", return_value=bad):
            self.bt._tick()                               # 5[0]: a TypeError
        self.assertFalse(self.bt._busy)
        self.assertEqual(self.bt.deviceName, "Pixel")
        self.assertEqual(len(logged(self.printed)), 1)

    def test_a_crash_while_trusting_still_applies_the_poll(self):
        def busctl(*args, **kw):
            if args[0] == "set-property":
                raise TypeError("trust")
            return busctl_says(phone("Pixel", trusted=False))
        with mock.patch("backend.bluetooth._busctl", side_effect=busctl):
            for _ in range(2):
                self.bt._tick()
                self.assertFalse(self.bt._busy)
        self.assertEqual(self.bt.deviceName, "Pixel")
        self.assertEqual(len(logged(self.printed)), 1)

    def test_no_bluez_is_the_usual_quiet_blank_state(self):
        self.poll(phone("Pixel"))
        for error in (FileNotFoundError("busctl"), subprocess.TimeoutExpired("busctl", 3)):
            with mock.patch("backend.bluetooth._busctl", side_effect=error):
                self.bt._tick()
            self.assertFalse(self.bt._busy)
            self.assertFalse(self.bt.adapterPresent)
            self.assertEqual(self.bt.deviceName, "")
        self.assertEqual(logged(self.printed), [])


if __name__ == "__main__":
    unittest.main()
