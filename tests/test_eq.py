"""Off-Pi tests for backend/eq.py: saved gains, presets, what gets written to
PipeWire, and that the writer thread survives a failed write.

    python3 -m unittest tests.test_eq
"""

import subprocess
import threading
import time
import unittest
from unittest import mock

try:
    from PyQt6.QtCore import QCoreApplication

    from backend import eq
except ImportError as e:
    raise unittest.SkipTest(f"PyQt6 isn't installed ({e})")

app = QCoreApplication.instance() or QCoreApplication([])


class FakeSettings:
    def __init__(self):
        self.d = {}

    def get(self, k, default=None):
        return self.d.get(k, default)

    def set(self, k, v):
        self.d[k] = v


class LoadTests(unittest.TestCase):
    def make(self, raw):
        s = FakeSettings()
        s.d["eq"] = raw
        return eq.Equalizer(s)

    def test_empty_gives_flat(self):
        self.assertEqual(self.make("")._gains, [0, 0, 0, 0, 0])

    def test_loads_saved_gains(self):
        self.assertEqual(self.make("1,2,3,4,5")._gains, [1, 2, 3, 4, 5])

    def test_clamps_to_limit(self):
        self.assertEqual(self.make("99,-99,0,0,0")._gains, [12, -12, 0, 0, 0])

    def test_wrong_count_gives_flat(self):
        self.assertEqual(self.make("1,2,3")._gains, [0, 0, 0, 0, 0])

    def test_not_numbers_gives_flat(self):
        self.assertEqual(self.make("a,b,c,d,e")._gains, [0, 0, 0, 0, 0])


class PresetTests(unittest.TestCase):
    def setUp(self):
        self.settings = FakeSettings()
        self.eq = eq.Equalizer(self.settings)

    def test_fresh_is_flat(self):
        self.assertEqual(self.eq.preset, "Flat")

    def test_apply_preset(self):
        self.eq.applyPreset("Road")
        self.assertEqual(self.eq.preset, "Road")
        self.assertEqual(self.eq.gains, [4, 2, 0, 2, 3])

    def test_change_one_band_is_custom(self):
        self.eq.setGain(0, 5)
        self.assertEqual(self.eq.gains, [5, 0, 0, 0, 0])
        self.assertEqual(self.eq.preset, "Custom")

    def test_gain_index_out_of_range_does_nothing(self):
        self.eq.setGain(9, 5)
        self.eq.setGain(-1, 5)
        self.assertEqual(self.eq.gains, [0, 0, 0, 0, 0])
        self.assertNotIn("eq", self.settings.d)

    def test_set_all_saves(self):
        self.eq.applyPreset("Road")
        self.assertEqual(self.settings.get("eq"), "4,2,0,2,3")


class PushTests(unittest.TestCase):
    def test_pending_string(self):
        e = eq.Equalizer(FakeSettings())
        e._pw = True
        e._gains = [4, 2, 0, 2, 3]
        e._push()
        self.assertTrue(e._pending.startswith('"pre:Gain" -4.0 "bass:Gain" 4.0'), e._pending)
        self.assertEqual(
            e._pending,
            '"pre:Gain" -4.0 "bass:Gain" 4.0 "low:Gain" 2.0 "mid:Gain" 0.0 '
            '"high:Gain" 2.0 "treb:Gain" 3.0')


class PwCliTests(unittest.TestCase):
    def test_missing_binary_gives_empty(self):
        with mock.patch("backend.eq.subprocess.run", side_effect=FileNotFoundError()):
            self.assertEqual(eq._pw_cli("i", eq.NODE), "")

    def test_timeout_gives_empty(self):
        with mock.patch("backend.eq.subprocess.run",
                        side_effect=subprocess.TimeoutExpired("pw-cli", 3)):
            self.assertEqual(eq._pw_cli("i", eq.NODE), "")

    def test_bad_utf8_gives_empty(self):
        err = UnicodeDecodeError("utf-8", b"\xff", 0, 1, "bad")
        with mock.patch("backend.eq.subprocess.run", side_effect=err):
            self.assertEqual(eq._pw_cli("i", eq.NODE), "")

    def test_decodes_with_replacement(self):
        with mock.patch("backend.eq.subprocess.run") as run:
            run.return_value = subprocess.CompletedProcess([], 0, stdout="ok", stderr="")
            self.assertEqual(eq._pw_cli("i", eq.NODE), "ok")
        self.assertEqual(run.call_args.kwargs["errors"], "replace")

    def test_node_id_parses(self):
        with mock.patch("backend.eq._pw_cli", return_value="  id: 42, type PipeWire:Interface:Node\n"):
            self.assertEqual(eq.node_id(), 42)

    def test_node_id_none_when_absent(self):
        with mock.patch("backend.eq._pw_cli", return_value=""):
            self.assertIsNone(eq.node_id())


class WriterSurvivesTests(unittest.TestCase):
    def test_writer_keeps_going_after_an_error(self):
        e = eq.Equalizer(FakeSettings())
        e._pw = True
        calls = []

        def fake_cli(*args, **kwargs):
            calls.append(args)
            if len(calls) == 1:
                raise RuntimeError("first write fails")
            return ""

        with mock.patch("backend.eq._pw_cli", side_effect=fake_cli), \
                mock.patch.object(eq.errorlog.log, "report") as report:
            t = threading.Thread(target=e._writer, daemon=True)
            t.start()

            e._gains = [1, 0, 0, 0, 0]
            e._push()
            self._wait_for(lambda: len(calls) >= 1)

            e._gains = [2, 0, 0, 0, 0]
            e._push()
            self._wait_for(lambda: len(calls) >= 2)

            self.assertTrue(t.is_alive())
            self.assertEqual(len(calls), 2)
            report.assert_called_once()

    def _wait_for(self, cond, limit=2.0):
        end = time.monotonic() + limit
        while not cond() and time.monotonic() < end:
            time.sleep(0.01)
        self.assertTrue(cond(), "writer did not make the write")


if __name__ == "__main__":
    unittest.main()
