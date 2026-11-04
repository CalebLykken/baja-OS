"""Off-Pi tests for the --compare mode of tools/startup_report.py: the
before and after medians and deltas per phase, and the table they print.

    python3 -m unittest tests.test_startup_report_compare
"""

import importlib.util
import io
import os
import tempfile
import unittest
from contextlib import redirect_stderr, redirect_stdout

_PATH = os.path.join(os.path.dirname(__file__), "..", "tools", "startup_report.py")
_spec = importlib.util.spec_from_file_location("startup_report", _PATH)
sr = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(sr)


class CompareTest(unittest.TestCase):
    def test_medians_and_deltas_per_phase(self):
        records = [({"imports": 100, "qml": 1000}, None),
                   ({"imports": 200, "qml": 1200}, None),
                   ({"imports": 50, "qml": 900}, None),
                   ({"imports": 70, "qml": 800}, None)]
        rows = sr.compare(records, 2)
        self.assertEqual(rows, [("imports", 150, 60, -90),
                                ("qml", 1100, 850, -250)])

    def test_even_halves_use_the_median(self):
        records = [({"qml": 100}, None), ({"qml": 300}, None),
                   ({"qml": 200}, None), ({"qml": 400}, None)]
        rows = sr.compare(records, 2)
        self.assertEqual(rows, [("qml", 200, 300, 100)])

    def test_phase_only_after_has_none_before(self):
        records = [({"qml": 100}, None),
                   ({"qml": 200, "first frame": 500}, None)]
        rows = sr.compare(records, 1)
        self.assertEqual(rows, [("qml", 100, 200, 100),
                                ("first frame", None, 500, None)])

    def test_phase_only_before_has_none_after(self):
        records = [({"qml": 100, "old phase": 40}, None),
                   ({"qml": 200}, None)]
        rows = sr.compare(records, 1)
        self.assertEqual(rows, [("qml", 100, 200, 100),
                                ("old phase", 40, None, None)])

    def test_first_seen_order_across_both_halves(self):
        records = [({"imports": 1}, None), ({"qml": 2}, None),
                   ({"imports": 3, "first frame": 4}, None)]
        rows = sr.compare(records, 1)
        self.assertEqual([name for name, *_ in rows],
                         ["imports", "qml", "first frame"])

    def test_system_up_row(self):
        records = [({"qml": 1}, 10.0), ({"qml": 2}, 12.0), ({"qml": 3}, 20.0)]
        rows = sr.compare(records, 1)
        self.assertEqual(rows[-1], ("system up (s)", 11.0, 20.0, 9.0))

    def test_system_up_row_absent_without_uptime(self):
        rows = sr.compare([({"qml": 1}, None), ({"qml": 2}, None)], 1)
        self.assertEqual([name for name, *_ in rows], ["qml"])


class RenderCompareTest(unittest.TestCase):
    ROWS = [("imports", 150, 60, -90),
            ("qml", 1100, 850, -250),
            ("first frame", None, 500, None),
            ("same", 10, 10, 0),
            ("slower", 10, 45, 35)]

    def test_header_and_signed_deltas(self):
        lines = sr.render_compare(self.ROWS)
        self.assertEqual(lines[0].split(), ["phase", "before", "after", "delta"])
        self.assertEqual(lines[1].split(), ["imports", "150", "60", "-90"])
        self.assertEqual(lines[4].split(), ["same", "10", "10", "0"])
        self.assertEqual(lines[5].split(), ["slower", "10", "45", "+35"])

    def test_missing_side_renders_dash(self):
        lines = sr.render_compare(self.ROWS)
        self.assertEqual(lines[3].split(), ["first", "frame", "-", "500", "-"])

    def test_numbers_are_right_aligned(self):
        lines = sr.render_compare(self.ROWS)
        # Right-aligned numbers end at the same column on every row.
        self.assertEqual(len({len(line) for line in lines}), 1)
        self.assertEqual(len(lines), len(self.ROWS) + 1)

    def test_even_median_renders_without_decimal(self):
        lines = sr.render_compare([("qml", 250.0, 300.0, 50.0)])
        self.assertEqual(lines[1].split(), ["qml", "250", "300", "+50"])


class MainCompareTest(unittest.TestCase):
    def _run(self, text, argv_extra=()):
        with tempfile.TemporaryDirectory() as d:
            path = os.path.join(d, "journal.txt")
            with open(path, "w", encoding="utf-8") as f:
                f.write(text)
            out = io.StringIO()
            err = io.StringIO()
            with redirect_stdout(out), redirect_stderr(err):
                code = sr.main([path, *argv_extra])
        return code, out.getvalue(), err.getvalue()

    @staticmethod
    def _journal(values):
        return "".join(f"Startup: imports {ms} ms, qml {ms * 2} ms\n"
                       for ms in values)

    def test_prints_compare_header(self):
        code, out, _ = self._run(self._journal((100, 200, 300, 400)),
                                 ["--compare", "2"])
        self.assertEqual(code, 0)
        lines = out.splitlines()
        self.assertEqual(lines[0], "4 starts: 2 before, 2 after")
        self.assertEqual(lines[1].split(), ["phase", "before", "after", "delta"])
        self.assertEqual(lines[2].split(), ["imports", "150", "350", "+200"])
        self.assertNotIn("median", out)

    def test_not_enough_starts_returns_1(self):
        code, out, err = self._run(self._journal((100, 200)),
                                   ["--compare", "2"])
        self.assertEqual(code, 1)
        self.assertEqual(out, "")
        self.assertIn("need more than 2 starts to compare, found 2", err)

    def test_compare_larger_than_records_returns_1(self):
        code, _, err = self._run(self._journal((100, 200, 300)),
                                 ["--compare", "5"])
        self.assertEqual(code, 1)
        self.assertIn("need more than 5 starts to compare, found 3", err)

    def test_compare_zero_is_an_argument_error(self):
        out = io.StringIO()
        err = io.StringIO()
        with redirect_stdout(out), redirect_stderr(err):
            with self.assertRaises(SystemExit):
                sr.main(["/nonexistent/journal.txt", "--compare", "0"])
        self.assertIn("--compare must be at least 1", err.getvalue())

    def test_last_applies_before_compare(self):
        # --last 4 keeps 300, 400, 500, 600; those compare as 300, 400 | 500, 600.
        code, out, _ = self._run(self._journal((100, 200, 300, 400, 500, 600)),
                                 ["--last", "4", "--compare", "2"])
        self.assertEqual(code, 0)
        lines = out.splitlines()
        self.assertEqual(lines[0], "4 starts: 2 before, 2 after")
        self.assertEqual(lines[2].split(), ["imports", "350", "550", "+200"])

    def test_last_smaller_than_compare_returns_1(self):
        code, _, err = self._run(self._journal((100, 200, 300)),
                                 ["--last", "2", "--compare", "2"])
        self.assertEqual(code, 1)
        self.assertIn("need more than 2 starts to compare, found 2", err)


if __name__ == "__main__":
    unittest.main()
