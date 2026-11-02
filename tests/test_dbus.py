"""Off-Pi tests for backend/dbus.py, with the bus faked: a signal triggers one
debounced refresh, no bus or a failed subscription or a missing service means
polling, and nothing raises. FakeBus is shared with the backends' tests.

    python3 -m unittest tests.test_dbus
"""

import time
import unittest
from unittest import mock

from PyQt6.QtCore import QCoreApplication

from backend import dbus
from backend.dbus import BusWatch

app = QCoreApplication.instance() or QCoreApplication([])


class FakeReply:
    def __init__(self, value):
        self._value = value

    def isValid(self):
        return True

    def value(self):
        return self._value


class FakeBus:
    """The bits of QDBusConnection that BusWatch uses."""

    def __init__(self, subscribes=True, running=True):
        self.subscribes = subscribes
        self.running = running
        self.subscribed = []
        self.slot = None

    def connect(self, service, path, interface, name, slot):
        self.subscribed.append((service, path, interface, name))
        self.slot = slot
        return self.subscribes

    def interface(self):
        return self

    def isServiceRegistered(self, service):
        return FakeReply(self.running)


def on_bus(bus):
    """Patcher: BusWatch finds this bus (None: there's no bus, as on a Mac)."""
    return mock.patch("backend.dbus.system_bus", return_value=bus)


def spin(seconds):
    """Run the event loop for a moment, for the real debounce timer."""
    end = time.monotonic() + seconds
    while time.monotonic() < end:
        app.processEvents()
        time.sleep(0.005)


SIGNALS = [("/", "org.example.A", "One"), ("", "org.example.B", "Two")]


class BusWatchTest(unittest.TestCase):
    def setUp(self):
        self.changes = mock.Mock()
        self.watch = BusWatch("org.example", SIGNALS, self.changes, debounce_ms=20)
        self.printed = mock.patch("builtins.print").start()
        self.addCleanup(mock.patch.stopall)

    def test_subscribes_to_each_signal(self):
        bus = FakeBus()
        with on_bus(bus):
            self.assertTrue(self.watch.start())
        self.assertEqual(bus.subscribed, [("org.example", "/", "org.example.A", "One"),
                                          ("org.example", "", "org.example.B", "Two")])
        self.assertTrue(self.watch.live())

    def test_no_bus_means_polling(self):
        with on_bus(None):
            self.assertFalse(self.watch.start())
        self.assertFalse(self.watch.live())

    def test_a_refused_subscription_means_polling(self):
        with on_bus(FakeBus(subscribes=False)):
            self.assertFalse(self.watch.start())
        self.assertFalse(self.watch.live())

    def test_a_subscription_that_raises_means_polling(self):
        bus = FakeBus()
        bus.connect = mock.Mock(side_effect=TypeError("nope"))
        with on_bus(bus):
            self.assertFalse(self.watch.start())
        self.assertFalse(self.watch.live())

    def test_not_live_while_the_service_is_down_and_live_again_after(self):
        bus = FakeBus(running=False)
        with on_bus(bus):
            self.assertTrue(self.watch.start())
        self.assertFalse(self.watch.live())
        bus.running = True
        self.assertTrue(self.watch.live())

    def test_a_lost_bus_is_not_live_and_doesnt_raise(self):
        bus = FakeBus()
        with on_bus(bus):
            self.watch.start()
        bus.interface = mock.Mock(return_value=None)    # what Qt gives on a dead connection
        self.assertFalse(self.watch.live())

    def test_a_real_message_is_taken(self):
        self.watch._on_signal(dbus.QDBusMessage.createSignal("/org/example", "org.example.A", "One"))
        self.assertTrue(self.watch._timer.isActive())
        self.watch._timer.stop()

    def test_a_burst_of_signals_is_one_refresh(self):
        for _ in range(5):
            self.watch._on_signal()
        self.changes.assert_not_called()
        spin(0.06)
        self.changes.assert_called_once()

    def test_a_steady_stream_cant_hold_the_refresh_off(self):
        end = time.monotonic() + 0.1
        while time.monotonic() < end:
            self.watch._on_signal()
            spin(0.005)
        self.assertGreaterEqual(self.changes.call_count, 2)

    def test_a_later_signal_refreshes_again(self):
        self.watch._on_signal()
        spin(0.06)
        self.watch._on_signal()
        spin(0.06)
        self.assertEqual(self.changes.call_count, 2)

    def test_a_refresh_that_raises_stays_in_the_slot(self):
        self.changes.side_effect = RuntimeError("boom")
        self.watch._fire()
        self.assertIn("boom", self.printed.call_args.args[0])

    def test_a_timer_that_fails_stays_in_the_slot(self):
        self.watch._timer = mock.Mock()
        self.watch._timer.isActive.side_effect = RuntimeError("deleted")
        self.watch._on_signal()
        self.assertIn("deleted", self.printed.call_args.args[0])

    def test_the_real_binding_takes_the_slot(self):
        """PyQt only accepts a decorated slot of a QObject: an undecorated one
        raises TypeError, here as on the Pi, connected or not."""
        bus = dbus.QDBusConnection.systemBus()
        result = bus.connect("org.example", "", dbus.PROPERTIES, "PropertiesChanged", self.watch._on_signal)
        self.assertIsInstance(result, bool)
        self.assertGreaterEqual(self.watch.metaObject().indexOfSlot("_on_signal(QDBusMessage)"), 0)


if __name__ == "__main__":
    unittest.main()
