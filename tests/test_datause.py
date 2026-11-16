"""Off-Pi tests for backend/datause.py with a fake /sys/class/net and clock.

    python3 -m unittest tests.test_datause
"""

import os
import shutil
import tempfile
import time
import unittest

from PyQt6.QtCore import QCoreApplication

from backend.datause import SAMPLE_EVERY_MS, SAVE_EVERY_SAMPLES, DataUse, format_bytes

app = QCoreApplication.instance() or QCoreApplication([])


class FakeSettings:
    def __init__(self):
        self.d = {}
        self.writes = 0          # counts writes to the data-use setting

    def get(self, k, default=None):
        return self.d.get(k, default)

    def set(self, k, v):
        if k == "dataUse":
            self.writes += 1
        self.d[k] = v


def stamp(y, m, d):
    return time.mktime((y, m, d, 12, 0, 0, 0, 0, -1))


class DataUseTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = self.tmp.name
        self.now = stamp(2026, 10, 15)
        self.settings = FakeSettings()

    def iface(self, name, rx, tx):
        d = os.path.join(self.root, name, "statistics")
        os.makedirs(d, exist_ok=True)
        for f, v in (("rx_bytes", rx), ("tx_bytes", tx)):
            with open(os.path.join(d, f), "w") as fh:
                fh.write(f"{v}\n")

    def make(self):
        return DataUse(self.settings, root=self.root, clock=lambda: self.now)

    def test_missing_interfaces_show_nothing(self):
        du = DataUse(self.settings, root=os.path.join(self.root, "nope"), clock=lambda: self.now)
        du.sample()
        self.assertFalse(du.available)

    def test_ignores_other_interfaces(self):
        self.iface("eth0", 5000, 5000)
        du = self.make()
        du.sample()
        self.assertFalse(du.available)

    def test_adds_wifi_and_tether_deltas(self):
        self.iface("wlan0", 100, 50)
        self.iface("bnep0", 10, 10)
        du = self.make()
        du.sample()
        self.assertEqual(du.bytesThisMonth, 170)
        self.iface("wlan0", 300, 150)
        du.sample()
        self.assertEqual(du.bytesThisMonth, 470)
        self.assertTrue(du.available)

    def test_counter_reset_counts_new_bytes(self):
        self.iface("wlan0", 1000, 1000)
        du = self.make()
        du.sample()
        self.iface("wlan0", 30, 20)         # rebooted
        du.sample()
        self.assertEqual(du.bytesThisMonth, 2050)

    def test_a_tether_that_went_away_counts_from_zero_when_it_is_back(self):
        self.iface("bnep0", 900, 100)
        du = self.make()
        du.sample()
        shutil.rmtree(os.path.join(self.root, "bnep0"))
        self.iface("wlan0", 10, 0)
        du.sample()
        self.assertNotIn("bnep0", du._last)
        self.iface("bnep0", 1500, 0)        # a new connection, already past the old count
        du.sample()
        self.assertEqual(du.bytesThisMonth, 1000 + 10 + 1500)

    def test_the_last_interface_going_away_is_saved_too(self):
        self.iface("bnep0", 900, 100)
        du = self.make()
        du.sample()
        shutil.rmtree(os.path.join(self.root, "bnep0"))
        du.sample()
        again = self.make()
        self.assertEqual(again._last, {})

    def test_an_unreadable_interface_keeps_its_place(self):
        self.iface("wlan0", 500, 0)
        du = self.make()
        du.sample()
        with open(os.path.join(self.root, "wlan0", "statistics", "rx_bytes"), "w") as f:
            f.write("garbage")
        du.sample()
        self.iface("wlan0", 600, 0)
        du.sample()
        self.assertEqual(du.bytesThisMonth, 600)    # not 500 + 600

    def test_month_rollover(self):
        self.iface("wlan0", 100, 0)
        du = self.make()
        du.sample()
        self.now = stamp(2026, 11, 1)
        self.iface("wlan0", 150, 0)
        du.sample()
        self.assertEqual(du.bytesThisMonth, 50)

    def test_survives_restart(self):
        self.iface("wlan0", 100, 0)
        self.make().sample()
        self.iface("wlan0", 400, 0)
        du = self.make()
        du.sample()
        self.assertEqual(du.bytesThisMonth, 400)

    def test_earlier_month_clock_keeps_the_total(self):
        self.iface("wlan0", 100, 0)
        self.make().sample()
        self.now = stamp(2026, 9, 1)       # the Pi's clock before it syncs
        self.iface("wlan0", 150, 0)
        du = self.make()
        du.sample()
        self.assertEqual(du.bytesThisMonth, 150)

    def roll(self, to):
        self.iface("wlan0", 2_100_000_000, 0)
        du = self.make()
        du.sample()
        self.now = to
        self.iface("wlan0", 2_100_000_100, 0)
        du.sample()
        return du

    def test_rollover_keeps_last_month(self):
        du = self.roll(stamp(2026, 11, 2))
        self.assertEqual(du.text, "0 KB (2.1 GB last month)")
        self.assertEqual(du.lastMonthBytes, 2_100_000_000)

    def test_rollover_across_new_year(self):
        self.now = stamp(2026, 12, 20)
        du = self.roll(stamp(2027, 1, 3))
        self.assertEqual(du.text, "0 KB (2.1 GB last month)")
        self.assertEqual(du.lastMonthBytes, 2_100_000_000)

    def test_skipped_month_shows_no_last_month(self):
        du = self.roll(stamp(2026, 12, 2))
        self.assertEqual(du.lastMonthBytes, 0)
        self.assertNotIn("(", du.text)

    def test_empty_old_month_shows_no_last_month(self):
        self.iface("eth0", 1, 1)
        du = self.make()
        du.sample()
        self.now = stamp(2026, 11, 2)
        du.sample()
        self.assertEqual(du.lastMonthBytes, 0)

    def test_last_month_survives_restart(self):
        self.roll(stamp(2026, 11, 2))
        du = self.make()
        self.assertEqual(du.lastMonthBytes, 2_100_000_000)
        self.assertEqual(du.text, "0 KB (2.1 GB last month)")

    def test_stale_last_month_is_not_shown(self):
        self.roll(stamp(2026, 11, 2))
        self.now = stamp(2027, 1, 5)
        du = self.make()
        du.sample()
        self.assertEqual(du.lastMonthBytes, 0)
        self.assertNotIn("(", du.text)
        self.assertNotIn("prev", self.settings.d["dataUse"])

    def test_malformed_prev_keeps_this_months_bytes(self):
        for prev in ('"x"', '{"month": "2026-10", "bytes": -5}', '{"month": "2026-10", "bytes": Infinity}',
                     '{"month": "2026-10", "bytes": "9"}', '{"month": "2026-10", "bytes": 1e400}',
                     '{"month": 7, "bytes": 5}', '{"month": "2026-13", "bytes": 5}', '{"bytes": 5}', 'null'):
            self.settings.d["dataUse"] = '{"month": "2026-11", "bytes": 500, "last": {}, "prev": %s}' % prev
            du = self.make()
            self.assertEqual(du.bytesThisMonth, 500, prev)
            self.assertEqual(du.lastMonthBytes, 0, prev)
            self.assertEqual(du.text, "0 KB", prev)

    def test_earlier_month_clock_does_not_create_last_month(self):
        self.iface("wlan0", 100, 0)
        self.make().sample()
        self.now = stamp(2026, 9, 1)
        du = self.make()
        du.sample()
        self.assertEqual(du.lastMonthBytes, 0)
        self.assertNotIn("prev", self.settings.d["dataUse"])

    def test_infinite_saved_bytes_starts_over(self):
        self.settings.d["dataUse"] = '{"month": "2026-11", "bytes": Infinity, "last": {}}'
        self.iface("wlan0", 7, 3)
        du = self.make()
        du.sample()
        self.assertEqual(du.bytesThisMonth, 10)

    def test_bad_saved_state_starts_over(self):
        self.settings.d["dataUse"] = "garbage"
        self.iface("wlan0", 7, 3)
        du = self.make()
        du.sample()
        self.assertEqual(du.bytesThisMonth, 10)

    def test_start_does_not_sample_at_once(self):
        self.iface("wlan0", 100, 50)
        du = self.make()
        du.start()
        # Cleanups run after the test returns; the lambdas hold du so the
        # QObject (and its child timers) is not collected before they stop.
        self.addCleanup(lambda: (du._first.stop(), du._timer.stop()))
        self.assertNotIn("dataUse", self.settings.d)
        self.assertFalse(du.available)
        self.assertTrue(du._first.isSingleShot())
        self.assertLess(du._first.interval(), SAMPLE_EVERY_MS)
        du._first.timeout.emit()
        self.assertIn("dataUse", self.settings.d)
        self.assertTrue(du.available)
        self.assertEqual(du.bytesThisMonth, 150)

    def test_five_samples_write_settings_once(self):
        du = self.make()
        for i in range(1, 6):
            self.iface("wlan0", 100 * i, 0)
            du.sample()
            self.assertEqual(du.bytesThisMonth, 100 * i)    # the figure on screen still grows every sample
        self.assertEqual(self.settings.writes, 1)           # only the first sample after start

    def test_writes_again_after_save_every_samples(self):
        du = self.make()
        for i in range(1, SAVE_EVERY_SAMPLES + 2):
            self.iface("wlan0", 100 * i, 0)
            du.sample()
        self.assertEqual(self.settings.writes, 2)           # samples 1 and 1 + SAVE_EVERY_SAMPLES
        self.assertEqual(du.bytesThisMonth, 100 * (SAVE_EVERY_SAMPLES + 1))

    def test_month_change_writes_at_once(self):
        self.iface("wlan0", 100, 0)
        du = self.make()
        du.sample()
        self.iface("wlan0", 200, 0)
        du.sample()
        self.assertEqual(self.settings.writes, 1)
        self.now = stamp(2026, 11, 1)
        self.iface("wlan0", 250, 0)
        du.sample()
        self.assertEqual(self.settings.writes, 2)
        self.assertIn('"month": "2026-11"', self.settings.d["dataUse"])
        self.assertEqual(du.bytesThisMonth, 50)

    def test_interface_going_away_writes_at_once(self):
        self.iface("bnep0", 900, 100)
        du = self.make()
        du.sample()
        self.iface("wlan0", 10, 0)
        du.sample()
        self.assertEqual(self.settings.writes, 1)           # wlan0 is new, nothing gone yet
        shutil.rmtree(os.path.join(self.root, "bnep0"))
        du.sample()
        self.assertEqual(self.settings.writes, 2)

    def test_restart_after_an_unsaved_sample_counts_correctly(self):
        self.iface("wlan0", 100, 0)
        du = self.make()
        du.sample()                                          # saved: 100
        self.iface("wlan0", 400, 0)
        du.sample()                                          # not saved yet
        self.assertEqual(self.settings.writes, 1)
        self.assertEqual(du.bytesThisMonth, 400)
        restarted = self.make()
        restarted.sample()                                   # counts 300 more from the saved 100
        self.assertEqual(restarted.bytesThisMonth, 400)

    def test_restart_after_reboot_counts_the_new_counter(self):
        self.iface("wlan0", 100, 0)
        du = self.make()
        du.sample()                                          # saved: 100
        self.iface("wlan0", 40, 0)                           # rebooted, counter from zero
        du.sample()
        restarted = self.make()
        restarted.sample()
        self.assertEqual(restarted.bytesThisMonth, 140)

    def test_save_writes_now(self):
        self.iface("wlan0", 100, 0)
        du = self.make()
        du.sample()
        self.iface("wlan0", 300, 0)
        du.sample()
        self.assertEqual(self.settings.writes, 1)
        du.save()
        self.assertEqual(self.settings.writes, 2)
        self.assertEqual(self.make().bytesThisMonth, 300)

    def test_format(self):
        self.assertEqual(format_bytes(1_200_000_000), "1.2 GB")
        self.assertEqual(format_bytes(5_000_000), "5 MB")

    def test_limit_defaults_off(self):
        self.iface("wlan0", 6_000_000_000, 0)
        du = self.make()
        du.sample()
        self.assertEqual(du.limitGb, 0)
        self.assertFalse(du.overLimit)

    def test_set_limit_warns_and_saves(self):
        self.iface("wlan0", 6_000_000_000, 0)
        du = self.make()
        du.sample()
        du.setLimit(5)
        self.assertTrue(du.overLimit)
        self.assertEqual(self.settings.d["dataLimitGb"], 5)
        du.setLimit(10)
        self.assertFalse(du.overLimit)

    def test_limit_follows_this_months_figure(self):
        du = self.roll(stamp(2026, 11, 2))
        du.setLimit(10)
        self.assertEqual(du.text, "0 KB of 10 GB (2.1 GB last month)")
        du.setLimit(0)
        self.assertEqual(du.text, "0 KB (2.1 GB last month)")

    def test_garbage_saved_limit_reads_as_off(self):
        for bad in ("lots", None, "", "-4", "1e9x", [1]):
            self.settings.d["dataLimitGb"] = bad
            self.assertEqual(self.make().limitGb, 0)
        self.settings.d["dataLimitGb"] = "9999"
        self.assertEqual(self.make().limitGb, 500)


if __name__ == "__main__":
    unittest.main()
