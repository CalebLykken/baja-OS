"""Off-Pi tests for backend/powerlog.py: reading the power chip's report and
the firmware's flags, picking kernel lines, and dropping old logs.

    python3 -m unittest tests.test_powerlog
"""

import os
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from backend.powerlog import (MAX_NOTES, KERNEL_BACKOFF_FIRST, KERNEL_BACKOFF_MAX, KERNEL_RUN_OK_S,
                              KERNEL_WORTH_KEEPING, flag_names, kernel_cmd,
                              logged_kernel_events, new_kernel_events, next_backoff,
                              parse_pmic, prune, PowerLog)

PMIC = """\
     3V7_WL_SW_A current(0)=0.10000000A
       VDD_CORE_A current(7)=2.00000000A
   HDMI_A current(13)=0.01000000A
     3V7_WL_SW_V volt(8)=3.70000000V
       VDD_CORE_V volt(15)=0.80000000V
   HDMI_V volt(23)=5.00000000V
        EXT5V_V volt(24)=4.81250000V
         BATT_V volt(25)=0.00000000V
"""


class ParseTest(unittest.TestCase):
    def test_input_volts_and_watts(self):
        volts, watts = parse_pmic(PMIC)
        self.assertAlmostEqual(volts, 4.8125)
        self.assertAlmostEqual(watts, 0.1 * 3.7 + 2 * 0.8 + 0.01 * 5, places=2)

    def test_nothing_to_read(self):
        self.assertEqual(parse_pmic(""), (None, None))


class FlagsTest(unittest.TestCase):
    def test_now_and_since_boot(self):
        self.assertEqual(flag_names(0x50001),
                         "under-voltage now, under-voltage since boot, throttled since boot")

    def test_none(self):
        self.assertEqual(flag_names(0), "none")


class KernelTest(unittest.TestCase):
    def test_keeps_what_points_at_power_or_the_screen(self):
        for line in ("hwmon hwmon2: Undervoltage detected!",
                     "usb 3-1: USB disconnect, device number 4",
                     "usb 1-1-port2: over-current condition",
                     "vc4-drm axi:gpu: [drm] flip_done timed out"):
            self.assertTrue(KERNEL_WORTH_KEEPING.search(line), line)

    def test_drops_the_rest(self):
        self.assertFalse(KERNEL_WORTH_KEEPING.search("EXT4-fs (mmcblk0p2): re-mounted"))


class RestartReplayTest(unittest.TestCase):
    LINES = ["[   12.5] kernel: hwmon hwmon2: Undervoltage detected!\n",
             "[   13.0] kernel: some chatter\n",
             "[   40.1] kernel: usb 3-1: USB disconnect, device number 4\n"]

    def test_first_run_records_the_boot(self):
        got = list(new_kernel_events(self.LINES, set()))
        self.assertEqual(len(got), 2)
        self.assertTrue(got[0].startswith("kernel: [   12.5]"))

    def test_restart_skips_what_the_file_holds(self):
        with tempfile.TemporaryDirectory() as d:
            log = Path(d) / "abcd.log"
            first = list(new_kernel_events(self.LINES[:1], set()))
            log.write_text("# SAMPLE|x\nEVENT|10:00:00|5.0|app started\n"
                           + "".join(f"EVENT|10:00:01|6.0|{t}\n" for t in first))
            seen = logged_kernel_events(log)
            self.assertEqual(seen, set(first))
            new = list(new_kernel_events(self.LINES, seen))
            self.assertEqual(len(new), 1)
            self.assertIn("USB disconnect", new[0])

    def test_missing_file(self):
        self.assertEqual(logged_kernel_events("/nonexistent/x.log"), set())


class PruneTest(unittest.TestCase):
    def test_keeps_the_newest(self):
        with tempfile.TemporaryDirectory() as d:
            for i in range(4):
                f = Path(d, f"{i}.log")
                f.write_text("x")
                os.utime(f, (i, i))
            prune(d, keep=2)
            self.assertEqual(sorted(p.name for p in Path(d).iterdir()), ["2.log", "3.log"])

    def test_a_file_vanishing_midway_is_skipped(self):
        with tempfile.TemporaryDirectory() as d:
            for i in range(4):
                f = Path(d, f"{i}.log")
                f.write_text("x")
                os.utime(f, (i, i))
            real = Path.stat

            def flaky(self, *a, **k):
                if self.name == "1.log":
                    raise FileNotFoundError(self.name)
                return real(self, *a, **k)

            with mock.patch.object(Path, "stat", flaky):
                prune(d, keep=2)
            self.assertEqual(sorted(p.name for p in Path(d).iterdir()), ["1.log", "2.log", "3.log"])

    def test_a_failed_delete_does_not_raise(self):
        with tempfile.TemporaryDirectory() as d:
            for i in range(3):
                Path(d, f"{i}.log").write_text("x")
            with mock.patch.object(Path, "unlink", side_effect=PermissionError):
                prune(d, keep=1)


class KernelFollowerTest(unittest.TestCase):
    def test_every_run_reads_the_whole_boot(self):
        # A restart reads from the start too, so lines logged while the follower
        # was down are not lost; the seen set keeps them from being recorded twice.
        cmd = kernel_cmd()
        self.assertEqual(cmd[cmd.index("-n") + 1], "all")
        self.assertNotIn("--since", cmd)
        self.assertIn("-f", cmd)

    def test_a_follower_restart_records_only_what_is_new(self):
        seen = set()
        before = ["[   12.5] kernel: hwmon hwmon2: Undervoltage detected!\n"]
        during_gap = ["[   80.0] kernel: usb 3-1: USB disconnect, device number 4\n"]
        self.assertEqual(len(list(new_kernel_events(before, seen))), 1)
        again = list(new_kernel_events(before + during_gap, seen))
        self.assertEqual(len(again), 1)
        self.assertIn("USB disconnect", again[0])

    def test_backoff_doubles_to_the_cap(self):
        wait, seen = KERNEL_BACKOFF_FIRST, []
        for _ in range(10):
            wait = next_backoff(wait, 1)
            seen.append(wait)
        self.assertEqual(seen[:3], [10, 20, 40])
        self.assertEqual(seen[-1], KERNEL_BACKOFF_MAX)
        self.assertLessEqual(max(seen), KERNEL_BACKOFF_MAX)

    def test_backoff_resets_after_a_long_run(self):
        self.assertEqual(next_backoff(KERNEL_BACKOFF_MAX, KERNEL_RUN_OK_S + 1), KERNEL_BACKOFF_FIRST)


class NoteTest(unittest.TestCase):
    """note() is for other threads: it queues, the sampling thread writes."""

    def setUp(self):
        self._dir = tempfile.TemporaryDirectory()
        self.addCleanup(self._dir.cleanup)
        self.path = Path(self._dir.name) / "x.log"
        self.p = PowerLog(folder=self._dir.name)
        self.p._file = open(self.path, "a", buffering=1)
        self.addCleanup(self.p._file.close)
        patches = [mock.patch("builtins.print"), mock.patch("backend.powerlog.os.fsync")]
        self.fsync = patches[1].start()
        patches[0].start()
        for patcher in patches:
            self.addCleanup(patcher.stop)

    def events(self):
        return [line.split("|", 3) for line in self.path.read_text().splitlines()
                if line.startswith("EVENT|")]

    def test_a_note_from_a_thread_is_written_on_the_drain_with_its_own_time(self):
        import threading
        with mock.patch.object(PowerLog, "_stamp", side_effect=["10:00:00|1.0", "10:00:05|6.0"]):
            t = threading.Thread(target=lambda: (self.p.note("car quiet"), self.p.note("countdown")))
            t.start()
            t.join()
        self.assertEqual(self.events(), [])
        self.p._drain_notes()
        self.assertEqual([(e[1], e[2], e[3]) for e in self.events()],
                         [("10:00:00", "1.0", "car quiet"), ("10:00:05", "6.0", "countdown")])
        self.p._drain_notes()
        self.assertEqual(len(self.events()), 2)

    def test_note_never_forces_to_the_card(self):
        self.p.note("car quiet")
        self.fsync.assert_not_called()

    def test_a_full_queue_drops_the_oldest(self):
        for i in range(MAX_NOTES + 5):
            self.p.note(f"n{i}")
        self.p._drain_notes()
        texts = [e[3] for e in self.events()]
        self.assertEqual(len(texts), MAX_NOTES)
        self.assertEqual(texts[0], "n5")
        self.assertEqual(texts[-1], f"n{MAX_NOTES + 4}")


if __name__ == "__main__":
    unittest.main()
