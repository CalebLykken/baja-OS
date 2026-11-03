"""Off-Pi tests for backend/settings.py: changes are written together, a
moment after the last one (but never later than a max wait), on a writer
thread of their own, so the UI thread never waits on a sync."""

import os
import tempfile
import threading
import time
import unittest
from unittest import mock

from PyQt6.QtCore import QCoreApplication, QSettings

from backend.settings import Settings

app = QCoreApplication.instance() or QCoreApplication([])
MAIN = threading.get_ident()


class FakeStore:
    """Counts what QSettings would have been asked to do, and on which
    thread. One shared backing dict stands in for the file."""

    def __init__(self, **values):
        self.values = dict(values)
        self.opens = []                 # thread of each open
        self.calls = []                 # (method, thread) after opening
        self.set_value_calls = 0
        self.syncs = 0
        self.sync_gate = None           # a threading.Event a sync waits on
        self.fail_syncs = 0             # this many syncs raise
        self.lock = threading.Lock()

    def open(self):
        self.opens.append(threading.get_ident())
        return self

    def allKeys(self):
        return list(self.values)

    def value(self, key, default=None):
        self.calls.append(("value", threading.get_ident()))
        return self.values.get(key, default)

    def setValue(self, key, value):
        self.calls.append(("setValue", threading.get_ident()))
        with self.lock:
            self.set_value_calls += 1
            self.values[key] = value

    def sync(self):
        self.calls.append(("sync", threading.get_ident()))
        if self.sync_gate is not None:
            self.sync_gate.wait(5)
        with self.lock:
            if self.fail_syncs:
                self.fail_syncs -= 1
                raise OSError("disk full")
            self.syncs += 1


def pump_until(cond, timeout=3.0):
    end = time.monotonic() + timeout
    while not cond() and time.monotonic() < end:
        app.processEvents()
        time.sleep(0.002)
    return cond()


class SettingsTest(unittest.TestCase):
    def make(self, store=None, **kw):
        self.store = store or FakeStore()
        kw.setdefault("flush_after_ms", 20)
        s = Settings(open_store=self.store.open, **kw)
        self.addCleanup(s.close, 1)
        return s

    def setUp(self):
        self.s = self.make()

    def test_a_burst_of_changes_is_one_sync_and_nothing_before_it(self):
        for v in range(50):                 # a slider drag
            self.s.set("volume", v)
        self.assertEqual((self.store.set_value_calls, self.store.syncs), (0, 0))
        self.assertTrue(self.s.flush(wait=True))
        self.assertEqual(self.store.syncs, 1)
        self.assertEqual(self.store.values["volume"], 49)

    def test_different_keys_share_one_sync(self):
        self.s.set("volume", 10)
        self.s.set("music", "{}")
        self.s.set("style", "trail")
        self.s.flush(wait=True)
        self.assertEqual(self.store.syncs, 1)
        self.assertEqual(self.store.values, {"volume": 10, "music": "{}", "style": "trail"})

    def test_the_ui_thread_only_reads_the_file_once_at_start(self):
        s = self.make(FakeStore(volume="40", style="trail"))
        reads_at_start = list(self.store.calls)
        self.assertEqual(self.store.opens, [MAIN])
        self.assertTrue(all(t == MAIN and m == "value" for m, t in reads_at_start))
        for v in range(5):
            s.set("volume", v)
            s.get("volume")
            s.get("style")
        s.set("route", "{...}")
        s.flush(wait=True)
        later = self.store.calls[len(reads_at_start):]
        self.assertTrue(later)
        self.assertNotIn(MAIN, [t for _, t in later])          # writes: the writer thread
        self.assertEqual(len(self.store.opens), 2)            # it opened its own store
        self.assertNotEqual(self.store.opens[1], MAIN)

    def test_get_sees_what_was_saved_and_what_was_set_this_run(self):
        s = self.make(FakeStore(volume="40", style="trail"))
        self.assertEqual(s.get("style"), "trail")
        self.assertEqual(s.get_int("volume", 0), 40)
        s.set("volume", 55)
        self.assertEqual(s.get("volume"), 55)
        s.flush(wait=True)
        self.assertEqual(s.get("volume"), 55)               # still, once written
        self.assertEqual(s.get("other", "dflt"), "dflt")

    def test_a_value_that_is_already_there_writes_nothing(self):
        s = self.make(FakeStore(style="trail"))
        s.set("style", "trail")
        s.set("volume", 5)
        s.set("volume", 5)
        s.flush(wait=True)
        self.assertEqual(self.store.set_value_calls, 1)

    def test_flush_with_nothing_waiting_doesnt_sync(self):
        self.s.flush(wait=True)
        self.s.set("a", 1)
        self.s.flush(wait=True)
        self.s.flush(wait=True)
        self.assertEqual(self.store.syncs, 1)

    def test_the_route_is_handed_over_at_once(self):
        self.s.set("volume", 5)
        self.s.set("route", "{...}")
        # No event loop turn needed: the writer thread has it already.
        end = time.monotonic() + 3
        while self.store.syncs == 0 and time.monotonic() < end:
            time.sleep(0.002)
        self.assertEqual(self.store.values["route"], "{...}")
        self.assertEqual(self.store.syncs, 1)
        self.assertEqual(self.store.values["volume"], 5)    # rode along

    def test_clearing_the_route_is_handed_over_at_once(self):
        s = self.make(FakeStore(route="{...}"))
        s.set("route", "")
        self.assertTrue(pump_until(lambda: self.store.syncs == 1))
        self.assertEqual(self.store.values["route"], "")

    def test_the_timer_writes_a_burst_once_it_goes_quiet(self):
        for v in range(10):
            self.s.set("volume", v)
        self.assertTrue(pump_until(lambda: self.store.syncs == 1))
        time.sleep(0.05)
        app.processEvents()
        self.assertEqual(self.store.syncs, 1)
        self.assertEqual(self.store.values["volume"], 9)

    def test_a_key_that_never_stops_changing_is_still_written_by_the_max_wait(self):
        s = self.make(flush_after_ms=100, max_wait_ms=150)
        start = time.monotonic()
        first = None
        v = 0
        while time.monotonic() - start < 0.6:   # changes every 10 ms: never quiet
            s.set("music", v)
            v += 1
            app.processEvents()
            if first is None and self.store.syncs:
                first = time.monotonic() - start
            time.sleep(0.01)
        self.assertIsNotNone(first)
        self.assertLess(first, 0.4)             # ~0.15 s, well before it went quiet
        self.assertGreaterEqual(self.store.syncs, 2)   # and again after the next max wait
        self.assertLessEqual(self.store.syncs, 6)

    def test_music_saved_every_5s_never_syncs_on_the_ui_thread(self):
        # MediaHub's cadence, scaled down: a save each "5 s" tick.
        s = self.make(flush_after_ms=15, max_wait_ms=100)
        for tick in range(5):
            s.set("music", f'{{"position": {tick * 5}}}')
            pump_until(lambda: self.store.syncs == tick + 1, 1)
        self.assertEqual(self.store.syncs, 5)
        self.assertNotIn(MAIN, [t for m, t in self.store.calls if m in ("sync", "setValue")])

    def test_a_slow_sync_doesnt_block_set_and_later_changes_merge(self):
        self.store.sync_gate = threading.Event()
        self.s.set("volume", 1)
        self.s.flush()                          # writer now stuck in sync
        self.assertTrue(pump_until(lambda: any(m == "sync" for m, _ in self.store.calls)))
        started = time.monotonic()
        for v in range(2, 30):
            self.s.set("volume", v)
            self.s.set("style", f"s{v}")
            self.s.flush()                      # 28 batches while it's busy
        self.assertLess(time.monotonic() - started, 0.2)
        self.store.sync_gate.set()
        self.assertTrue(self.s.flush(wait=True))
        self.assertEqual(self.store.syncs, 2)   # the stuck one, then all the rest at once
        self.assertEqual(self.store.values, {"volume": 29, "style": "s29"})

    def test_flush_and_wait_finishes_the_write_before_returning(self):
        self.store.sync_gate = threading.Event()
        self.s.set("volume", 7)
        threading.Timer(0.1, self.store.sync_gate.set).start()
        self.assertTrue(self.s.flush(wait=True))
        self.assertEqual((self.store.syncs, self.store.values["volume"]), (1, 7))

    def test_flush_and_wait_also_waits_for_a_write_already_under_way(self):
        self.store.sync_gate = threading.Event()
        self.s.set("route", "{...}")            # handed over at once
        threading.Timer(0.1, self.store.sync_gate.set).start()
        self.assertTrue(self.s.flush(wait=True))
        self.assertEqual(self.store.syncs, 1)

    def test_flush_and_wait_gives_up_after_its_timeout(self):
        self.store.sync_gate = threading.Event()
        self.addCleanup(self.store.sync_gate.set)
        self.s.set("volume", 7)
        started = time.monotonic()
        self.assertFalse(self.s.flush(wait=True, timeout=0.1))
        self.assertLess(time.monotonic() - started, 1)

    def test_close_writes_everything_waiting(self):
        self.s.set("volume", 3)
        self.s.set("style", "trail")
        self.s.close()
        self.assertEqual(self.store.values, {"volume": 3, "style": "trail"})
        self.assertEqual(self.store.syncs, 1)

    def test_a_failed_write_is_tried_again_with_the_next(self):
        self.store.fail_syncs = 1
        self.s.set("volume", 3)
        with mock.patch("builtins.print"):
            self.s.flush(wait=True)
        self.assertEqual(self.store.syncs, 0)
        self.s.set("style", "trail")
        self.s.flush(wait=True)
        self.assertEqual(self.store.syncs, 1)
        self.assertEqual(self.store.values, {"volume": 3, "style": "trail"})

    def test_a_failed_write_doesnt_undo_a_newer_value(self):
        self.store.fail_syncs = 1
        self.s.set("volume", 3)
        with mock.patch("builtins.print"):
            self.s.flush(wait=True)
        self.s.set("volume", 4)
        self.s.flush(wait=True)
        self.assertEqual(self.store.values["volume"], 4)

    def test_get_int_falls_back_on_junk(self):
        self.s.set("volume", "loud")
        self.assertEqual(self.s.get_int("volume", 40), 40)


class RealFileTest(unittest.TestCase):
    """The same against a real QSettings file, read back by a fresh one."""

    def test_written_on_the_writer_thread_and_read_back_next_run(self):
        path = os.path.join(tempfile.mkdtemp(), "baja-os.conf")
        open_store = lambda: QSettings(path, QSettings.Format.IniFormat)
        s = Settings(open_store=open_store, flush_after_ms=10)
        s.set("volume", 33)
        s.set("route", "{...}")
        s.close()
        again = Settings(open_store=open_store)
        self.addCleanup(again.close, 1)
        self.assertEqual(again.get_int("volume", 0), 33)
        self.assertEqual(again.get("route"), "{...}")
        self.assertIsNone(again.get("missing"))


if __name__ == "__main__":
    unittest.main()
