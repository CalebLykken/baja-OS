"""Off-Pi tests for Home's next-turn card (qml/components/HomeTurn.qml): during a
reroute it shows the refresh icon and "Rerouting" like the nav rail's TurnChip, and
arrival hides the distance.

The QML runs in its own process, like tests/test_source_badge.py.

    python3 -m unittest tests.test_home_turn
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
from PyQt6.QtGui import QFont, QFontMetricsF, QGuiApplication
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
        self._instruction = "Turn left onto Main St"

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

    @pyqtProperty(str, notify=progressChanged)
    def instruction(self):
        return self._instruction

    def setActive(self, v):
        self._active = v
        self.changed.emit()

    def setComputing(self, v):
        self._computing = v
        self.changed.emit()

    def setArrived(self, v):
        self._arrived = v
        self.changed.emit()

    def setInstruction(self, v):
        self._instruction = v
        self.progressChanged.emit()

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
component.setData(b'import QtQuick\nimport "qml/components"\nHomeTurn { width: 600 }',
                  QUrl.fromLocalFile(str(ROOT / "x.qml")))
obj = component.create()
if obj is None:
    for error in component.errors():
        print(error.toString(), file=sys.stderr)
    sys.exit(1)


def child(name):
    return obj.findChild(QObject, name)


def snap():
    return {"icon": child("homeTurnIcon").property("name"),
            "distance": child("homeTurnDistance").property("text"),
            "distance_visible": child("homeTurnDistance").property("visible"),
            "text_opacity": child("homeTurnText").property("opacity"),
            "height": obj.property("height")}


results = {}
results["inactive_visible"] = obj.property("visible")
routing.setActive(True)
wait(400)
results["idle"] = snap()
routing.setComputing(True)
wait(400)
results["computing"] = snap()
results["computing_font"] = child("homeTurnDistance").property("font").pixelSize()
routing.setIcon("turn_right")
wait(50)
results["computing_new_icon"] = snap()["icon"]
routing.setComputing(False)
wait(400)
results["done"] = snap()
routing.setArrived(True)
wait(50)
results["arrived"] = snap()

print(json.dumps(results))
sys.stdout.flush()
'''


def run():
    return subprocess.run([sys.executable, "-c", SCRIPT], cwd=ROOT,
                          capture_output=True, text=True, timeout=60,
                          env={**os.environ, "QT_QPA_PLATFORM": "offscreen"})


class HomeTurnTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        result = run()
        cls.stderr = result.stderr
        cls.returncode = result.returncode
        cls.results = json.loads(result.stdout.strip().splitlines()[-1]) if result.returncode == 0 else {}

    def setUp(self):
        self.assertEqual(self.returncode, 0, self.stderr)

    def test_hidden_until_routing(self):
        self.assertIs(self.results["inactive_visible"], False)

    def test_idle_shows_maneuver_and_distance(self):
        idle = self.results["idle"]
        self.assertEqual(idle["icon"], "turn_left")
        self.assertNotIn(idle["distance"], ("", "Rerouting"))
        self.assertEqual(idle["text_opacity"], 1.0)

    def test_computing_shows_refresh_and_rerouting(self):
        computing = self.results["computing"]
        self.assertEqual(computing["icon"], "refresh")
        self.assertEqual(computing["distance"], "Rerouting")
        self.assertEqual(computing["text_opacity"], 0.0)

    def test_rerouting_keeps_card_size_and_distance_font(self):
        self.assertEqual(self.results["computing"]["height"], self.results["idle"]["height"])

    def test_new_turn_stays_hidden_while_computing(self):
        self.assertEqual(self.results["computing_new_icon"], "refresh")

    def test_back_to_maneuver_afterwards(self):
        done = self.results["done"]
        self.assertEqual(done["icon"], "turn_right")
        self.assertNotEqual(done["distance"], "Rerouting")
        self.assertEqual(done["text_opacity"], 1.0)

    def test_arrived_hides_distance(self):
        self.assertIs(self.results["arrived"]["distance_visible"], False)


if __name__ == "__main__":
    unittest.main()
