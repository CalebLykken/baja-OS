"""Off-Pi tests for backend/system.py: asking systemd to reboot or shut down
(systemctl faked), and that a crashing status check is logged once, frees the
busy flag, keeps the old readings, and lets the next check run.

    python3 -m unittest tests.test_system
"""

import subprocess
import unittest
from types import SimpleNamespace
from unittest import mock

from PyQt6.QtCore import QCoreApplication

from backend import system as system_module
from backend.system import SystemInfo, can_power, power

app = QCoreApplication.instance() or QCoreApplication([])


def ran(code, out="", err=""):
    return subprocess.CompletedProcess(["systemctl"], code, out, err)


class PowerTest(unittest.TestCase):
    def test_yes(self):
        with mock.patch("subprocess.run", return_value=ran(0)) as run:
            self.assertEqual(power("poweroff"), "")
        self.assertEqual(run.call_args[0][0], ["systemctl", "--no-ask-password", "poweroff"])

    def test_no_polkit_rule(self):
        err = "Failed to power off system via logind: Access denied\n"
        with mock.patch("subprocess.run", return_value=ran(1, err=err)):
            self.assertEqual(power("poweroff"), err.strip())

    def test_failed_without_a_reason(self):
        with mock.patch("subprocess.run", return_value=ran(1)):
            self.assertIn("failed", power("poweroff"))

    def test_no_systemctl(self):
        with mock.patch("subprocess.run", side_effect=FileNotFoundError):
            self.assertIn("isn't installed", power("poweroff"))

    def test_no_answer(self):
        with mock.patch("subprocess.run", side_effect=subprocess.TimeoutExpired("systemctl", 10)):
            self.assertIn("didn't answer", power("reboot"))


class InlineThread:
    """Stands in for threading.Thread: start() runs the work on the spot."""

    def __init__(self, target=None, daemon=None):
        self.target = target

    def start(self):
        self.target()


def logged(printed):
    return [c.args[0] for c in printed.call_args_list if c.args and "System" in str(c.args[0])]


class HoldTest(unittest.TestCase):
    """Reboot and shut down wait for an update's merge, but not for ever."""

    def setUp(self):
        self.busy = True
        self.sys = SystemInfo()
        self.sys.hold_power_while(lambda: self.busy)
        self.asked = []
        p = mock.patch("backend.system.power", side_effect=lambda a: self.asked.append(a) or "")
        p.start()
        self.addCleanup(p.stop)
        t = mock.patch("backend.system.threading.Thread", InlineThread)
        t.start()
        self.addCleanup(t.stop)

    def tick(self):
        self.sys._held_tick()

    def test_not_busy_goes_at_once(self):
        self.busy = False
        self.sys.powerOff()
        self.assertEqual(self.asked, ["poweroff"])

    def test_waits_for_the_merge(self):
        self.sys.reboot()
        self.tick()
        self.assertEqual(self.asked, [])
        self.busy = False
        self.tick()
        self.assertEqual(self.asked, ["reboot"])
        self.assertFalse(self.sys._hold_timer.isActive())

    def test_gives_up_in_bounded_time(self):
        with mock.patch.object(system_module, "POWER_HOLD_S", 0):
            self.sys.powerOff()
        self.tick()                         # still merging: shuts down anyway
        self.assertEqual(self.asked, ["poweroff"])

    def test_cancelling_drops_the_wait(self):
        self.sys.powerOff()
        self.sys.cancel_power()
        self.assertFalse(self.sys._hold_timer.isActive())
        self.assertIsNone(self.sys._held)
        self.assertEqual(self.asked, [])

    def test_cancelling_with_nothing_waiting_is_harmless(self):
        self.sys.cancel_power()
        self.assertIsNone(self.sys._held)

    def test_asking_again_does_not_extend_the_wait(self):
        self.sys.powerOff()
        until = self.sys._held[1]
        self.sys.powerOff()
        self.assertEqual(self.sys._held[1], until)
        self.sys._hold_timer.stop()


class CanPowerTest(unittest.TestCase):
    def test_answers(self):
        for out, want in (('s "yes"\n', True), ('s "no"\n', False), ('s "challenge"\n', False)):
            with mock.patch("subprocess.run", return_value=ran(0, out)):
                self.assertIs(can_power(), want)

    def test_no_answer_is_none(self):
        with mock.patch("subprocess.run", return_value=ran(1, "", "not running")):
            self.assertIsNone(can_power())
        with mock.patch("subprocess.run", side_effect=FileNotFoundError):
            self.assertIsNone(can_power())


class StatusCheckTest(unittest.TestCase):
    def setUp(self):
        self.version = mock.patch("backend.system.version_text", return_value="v1 (abc)").start()
        self.system = SystemInfo()
        mock.patch("backend.system.threading", SimpleNamespace(Thread=InlineThread)).start()
        self.printed = mock.patch("builtins.print").start()
        self.addCleanup(mock.patch.stopall)

    def check(self, used=1000, error=None):
        """One check, with the memory reading faked to give `used` or raise."""
        memory = mock.patch("backend.system.memory_mb", side_effect=error) if error else \
            mock.patch("backend.system.memory_mb", return_value=(used, 4000))
        with memory, mock.patch("backend.system.cpu_temp", return_value=50.0), \
                mock.patch("backend.system.fan_rpm", return_value=None), \
                mock.patch("backend.system.power_state", return_value=""), \
                mock.patch("backend.system.uptime_text", return_value="5 min"), \
                mock.patch("backend.system.can_power", return_value=False):
            self.system._check()

    def asked(self, answers):
        """Three checks with logind answering in turn; how often it was asked."""
        with mock.patch("backend.system.memory_mb", return_value=(1, 2)), \
                mock.patch("backend.system.power_state", return_value=""), \
                mock.patch("backend.system.can_power", side_effect=answers) as ask:
            for _ in range(3):
                self.system._check()
        return ask.call_count

    def test_version_is_read_by_the_first_check_not_the_constructor(self):
        self.version.assert_not_called()
        self.assertEqual(self.system.version, "")
        seen = []
        self.system.changed.connect(lambda: seen.append(self.system.version))
        self.check()
        self.check()
        self.assertEqual(self.system.version, "v1 (abc)")
        self.assertEqual(self.version.call_count, 1)
        self.assertEqual(seen[0], "v1 (abc)")

    def test_a_crashing_version_read_leaves_it_blank_and_checks_go_on(self):
        self.version.side_effect = RuntimeError("git")
        self.check()
        self.assertEqual(self.system.version, "")
        self.assertEqual(self.system.memUsed, 1000)

    def test_logind_is_asked_once(self):
        self.assertEqual(self.asked([True]), 1)
        self.assertTrue(self.system.canPower)

    def test_a_no_is_an_answer_too(self):
        self.assertEqual(self.asked([False]), 1)
        self.assertFalse(self.system.canPower)

    def test_logind_is_asked_again_until_it_answers(self):
        self.assertEqual(self.asked([None, None, True]), 3)    # not up yet at boot
        self.assertTrue(self.system.canPower)

    def test_two_crashing_checks_log_once_and_keep_the_readings(self):
        self.check(used=1000)
        self.assertEqual((self.system.memUsed, self.system.temp), (1000, 50.0))
        for _ in range(2):
            self.check(error=TypeError("surprise"))
            self.assertFalse(self.system._busy)           # the next check can run
            self.assertEqual((self.system.memUsed, self.system.temp), (1000, 50.0))
        lines = logged(self.printed)
        self.assertEqual(len(lines), 1)
        self.assertIn("TypeError: surprise", lines[0])
        self.assertIn("Traceback", lines[0])

    def test_the_next_check_after_a_crash_applies_good_data(self):
        self.check(used=1000)
        self.check(error=TypeError("surprise"))
        self.check(used=1200)
        self.assertEqual(self.system.memUsed, 1200)
        self.assertFalse(self.system._busy)
        lines = logged(self.printed)
        self.assertEqual(len(lines), 2)
        self.assertIn("working again", lines[1])

    def test_a_failing_disk_reading_is_caught_too(self):
        with mock.patch("backend.system.memory_mb", return_value=(1, 2)), \
                mock.patch("backend.system.shutil.disk_usage", side_effect=OSError("gone")):
            self.system._check()
        self.assertFalse(self.system._busy)
        self.assertEqual(len(logged(self.printed)), 1)


if __name__ == "__main__":
    unittest.main()
