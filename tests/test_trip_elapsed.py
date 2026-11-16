"""Off-Pi tests that qml/components/Trip.qml counts the time that really
passed between ticks, not one second per Timer tick, and leaves `started`
alone. The QML half runs in a subprocess because other test modules hold a
QCoreApplication.

    python3 -m unittest tests.test_trip_elapsed
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
from PyQt6.QtCore import QObject, QUrl, pyqtProperty
from PyQt6.QtGui import QGuiApplication
from PyQt6.QtQml import QQmlComponent, QQmlEngine

ROOT = Path(sys.argv[1])
app = QGuiApplication(sys.argv)


class Vehicle(QObject):
    @pyqtProperty(bool, constant=True)
    def speedKnown(self): return True

    @pyqtProperty(float, constant=True)
    def speed(self): return 30.0

    @pyqtProperty(bool, constant=True)
    def engineKnown(self): return False

    @pyqtProperty(float, constant=True)
    def boost(self): return 0.0


engine = QQmlEngine()
vehicle = Vehicle()
engine.rootContext().setContextProperty("vehicle", vehicle)


def make():
    c = QQmlComponent(engine)
    c.setData(b'import QtQuick\nimport "qml/components"\nTrip { property int changes: 0; onStartedChanged: changes++ }',
              QUrl.fromLocalFile(str(ROOT / "x.qml")))
    trip = c.create()
    if trip is None:
        print([e.toString() for e in c.errors()])
        sys.exit(1)
    return trip


out = {}
import time
T0 = int(time.time() * 1000)

trip = make()
trip.setProperty("lastTick", float(T0))
changes0 = trip.property("changes")
for i in range(1, 11):
    trip.tick(float(T0 + i * 1000))
out["metres_normal"] = trip.property("metres")
out["moving_normal"] = trip.property("movingSeconds")
out["started_changes"] = trip.property("changes") - changes0
# A late tick: 4 s passed.
trip.tick(float(T0 + 14000))
out["metres_late"] = trip.property("metres")
out["running_late"] = trip.property("runningSeconds")
# A clock step of 60 s counts as one second.
before = trip.property("metres")
trip.tick(float(T0 + 14000 + 60000))
out["step_added"] = trip.property("metres") - before

print(json.dumps(out))
'''


class TripElapsedTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        env = dict(os.environ, QT_QPA_PLATFORM="offscreen")
        result = subprocess.run([sys.executable, "-c", SCRIPT, str(ROOT)], cwd=ROOT,
                                capture_output=True, text=True, timeout=60, env=env)
        if result.returncode != 0:
            raise AssertionError(result.stdout + result.stderr)
        cls.out = json.loads(result.stdout.strip().splitlines()[-1])

    def test_normal_ticks_count_each_second(self):
        self.assertAlmostEqual(self.out["metres_normal"], 30 * 0.44704 * 10, places=3)
        self.assertAlmostEqual(self.out["moving_normal"], 10, places=6)

    def test_started_is_not_rewritten_by_normal_ticks(self):
        self.assertEqual(self.out["started_changes"], 0)

    def test_a_late_tick_counts_the_time_that_passed(self):
        self.assertAlmostEqual(self.out["metres_late"], 30 * 0.44704 * 14, places=3)
        self.assertAlmostEqual(self.out["running_late"], 14, places=6)

    def test_a_clock_step_counts_one_second(self):
        self.assertAlmostEqual(self.out["step_added"], 30 * 0.44704, places=3)


if __name__ == "__main__":
    unittest.main()
