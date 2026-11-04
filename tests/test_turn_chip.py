"""Off-Pi tests for the nav rail's turn chip (qml/components/TurnChip.qml): during a
reroute it shows the refresh icon and "Rerouting" like the Maps turn card, and the
arrival label reads "Arrived".

The QML runs in its own process, like tests/test_source_badge.py.

    python3 -m unittest tests.test_turn_chip
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


class Routing(QObject):
    changed = pyqtSignal()
    progressChanged = pyqtSignal()

    def __init__(self):
        super().__init__()
        self._active = False
        self._computing = False
        self._arrived = False
        self._icon = "turn_left"
        self._distance = 250.0

    @pyqtProperty(bool, notify=changed)
    def active(self):
        return self._active

    @pyqtProperty(bool, notify=changed)
    def computing(self):
        return self._computing

    @pyqtProperty(bool, notify=changed)
    def arrived(self):
        return self._arrived

    @pyqtProperty(str, notify=progressChanged)
    def maneuverIcon(self):
        return self._icon

    @pyqtProperty(float, notify=progressChanged)
    def distanceToTurn(self):
        return self._distance

    def setActive(self, v):
        self._active = v
        self.changed.emit()

    def setComputing(self, v):
        self._computing = v
        self.changed.emit()

    def setArrived(self, v):
        self._arrived = v
        self.changed.emit()

    def setIcon(self, v):
        self._icon = v
        self.progressChanged.emit()


def wait(ms):
    loop = QEventLoop()
    QTimer.singleShot(ms, loop.quit)
    loop.exec()


routing = Routing()
engine = QQmlEngine()
engine.rootContext().setContextProperty("routing", routing)
component = QQmlComponent(engine)
component.setData(b'import QtQuick\nimport "qml/components"\nTurnChip {}',
                  QUrl.fromLocalFile(str(ROOT / "x.qml")))
obj = component.create()
if obj is None:
    for error in component.errors():
        print(error.toString(), file=sys.stderr)
    sys.exit(1)


def icon():
    return obj.findChild(QObject, "turnIcon").property("name")


def label():
    return obj.findChild(QObject, "turnLabel").property("text")


results = {}
routing.setActive(True)
wait(100)
results["active_icon"] = icon()
results["active_label"] = label()

routing.setComputing(True)
wait(50)
results["computing_icon"] = icon()
results["computing_label"] = label()

routing.setIcon("turn_right")
wait(400)
results["computing_new_turn_icon"] = icon()

routing.setComputing(False)
wait(400)
results["done_icon"] = icon()
results["done_label"] = label()
results["done_opacity"] = obj.findChild(QObject, "turnIcon").property("opacity")

routing.setArrived(True)
wait(50)
results["arrived_label"] = label()

print(json.dumps(results))
sys.stdout.flush()
'''


def run():
    return subprocess.run([sys.executable, "-c", SCRIPT], cwd=ROOT,
                          capture_output=True, text=True, timeout=60,
                          env={**os.environ, "QT_QPA_PLATFORM": "offscreen"})


class TurnChipTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        result = run()
        cls.stderr = result.stderr
        cls.returncode = result.returncode
        cls.results = json.loads(result.stdout.strip().splitlines()[-1]) if result.returncode == 0 else {}

    def setUp(self):
        self.assertEqual(self.returncode, 0, self.stderr)

    def test_active_shows_turn_and_distance(self):
        self.assertEqual(self.results["active_icon"], "turn_left")
        self.assertNotIn(self.results["active_label"], ("", "Rerouting", "Arrived"))

    def test_computing_shows_refresh_and_rerouting(self):
        self.assertEqual(self.results["computing_icon"], "refresh")
        self.assertEqual(self.results["computing_label"], "Rerouting")

    def test_new_turn_stays_hidden_while_computing(self):
        self.assertEqual(self.results["computing_new_turn_icon"], "refresh")

    def test_new_turn_shows_when_computing_ends(self):
        self.assertEqual(self.results["done_icon"], "turn_right")
        self.assertEqual(self.results["done_opacity"], 1.0)
        self.assertNotEqual(self.results["done_label"], "Rerouting")

    def test_arrival_reads_arrived(self):
        self.assertEqual(self.results["arrived_label"], "Arrived")


if __name__ == "__main__":
    unittest.main()
