"""Off-Pi tests for tools/startup_report.py: parsing the Startup: summary
lines, per-phase statistics, and the command-line table.

    python3 -m unittest tests.test_startup_report
"""

import importlib.util
import io
import os
import tempfile
import unittest
from contextlib import redirect_stdout

from backend.startup import StartupClock

_PATH = os.path.join(os.path.dirname(__file__), "..", "tools", "startup_report.py")
_spec = importlib.util.spec_from_file_location("startup_report", _PATH)
sr = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(sr)


class FakeNow:
    """A monotonic clock the test moves by hand, in seconds."""

    def __init__(self, t=100.0):
        self.t = t

    def __call__(self):
        return self.t


class ParseTest(unittest.TestCase):
    def test_full_line(self):
        phases, up = sr.parse(
            "Startup: imports 412 ms, backends 900 ms, first frame 2100 ms "
            "(system up 14.2 s)")
        self.assertEqual(phases, {"imports": 412, "backends": 900, "first frame": 2100})
        self.assertEqual(up, 14.2)

    def test_journal_prefix(self):
        phases, up = sr.parse(
            "May 01 12:00:00 baja python3[812]: Startup: imports 412 ms (system up 3.0 s)")
        self.assertEqual(phases, {"imports": 412})
        self.assertEqual(up, 3.0)

    def test_without_system_up(self):
        phases, up = sr.parse("Startup: imports 412 ms, qml 1840 ms")
        self.assertEqual(phases, {"imports": 412, "qml": 1840})
        self.assertIsNone(up)

    def test_malformed_piece_skipped(self):
        phases, up = sr.parse(
            "Startup: imports 400 ms, bogus, qml x ms, first frame 2100 ms "
            "(system up 14.0 s)")
        self.assertEqual(phases, {"imports": 400, "first frame": 2100})
        self.assertEqual(up, 14.0)

    def test_non_startup_line_is_none(self):
        self.assertIsNone(sr.parse("baja-os[812]: GPS fix acquired"))
        self.assertIsNone(sr.parse(""))


class RoundTripTest(unittest.TestCase):
    def test_parse_reads_back_the_clock_summary(self):
        now = FakeNow(100.0)
        clock = StartupClock(now=now, uptime=lambda: 14.2)
        now.t = 100.4
        clock.mark("imports")
        now.t = 101.8
        clock.mark("qml")
        now.t = 102.1
        clock.mark("first frame")
        phases, up = sr.parse(clock.summary())
        self.assertEqual(phases, {"imports": 400, "qml": 1800, "first frame": 2100})
        self.assertEqual(up, 14.2)


class SummariseTest(unittest.TestCase):
    def test_odd_count_median(self):
        records = [({"qml": 100}, None), ({"qml": 300}, None), ({"qml": 200}, None)]
        rows = dict(sr.summarise(records))
        self.assertEqual(rows["qml"]["n"], 3)
        self.assertEqual(rows["qml"]["median"], 200)
        self.assertEqual(rows["qml"]["min"], 100)
        self.assertEqual(rows["qml"]["max"], 300)
        self.assertEqual(rows["qml"]["latest"], 200)

    def test_even_count_median(self):
        records = [({"qml": 100}, None), ({"qml": 200}, None),
                   ({"qml": 300}, None), ({"qml": 400}, None)]
        rows = dict(sr.summarise(records))
        self.assertEqual(rows["qml"]["median"], 250)
        self.assertEqual(rows["qml"]["latest"], 400)

    def test_first_seen_order_and_system_up_row(self):
        records = [({"imports": 1, "qml": 2}, 10.0),
                   ({"qml": 4, "first frame": 5}, None)]
        rows = sr.summarise(records)
        self.assertEqual([name for name, _ in rows],
                         ["imports", "qml", "first frame", "system up (s)"])
        self.assertEqual(rows[1][1]["n"], 2)
        self.assertEqual(rows[3][1]["n"], 1)
        self.assertEqual(rows[3][1]["median"], 10.0)

    def test_no_system_up_row_without_uptime(self):
        rows = sr.summarise([({"qml": 2}, None)])
        self.assertEqual([name for name, _ in rows], ["qml"])


class SelectLastTest(unittest.TestCase):
    def test_keeps_the_newest(self):
        records = [({"qml": 1}, None), ({"qml": 2}, None), ({"qml": 3}, None)]
        self.assertEqual(sr.select_last(records, 2), records[1:])
        self.assertEqual(sr.select_last(records, 10), records)


class MainTest(unittest.TestCase):
    def _run(self, text, argv_extra=()):
        with tempfile.TemporaryDirectory() as d:
            path = os.path.join(d, "journal.txt")
            with open(path, "w", encoding="utf-8") as f:
                f.write(text)
            out = io.StringIO()
            with redirect_stdout(out):
                code = sr.main([path, *argv_extra])
        return code, out.getvalue()

    def test_prints_each_phase(self):
        code, out = self._run(
            "x\nStartup: imports 400 ms, qml 1800 ms, first frame 2100 ms (system up 14.0 s)\n"
            "Startup: imports 420 ms, qml 1900 ms, first frame 2200 ms (system up 20.0 s)\n")
        self.assertEqual(code, 0)
        self.assertIn("2 starts", out)
        for name in ("imports", "qml", "first frame", "system up (s)"):
            self.assertIn(name, out)

    def test_no_startup_lines_returns_1(self):
        code, out = self._run("nothing here\nsecond line\n")
        self.assertEqual(code, 1)
        self.assertIn("no Startup: lines found", out)

    def test_last_limits_the_starts_counted(self):
        text = "".join(f"Startup: imports {ms} ms\n" for ms in (100, 200, 300))
        code, out = self._run(text, ["--last", "2"])
        self.assertEqual(code, 0)
        self.assertIn("2 starts", out)
        self.assertNotIn("3 starts", out)
        imports_row = [l for l in out.splitlines() if l.startswith("imports")][0]
        self.assertEqual(imports_row.split(), ["imports", "2", "250", "200", "300", "300"])

    def test_missing_file_returns_2(self):
        out = io.StringIO()
        with redirect_stdout(out):
            code = sr.main(["/nonexistent/journal.txt"])
        self.assertEqual(code, 2)


if __name__ == "__main__":
    unittest.main()
