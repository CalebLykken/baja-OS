"""Off-Pi tests for the Wi-Fi signal bars (qml/components/SignalBars.qml):
zero signal lights no bar, each step from 25 up lights one more, and the
bars are whole-pixel steps that fill the 33 px the Row takes up.

Nothing in the component animates or runs a timer, so the QML is also
checked as plain text.

The QML runs in its own process, like tests/test_source_badge.py, so the
QCoreApplication other test modules create at import time doesn't get in the way.

    python3 -m unittest tests.test_signal_bars
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
COMPONENT = ROOT / "qml" / "components" / "SignalBars.qml"

SCRIPT = r'''
import json, sys
from pathlib import Path
from PyQt6.QtCore import QUrl
from PyQt6.QtGui import QGuiApplication
from PyQt6.QtQml import QQmlComponent, QQmlEngine

app = QGuiApplication(sys.argv)
ROOT = Path.cwd()

engine = QQmlEngine()
component = QQmlComponent(engine)
component.setData(b'import QtQuick\nimport "qml/components"\nSignalBars { signal: 0 }',
                  QUrl.fromLocalFile(str(ROOT / "x.qml")))
if component.isError():
    for error in component.errors():
        print(error.toString(), file=sys.stderr)
    sys.exit(1)
obj = component.create()
if obj is None:
    for error in component.errors():
        print(error.toString(), file=sys.stderr)
    sys.exit(1)

results = {}
for signal in (0, 10, 25, 50, 75, 100):
    obj.setProperty("signal", signal)
    results[str(signal)] = obj.property("count")

results["width"] = obj.property("width")
results["implicitWidth"] = obj.property("implicitWidth")

# The bars are the visual children of the Row: the Rectangles, which have a radius.
from PyQt6 import sip
from PyQt6.QtQuick import QQuickItem
row = sip.cast(obj, QQuickItem)
results["heights"] = [child.height() for child in row.childItems()
                      if child.property("radius") is not None]

print(json.dumps(results))
sys.stdout.flush()
'''


def run():
    return subprocess.run([sys.executable, "-c", SCRIPT], cwd=ROOT,
                          capture_output=True, text=True, timeout=60,
                          env={**os.environ, "QT_QPA_PLATFORM": "offscreen"})


class SignalBarsTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        result = run()
        cls.stderr = result.stderr
        cls.returncode = result.returncode
        cls.results = json.loads(result.stdout.strip().splitlines()[-1]) if result.returncode == 0 else {}

    def setUp(self):
        self.assertEqual(self.returncode, 0, self.stderr)

    def test_zero_signal_lights_no_bar(self):
        self.assertEqual(self.results["0"], 0)

    def test_weak_but_usable_signal_lights_one_bar(self):
        self.assertEqual(self.results["10"], 1)

    def test_each_step_lights_one_more_bar(self):
        self.assertEqual(self.results["25"], 2)
        self.assertEqual(self.results["50"], 3)
        self.assertEqual(self.results["75"], 4)
        self.assertEqual(self.results["100"], 4)

    def test_row_is_33_px_wide(self):
        self.assertEqual(self.results["implicitWidth"], 33)
        self.assertEqual(self.results["width"], 33)

    def test_bar_heights_are_whole_pixels_and_rise(self):
        heights = self.results["heights"]
        self.assertEqual(len(heights), 4, heights)
        for height in heights:
            self.assertEqual(height, int(height))
        self.assertEqual(heights, sorted(heights))
        self.assertEqual(len(set(heights)), 4)

    def test_component_has_no_animation_or_timer(self):
        text = COMPONENT.read_text(encoding="utf-8")
        for word in ("Animation", "Behavior", "Timer"):
            self.assertNotIn(word, text)


if __name__ == "__main__":
    unittest.main()
