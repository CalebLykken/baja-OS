"""Off-Pi tests for when the trip is saved: at a stop, and on the way out
before settings are flushed. Without those, up to 30 s of driving (and a
peak boost reached while stopped) is lost when the updater restarts the
dashboard at a stop. The QML half runs in a subprocess because other test
modules hold a QCoreApplication.

    python3 -m unittest tests.test_trip_save_points
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
from PyQt6.QtCore import QObject, QTimer, QUrl, QEventLoop, pyqtProperty, pyqtSignal
from PyQt6.QtGui import QGuiApplication
from PyQt6.QtQml import QQmlComponent, QQmlEngine

sys.path.insert(0, sys.argv[1])
import backend.trip as t
from backend.trip import TripStore, connect_quit

ROOT = Path(sys.argv[1])
app = QGuiApplication(sys.argv)
t.boot_id = lambda: "boot-a"


class Vehicle(QObject):
    mph = 60.0

    @pyqtProperty(bool, constant=True)
    def speedKnown(self): return True

    @pyqtProperty(float)
    def speed(self): return Vehicle.mph

    @pyqtProperty(bool, constant=True)
    def engineKnown(self): return False

    @pyqtProperty(float, constant=True)
    def boost(self): return 0.0


class Settings:
    def __init__(self):
        self.values = {}
        self.on_disk = None

    def get(self, key, default=None):
        return self.values.get(key, default)

    def set(self, key, value):
        self.values[key] = value

    def flush_and_wait(self):
        self.on_disk = self.values.get("trip")


class Quit(QObject):
    aboutToQuit = pyqtSignal()


def wait(ms):
    loop = QEventLoop()
    QTimer.singleShot(ms, loop.quit)
    loop.exec()


def start():
    settings = Settings()
    engine = QQmlEngine()
    store = TripStore(settings)
    vehicle = Vehicle()
    engine.rootContext().setContextProperty("vehicle", vehicle)
    engine.rootContext().setContextProperty("tripStore", store)
    component = QQmlComponent(engine)
    component.setData(b'import QtQuick\nimport "qml/components"\nTrip {}',
                      QUrl.fromLocalFile(str(ROOT / "x.qml")))
    trip = component.create()
    if trip is None:
        print([e.toString() for e in component.errors()])
        sys.exit(1)
    return settings, store, trip, (engine, vehicle)


out = {}

# Rolling 1.3 s (not a 30 s mark, no milestone): nothing saved. Then stopped:
# saved once, with the metres counted. Parked on: nothing more.
Vehicle.mph = 60.0
settings, store, trip, engine = start()
wait(1300)
out["rolling_saved"] = settings.values.get("trip")
Vehicle.mph = 0.0
wait(1000)
out["stopped_saved"] = settings.values.get("trip")
first = settings.values.get("trip")
settings.values["trip"] = "sentinel"
wait(2200)
out["parked_saved"] = settings.values.get("trip")

# Quitting while rolling: the trip saves before the flush reaches the disk.
Vehicle.mph = 60.0
settings, store, trip, engine = start()
wait(1300)
q = Quit()
connect_quit(q.aboutToQuit, store, settings.flush_and_wait)
out["before_quit"] = settings.values.get("trip")
q.aboutToQuit.emit()
out["flushed"] = settings.on_disk
out["after_quit"] = settings.values.get("trip")

print(json.dumps(out))
'''


class TripSavePointsTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        env = dict(os.environ, QT_QPA_PLATFORM="offscreen")
        result = subprocess.run([sys.executable, "-c", SCRIPT, str(ROOT)], cwd=ROOT,
                                capture_output=True, text=True, timeout=60, env=env)
        if result.returncode != 0:
            raise AssertionError(result.stdout + result.stderr)
        cls.out = json.loads(result.stdout.strip().splitlines()[-1])

    def test_nothing_is_saved_while_rolling_between_marks(self):
        self.assertIsNone(self.out["rolling_saved"])

    def test_it_is_saved_when_the_truck_stops(self):
        saved = json.loads(self.out["stopped_saved"])
        self.assertGreater(saved["metres"], 20)
        self.assertGreaterEqual(saved["moving"], 1)

    def test_nothing_is_saved_while_parked(self):
        self.assertEqual(self.out["parked_saved"], "sentinel")

    def test_it_is_saved_on_the_way_out_and_before_the_flush(self):
        self.assertIsNone(self.out["before_quit"])
        self.assertIsNotNone(self.out["flushed"])
        saved = json.loads(self.out["flushed"])
        self.assertGreater(saved["metres"], 20)
        self.assertEqual(self.out["flushed"], self.out["after_quit"])


if __name__ == "__main__":
    unittest.main()
