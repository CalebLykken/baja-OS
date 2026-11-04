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

from backend.wifi import (HOTSPOT_ADDRESS, IPHONE_GATEWAY, LOST_SCAN_S, SAFETY_WATCH_MS, TETHER_AFTER_S, UNTETHER_AFTER_S,
                          WATCH_EVERY_MS, Wifi, saved_connections, scan, split_terse, valid_ssid)
from tests.test_dbus import FakeBus, on_bus

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
                 (0, "", ""), (0, HOTSPOT_ADDRESS, "")]
        with mock.patch("backend.wifi.nmcli", side_effect=reply):
            self.wifi._ensure_hotspot_address()
        self.assertIn("working again", logged(self.printed)[-1])


class SavedConnectionsTest(unittest.TestCase):
    """The saved name must come back as the scan spells it."""

    def saved(self, ssid):
        def reply(*args, **kw):
            if "UUID,NAME,TYPE,DEVICE,STATE" in args:
                return 0, "u-1:Profile:802-11-wireless:wlan0:activated\n", ""
            # nmcli only writes the name raw when told not to escape it
            return 0, ssid + "\n" if "no" in args else ssid.replace("\\", "\\\\").replace(":", "\\:") + "\n", ""
        with mock.patch("backend.wifi.nmcli", side_effect=reply):
            return saved_connections()[0]["ssid"]

    def test_colons_and_backslashes_in_a_name_survive(self):
        self.assertEqual(self.saved("Shop:Guest"), "Shop:Guest")
        self.assertEqual(self.saved("Back\\slash"), "Back\\slash")

    def test_a_names_own_spaces_stay(self):
        self.assertEqual(self.saved(" Cafe "), " Cafe ")


class FakeNM:
    """Just enough of nmcli for the Wi-Fi backend: permissions, the connection
    list, a scan listing and a few settings. Records every call."""

    def __init__(self):
        self.calls = []
        self.control = "yes"
        self.list_rc = 0               # what `connection show` returns
        self.wifi_up = True
        self.wifi_retrying = False     # NetworkManager trying a hotspot that's gone
        self.gateway = "192.168.1.1"
        self.tether = False            # is there a saved Bluetooth connection?
        self.tether_up = False

    def __call__(self, *args, input=None, timeout=10):
        self.calls.append(args)
        if "PERMISSION,VALUE" in args:
            return 0, f"org.freedesktop.NetworkManager.network-control:{self.control}\n", ""
        if "UUID,NAME,TYPE,DEVICE,STATE" in args:
            if self.list_rc:
                return self.list_rc, "", "timed out"
            wifi = ("wlan0:activated" if self.wifi_up
                    else "wlan0:activating" if self.wifi_retrying else ":")
            lines = ["u-phone:Phone:802-11-wireless:" + wifi,
                     "u-lo:lo:loopback:lo:activated"]
            if self.tether:
                lines.append("u-bt:Pixel Network:bluetooth:" + ("AA\\:BB:activated" if self.tether_up else ":"))
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


class SignalsTest(unittest.TestCase):
    """NetworkManager's signals drive the watchdog, faked at the bus: it polls
    as before without them, and the tethering deadlines still hold with them."""

    def setUp(self):
        self.nm = FakeNM()
        self.clock = 1000.0
        self.wifi = Wifi({})
        self.wifi._available = True
        self.wifi._settings = mock.Mock()
        INLINE.start()
        mock.patch("backend.wifi.nmcli", self.nm).start()
        mock.patch("backend.wifi.time", SimpleNamespace(monotonic=lambda: self.clock)).start()
        mock.patch("builtins.print").start()
        self.addCleanup(mock.patch.stopall)
        self.addCleanup(self.wifi._watch_timer.stop)

    def started(self, bus):
        with on_bus(bus):
            self.wifi.start()
        self.nm.calls.clear()

    def interval(self):
        return self.wifi._watch_timer.interval()

    def wait(self):
        """Sit out the timer as it's set, on the fake clock."""
        self.clock += self.interval() / 1000
        self.wifi._watch()

    def test_a_signal_reads_the_list(self):
        self.started(FakeBus())
        self.wifi._nm._on_signal()
        self.assertTrue(self.wifi._nm._timer.isActive())
        self.wifi._nm._timer.stop()
        self.wifi._nm._fire()
        self.assertEqual(self.nm.ran("UUID,NAME,TYPE,DEVICE,STATE"), [("-t", "-f", "UUID,NAME,TYPE,DEVICE,STATE",
                                                                      "connection", "show")])
        self.assertEqual(self.nm.rescans(), [])

    def test_a_signal_during_a_poll_reads_again_after_it(self):
        self.started(FakeBus())
        self.wifi._polling = True
        self.wifi._signalled()
        self.assertEqual(self.nm.calls, [])
        self.wifi._on_polled(None)
        self.assertTrue(self.wifi._nm._timer.isActive())
        self.wifi._nm._timer.stop()

    def test_without_a_bus_it_polls_as_often_as_ever(self):
        self.started(None)
        self.assertEqual(self.interval(), WATCH_EVERY_MS)
        self.assertTrue(self.wifi._watch_timer.isActive())

    def test_with_signals_and_nothing_to_decide_it_relaxes(self):
        self.started(FakeBus())
        self.assertEqual(self.interval(), SAFETY_WATCH_MS)
        self.assertTrue(self.wifi._watch_timer.isActive())

    def test_a_failed_read_goes_back_to_the_quick_poll(self):
        self.started(FakeBus())
        self.wifi._on_polled(None)
        self.assertEqual(self.interval(), WATCH_EVERY_MS)

    def test_network_manager_stopped_means_the_quick_poll(self):
        bus = FakeBus()
        self.started(bus)
        bus.running = False
        self.wifi._watch()
        self.assertEqual(self.interval(), WATCH_EVERY_MS)

    def test_with_no_wifi_it_keeps_looking_for_the_hotspot(self):
        self.nm.wifi_up = False
        self.started(FakeBus())
        self.assertEqual(self.interval(), WATCH_EVERY_MS)
        for _ in range(3):
            self.wait()
        self.assertEqual(len(self.nm.ran("device", "wifi", "rescan")), 3)

    def test_a_signal_storm_with_no_wifi_doesnt_scan_any_faster(self):
        self.nm.wifi_up = False
        self.started(FakeBus())
        self.clock += LOST_SCAN_S
        for _ in range(5):
            self.wifi._watch()
        self.assertEqual(len(self.nm.ran("device", "wifi", "rescan")), 1)

    def test_on_wifi_the_watchdog_never_scans(self):
        self.started(FakeBus())
        for _ in range(3):
            self.wait()
        self.assertEqual(self.nm.ran("device", "wifi", "rescan"), [])

    def test_tethered_with_no_wifi_it_leaves_the_radio_alone(self):
        self.nm.tether, self.nm.tether_up, self.nm.wifi_up = True, True, False
        self.started(FakeBus())
        self.wait()
        self.assertEqual(self.nm.ran("device", "wifi", "rescan"), [])

    def test_the_phone_comes_up_on_time_with_no_signal_to_prompt_it(self):
        self.nm.tether, self.nm.wifi_up = True, False
        self.started(FakeBus())
        self.wifi._watch()                                 # learns the permission
        started = self.clock
        while not self.nm.ran("connection", "up"):
            self.wait()
            self.assertLess(self.clock - started, TETHER_AFTER_S + WATCH_EVERY_MS / 1000 + 2)

    def test_the_phone_is_let_go_on_time_with_no_signal_to_prompt_it(self):
        self.nm.tether, self.nm.wifi_up, self.nm.tether_up = True, True, True
        self.started(FakeBus())
        self.wifi._watch()
        started = self.clock
        while self.nm.tether_up:
            self.wait()
            self.assertLess(self.clock - started, UNTETHER_AFTER_S + WATCH_EVERY_MS / 1000 + 2)

    def test_once_tethered_with_no_wifi_it_relaxes(self):
        self.nm.tether, self.nm.wifi_up, self.nm.tether_up = True, False, True
        self.started(FakeBus())
        self.wifi._watch()
        self.assertEqual(self.interval(), SAFETY_WATCH_MS)

    def test_switching_tethering_off_acts_without_waiting_for_the_safety_poll(self):
        self.nm.tether, self.nm.wifi_up, self.nm.tether_up = True, False, True
        self.started(FakeBus())
        self.wifi._watch()
        self.wifi.setTethering(False)
        self.assertTrue(self.wifi._nm._timer.isActive())
        self.wifi._nm._timer.stop()
        self.wifi._nm._fire()
        self.assertFalse(self.nm.tether_up)


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
        self.assertEqual(self.nm.calls, [("-t", "-f", "UUID,NAME,TYPE,DEVICE,STATE", "connection", "show")] * 3)

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
        self.assertEqual(len(self.nm.ran("connection", "modify", "+ipv4.addresses")), 1)
        self.assertEqual(len(self.nm.ran("IP4.GATEWAY,GENERAL.CONNECTION")), 1)

    def test_any_network_it_lands_on_is_set_to_retry_forever(self):
        self.wifi.start()                            # not joined here, and not a hotspot
        self.assertEqual(self.nm.ran("connection", "modify", "Phone")[0][-4:],
                         ("connection.autoconnect-retries", "0", "802-11-wireless.powersave", "2"))

    def test_a_saved_network_out_of_range_asks_if_the_hotspot_is_on(self):
        why = Wifi._why("Error: Connection activation failed: The Wi-Fi network could not be found", "Phone")
        self.assertEqual(why, "Can't see Phone; is the hotspot on?")

    # ---- the phone as a backup ------------------------------------------------
    def test_a_hotspot_still_being_retried_is_not_wifi(self):
        # NetworkManager keeps trying a saved hotspot that's gone, so the
        # connection has a device on every tick without ever being up.
        self.nm.tether, self.nm.wifi_up, self.nm.wifi_retrying = True, False, True
        self.wifi.start()
        for _ in range(5):
            self.tick()                                    # 50 s
        self.assertEqual(self.nm.ran("connection", "up"), [("connection", "up", "uuid", "u-bt")])

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


class WrongPasswordTest(unittest.TestCase):
    """A saved network whose password changed asks for the new one."""

    def setUp(self):
        self.wifi = Wifi({})
        self.wifi._available = False         # keep the refresh after joining out of it
        self.wifi._saved = [{"uuid": "u-phone", "ssid": "Phone", "type": "802-11-wireless"}]
        INLINE.start()
        self.addCleanup(mock.patch.stopall)
        self.asked = []
        self.wifi.passwordNeeded.connect(self.asked.append)

    def join(self, ssid, password, rc, err):
        with mock.patch("backend.wifi.nmcli", return_value=(rc, "", err)):
            self.wifi.join(ssid, password)

    def test_a_wrong_saved_password_asks_for_a_new_one(self):
        self.join("Phone", "", 4, "Error: Connection activation failed: (7) Secrets were required, but not provided.")
        self.assertEqual(self.wifi.message, "Wrong password for Phone")
        self.assertEqual(self.asked, ["Phone"])
        self.assertEqual(self.wifi.busy, "")

    def test_other_failures_and_successes_dont_ask(self):
        self.join("Phone", "", 10, "Error: No network with SSID 'Phone' found.")
        self.join("Phone", "", 0, "")
        self.assertEqual(self.asked, [])

    def test_a_wrong_password_typed_in_the_sheet_doesnt_loop(self):
        self.join("Phone", "hunter22", 4, "Error: Secrets were required, but not provided.")
        self.assertEqual(self.wifi.message, "Wrong password for Phone")
        self.assertEqual(self.asked, [])


class HiddenNetworkTest(unittest.TestCase):
    """A network typed in by hand joins with `hidden yes`, the password on stdin."""

    def setUp(self):
        self.wifi = Wifi({})
        self.wifi._available = False
        INLINE.start()
        self.addCleanup(mock.patch.stopall)
        self.calls = []

    def fake(self, *args, input=None, timeout=10):
        self.calls.append((args, input))
        return self.rc, "", self.err

    def join(self, ssid, password, rc=0, err=""):
        self.rc, self.err = rc, err
        with mock.patch("backend.wifi.nmcli", self.fake):
            self.wifi.joinHidden(ssid, password)

    def test_joins_with_hidden_yes_and_the_password_on_stdin(self):
        self.join("Secret Net", "hunter22")
        args, stdin = self.calls[0]
        self.assertEqual(args, ("--ask", "device", "wifi", "connect", "Secret Net", "hidden", "yes"))
        self.assertEqual(stdin, "hunter22\n")
        self.assertNotIn("hunter22", " ".join(a for c, _ in self.calls for a in c))
        self.assertEqual(self.wifi.message, "Connected to Secret Net")

    def test_an_open_hidden_network_sends_no_password(self):
        self.join("Open", "")
        self.assertEqual(self.calls[0], (("device", "wifi", "connect", "Open", "hidden", "yes"), None))

    def test_a_wrong_password_says_so_and_frees_the_page(self):
        self.join("Secret Net", "nope", 4, "Error: Secrets were required, but not provided.")
        self.assertEqual(self.wifi.message, "Wrong password for Secret Net")
        self.assertEqual(self.wifi.busy, "")

    def test_the_name_goes_to_nmcli_as_one_argument(self):
        self.join("a; reboot $(x)", "hunter22")
        self.assertEqual(self.calls[0][0][4], "a; reboot $(x)")

    def test_a_bad_name_never_reaches_nmcli(self):
        for bad in ("", "x" * 33, "a\nb", "a\x00b"):
            self.join(bad, "hunter22")
        self.assertEqual(self.calls, [])
        self.assertEqual(self.wifi.message, "That isn't a valid network name")

    def test_a_saved_network_of_that_name_is_replaced(self):
        self.wifi._saved = [{"uuid": "u1", "ssid": "Secret Net", "type": "802-11-wireless"}]
        self.join("Secret Net", "hunter22")
        self.assertEqual(self.calls[0][0], ("connection", "delete", "uuid", "u1"))

    def join_seq(self, results):
        """joinHidden with nmcli answering from results, one per call."""
        it = iter(results)

        def fake(*args, input=None, timeout=10):
            self.calls.append((args, input))
            return next(it, (0, "", ""))
        with mock.patch("backend.wifi.nmcli", fake), \
                mock.patch("backend.wifi.time.sleep") as sleep:
            self.wifi.joinHidden("Secret Net", "hunter22")
        return sleep

    def test_a_missed_first_scan_is_retried_after_a_pause(self):
        sleep = self.join_seq([(10, "", "Error: No network with SSID 'Secret Net' found."),
                               (10, "", "Error: Failed to scan hidden SSID"), (0, "", "")])
        self.assertEqual(sleep.call_count, 2)
        sleep.assert_called_with(5)
        tries = [c for c in self.calls if c[0][0] == "--ask"]
        self.assertEqual([t[1] for t in tries], ["hunter22\n"] * 3)
        self.assertEqual(self.wifi.message, "Connected to Secret Net")

    def test_the_retries_stop_after_two_and_the_page_is_freed(self):
        miss = (10, "", "Error: No network with SSID 'Secret Net' found.")
        sleep = self.join_seq([miss] * 5)
        self.assertEqual(sleep.call_count, 2)
        self.assertEqual(len([c for c in self.calls if c[0][0] == "--ask"]), 3)
        self.assertEqual(self.wifi.message, "Can't see Secret Net; is the hotspot on?")
        self.assertEqual(self.wifi.busy, "")

    def test_a_wrong_password_is_not_retried(self):
        sleep = self.join_seq([(4, "", "Error: Secrets were required, but not provided.")])
        self.assertEqual(sleep.call_count, 0)

    def test_valid_ssid_counts_bytes(self):
        self.assertTrue(valid_ssid("é" * 16))
        self.assertFalse(valid_ssid("é" * 17))


class SplitTerseTest(unittest.TestCase):
    def test_plain_fields(self):
        self.assertEqual(split_terse("*:Home:80:WPA2"), ["*", "Home", "80", "WPA2"])

    def test_an_escaped_colon_stays_in_the_field(self):
        self.assertEqual(split_terse(r"AA\:BB\:CC:Cafe\: Free:55"), ["AA:BB:CC", "Cafe: Free", "55"])

    def test_empty_fields_are_kept(self):
        self.assertEqual(split_terse(":Home::"), ["", "Home", "", ""])
        self.assertEqual(split_terse(""), [""])

    def test_a_colon_at_either_end_of_a_name(self):
        self.assertEqual(split_terse(r"\:a\::1"), [":a:", "1"])

    def test_an_escaped_backslash_is_one_backslash(self):
        self.assertEqual(split_terse(r"C\\D:1"), ["C\\D", "1"])

    def test_a_name_ending_in_a_backslash_still_ends(self):
        # nmcli writes the name "ab\" as ab\\ and then the separator: the
        # colon after an escaped backslash is a real one, but split_terse
        # sees a backslash in front of it and keeps the two fields as one.
        self.assertEqual(split_terse("ab\\\\:70"), ["ab\\", "70"])


if __name__ == "__main__":
    unittest.main()
