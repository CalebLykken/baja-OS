"""Off-Pi tests for backend/wifi.py: a bad line in the scan doesn't lose it, a
crashing scan, join or forget is logged once, frees the busy flag, keeps
what the page had, and lets the next one run, and the radio only scans
(`--rescan yes`) while the Wi-Fi settings are open: startup and the
tethering watchdog read the connection list instead, and the watchdog still
brings the phone up when Wi-Fi is gone and lets it go once Wi-Fi is back.
nmcli and the clock are faked, and the worker thread runs right where it's
started.

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


class FakeNM:
    """Just enough of nmcli for the Wi-Fi backend: permissions, the connection
    list, a scan listing and a few settings. Records every call."""

    def __init__(self):
        self.calls = []
        self.control = "yes"
        self.list_rc = 0               # what `connection show` returns
        self.wifi_up = True
        self.gateway = "192.168.1.1"
        self.tether = False            # is there a saved Bluetooth connection?
        self.tether_up = False

    def __call__(self, *args, input=None, timeout=10):
        self.calls.append(args)
        if "PERMISSION,VALUE" in args:
            return 0, f"org.freedesktop.NetworkManager.network-control:{self.control}\n", ""
        if "UUID,NAME,TYPE,DEVICE" in args:
            if self.list_rc:
                return self.list_rc, "", "timed out"
            lines = ["u-phone:Phone:802-11-wireless:" + ("wlan0" if self.wifi_up else ""),
                     "u-lo:lo:loopback:lo"]
            if self.tether:
                lines.append("u-bt:Pixel Network:bluetooth:" + ("AA\\:BB" if self.tether_up else ""))
            return 0, "\n".join(lines) + "\n", ""
        if "802-11-wireless.ssid" in args:
            return 0, "Phone\n", ""
        if "wifi" in args and "list" in args:
            return 0, ("*" if self.wifi_up else " ") + ":Phone:70:WPA2\n :Cafe:60:WPA2\n", ""
        if "IP4.GATEWAY,GENERAL.CONNECTION" in args:
            return 0, f"IP4.GATEWAY:{self.gateway}\nGENERAL.CONNECTION:Phone\n", ""
        if args[:2] == ("connection", "up") and args[-1] == "u-bt":
            self.tether_up = True
        if args[:2] == ("connection", "down") and args[-1] == "u-bt":
            self.tether_up = False
        return 0, "", ""

    def rescans(self):
        """The `--rescan` value of each scan so far: 'yes' or 'no'."""
        return [a[a.index("--rescan") + 1] for a in self.calls if "--rescan" in a]

    def ran(self, *words):
        return [a for a in self.calls if all(w in a for w in words)]


class RadioTest(unittest.TestCase):
    """Who is allowed to scan, and what the watchdog does instead."""

    def setUp(self):
        self.nm = FakeNM()
        self.clock = 1000.0
        self.wifi = Wifi({})
        self.wifi._available = True          # no nmcli on a Mac
        INLINE.start()
        mock.patch("backend.wifi.nmcli", self.nm).start()
        mock.patch("backend.wifi.time", SimpleNamespace(monotonic=lambda: self.clock)).start()
        self.printed = mock.patch("builtins.print").start()
        self.addCleanup(mock.patch.stopall)
        self.addCleanup(self.wifi._watch_timer.stop)
        self.addCleanup(self.wifi._scan_timer.stop)

    def tick(self, seconds=10):
        """The watchdog's next tick, `seconds` later."""
        self.clock += seconds
        self.wifi._watch()

    def test_startup_and_the_watchdog_never_scan(self):
        self.wifi.start()
        for _ in range(10):
            self.tick()
        self.assertEqual(self.nm.ran("wifi", "list"), [])
        self.assertEqual(self.nm.rescans(), [])
        self.assertTrue(self.wifi.canControl)           # still learned without a scan
        self.assertEqual(self.wifi.networks, [])        # the list waits for Settings

    def test_the_wifi_settings_scan_while_they_are_open(self):
        self.wifi.setScanning(True)
        self.assertEqual(self.nm.rescans(), ["yes"])
        self.assertEqual([n["ssid"] for n in self.wifi.networks], ["Phone", "Cafe"])
        self.assertTrue(self.wifi._scan_timer.isActive())
        self.wifi.setScanning(False)
        self.assertFalse(self.wifi._scan_timer.isActive())
        for _ in range(5):
            self.tick()
        self.assertEqual(self.nm.rescans(), ["yes"])    # nothing more once they are closed

    def test_without_permission_even_the_settings_scan_is_a_cached_one(self):
        self.nm.control = "no"
        self.wifi.setScanning(True)
        self.assertEqual(self.nm.rescans(), ["no"])

    def test_a_steady_tick_is_one_cheap_read(self):
        self.wifi.start()
        self.tick()                          # the first ticks also learn the permission and the gateway
        self.nm.calls.clear()
        for _ in range(3):
            self.tick()
        self.assertEqual(self.nm.calls, [("-t", "-f", "UUID,NAME,TYPE,DEVICE", "connection", "show")] * 3)

    def test_joining_rescans_only_if_the_settings_are_still_open(self):
        self.wifi.setScanning(True)
        self.wifi.join("Phone", "")
        self.assertEqual(self.wifi.message, "Connected to Phone")
        self.assertEqual(self.nm.rescans(), ["yes", "yes"])      # the join's own refresh
        self.wifi.setScanning(False)
        self.wifi.forget("Phone")
        self.assertEqual(self.wifi.message, "Forgot Phone")
        self.assertEqual(self.nm.rescans(), ["yes", "yes"])      # closed: no scan after the forget

    def test_the_watchdog_keeps_the_network_names_the_scan_found(self):
        self.wifi.setScanning(True)
        self.tick()
        self.assertEqual([c["ssid"] for c in self.wifi._saved if c["type"] == "802-11-wireless"], ["Phone"])
        self.assertTrue(self.wifi.networks[0]["saved"])
        self.nm.calls.clear()
        self.wifi.join("Phone", "")                  # a saved network is joined by its saved connection
        self.assertEqual(self.nm.ran("connection", "up")[0][-1], "u-phone")

    def test_a_hotspot_is_given_its_fixed_address_once(self):
        self.nm.gateway = IPHONE_GATEWAY
        self.wifi.start()
        for _ in range(3):
            self.tick()
        self.assertEqual(len(self.nm.ran("connection", "modify")), 1)
        self.assertEqual(len(self.nm.ran("IP4.GATEWAY,GENERAL.CONNECTION")), 1)

    # ---- the phone as a backup ------------------------------------------------
    def test_no_wifi_for_a_minute_brings_the_phone_up_and_wifi_back_lets_it_go(self):
        self.nm.tether, self.nm.wifi_up = True, False
        self.wifi.start()                                  # t=1000: no Wi-Fi from here
        for _ in range(4):
            self.tick()                                    # up to 40 s
        self.assertEqual(self.nm.ran("connection", "up"), [])
        self.assertFalse(self.wifi.tetherActive)
        self.assertEqual(self.wifi.tetherPhone, "Pixel")
        self.tick()                                        # 50 s
        self.assertEqual(self.nm.ran("connection", "up"), [("connection", "up", "uuid", "u-bt")])
        self.tick()
        self.assertTrue(self.wifi.tetherActive)
        self.assertEqual(len(self.nm.ran("connection", "up")), 1)    # tries once, not every tick
        self.nm.wifi_up = True                             # Wi-Fi is back
        for _ in range(7):
            self.tick()                                    # 60 s of it, counted from the first tick that sees it
        self.assertEqual(self.nm.ran("connection", "down"), [])
        self.assertTrue(self.wifi.tetherActive)
        self.tick()                                        # over 60 s
        self.assertEqual(self.nm.ran("connection", "down"), [("connection", "down", "uuid", "u-bt")])
        self.tick()
        self.assertFalse(self.wifi.tetherActive)
        self.assertEqual(self.nm.rescans(), [])            # and none of it scanned

    def test_a_short_wifi_gap_doesnt_bring_the_phone_up(self):
        self.nm.tether = True
        self.wifi.start()
        self.nm.wifi_up = False
        for _ in range(3):
            self.tick()                                    # 30 s without
        self.nm.wifi_up = True
        self.tick()
        self.nm.wifi_up = False
        for _ in range(4):
            self.tick()                                    # 40 s without, from the start of this gap
        self.assertEqual(self.nm.ran("connection", "up"), [])

    def test_a_phone_paired_later_is_noticed_without_opening_settings(self):
        self.nm.wifi_up = False
        self.wifi.start()
        for _ in range(10):
            self.tick()                                    # 100 s with no phone saved yet
        self.assertEqual(self.wifi.tetherPhone, "")
        changes = []
        self.wifi.changed.connect(lambda: changes.append(1))
        self.nm.tether = True
        self.tick()
        self.assertEqual(self.wifi.tetherPhone, "Pixel")
        self.assertEqual(len(changes), 1)
        self.assertEqual(self.nm.ran("connection", "up"), [("connection", "up", "uuid", "u-bt")])
        self.assertEqual(self.nm.rescans(), [])

    def test_tethering_off_lets_the_phone_go_and_keeps_it_down(self):
        self.nm.tether, self.nm.tether_up, self.nm.wifi_up = True, True, False
        self.wifi._tether = False
        self.wifi.start()
        self.assertTrue(self.wifi.tetherActive)
        self.tick()
        self.assertEqual(self.nm.ran("connection", "down"), [("connection", "down", "uuid", "u-bt")])
        for _ in range(10):
            self.tick()
        self.assertEqual(self.nm.ran("connection", "up"), [])

    def test_without_permission_the_phone_is_left_alone(self):
        self.nm.control = "no"
        self.nm.tether, self.nm.wifi_up = True, False
        self.wifi.start()
        for _ in range(10):
            self.tick()
        self.assertEqual(self.nm.ran("connection", "up"), [])
        self.assertFalse(self.wifi.canControl)

    def test_a_failed_read_doesnt_count_as_no_wifi(self):
        self.nm.tether = True
        self.nm.list_rc = 1                              # nmcli timed out
        self.wifi.start()
        for _ in range(10):
            self.tick()
        self.assertIsNone(self.wifi._no_wifi_since)
        self.assertEqual(self.nm.ran("connection", "up"), [])
        self.assertFalse(self.wifi._polling)             # and the next tick still runs
        self.nm.list_rc = 0
        self.tick()
        self.assertEqual(self.wifi.tetherPhone, "Pixel")

    def test_a_crashing_watchdog_read_is_logged_once_and_the_next_tick_runs(self):
        self.nm.tether = True
        with mock.patch("backend.wifi.connections", side_effect=TypeError("surprise")):
            for _ in range(3):
                self.tick()
                self.assertFalse(self.wifi._polling)
        lines = logged(self.printed)
        self.assertEqual(len(lines), 1)
        self.assertIn("TypeError: surprise", lines[0])
        self.assertEqual(self.wifi.tetherPhone, "")
        self.tick()
        self.assertEqual(self.wifi.tetherPhone, "Pixel")
        self.assertIn("working again", logged(self.printed)[-1])


if __name__ == "__main__":
    unittest.main()
