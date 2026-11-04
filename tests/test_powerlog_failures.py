"""Off-Pi tests for backend/powerlog.py: a sample that keeps failing is logged
once (and once when it recovers), not on every sample.

    python3 -m unittest tests.test_powerlog_failures
"""

import os
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from backend.powerlog import PowerLog


class SampleFailureTest(unittest.TestCase):
    def setUp(self):
        self._dir = tempfile.TemporaryDirectory()
        self.addCleanup(self._dir.cleanup)
        self.log_path = Path(self._dir.name) / "x.log"
        self.p = PowerLog(folder=self._dir.name)
        self.p._file = open(self.log_path, "a", buffering=1)
        self.addCleanup(self.p._file.close)
        # Keep the output quiet, and count the fsyncs an event costs.
        for patcher in (mock.patch("builtins.print"), mock.patch("backend.powerlog.os.fsync")):
            patcher.start()
            self.addCleanup(patcher.stop)
        self.fsync = os.fsync

    def run_samples(self, outcomes):
        """Run _sample_once() once per outcome: an exception to raise, or None to succeed."""
        with mock.patch.object(self.p, "_sample", side_effect=outcomes):
            for _ in outcomes:
                self.p._sample_once()

    def event_lines(self):
        return [line for line in self.log_path.read_text().splitlines() if line.startswith("EVENT|")]

    def test_same_error_fifty_times_is_logged_once(self):
        self.run_samples([ValueError("bad meminfo")] * 50)
        lines = self.event_lines()
        self.assertEqual(len(lines), 1)
        self.assertIn("sample failed: ValueError: bad meminfo", lines[0])

    def test_two_different_errors_are_two_lines(self):
        self.run_samples([ValueError("first")] * 3 + [OSError("second")] * 3)
        lines = self.event_lines()
        self.assertEqual(len(lines), 2)
        self.assertIn("sample failed: ValueError: first", lines[0])
        self.assertIn("sample failed: OSError: second", lines[1])

    def test_recovery_is_logged_once_with_the_count(self):
        self.run_samples([ValueError("x"), ValueError("x"), None, None, None])
        lines = self.event_lines()
        self.assertEqual(len(lines), 2)
        self.assertIn("sample failed: ValueError: x", lines[0])
        self.assertIn("samples working again after 2 failed", lines[1])

    def test_failing_again_after_recovery_is_logged_again(self):
        self.run_samples([ValueError("x"), None, ValueError("x"), ValueError("x")])
        lines = self.event_lines()
        self.assertEqual(len(lines), 3)
        self.assertIn("sample failed: ValueError: x", lines[0])
        self.assertIn("samples working again after 1 failed", lines[1])
        self.assertIn("sample failed: ValueError: x", lines[2])

    def test_success_all_along_logs_nothing(self):
        self.run_samples([None] * 10)
        self.assertEqual(self.event_lines(), [])
        self.assertEqual(self.p._sample_fails, 0)

    def test_repeated_failure_does_not_fsync_each_time(self):
        self.run_samples([ValueError("x")] * 50)
        self.assertEqual(self.fsync.call_count, 1)


if __name__ == "__main__":
    unittest.main()
