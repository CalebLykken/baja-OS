"""Off-Pi tests for backend/settings.py: changes are written together, a
moment after the last one, instead of one fsync'd rewrite per change."""

import time
import unittest

from PyQt6.QtCore import QCoreApplication

from backend.settings import Settings

app = QCoreApplication.instance() or QCoreApplication([])


class FakeStore:
    """Counts what QSettings would have been asked to do."""

    def __init__(self, **values):
        self.values = dict(values)
        self.set_value_calls = 0
        self.syncs = 0

    def value(self, key, default=None):
        return self.values.get(key, default)

    def setValue(self, key, value):
        self.set_value_calls += 1
        self.values[key] = value

    def sync(self):
        self.syncs += 1


class SettingsTest(unittest.TestCase):
    def setUp(self):
        self.store = FakeStore()
        self.s = Settings(store=self.store, flush_after_ms=20)

    def test_a_burst_of_changes_is_one_sync_and_nothing_before_it(self):
        for v in range(50):                 # a slider drag
            self.s.set("volume", v)
        self.assertEqual((self.store.set_value_calls, self.store.syncs), (0, 0))
        self.s.flush()
        self.assertEqual(self.store.syncs, 1)
        self.assertEqual(self.store.values["volume"], 49)

    def test_different_keys_share_one_sync(self):
        self.s.set("volume", 10)
        self.s.set("music", "{}")
        self.s.set("style", "trail")
        self.s.flush()
        self.assertEqual(self.store.syncs, 1)
        self.assertEqual(self.store.values, {"volume": 10, "music": "{}", "style": "trail"})

    def test_get_sees_changes_that_are_still_waiting(self):
        self.store.values["volume"] = "40"
        self.s.set("volume", 55)
        self.assertEqual(self.s.get("volume"), 55)
        self.assertEqual(self.s.get_int("volume", 0), 55)
        self.assertEqual(self.s.get("other", "dflt"), "dflt")

    def test_a_value_that_is_already_there_writes_nothing(self):
        self.store.values["style"] = "trail"
        self.s.set("style", "trail")
        self.s.set("volume", 5)
        self.s.set("volume", 5)
        self.s.flush()
        self.assertEqual(self.store.set_value_calls, 1)

    def test_flush_with_nothing_waiting_doesnt_sync(self):
        self.s.flush()
        self.s.set("a", 1)
        self.s.flush()
        self.s.flush()
        self.assertEqual(self.store.syncs, 1)

    def test_the_route_is_written_at_once(self):
        self.s.set("volume", 5)
        self.s.set("route", "{...}")
        self.assertEqual(self.store.values["route"], "{...}")
        self.assertEqual(self.store.syncs, 1)
        self.assertEqual(self.store.values["volume"], 5)    # rode along

    def test_clearing_the_route_is_written_at_once(self):
        self.store.values["route"] = "{...}"
        self.s.set("route", "")
        self.assertEqual(self.store.values["route"], "")
        self.assertEqual(self.store.syncs, 1)

    def test_the_timer_writes_a_burst_once_it_goes_quiet(self):
        for v in range(10):
            self.s.set("volume", v)
        end = time.monotonic() + 2
        while self.store.syncs == 0 and time.monotonic() < end:
            app.processEvents()
            time.sleep(0.005)
        self.assertEqual(self.store.syncs, 1)
        self.assertEqual(self.store.values["volume"], 9)

    def test_get_int_falls_back_on_junk(self):
        self.s.set("volume", "loud")
        self.assertEqual(self.s.get_int("volume", 40), 40)


if __name__ == "__main__":
    unittest.main()
