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

from backend.dbus import NM_DEBOUNCE_MS
from backend.network import CHECK_EVERY_MS, SAFETY_CHECK_MS, Network, internet_state, wifi_name
from tests.test_dbus import FakeBus, on_bus

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
                mock.patch("backend.network.internet_state", return_value=(online, False)):
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
                mock.patch("backend.network.internet_state", side_effect=AttributeError("x")):
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



def nm(out="full\n", code=0):
    return mock.patch("backend.network.subprocess.run",
                      return_value=SimpleNamespace(stdout=out, returncode=code))


class InternetStateTest(unittest.TestCase):
    def setUp(self):
        mock.patch("backend.network.shutil.which", return_value="/usr/bin/nmcli").start()
        self.tcp = mock.patch("backend.network.tcp_online", return_value=False).start()
        self.addCleanup(mock.patch.stopall)

    def test_nm_states(self):
        for out, want in (("full\n", (True, False)), ("portal\n", (False, True)),
                          ("limited\n", (False, False)), ("none\n", (False, False))):
            with nm(out):
                self.assertEqual(internet_state(), want, out)
        self.tcp.assert_not_called()

    def test_nmcli_missing_uses_tcp_probe(self):
        self.tcp.return_value = True
        with mock.patch("backend.network.shutil.which", return_value=None):
            self.assertEqual(internet_state(), (True, False))
        self.tcp.assert_called_once()

    def test_nmcli_failing_uses_tcp_probe(self):
        self.tcp.return_value = True
        for run in (nm("", 8), nm("unknown\n", 1), nm("unknown\n", 0),
                    mock.patch("backend.network.subprocess.run", side_effect=OSError)):
            with run:
                self.assertEqual(internet_state(), (True, False))

    def test_portal_reaches_the_property(self):
        net = Network()
        net._apply(("10.0.0.5", "Cafe", False, True))
        self.assertTrue(net.portal)
        self.assertFalse(net.online)


class SignalsTest(unittest.TestCase):
    """NetworkManager's signals drive the check, faked at the bus; polling is
    the fallback, and the TCP probe needs it."""

    def setUp(self):
        self.net = Network()
        INLINE.start()
        self.lookup = mock.patch("backend.network.wifi_name", return_value="Phone").start()
        mock.patch("backend.network.local_ip", return_value="10.0.0.5").start()
        mock.patch("backend.network.internet_state", return_value=(True, False)).start()
        mock.patch("builtins.print").start()
        self.addCleanup(self.net._timer.stop)
        self.addCleanup(mock.patch.stopall)

    def started(self, bus):
        with on_bus(bus):
            self.net.start()
        self.lookup.reset_mock()

    def test_subscribes_to_network_manager(self):
        bus = FakeBus()
        self.started(bus)
        names = {(s[1], s[2], s[3]) for s in bus.subscribed}
        root = "/org/freedesktop/NetworkManager"
        self.assertIn((root, "org.freedesktop.NetworkManager", "StateChanged"), names)
        self.assertIn((root, "org.freedesktop.DBus.Properties", "PropertiesChanged"), names)
        self.assertIn(("", "org.freedesktop.NetworkManager.Connection.Active", "StateChanged"), names)
        self.assertNotIn(("", "org.freedesktop.DBus.Properties", "PropertiesChanged"), names)    # signal strength

    def test_a_signal_checks_after_the_debounce(self):
        bus = FakeBus()
        self.started(bus)
        for _ in range(5):
            bus.slot()
        self.lookup.assert_not_called()
        self.assertTrue(self.net._nm._timer.isActive())
        self.assertEqual(self.net._nm._timer.interval(), NM_DEBOUNCE_MS)
        self.net._nm._timer.stop()
        self.net._nm._fire()
        self.lookup.assert_called_once()

    def test_a_signal_during_a_check_checks_again_after_it(self):
        self.started(FakeBus())
        self.net._busy = True
        self.net._signalled()
        self.lookup.assert_not_called()
        self.net._apply(None)
        self.assertTrue(self.net._nm._timer.isActive())
        self.net._nm._timer.stop()

    def test_without_a_bus_it_checks_as_often_as_ever(self):
        self.started(None)
        self.assertEqual(self.net._timer.interval(), CHECK_EVERY_MS)
        self.assertTrue(self.net._timer.isActive())

    def test_with_signals_it_relaxes(self):
        self.started(FakeBus())
        self.assertEqual(self.net._timer.interval(), SAFETY_CHECK_MS)
        self.assertTrue(self.net._timer.isActive())

    def test_network_manager_stopped_means_the_quick_checks(self):
        bus = FakeBus()
        self.started(bus)
        bus.running = False
        self.net._check()
        self.assertEqual(self.net._timer.interval(), CHECK_EVERY_MS)
        bus.running = True
        self.net._check()
        self.assertEqual(self.net._timer.interval(), SAFETY_CHECK_MS)


if __name__ == "__main__":
    unittest.main()
