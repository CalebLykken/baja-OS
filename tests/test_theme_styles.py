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


# Sets Theme.style at runtime and reads back the resolved token set (`s`) for
# day and night, so the fallback is tested through the real bindings.
FALLBACK_SCRIPT = r'''
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
out = {}
for style in ["trail", "no-such-style", "atlantic"]:
    for dark in (True, False):
        theme.setProperty("style", style)
        theme.setProperty("dark", dark)
        out[style + "|" + str(dark)] = theme.property("s").toVariant()
print(json.dumps(out))
'''


@unittest.skipUnless(HAVE_QT, "PyQt6 isn't installed")
class StyleFallbackTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        env = dict(os.environ, QT_QPA_PLATFORM="offscreen")
        result = subprocess.run([sys.executable, "-c", FALLBACK_SCRIPT, str(ROOT)], cwd=ROOT,
                                capture_output=True, text=True, timeout=60, env=env)
        if result.returncode != 0:
            raise AssertionError(result.stdout + result.stderr)
        cls.out = json.loads(result.stdout.strip().splitlines()[-1])

    def test_unknown_style_renders_trail_at_night(self):
        unknown, trail = self.out["no-such-style|True"], self.out["trail|True"]
        for key in ("bg", "accent", "backdrop", "radius"):
            self.assertEqual(unknown[key], trail[key], key)
        self.assertEqual(unknown, trail)

    def test_unknown_style_renders_trail_by_day(self):
        unknown, trail = self.out["no-such-style|False"], self.out["trail|False"]
        for key in ("bg", "accent", "backdrop", "radius"):
            self.assertEqual(unknown[key], trail[key], key)
        self.assertEqual(unknown, trail)
        # The day set is Trail's light set, not its night colours.
        self.assertEqual(unknown["bg"], "#e8e3d4")

    def test_known_style_still_resolves(self):
        night = self.out["atlantic|True"]
        day = self.out["atlantic|False"]
        self.assertEqual(night["bg"], "#0a1420")
        self.assertEqual(day["accent"], "#2a5fa8")
        self.assertEqual(night["backdrop"], "waves")


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

    def test_midnight_is_flat_black_at_night(self):
        # Midnight is the OLED night look: pure black ground, no backdrop.
        night = self.out["night"]["midnight"]
        self.assertEqual(night["bg"], "#000000")
        self.assertEqual(night["backdrop"], "none")
        self.assertIn("midnight", main_choices())
        self.assertEqual(self.out["titles"]["midnight"], "Midnight")

    def test_desert_is_sand_and_turquoise(self):
        # Desert: brown panels and sand text at night, sand paper by day,
        # with a turquoise accent that stays apart from the warning red.
        night = self.out["night"]["desert"]
        day = self.out["day"]["desert"]
        self.assertEqual(night["bg"], "#18120c")
        self.assertEqual(night["accent"], "#3fc1b0")
        self.assertEqual(day["bg"], "#eadfc6")
        self.assertEqual(day["accent"], "#0b766a")
        self.assertEqual(night["numFont"], "Nimbus Sans")
        self.assertEqual(night["backdrop"], "dunes")
        self.assertIn("desert", main_choices())
        self.assertEqual(self.out["titles"]["desert"], "Desert")

    def test_glacier_is_ice_cyan_and_round(self):
        # Glacier: cyan accent on deep teal-black at night, cool near-white by
        # day, and the roundest corners of any style.
        night = self.out["night"]["glacier"]
        day = self.out["day"]["glacier"]
        self.assertEqual(night["bg"], "#071216")
        self.assertEqual(night["accent"], "#7fe0f0")
        self.assertEqual(day["bg"], "#e3eef2")
        self.assertEqual(day["accent"], "#0a6f8c")
        self.assertEqual(night["radius"], 20)
        self.assertEqual(night["backdrop"], "facets")
        self.assertIn("glacier", main_choices())
        self.assertEqual(self.out["titles"]["glacier"], "Glacier")

    def test_lcd_is_green_monochrome(self):
        # LCD: phosphor green on near-black at night, a grey-green calculator
        # by day, segment gauges, a mono numeral face, and orange-red warnings.
        night = self.out["night"]["lcd"]
        day = self.out["day"]["lcd"]
        self.assertEqual(night["bg"], "#050b05")
        self.assertEqual(night["text"], "#b9f27a")
        self.assertEqual(night["warn"], "#ff6a3d")
        self.assertEqual(day["bg"], "#c3cea4")
        self.assertEqual(night["numFont"], "DejaVu Sans Mono")
        self.assertFalse(night["numItalic"])
        self.assertEqual(night["gauge"], "segments")
        self.assertEqual(night["backdrop"], "scanlines")
        self.assertIn("lcd", main_choices())
        self.assertEqual(self.out["titles"]["lcd"], "LCD")

    def test_sunset_is_purple_with_gold_accent(self):
        # Sunset: deep purple with a gold accent at night, soft pink-white by
        # day. The gold stays apart from the pink-red warning colour.
        night = self.out["night"]["sunset"]
        day = self.out["day"]["sunset"]
        self.assertEqual(night["bg"], "#140a1f")
        self.assertEqual(night["accent"], "#ffb347")
        self.assertEqual(night["warn"], "#ff4d6d")
        self.assertEqual(night["radius"], 18)
        self.assertEqual(night["backdrop"], "horizon")
        self.assertEqual(day["bg"], "#f3e6ea")
        self.assertEqual(day["accent"], "#b4540a")
        self.assertIn("sunset", main_choices())
        self.assertEqual(self.out["titles"]["sunset"], "Sunset")


if __name__ == "__main__":
    unittest.main()
