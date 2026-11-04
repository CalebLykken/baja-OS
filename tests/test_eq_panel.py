"""Off-Pi tests for the equalizer polish: EqSlider's tap lights the tapped
segment, the true minus sign and number font in EqualizerPanel, and the label
widths against the narrowest column (Settings > Sound), in DejaVu Sans Bold,
which is what the Pi and CI fall back to.

    python3 -m unittest tests.test_eq_panel
"""

import json
import os
import subprocess
import sys
import unittest
from pathlib import Path

try:
    import PyQt6.QtQml  # noqa: F401
except ImportError:
    raise unittest.SkipTest("PyQt6 isn't installed")

ROOT = Path(__file__).resolve().parent.parent

SCRIPT = r'''
import json, sys
from pathlib import Path
from PyQt6.QtCore import Q_ARG, QMetaObject, QObject, Qt, QUrl
from PyQt6.QtGui import QFont, QFontMetricsF, QGuiApplication
from PyQt6.QtQml import QQmlComponent, QQmlEngine

ROOT = Path(sys.argv[1])
app = QGuiApplication(sys.argv)
engine = QQmlEngine()

component = QQmlComponent(engine)
component.setData(
    b'import QtQuick\nimport "qml/components"\nEqSlider { width: 56; height: 240; limit: 12 }',
    QUrl.fromLocalFile(str(ROOT / "x.qml")))
obj = component.create()
if obj is None:
    print([e.toString() for e in component.errors()])
    sys.exit(1)
area = obj.findChild(QObject, "eqDrag")
got = []
obj.moved.connect(got.append)
out = {}
for name, y in [("top_lower_half", 4), ("middle", 120), ("just_above", 114),
                ("just_below", 126), ("dead_zone_edge", 117.5), ("bottom", 240),
                ("cut_upper_half", 236), ("past_top", -30), ("past_bottom", 300)]:
    del got[:]
    QMetaObject.invokeMethod(area, "apply", Qt.ConnectionType.DirectConnection, Q_ARG("QVariant", y))
    out[name] = got[-1]


def width(text, px, spacing=0.0):
    f = QFont("DejaVu Sans")
    f.setPixelSize(px)
    f.setBold(True)
    f.setLetterSpacing(QFont.SpacingType.AbsoluteSpacing, spacing)
    return QFontMetricsF(f).horizontalAdvance(text)


out["w_db"] = width("−12 dB", 30)
out["w_presence"] = width("PRESENCE", 20, 2)
out["w_lowmid"] = width("LOW MID", 20, 2)
print(json.dumps(out))
'''


class EqPanelTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        env = dict(os.environ, QT_QPA_PLATFORM="offscreen")
        result = subprocess.run([sys.executable, "-c", SCRIPT, str(ROOT)], cwd=ROOT,
                                capture_output=True, text=True, timeout=60, env=env)
        if result.returncode != 0:
            raise AssertionError(result.stdout + result.stderr)
        cls.out = json.loads(result.stdout.strip().splitlines()[-1])
        cls.src = (ROOT / "qml/components/EqualizerPanel.qml").read_text()

    def test_tap_lights_tapped_segment(self):
        self.assertEqual(self.out["top_lower_half"], 12)
        self.assertEqual(self.out["cut_upper_half"], -12)
        self.assertEqual(self.out["bottom"], -12)

    def test_zero_reachable_by_tap(self):
        self.assertEqual(self.out["middle"], 0)
        self.assertEqual(self.out["dead_zone_edge"], 0)

    def test_just_beyond_dead_zone(self):
        self.assertEqual(self.out["just_above"], 1)
        self.assertEqual(self.out["just_below"], -1)

    def test_drag_past_ends_clamps(self):
        self.assertEqual(self.out["past_top"], 12)
        self.assertEqual(self.out["past_bottom"], -12)

    def test_labels_fit_narrowest_column(self):
        for key in ("w_db", "w_presence", "w_lowmid"):
            self.assertLess(self.out[key], 150, key)

    def test_panel_source(self):
        self.assertIn("\\u2212", self.src)
        self.assertIn("numeric: true", self.src)
        self.assertNotIn("font.letterSpacing", self.src)
        self.assertNotIn("Your own", self.src)


if __name__ == "__main__":
    unittest.main()
