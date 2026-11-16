"""Off-Pi tests for Home's arrival pill (qml/components/HomeArrive.qml): the ETA
clock time, then "25 min · 12 mi" dimmer; at arrival it shows the arrival summary
(or hides) instead of an arrival time of "now" and a rounded-up distance.

The QML runs in its own process, like tests/test_home_turn.py.

    python3 -m unittest tests.test_home_arrive
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

    def __init__(self):
        super().__init__()
        self._v = {"active": False, "arrived": False, "remainingTime": 1500.0,
                   "remainingDistance": 19312.0, "arrivalSummary": ""}

    def _get(name):
        return lambda self: self._v[name]

    active = pyqtProperty(bool, _get("active"), notify=changed)
    arrived = pyqtProperty(bool, _get("arrived"), notify=changed)
    remainingTime = pyqtProperty(float, _get("remainingTime"), notify=changed)
    remainingDistance = pyqtProperty(float, _get("remainingDistance"), notify=changed)
    arrivalSummary = pyqtProperty(str, _get("arrivalSummary"), notify=changed)

    def set(self, **kw):
        self._v.update(kw)
        self.changed.emit()


def wait(ms):
    loop = QEventLoop()
    QTimer.singleShot(ms, loop.quit)
    loop.exec()


routing = Routing()
engine = QQmlEngine()
engine.rootContext().setContextProperty("routing", routing)
component = QQmlComponent(engine)
component.setData(b'import QtQuick\nimport "qml/components"\n'
                  b'Item { width: 445; height: 300; HomeArrive { objectName: "pill"; anchors { left: parent.left; bottom: parent.bottom; margins: 12 } } }',
                  QUrl.fromLocalFile(str(ROOT / "x.qml")))
obj = component.create()
if obj is None:
    for error in component.errors():
        print(error.toString(), file=sys.stderr)
    sys.exit(1)


def child(name):
    return obj.findChild(QObject, name)


def snap():
    return {"eta": child("arriveEta").property("text"),
            "eta_visible": child("arriveEta").property("visible"),
            "rest": child("arriveRest").property("text"),
            "visible": child("pill").property("visible"),
            "width": child("pill").property("width")}


results = {}
results["inactive"] = snap()
routing.set(active=True)
wait(400)
results["driving"] = snap()
routing.set(remainingDistance=15.0, remainingTime=5.0, arrived=True)
wait(400)
results["arrived_plain"] = snap()
routing.set(arrivalSummary="14 min · right on time")
wait(400)
results["arrived_summary"] = snap()
routing.set(remainingDistance=900000.0, remainingTime=40000.0, arrived=False, arrivalSummary="")
wait(400)
results["far"] = snap()

print(json.dumps(results))
sys.stdout.flush()
'''


def run():
    return subprocess.run([sys.executable, "-c", SCRIPT], cwd=ROOT,
                          capture_output=True, text=True, timeout=60,
                          env={**os.environ, "QT_QPA_PLATFORM": "offscreen"})


class HomeArriveTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        result = run()
        cls.stderr = result.stderr
        cls.returncode = result.returncode
        cls.results = json.loads(result.stdout.strip().splitlines()[-1]) if result.returncode == 0 else {}

    def setUp(self):
        self.assertEqual(self.returncode, 0, self.stderr)

    def test_hidden_until_routing(self):
        self.assertIs(self.results["inactive"]["visible"], False)

    def test_shows_eta_duration_and_distance(self):
        d = self.results["driving"]
        self.assertIs(d["visible"], True)
        self.assertRegex(d["eta"], r"^\d{1,2}:\d{2}")
        self.assertIn("25 min", d["rest"])
        self.assertIn("mi", d["rest"])

    def test_arrived_without_summary_hides(self):
        a = self.results["arrived_plain"]
        self.assertIs(a["visible"], False)
        self.assertNotIn("ft", a["rest"])

    def test_arrived_shows_summary_only(self):
        a = self.results["arrived_summary"]
        self.assertIs(a["visible"], True)
        self.assertIs(a["eta_visible"], False)
        self.assertEqual(a["rest"], "14 min · right on time")

    def test_fits_in_the_map_tile(self):
        self.assertLessEqual(self.results["far"]["width"], 445 - 24)
        self.assertIn("h", self.results["far"]["rest"])


if __name__ == "__main__":
    unittest.main()
