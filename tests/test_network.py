"""Off-Pi tests that a crashing network check (backend/network.py) is logged
once, frees the busy flag, keeps the last result, and lets the next check
run. The lookups are faked, and the worker thread runs right where it's
started.

    python3 -m unittest tests.test_network
"""

import unittest
from types import SimpleNamespace
from unittest import mock

from PyQt6.QtCore import QCoreApplication

from backend.network import Network, wifi_name

app = QCoreApplication.instance() or QCoreApplication([])


class InlineThread:
    """Stands in for threading.Thread: start() runs the work on the spot."""

    def __init__(self, target=None, daemon=None):
        self.target = target

    def start(self):
        self.target()


INLINE = mock.patch("backend.network.threading", SimpleNamespace(Thread=InlineThread))


def logged(printed):
    return [c.args[0] for c in printed.call_args_list if c.args and "Network" in str(c.args[0])]


class CheckFailureTest(unittest.TestCase):
    def setUp(self):
        self.net = Network()
        INLINE.start()
        self.printed = mock.patch("builtins.print").start()
        self.addCleanup(mock.patch.stopall)

    def check(self, ip="10.0.0.5", ssid="Phone", online=True, error=None):
        ssid_lookup = mock.patch("backend.network.wifi_name", side_effect=error) if error else \
            mock.patch("backend.network.wifi_name", return_value=ssid)
        with mock.patch("backend.network.local_ip", return_value=ip), ssid_lookup, \
                mock.patch("backend.network.is_online", return_value=online):
            self.net._check()

    def test_two_crashing_checks_log_once_and_keep_the_result(self):
        self.check()
        self.assertEqual((self.net.ip, self.net.ssid, self.net.online), ("10.0.0.5", "Phone", True))
        for _ in range(2):
            self.check(error=TypeError("surprise"))
            self.assertFalse(self.net._busy)              # the next check can run
            self.assertEqual((self.net.ip, self.net.ssid, self.net.online), ("10.0.0.5", "Phone", True))
        lines = logged(self.printed)
        self.assertEqual(len(lines), 1)
        self.assertIn("TypeError: surprise", lines[0])
        self.assertIn("Traceback", lines[0])

    def test_the_next_check_after_a_crash_applies_good_data(self):
        self.check(error=TypeError("surprise"))
        self.assertFalse(self.net.checked)                # never had a good answer
        self.check(ip="", ssid="", online=False)
        self.assertTrue(self.net.checked)
        self.assertFalse(self.net.online)
        self.assertFalse(self.net._busy)
        lines = logged(self.printed)
        self.assertEqual(len(lines), 2)
        self.assertIn("working again", lines[1])

    def test_a_crash_in_a_later_lookup_is_caught_too(self):
        with mock.patch("backend.network.local_ip", return_value="10.0.0.5"), \
                mock.patch("backend.network.wifi_name", return_value="Phone"), \
                mock.patch("backend.network.is_online", side_effect=AttributeError("x")):
            self.net._check()
        self.assertFalse(self.net._busy)
        self.assertEqual(len(logged(self.printed)), 1)


class WifiNameTest(unittest.TestCase):
    def test_reads_the_cached_list_so_the_radio_is_not_scanned(self):
        listing = SimpleNamespace(stdout="no:Cafe\nyes:Phone\n")
        with mock.patch("backend.network.shutil.which", return_value="/usr/bin/nmcli"), \
                mock.patch("backend.network.subprocess.run", return_value=listing) as run:
            self.assertEqual(wifi_name(), "Phone")
        args = run.call_args.args[0]
        self.assertEqual(args[args.index("--rescan") + 1], "no")


if __name__ == "__main__":
    unittest.main()
