"""Off-Pi tests for asking systemd to reboot or shut down (backend/system.py),
with systemctl faked.

    python3 -m unittest tests.test_system
"""

import subprocess
import unittest
from unittest import mock

from backend.system import power


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


if __name__ == "__main__":
    unittest.main()
