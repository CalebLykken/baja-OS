"""Off-Pi tests for the Home page's coolant label (qml/pages/HomePage.qml): the
Coolant readout says "Warming up" while the engine is known and coolant is
below 155 F, and goes back to "Coolant" at 160 F. Between the two lines the
last state holds, so the label can't flicker at the edge.

The QML runs in its own process, like tests/test_source_badge.py, so the
QCoreApplication other test modules create at import time doesn't get in the way.

    python3 -m unittest tests.test_home_warmup
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
from PyQt6.QtCore import QObject, QUrl, pyqtProperty, pyqtSignal
from PyQt6.QtGui import QGuiApplication
from PyQt6.QtQml import QQmlComponent, QQmlEngine

app = QGuiApplication(sys.argv)
ROOT = Path.cwd()


class Vehicle(QObject):
    changed = pyqtSignal()

    def __init__(self):
        super().__init__()
        self._engineKnown = False
        self._coolant = 0.0

    @pyqtProperty(bool, notify=changed)
    def engineKnown(self):
        return self._engineKnown

    @pyqtProperty(bool, notify=changed)
    def simulated(self):
        return False

    @pyqtProperty(bool, notify=changed)
    def live(self):
        return False

    @pyqtProperty(float, notify=changed)
    def coolant(self):
        return self._coolant

    @pyqtProperty(bool, notify=changed)
    def voltageKnown(self):
        return False

    @pyqtProperty(float, notify=changed)
    def voltage(self):
        return 0.0

    @pyqtProperty(bool, notify=changed)
    def speedKnown(self):
        return False

    @pyqtProperty(float, notify=changed)
    def speed(self):
        return 0.0

    @pyqtProperty(float, notify=changed)
    def boost(self):
        return 0.0

    @pyqtProperty(list, notify=changed)
    def warnings(self):
        return []

    def set(self, known, coolant):
        self._engineKnown, self._coolant = known, coolant
        self.changed.emit()


def coolant_label(page):
    # The Coolant readout is the only Readout whose label is Coolant or Warming up.
    for child in page.findChildren(QObject):
        label = child.property("label")
        if label in ("Coolant", "Warming up"):
            return label
    return None


vehicle = Vehicle()
engine = QQmlEngine()
engine.rootContext().setContextProperty("vehicle", vehicle)
component = QQmlComponent(engine, QUrl.fromLocalFile(str(ROOT / "qml" / "pages" / "HomePage.qml")))
if component.isError():
    for error in component.errors():
        print(error.toString(), file=sys.stderr)
    sys.exit(1)
page = component.create()
if page is None:
    for error in component.errors():
        print(error.toString(), file=sys.stderr)
    sys.exit(1)

results = {}
results["initial"] = coolant_label(page)

steps = [
    ("cold_120", True, 120.0),
    ("cold_158", True, 158.0),
    ("warm_160", True, 160.0),
    ("warm_157", True, 157.0),
    ("cold_150", True, 150.0),
    ("held_158", True, 158.0),
    ("held_155", True, 155.0),
    ("unknown_150", False, 150.0),
    ("known_158_after_unknown", True, 158.0),
    ("cold_again_120", True, 120.0),
]
for name, known, coolant in steps:
    vehicle.set(known, coolant)
    results[name] = coolant_label(page)

print(json.dumps(results))
sys.stdout.flush()
'''


def run():
    return subprocess.run([sys.executable, "-c", SCRIPT], cwd=ROOT,
                          capture_output=True, text=True, timeout=60,
                          env={**os.environ, "QT_QPA_PLATFORM": "offscreen"})


class HomeWarmupTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        result = run()
        cls.stderr = result.stderr
        cls.returncode = result.returncode
        cls.results = json.loads(result.stdout.strip().splitlines()[-1]) if result.returncode == 0 else {}

    def setUp(self):
        self.assertEqual(self.returncode, 0, self.stderr)

    def test_no_engine_data_yet_reads_coolant(self):
        self.assertEqual(self.results["initial"], "Coolant")

    def test_cold_engine_reads_warming_up(self):
        self.assertEqual(self.results["cold_120"], "Warming up")
        self.assertEqual(self.results["cold_158"], "Warming up")

    def test_reaching_operating_temperature_reads_coolant(self):
        self.assertEqual(self.results["warm_160"], "Coolant")

    def test_dipping_back_under_the_line_does_not_flicker(self):
        self.assertEqual(self.results["warm_157"], "Coolant")

    def test_dropping_below_155_warms_up_again_and_holds_through_the_gap(self):
        self.assertEqual(self.results["cold_150"], "Warming up")
        self.assertEqual(self.results["held_158"], "Warming up")
        self.assertEqual(self.results["held_155"], "Warming up")

    def test_engine_unknown_reads_coolant(self):
        self.assertEqual(self.results["unknown_150"], "Coolant")

    def test_gap_after_unknown_does_not_warm_up_without_a_cold_reading(self):
        self.assertEqual(self.results["known_158_after_unknown"], "Coolant")

    def test_cold_again_after_unknown_warms_up(self):
        self.assertEqual(self.results["cold_again_120"], "Warming up")


if __name__ == "__main__":
    unittest.main()
