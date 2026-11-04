"""Off-Pi tests for backend.FailureLog: a failing check is logged once with its
traceback while the same error repeats, again when the error changes, and once
when it works again. Nothing is logged while it keeps working.

    python3 -m unittest tests.test_failure_logger
"""

import contextlib
import io
import unittest

from backend import FailureLog


def boom(message="broken"):
    """An exception with a real traceback, as a crashed check would have."""
    try:
        raise ValueError(message)
    except ValueError as e:
        return e


class FailureLogTest(unittest.TestCase):
    def setUp(self):
        self.log = FailureLog("Test: check failed", "Test: working again")

    def run_check(self, error=None):
        out = io.StringIO()
        with contextlib.redirect_stdout(out):
            self.log(error)
        return out.getvalue()

    def test_the_first_error_is_printed_once_with_its_traceback(self):
        out = self.run_check(boom())
        self.assertTrue(out.startswith("Test: check failed: ValueError: broken\n"))
        self.assertIn("Traceback (most recent call last):", out)
        self.assertIn('raise ValueError(message)', out)
        self.assertTrue(out.endswith("ValueError: broken\n"))
        self.assertEqual(self.log.error, "ValueError: broken")

    def test_the_same_error_again_prints_nothing(self):
        self.run_check(boom())
        self.assertEqual(self.run_check(boom()), "")
        self.assertEqual(self.run_check(boom()), "")
        self.assertEqual(self.log.error, "ValueError: broken")

    def test_a_different_error_prints_again(self):
        self.run_check(boom("first"))
        out = self.run_check(boom("second"))
        self.assertTrue(out.startswith("Test: check failed: ValueError: second\n"))
        self.assertEqual(self.log.error, "ValueError: second")

    def test_success_after_a_failure_prints_the_recovery_line_once(self):
        self.run_check(boom())
        self.assertEqual(self.run_check(), "Test: working again\n")
        self.assertEqual(self.log.error, "")
        self.assertEqual(self.run_check(), "")

    def test_success_with_no_prior_failure_prints_nothing(self):
        self.assertEqual(self.run_check(), "")
        self.assertEqual(self.log.error, "")

    def test_the_same_error_after_recovery_is_logged_again(self):
        self.run_check(boom())
        self.run_check()
        out = self.run_check(boom())
        self.assertTrue(out.startswith("Test: check failed: ValueError: broken\n"))


if __name__ == "__main__":
    unittest.main()
