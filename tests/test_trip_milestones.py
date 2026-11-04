"""Off-Pi tests for the milestone text in qml/components/Trip.qml: a message
only on a crossing of a round distance or an hour, never on a unit change.
Runs in a subprocess because other test modules hold a QCoreApplication.

    python3 -m unittest tests.test_trip_milestones
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
from PyQt6.QtCore import QUrl, QMetaObject, Qt, Q_RETURN_ARG, Q_ARG
from PyQt6.QtGui import QGuiApplication
from PyQt6.QtQml import QQmlComponent, QQmlEngine

ROOT = Path(sys.argv[1])
app = QGuiApplication(sys.argv)
engine = QQmlEngine()
component = QQmlComponent(engine)
component.setData(b'import QtQuick\nimport "qml/components"\nTrip {}',
                  QUrl.fromLocalFile(str(ROOT / "x.qml")))
trip = component.create()
if trip is None:
    print([e.toString() for e in component.errors()])
    sys.exit(1)

MI = 1609.344


def text(pm, m, ps, s, metric=False):
    value = QMetaObject.invokeMethod(
        trip, "milestoneText", Qt.ConnectionType.DirectConnection,
        Q_RETURN_ARG("QVariant"), Q_ARG("QVariant", pm), Q_ARG("QVariant", m),
        Q_ARG("QVariant", ps), Q_ARG("QVariant", s), Q_ARG("QVariant", metric))
    return value


out = {
    "ten": text(9.9 * MI, 10.1 * MI, 0, 0),
    "after_ten": text(10.1 * MI, 10.2 * MI, 0, 0),
    "km": text(9.9 * 1000, 10.1 * 1000, 0, 0, True),
    "km_100": text(99.9 * 1000, 100.1 * 1000, 0, 0, True),
    "unit_switch": text(15 * MI, 15 * MI, 0, 0, True),
    "unit_switch_back": text(10.5 * 1000, 10.5 * 1000, 0, 0, False),
    "hour": text(0, 0, 3599, 3600),
    "two_hours": text(0, 0, 7199, 7200),
    "hundred": text(99.9 * MI, 100.1 * MI, 0, 0),
    "two_hundred": text(199.9 * MI, 200.1 * MI, 0, 0),
    "both": text(9.9 * MI, 10.1 * MI, 3599, 3600),
    "none": text(1, 2, 5, 6),
}
print(json.dumps(out))
'''


class TripMilestoneTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        env = dict(os.environ, QT_QPA_PLATFORM="offscreen")
        result = subprocess.run([sys.executable, "-c", SCRIPT, str(ROOT)], cwd=ROOT,
                                capture_output=True, text=True, timeout=60, env=env)
        if result.returncode != 0:
            raise AssertionError(result.stdout + result.stderr)
        cls.out = json.loads(result.stdout.strip().splitlines()[-1])

    def test_ten_miles(self):
        self.assertEqual(self.out["ten"], "10 miles this trip")

    def test_nothing_after_the_crossing(self):
        self.assertEqual(self.out["after_ten"], "")
        self.assertEqual(self.out["none"], "")

    def test_km_when_metric(self):
        self.assertEqual(self.out["km"], "10 km this trip")
        self.assertEqual(self.out["km_100"], "100 km this trip")

    def test_unit_switch_fires_nothing(self):
        self.assertEqual(self.out["unit_switch"], "")
        self.assertEqual(self.out["unit_switch_back"], "")

    def test_hours(self):
        self.assertEqual(self.out["hour"], "An hour of driving")
        self.assertEqual(self.out["two_hours"], "Two hours of driving")

    def test_every_hundred(self):
        self.assertEqual(self.out["hundred"], "100 miles this trip")
        self.assertEqual(self.out["two_hundred"], "200 miles this trip")

    def test_distance_wins_over_time(self):
        self.assertEqual(self.out["both"], "10 miles this trip")


if __name__ == "__main__":
    unittest.main()
