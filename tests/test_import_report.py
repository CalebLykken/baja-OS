"""Off-Pi tests for tools/import_report.py: importtime parsing, parent and
importer attribution, the report lines, and the command line.

    python3 -m unittest tests.test_import_report
"""

import importlib.util
import io
import os
import tempfile
import unittest
from contextlib import redirect_stdout

_PATH = os.path.join(os.path.dirname(__file__), "..", "tools", "import_report.py")
_spec = importlib.util.spec_from_file_location("import_report", _PATH)
ir = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(ir)

# CPython prints children before their parent, two spaces of indent per level.
FIXTURE = """\
import time: self [us] | cumulative | imported package
import time:       100 |        100 |       email.parser
import time:      4288 |      33963 |     http.client
import time:       500 |      53000 |   urllib.request
import time:       300 |      60000 | backend.roadinfo
import time:       200 |        900 | json
junk line
import time:       100 |      70000 | backend.hub
import time:        50 |         50 | main
"""


class ParseTests(unittest.TestCase):
    def test_values_and_depths(self):
        recs = ir.parse(FIXTURE)
        self.assertEqual(len(recs), 7)
        self.assertEqual(recs[0], ("email.parser", 100, 100, 3))
        self.assertEqual(recs[1], ("http.client", 4288, 33963, 2))
        self.assertEqual(recs[2][3], 1)
        self.assertEqual(recs[3], ("backend.roadinfo", 300, 60000, 0))

    def test_garbage_never_raises(self):
        self.assertEqual(ir.parse(""), [])
        self.assertEqual(ir.parse("import time: x | y | z\n"), [])

    def test_parents(self):
        self.assertEqual(ir.build_parents(ir.parse(FIXTURE)), [
            "http.client", "urllib.request", "backend.roadinfo", None,
            None, None, None])

    def test_attribution_nearest_backend(self):
        who = ir.attribute(ir.parse(FIXTURE))
        self.assertEqual(who[0], "backend.roadinfo")
        self.assertEqual(who[2], "backend.roadinfo")
        self.assertEqual(who[4], "main")  # json imported at top level
        self.assertNotIn(3, who)  # a backend module itself
        self.assertNotIn(6, who)  # main itself


class ReportTests(unittest.TestCase):
    def test_heavy_listed_once_with_importer(self):
        text = "\n".join(ir.report(ir.parse(FIXTURE), top=5, min_ms=2.0))
        self.assertIn("urllib.request  <- backend.roadinfo", text)
        self.assertNotIn("http.client  <-", text)
        self.assertNotIn("email.parser  <-", text)
        self.assertIn("Total (outermost imports, interpreter boot excluded): 130.9 ms", text)

    def test_min_ms_and_top(self):
        recs = ir.parse(FIXTURE)
        text = "\n".join(ir.report(recs, top=1, min_ms=40.0))
        self.assertIn("urllib.request  <-", text)
        self.assertIn("backend.hub", text)
        text = "\n".join(ir.report(recs, top=5, min_ms=100.0))
        self.assertNotIn("urllib.request  <-", text)

    def test_importers_hint(self):
        lines = ir.report(ir.parse(FIXTURE), importers={"urllib.request": ["backend.hub"]})
        self.assertIn("also imported by: backend.hub", "\n".join(lines))


class BackendPackageTests(unittest.TestCase):
    def test_bare_backend_record_not_heavy(self):
        text = ("import time: self [us] | cumulative | imported package\n"
                "import time:       100 |      50000 | backend\n"
                "import time:       100 |      60000 | backend.hub\n")
        recs = ir.parse(text)
        self.assertEqual(ir.heavy_packages(recs, 2.0), [])
        self.assertNotIn("<- backend.startup", "\n".join(ir.report(recs)))
        self.assertNotIn("backend  <-", "\n".join(ir.report(recs)))


BOOT = """\
import time: self [us] | cumulative | imported package
import time:       200 |        200 | encodings
import time:      3000 |       3000 | site
import time:       400 |        400 |   argparse
import time:       100 |        100 |   json
import time:        50 |        500 | main
import time:       100 |      50000 |   PyQt6.QtCore
import time:       100 |     286000 | PyQt6.QtWebEngineQuick
import time:       100 |      24000 | backend.library
"""


class BootTests(unittest.TestCase):
    def test_boot_count_stops_before_mains_own_imports(self):
        recs = ir.parse(BOOT)
        self.assertEqual(ir.boot_count(recs), 2)  # encodings, site
        self.assertEqual(ir.boot_count(ir.parse(FIXTURE)), 0)
        self.assertEqual(ir.boot_count(ir.parse("")), 0)

    def test_boot_labelled_interpreter_not_main(self):
        recs = ir.parse(BOOT)
        who = ir.attribute(recs)
        self.assertEqual(who[0], "interpreter")
        self.assertEqual(who[1], "interpreter")
        self.assertEqual(who[2], "main")  # argparse, imported by main
        self.assertEqual(who[5], "main")  # QtCore under the lazy PyQt6 import
        self.assertEqual(who[6], "main")  # the lazy import itself
        text = "\n".join(ir.report(recs, min_ms=1.0))
        self.assertIn("site  <- interpreter", text)
        self.assertNotIn("site  <- main", text)

    def test_total_excludes_boot_includes_lazy_imports(self):
        text = "\n".join(ir.report(ir.parse(BOOT)))
        # main 0.5 + QtWebEngineQuick 286 + backend.library 24, not 3.2 of boot
        self.assertIn("interpreter boot excluded): 310.5 ms", text)
        self.assertIn("PyQt6.QtWebEngineQuick", text)

    def test_default_command_imports_the_lazy_startup_modules(self):
        for mod in ("main", "PyQt6.QtWebEngineQuick", "backend.library"):
            self.assertIn("import %s\n" % mod, ir._STARTUP_CODE)


class ScanTests(unittest.TestCase):
    def test_finds_top_of_line_imports(self):
        with tempfile.TemporaryDirectory() as d:
            for name, body in (
                ("a.py", "import urllib.request\n"),
                ("b.py", "from urllib import parse\n"),
                ("c.py", "def f():\n    import urllib.request\n"),
                ("d.py", "import json\n"),
            ):
                with open(os.path.join(d, name), "w") as f:
                    f.write(body)
            found = ir.scan_importers(d, {"urllib"})
        self.assertEqual(found, {"urllib": ["backend.a", "backend.b"]})

    def test_full_name_matching(self):
        with tempfile.TemporaryDirectory() as d:
            for name, body in (
                ("a.py", "import urllib.parse\n"),
                ("b.py", "from urllib import request\n"),
                ("c.py", "import os, urllib.request as r\n"),
                ("d.py", "from urllib import (parse,\n    error)\n"),
            ):
                with open(os.path.join(d, name), "w") as f:
                    f.write(body)
            found = ir.scan_importers(d, {"urllib.request", "urllib.parse"})
        self.assertEqual(found["urllib.request"], ["backend.b", "backend.c"])
        self.assertEqual(found["urllib.parse"], ["backend.a", "backend.d"])

    def test_missing_dir(self):
        self.assertEqual(ir.scan_importers("/no/such/dir", {"x"}), {})


class MainTests(unittest.TestCase):
    def _run(self, argv):
        buf = io.StringIO()
        with redirect_stdout(buf):
            code = ir.main(argv)
        return code, buf.getvalue()

    def _tmp(self, text):
        f = tempfile.NamedTemporaryFile("w", suffix=".txt", delete=False)
        f.write(text)
        f.close()
        self.addCleanup(os.unlink, f.name)
        return f.name

    def test_file_prints_table(self):
        code, out = self._run(["--file", self._tmp(FIXTURE)])
        self.assertEqual(code, 0)
        self.assertIn("urllib.request  <- backend.roadinfo", out)

    def test_empty_file(self):
        code, _ = self._run(["--file", self._tmp("")])
        self.assertEqual(code, 1)

    def test_missing_file(self):
        code, _ = self._run(["--file", "/no/such/importtime.txt"])
        self.assertEqual(code, 2)


if __name__ == "__main__":
    unittest.main()
