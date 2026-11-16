"""Every style names a real font family once Theme has resolved it.

A style may leave font or numFont as "" to mean the plain sans. On the Pi's
screen (eglfs) Qt doesn't turn an empty family into fontconfig's default: it
picks the first family installed, C059, a book serif, so Atlantic and Amber
came out in a serif face. Theme.font and Theme.numFont map "" to Theme.sans,
Liberation Sans (Nimbus Sans drew its regular weight in italic there).
Runs in a subprocess (other modules hold a QCoreApplication).

    python3 -m unittest tests.test_theme_font_fallback
"""

import json
import subprocess
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent

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
out = {"sans": theme.property("sans"), "styles": {}}
for name in theme.property("styleNames").toVariant():
    theme.setProperty("style", name)
    for dark in (True, False):
        theme.setProperty("dark", dark)
        out["styles"][name + (" night" if dark else " day")] = [
            theme.property("font"), theme.property("numFont")]
print(json.dumps(out))
'''


@unittest.skipUnless(HAVE_QT, "PyQt6 not installed")
class FontFallbackTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        run = subprocess.run([sys.executable, "-c", SCRIPT, str(ROOT)],
                             capture_output=True, text=True, timeout=60,
                             env={"QT_QPA_PLATFORM": "offscreen", **__import__("os").environ})
        if run.returncode != 0:
            raise AssertionError(run.stdout + run.stderr)
        cls.out = json.loads(run.stdout.strip().splitlines()[-1])

    def test_no_style_resolves_to_an_empty_family(self):
        for name, (font, num) in self.out["styles"].items():
            with self.subTest(style=name):
                self.assertTrue(font, "font")
                self.assertTrue(num, "numFont")

    def test_empty_means_the_sans(self):
        self.assertEqual(self.out["sans"], "Liberation Sans")
        self.assertEqual(self.out["styles"]["atlantic night"][0], "Liberation Sans")
        self.assertEqual(self.out["styles"]["trail night"][0], "URW Gothic")   # a named family is kept


if __name__ == "__main__":
    unittest.main()
