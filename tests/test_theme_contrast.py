"""Contrast checks for every Theme style, day and night: WCAG relative
luminance in plain Python, so a new or retuned style can't quietly ship
text or accents that wash out in sun or vanish at night. Loads Theme in a
subprocess (other modules hold a QCoreApplication).

    python3 -m unittest tests.test_theme_contrast
"""

import colorsys
import json
import os
import subprocess
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent

try:
    import PyQt6.QtQml  # noqa: F401
except ImportError:
    PyQt6 = None

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
holder = component.create()
if holder is None:
    print([e.toString() for e in component.errors()])
    sys.exit(1)
theme = holder.property("th")
print(json.dumps({"names": list(theme.property("styleNames").toVariant()),
                  "styles": theme.property("styles").toVariant(),
                  "light": theme.property("lightStyles").toVariant()}))
'''


def luminance(hex_colour):
    h = hex_colour.lstrip("#")
    channels = []
    for i in (0, 2, 4):
        c = int(h[i:i + 2], 16) / 255
        channels.append(c / 12.92 if c <= 0.03928 else ((c + 0.055) / 1.055) ** 2.4)
    return 0.2126 * channels[0] + 0.7152 * channels[1] + 0.0722 * channels[2]


def ratio(a, b):
    la, lb = sorted((luminance(a), luminance(b)), reverse=True)
    return (la + 0.05) / (lb + 0.05)


def hue(hex_colour):
    h = hex_colour.lstrip("#")
    r, g, b = (int(h[i:i + 2], 16) / 255 for i in (0, 2, 4))
    return colorsys.rgb_to_hsv(r, g, b)[0] * 360


# (foreground, background, minimum ratio). "bg" on "accent" is the label
# drawn in Theme.bg on a selected segment's accent fill.
NIGHT = [
    ("text", "panel", 7), ("textDim", "panel", 4.5), ("textDim", "bg", 4.5),
    ("accent", "panel", 4.5), ("warn", "panel", 4.5), ("ok", "panel", 4.5),
    ("bg", "accent", 4.5), ("line", "panel", 1.3),
]
# Day relaxes the accent pairs to the 3:1 large-text threshold (the labels
# are 30 px) but keeps body text strict.
DAY = [
    ("text", "panel", 7), ("textDim", "panel", 4.5), ("textDim", "panelHi", 4.0),
    ("warn", "panel", 4.5), ("ok", "panel", 3.0), ("accent", "panel", 3.0),
    ("bg", "accent", 3.0), ("line", "panel", 1.3),
]


@unittest.skipIf(PyQt6 is None, "PyQt6 isn't installed")
class ThemeContrastTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        env = dict(os.environ, QT_QPA_PLATFORM="offscreen")
        result = subprocess.run([sys.executable, "-c", SCRIPT, str(ROOT)], cwd=ROOT,
                                capture_output=True, text=True, timeout=60, env=env)
        if result.returncode != 0:
            raise AssertionError(result.stdout + result.stderr)
        cls.data = json.loads(result.stdout.strip().splitlines()[-1])

    def sets(self, mode):
        # Day colours merge over night ones, like Theme.s.
        for name in self.data["names"]:
            night = self.data["styles"][name]
            yield name, (night if mode == "night"
                         else {**night, **self.data["light"].get(name, {})})

    def check(self, mode, rules):
        for name, s in self.sets(mode):
            for fg, bg, minimum in rules:
                with self.subTest(style=name, mode=mode, pair=f"{fg} on {bg}"):
                    self.assertGreaterEqual(ratio(s[fg], s[bg]), minimum,
                                            f"{s[fg]} on {s[bg]}")

    def test_night(self):
        self.check("night", NIGHT)

    def test_day(self):
        self.check("day", DAY)

    def test_accent_and_warn_hues_differ(self):
        for mode in ("night", "day"):
            for name, s in self.sets(mode):
                with self.subTest(style=name, mode=mode):
                    d = abs(hue(s["accent"]) - hue(s["warn"]))
                    self.assertGreaterEqual(min(d, 360 - d), 10)


if __name__ == "__main__":
    unittest.main()
