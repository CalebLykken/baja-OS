"""Off-Pi integrity test for the style tables in qml/components/Theme.qml: every
style has a night and a day set with all its keys, and main.py's --style
choices list the same styles. Adding a theme without one of these fails here.
Runs in a subprocess (other modules hold a QCoreApplication).

    python3 -m unittest tests.test_theme_styles
"""

import ast
import json
import os
import re
import subprocess
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent

COLOURS = ["bg", "panel", "panelTop", "panelHi", "line", "text", "textDim", "accent", "warn", "ok"]
SHAPE = ["font", "numFont", "numItalic", "numWeight", "radius", "border", "gauge", "backdrop"]
HEX = re.compile(r"^#[0-9a-fA-F]{6}$")

try:
    import PyQt6.QtQml  # noqa: F401
    HAVE_QT = True
except ImportError:
    HAVE_QT = False

SCRIPT = r'''
import json, sys
from pathlib import Path
from PyQt6.QtCore import QUrl
from PyQt6.QtGui import QGuiApplication
from PyQt6.QtQml import QQmlComponent, QQmlEngine

ROOT = Path(sys.argv[1])
app = QGuiApplication(sys.argv)
engine = QQmlEngine()
component = QQmlComponent(engine)
component.setData(b'import QtQuick\nimport "qml/components"\nItem { property var th: Theme }',
                  QUrl.fromLocalFile(str(ROOT / "x.qml")))
obj = component.create()
if obj is None:
    print([e.toString() for e in component.errors()])
    sys.exit(1)
theme = obj.property("th")
print(json.dumps({
    "names": list(theme.property("styleNames").toVariant()),
    "night": theme.property("styles").toVariant(),
    "day": theme.property("lightStyles").toVariant(),
    "titles": theme.property("styleTitles").toVariant(),
}))
'''


def main_choices():
    text = (ROOT / "main.py").read_text()
    match = re.search(r'"--style".*?choices=(\[[^\]]*\])', text, re.S)
    return ast.literal_eval(match.group(1))


@unittest.skipUnless(HAVE_QT, "PyQt6 isn't installed")
class StyleTableTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        env = dict(os.environ, QT_QPA_PLATFORM="offscreen")
        result = subprocess.run([sys.executable, "-c", SCRIPT, str(ROOT)], cwd=ROOT,
                                capture_output=True, text=True, timeout=60, env=env)
        if result.returncode != 0:
            raise AssertionError(result.stdout + result.stderr)
        cls.out = json.loads(result.stdout.strip().splitlines()[-1])

    def test_every_style_has_night_and_day(self):
        for n in self.out["names"]:
            self.assertIn(n, self.out["night"], n)
            self.assertIn(n, self.out["day"], n)

    def test_no_orphan_entries(self):
        names = set(self.out["names"])
        self.assertEqual(set(self.out["night"]), names)
        self.assertEqual(set(self.out["day"]), names)

    def test_colours_are_hex(self):
        for n in self.out["names"]:
            for table in ("night", "day"):
                for key in COLOURS:
                    value = self.out[table][n].get(key)
                    self.assertTrue(isinstance(value, str) and HEX.match(value), (n, table, key))

    def test_night_has_shape_keys(self):
        for n in self.out["names"]:
            for key in SHAPE:
                self.assertIn(key, self.out["night"][n], (n, key))
            self.assertIn(self.out["night"][n]["gauge"], ("arc", "needle", "segments"), n)

    def test_day_holds_colours_only(self):
        for n in self.out["names"]:
            self.assertLessEqual(set(self.out["day"][n]), set(COLOURS), n)

    def test_every_style_has_a_title(self):
        for n in self.out["names"]:
            self.assertTrue(self.out["titles"].get(n), n)

    def test_main_choices_match(self):
        self.assertEqual(main_choices(), self.out["names"])


if __name__ == "__main__":
    unittest.main()
