"""Off-Pi tests for backend/wifi.py: a bad line in the scan doesn't lose it, and
a crashing scan, join or forget is logged once, frees the busy flag, keeps
what the page had, and lets the next one run. nmcli is faked, and the worker
thread runs right where it's started.

    python3 -m unittest tests.test_wifi
"""

import unittest
from types import SimpleNamespace
from unittest import mock

from PyQt6.QtCore import QCoreApplication

from backend.wifi import HOTSPOT_ADDRESS, IPHONE_GATEWAY, Wifi, scan

app = QCoreApplication.instance() or QCoreApplication([])


class InlineThread:
    """Stands in for threading.Thread: start() runs the work on the spot."""

    def __init__(self, target=None, daemon=None):
        self.target = target

    def start(self):
        self.target()


INLINE = mock.patch("backend.wifi.threading", SimpleNamespace(Thread=InlineThread))


def logged(printed):
    return [c.args[0] for c in printed.call_args_list if c.args and "Wi-Fi" in str(c.args[0])]


class ScanTest(unittest.TestCase):
    def scan(self, listing):
        with mock.patch("backend.wifi.nmcli", return_value=(0, listing, "")):
            return scan(rescan=False)

    def test_sorted_with_the_active_network_first(self):
        nets = self.scan(" :Cafe:80:WPA2\n*:Phone:40:WPA2\n :Open:60:--\n")
        self.assertEqual([n["ssid"] for n in nets], ["Phone", "Cafe", "Open"])
        self.assertTrue(nets[0]["active"])
        self.assertFalse(nets[2]["secure"])

    def test_a_bad_signal_doesnt_lose_the_scan(self):
        nets = self.scan("*:Phone:???:WPA2\n :Cafe:80:WPA2\n :Open::--\n :Odd:-:WPA2\n")
        by_name = {n["ssid"]: n for n in nets}
        self.assertEqual(set(by_name), {"Phone", "Cafe", "Open", "Odd"})
        self.assertEqual(by_name["Phone"]["signal"], 0)
        self.assertTrue(by_name["Phone"]["active"])       # the tether fallback relies on this
        self.assertEqual(by_name["Open"]["signal"], 0)
        self.assertEqual(by_name["Cafe"]["signal"], 80)


class WorkerFailureTest(unittest.TestCase):
    def setUp(self):
        self.wifi = Wifi({})
        self.wifi._available = True          # no nmcli on a Mac
        INLINE.start()
        self.printed = mock.patch("builtins.print").start()
        self.addCleanup(mock.patch.stopall)

    def refresh(self, nets=None, error=None):
        """One scan, with scan() faked to give nets or raise error."""
        fake = mock.patch("backend.wifi.scan", side_effect=error) if error else \
            mock.patch("backend.wifi.scan", return_value=nets)
        with fake, mock.patch("backend.wifi.can_control", return_value=False), \
                mock.patch("backend.wifi.saved_connections", return_value=[]):
            self.wifi.refresh()

    def test_two_crashing_scans_log_once_and_keep_the_list(self):
        self.refresh([{"ssid": "Cafe", "signal": 80, "secure": True, "active": False}])
        self.assertEqual([n["ssid"] for n in self.wifi.networks], ["Cafe"])
        for _ in range(2):
            self.refresh(error=TypeError("surprise"))
            self.assertFalse(self.wifi._scanning)         # the next scan can run
            self.assertEqual([n["ssid"] for n in self.wifi.networks], ["Cafe"])
        lines = logged(self.printed)
        self.assertEqual(len(lines), 1)
        self.assertIn("TypeError: surprise", lines[0])
        self.assertIn("Traceback", lines[0])

    def test_the_next_scan_after_a_crash_applies_good_data(self):
        self.refresh(error=TypeError("surprise"))
        self.refresh([{"ssid": "Phone", "signal": 50, "secure": True, "active": False}])
        self.assertEqual([n["ssid"] for n in self.wifi.networks], ["Phone"])
        self.assertFalse(self.wifi._scanning)
        lines = logged(self.printed)
        self.assertEqual(len(lines), 2)
        self.assertIn("working again", lines[1])

    def test_a_crashing_join_says_so_and_frees_the_page(self):
        self.wifi._available = False         # so the refresh after joining stays out of it
        with mock.patch("backend.wifi.nmcli", side_effect=TypeError("surprise")):
            for _ in range(2):
                self.wifi.join("Phone", "secret")
                self.assertEqual(self.wifi.busy, "")
                self.assertEqual(self.wifi.message, "Couldn't join Phone")
        self.assertEqual(len(logged(self.printed)), 1)
        with mock.patch("backend.wifi.nmcli", return_value=(0, "", "")):
            self.wifi.join("Phone", "secret")        # and the next join runs
        self.assertEqual(self.wifi.message, "Connected to Phone")
        self.assertEqual(self.wifi.busy, "")
        self.assertIn("working again", logged(self.printed)[-1])

    def test_a_crashing_forget_says_so_and_frees_the_page(self):
        self.wifi._available = False
        self.wifi._saved = [{"uuid": "u1", "name": "Phone", "type": "802-11-wireless",
                             "device": "", "ssid": "Phone"}]
        with mock.patch("backend.wifi.nmcli", side_effect=TypeError("surprise")):
            self.wifi.forget("Phone")
        self.assertEqual(self.wifi.busy, "")
        self.assertEqual(self.wifi.message, "Couldn't forget Phone")
        with mock.patch("backend.wifi.nmcli", return_value=(0, "", "")):
            self.wifi.forget("Phone")
        self.assertEqual(self.wifi.message, "Forgot Phone")

    def test_a_crash_in_the_hotspot_address_is_logged_once(self):
        with mock.patch("backend.wifi.nmcli", side_effect=TypeError("surprise")):
            for _ in range(2):
                self.wifi._ensure_hotspot_address()      # must not raise
        self.assertEqual(len(logged(self.printed)), 1)
        reply = [(0, f"IP4.GATEWAY:{IPHONE_GATEWAY}\nGENERAL.CONNECTION:Phone\n", ""),
                 (0, HOTSPOT_ADDRESS, "")]
        with mock.patch("backend.wifi.nmcli", side_effect=reply):
            self.wifi._ensure_hotspot_address()
        self.assertIn("working again", logged(self.printed)[-1])


if __name__ == "__main__":
    unittest.main()
