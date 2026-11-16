"""The engine warning chip (qml/components/EngineWarning.qml) names what is wrong in
a one-word legend under the value: HOT, LOW or HIGH (voltage), OVER, ENGINE. It stays
inside the 96 px chip and short enough not to reach the nav button above it.

The QML runs in its own process, like tests/test_turn_chip.py.

    python3 -m unittest tests.test_engine_warning_legend
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
from PyQt6.QtCore import QEventLoop, QObject, QTimer, QUrl, pyqtProperty, pyqtSignal
from PyQt6.QtGui import QGuiApplication
from PyQt6.QtQml import QQmlComponent, QQmlEngine

app = QGuiApplication(sys.argv)
ROOT = Path.cwd()


class Vehicle(QObject):
    changed = pyqtSignal()

    def __init__(self):
        super().__init__()
        self._warnings = []
        self._voltage = 13.8

    @pyqtProperty("QStringList", notify=changed)
    def warnings(self):
        return self._warnings

    @pyqtProperty(float, notify=changed)
    def coolant(self):
        return 112.0

    @pyqtProperty(float, notify=changed)
    def voltage(self):
        return self._voltage

    @pyqtProperty(float, notify=changed)
    def boost(self):
        return 20.0

    @pyqtProperty("QVariantMap", constant=True)
    def limits(self):
        return {"voltageLow": 12.0, "voltageHigh": 15.0}

    def show(self, warnings, voltage=13.8):
        self._voltage = voltage
        self._warnings = warnings
        self.changed.emit()


def wait(ms):
    loop = QEventLoop()
    QTimer.singleShot(ms, loop.quit)
    loop.exec()


vehicle = Vehicle()
engine = QQmlEngine()
engine.rootContext().setContextProperty("vehicle", vehicle)
component = QQmlComponent(engine)
component.setData(b'import QtQuick\nimport "qml/components"\nEngineWarning {}',
                  QUrl.fromLocalFile(str(ROOT / "x.qml")))
obj = component.create()
if obj is None:
    for error in component.errors():
        print(error.toString(), file=sys.stderr)
    sys.exit(1)

legend = obj.findChild(QObject, "engineWarningLegend")
results = {}
for name, warnings, volts in (("coolant", ["coolant"], 13.8), ("boost", ["boost"], 13.8),
                              ("mil", ["mil"], 13.8), ("low", ["voltage"], 11.2),
                              ("high", ["voltage"], 15.4)):
    vehicle.show([], 13.8)
    wait(50)
    vehicle.show(warnings, volts)
    wait(100)
    results[name] = legend.property("text")
    results[name + "_height"] = obj.property("height")
    results[name + "_fits"] = legend.property("width") <= obj.property("width") - 8

print(json.dumps(results))
sys.stdout.flush()
'''


class EngineWarningLegendTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        result = subprocess.run([sys.executable, "-c", SCRIPT], cwd=ROOT,
                                capture_output=True, text=True, timeout=60,
                                env={**os.environ, "QT_QPA_PLATFORM": "offscreen"})
        cls.stderr = result.stderr
        cls.returncode = result.returncode
        cls.results = json.loads(result.stdout.strip().splitlines()[-1]) if result.returncode == 0 else {}

    def setUp(self):
        self.assertEqual(self.returncode, 0, self.stderr)

    def test_legends(self):
        r = self.results
        self.assertEqual(r["coolant"], "Hot")
        self.assertEqual(r["low"], "Low")
        self.assertEqual(r["high"], "High")
        self.assertEqual(r["boost"], "Over")
        self.assertEqual(r["mil"], "Engine")

    def test_chip_stays_small(self):
        for name in ("coolant", "boost", "mil", "low", "high"):
            self.assertLessEqual(self.results[name + "_height"], 100, name)
            self.assertTrue(self.results[name + "_fits"], name)


if __name__ == "__main__":
    unittest.main()
