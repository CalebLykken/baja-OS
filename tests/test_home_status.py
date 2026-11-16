"""Off-Pi tests for the Home page's engine note (qml/pages/HomePage.qml): a dim
line above the readouts says "Engine not connected" when the engine is unknown
and nothing is simulated, with " · speed from GPS" added when only GPS gives a
speed. The QML runs in its own process, like tests/test_home_warmup.py.

    python3 -m unittest tests.test_home_status
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
        self.v = dict(live=False, simulated=False, engineKnown=False, speedKnown=False)

    def _p(name, sig=changed):
        return pyqtProperty(bool, lambda self: self.v[name], notify=sig)

    live = _p("live")
    simulated = _p("simulated")
    engineKnown = _p("engineKnown")
    speedKnown = _p("speedKnown")
    voltageKnown = pyqtProperty(bool, lambda self: False, notify=changed)
    voltage = pyqtProperty(float, lambda self: 0.0, notify=changed)
    speed = pyqtProperty(float, lambda self: 0.0, notify=changed)
    boost = pyqtProperty(float, lambda self: 0.0, notify=changed)
    coolant = pyqtProperty(float, lambda self: 0.0, notify=changed)
    warnings = pyqtProperty(list, lambda self: [], notify=changed)

    def set(self, **kw):
        self.v.update(kw)
        self.changed.emit()


vehicle = Vehicle()
engine = QQmlEngine()
engine.rootContext().setContextProperty("vehicle", vehicle)
component = QQmlComponent(engine, QUrl.fromLocalFile(str(ROOT / "qml" / "pages" / "HomePage.qml")))
page = component.create()
if page is None:
    for error in component.errors():
        print(error.toString(), file=sys.stderr)
    sys.exit(1)


def note():
    n = page.findChild(QObject, "homeEngineNote")
    return [bool(n.property("visible")), n.property("text")]


results = {}
for name, state in [
    ("not_connected", {}),
    ("gps_speed", dict(speedKnown=True)),
    ("gps_speed_live", dict(speedKnown=True, live=True)),
    ("engine_known", dict(engineKnown=True)),
    ("simulated", dict(simulated=True, engineKnown=True, speedKnown=True)),
    ("simulated_only", dict(simulated=True)),
]:
    vehicle.set(**{**dict(live=False, simulated=False, engineKnown=False, speedKnown=False), **state})
    results[name] = note()

print(json.dumps(results))
sys.stdout.flush()
'''


class HomeStatusTest(unittest.TestCase):
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

    def test_shown_with_plain_text_when_nothing_is_known(self):
        self.assertEqual(self.results["not_connected"], [True, "Engine not connected"])

    def test_names_gps_when_only_gps_gives_speed(self):
        self.assertEqual(self.results["gps_speed"], [True, "Engine not connected · speed from GPS"])

    def test_no_gps_mention_when_the_adapter_is_live(self):
        self.assertEqual(self.results["gps_speed_live"], [True, "Engine not connected"])

    def test_hidden_when_engine_known(self):
        self.assertFalse(self.results["engine_known"][0])

    def test_hidden_when_simulated(self):
        self.assertFalse(self.results["simulated"][0])
        self.assertFalse(self.results["simulated_only"][0])


if __name__ == "__main__":
    unittest.main()
