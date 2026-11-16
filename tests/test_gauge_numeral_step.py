"""Off-Pi tests for numberStep on qml/components/Gauge.qml: the numeral can show
the reading rounded to a step (RPM to the nearest 10) so the last digit stops
jittering at idle. With numberStep 0 the numeral is the value as it is, and the
unknown dash still shows. Runs in a subprocess because other test modules hold
a QCoreApplication.

    python3 -m unittest tests.test_gauge_numeral_step
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
from PyQt6.QtCore import QObject, QUrl
from PyQt6.QtGui import QGuiApplication
from PyQt6.QtQml import QQmlComponent, QQmlEngine

ROOT = Path(sys.argv[1])
app = QGuiApplication(sys.argv)
engine = QQmlEngine()


def make(props):
    component = QQmlComponent(engine)
    component.setData(
        ('import QtQuick\nimport "qml/components"\n'
         'Gauge { width: 300; height: 300; minValue: 0; maxValue: 7000; known: true; '
         'value: 0; %s }' % props).encode(),
        QUrl.fromLocalFile(str(ROOT / "x.qml")))
    obj = component.create()
    if obj is None:
        print([e.toString() for e in component.errors()])
        sys.exit(1)
    return obj


def numeral(obj):
    return obj.findChild(QObject, "gaugeNumber").property("text")


out = {}
g = make("numberStep: 10")
g.setProperty("value", 2604)
out["step_2604"] = numeral(g)
g.setProperty("value", 2605)
out["step_2605"] = numeral(g)
g.setProperty("value", 2598)
out["step_2598"] = numeral(g)
g.setProperty("value", 2605)
g.setProperty("numberStep", 0)
out["none_2605"] = numeral(g)
g.setProperty("known", False)
out["unknown"] = numeral(g)
out["unknown_dial_value"] = g.property("value")
print(json.dumps(out))
'''


class GaugeNumeralStepTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        env = dict(os.environ, QT_QPA_PLATFORM="offscreen")
        result = subprocess.run([sys.executable, "-c", SCRIPT, str(ROOT)], cwd=ROOT,
                                capture_output=True, text=True, timeout=60, env=env)
        if result.returncode != 0:
            raise AssertionError(result.stdout + result.stderr)
        cls.out = json.loads(result.stdout.strip().splitlines()[-1])

    def test_rounds_down_to_the_nearest_ten(self):
        self.assertEqual(self.out["step_2604"], "2600")

    def test_rounds_up_from_five(self):
        self.assertEqual(self.out["step_2605"], "2610")

    def test_rounds_a_jittering_idle_to_one_value(self):
        self.assertEqual(self.out["step_2598"], "2600")

    def test_zero_step_shows_the_value_as_it_is(self):
        self.assertEqual(self.out["none_2605"], "2605")

    def test_unknown_still_shows_the_dash(self):
        self.assertEqual(self.out["unknown"], "—")

    def test_dial_value_is_not_rounded(self):
        self.assertEqual(self.out["unknown_dial_value"], 2605)


if __name__ == "__main__":
    unittest.main()
