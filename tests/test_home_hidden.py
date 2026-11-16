"""Off-Pi tests that the Home page (qml/pages/HomePage.qml) stops re-evaluating
its readouts while it is hidden, and shows the latest values again on return.

The QML runs in its own process, like tests/test_source_badge.py, so the
QCoreApplication other test modules create at import time doesn't get in the way.

    python3 -m unittest tests.test_home_hidden
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
        self.reads = {"boost": 0, "coolant": 0, "speed": 0}
        self.vals = {"boost": 0.0, "coolant": 120.0, "speed": 0.0}

    def _get(self, name):
        self.reads[name] += 1
        return self.vals[name]

    @pyqtProperty(bool, notify=changed)
    def engineKnown(self):
        return True

    @pyqtProperty(bool, notify=changed)
    def simulated(self):
        return False

    @pyqtProperty(bool, notify=changed)
    def live(self):
        return False

    @pyqtProperty(float, notify=changed)
    def coolant(self):
        return self._get("coolant")

    @pyqtProperty(bool, notify=changed)
    def voltageKnown(self):
        return False

    @pyqtProperty(float, notify=changed)
    def voltage(self):
        return 0.0

    @pyqtProperty(bool, notify=changed)
    def speedKnown(self):
        return True

    @pyqtProperty(float, notify=changed)
    def speed(self):
        return self._get("speed")

    @pyqtProperty(float, notify=changed)
    def boost(self):
        return self._get("boost")

    @pyqtProperty(list, notify=changed)
    def warnings(self):
        return []

    def set(self, **vals):
        self.vals.update(vals)
        self.changed.emit()


def readout(page, label):
    for child in page.findChildren(QObject):
        if child.property("label") == label:
            return child
    return None


def find(page, labels):
    for child in page.findChildren(QObject):
        if child.property("label") in labels:
            return child


def coolant(page):
    return find(page, ("Coolant", "Warming up"))


def shown(page):
    return {"boost": readout(page, "Boost").property("value"),
            "coolant": coolant(page).property("value"),
            "speed": readout(page, "Speed").property("value"),
            "label": coolant(page).property("label")}


vehicle = Vehicle()
engine = QQmlEngine()
engine.rootContext().setContextProperty("vehicle", vehicle)
component = QQmlComponent(engine, QUrl.fromLocalFile(str(ROOT / "qml" / "pages" / "HomePage.qml")))
from PyQt6.QtQuick import QQuickItem, QQuickWindow
window = QQuickWindow()
page = component.create()
if page is None:
    for error in component.errors():
        print(error.toString(), file=sys.stderr)
    sys.exit(1)

# A page with no window is never visible; put it in one so visible means something.
page.setParentItem(window.contentItem())
results = {}
vehicle.set(boost=5.0, coolant=120.0, speed=30.0)
results["visible"] = shown(page)

page.setProperty("visible", False)
before = dict(vehicle.reads)
for i in range(20):
    vehicle.set(boost=10.0 + i, coolant=100.0 + i, speed=40.0 + i)
results["reads_grew"] = {k: vehicle.reads[k] - before[k] for k in before}
results["hidden"] = shown(page)

# Warms up past 160 F while hidden, then comes back.
vehicle.set(boost=1.0, coolant=185.0, speed=62.0)
page.setProperty("visible", True)
results["returned"] = shown(page)
print(json.dumps(results))
sys.stdout.flush()
'''


def run():
    return subprocess.run([sys.executable, "-c", SCRIPT], cwd=ROOT,
                          capture_output=True, text=True, timeout=60,
                          env={**os.environ, "QT_QPA_PLATFORM": "offscreen"})


class HomeHiddenTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        result = run()
        cls.stderr = result.stderr
        cls.returncode = result.returncode
        cls.results = json.loads(result.stdout.strip().splitlines()[-1]) if result.returncode == 0 else {}

    def setUp(self):
        self.assertEqual(self.returncode, 0, self.stderr)

    def test_visible_page_follows_the_vehicle(self):
        self.assertEqual(self.results["visible"]["speed"], "30")
        self.assertEqual(self.results["visible"]["boost"], "5.0")

    def test_hidden_page_does_not_read_the_vehicle(self):
        self.assertEqual(self.results["reads_grew"], {"boost": 0, "coolant": 0, "speed": 0})

    def test_hidden_page_keeps_its_last_values(self):
        self.assertEqual(self.results["hidden"]["speed"], "30")
        self.assertEqual(self.results["hidden"]["label"], "Warming up")

    def test_returning_shows_the_latest_values_and_label(self):
        self.assertEqual(self.results["returned"]["speed"], "62")
        self.assertEqual(self.results["returned"]["label"], "Coolant")
        self.assertNotEqual(self.results["returned"]["coolant"], self.results["hidden"]["coolant"])


if __name__ == "__main__":
    unittest.main()
