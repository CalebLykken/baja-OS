"""Off-Pi tests for the demo switch (backend/demo.py): on_pi() reading the
board model, and allowed() choosing between a forced flag and the default.

Plain Python, no PyQt6, no real /proc: the board model file is a temp file.

    python3 -m unittest tests.test_demo
"""

import tempfile
import unittest
from pathlib import Path
from unittest import mock

from backend import demo


class AllowedTest(unittest.TestCase):
    def test_no_flag_takes_the_default(self):
        self.assertIs(demo.allowed(None, True), True)
        self.assertIs(demo.allowed(None, False), False)

    def test_a_flag_overrides_the_default(self):
        self.assertIs(demo.allowed(True, False), True)     # --demo
        self.assertIs(demo.allowed(False, True), False)    # --no-demo


class OnPiTest(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)

    def model_file(self, contents):
        path = Path(self._tmp.name) / "model"
        path.write_bytes(contents)
        return path

    def check_on_pi(self, path):
        with mock.patch("backend.demo.MODEL", path):
            return demo.on_pi()

    def test_raspberry_pi_is_on_pi(self):
        # /proc/device-tree/model is NUL-terminated on the real board
        path = self.model_file(b"Raspberry Pi 5 Model B Rev 1.0\x00")
        self.assertIs(self.check_on_pi(path), True)

    def test_other_board_is_not_on_pi(self):
        path = self.model_file(b"MacBook")
        self.assertIs(self.check_on_pi(path), False)

    def test_missing_model_file_is_not_on_pi(self):
        path = Path(self._tmp.name) / "no-such-model"
        self.assertIs(self.check_on_pi(path), False)


if __name__ == "__main__":
    unittest.main()
