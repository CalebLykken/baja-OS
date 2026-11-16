"""Off-Pi tests for the reference mark on qml/components/Gauge.qml (the zero
mark on the Boost gauge): markFrac is where markValue sits on the scale, and
-1 when no mark is set. Runs in a subprocess because other test modules hold a
QCoreApplication.

    python3 -m unittest tests.test_gauge_zero_mark
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
from PyQt6.QtCore import QUrl
from PyQt6.QtGui import QGuiApplication
from PyQt6.QtQml import QQmlComponent, QQmlEngine

ROOT = Path(sys.argv[1])
app = QGuiApplication(sys.argv)
engine = QQmlEngine()


def make(props):
    component = QQmlComponent(engine)
    component.setData(
        ('import QtQuick\nimport "qml/components"\n'
         'Gauge { width: 300; height: 300; value: 5; %s }' % props).encode(),
        QUrl.fromLocalFile(str(ROOT / "x.qml")))
    obj = component.create()
    if obj is None:
        print([e.toString() for e in component.errors()])
        sys.exit(1)
    return obj


out = {}
g = make("minValue: -15; maxValue: 20; markValue: 0")
out["boost"] = g.property("markFrac")
g.setProperty("markValue", 40)
out["above"] = g.property("markFrac")
g.setProperty("markValue", -30)
out["below"] = g.property("markFrac")
out["unset"] = make("minValue: -15; maxValue: 20").property("markFrac")
print(json.dumps(out))
'''


class GaugeZeroMarkTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        env = dict(os.environ, QT_QPA_PLATFORM="offscreen")
        result = subprocess.run([sys.executable, "-c", SCRIPT, str(ROOT)], cwd=ROOT,
                                capture_output=True, text=True, timeout=60, env=env)
        if result.returncode != 0:
            raise AssertionError(result.stdout + result.stderr)
        cls.out = json.loads(result.stdout.strip().splitlines()[-1])

    def test_mark_sits_at_zero_of_minus_15_to_20(self):
        self.assertAlmostEqual(self.out["boost"], (0 + 15) / 35)

    def test_mark_outside_the_scale_is_clamped(self):
        self.assertEqual(self.out["above"], 1)
        self.assertEqual(self.out["below"], 0)

    def test_no_mark_is_minus_one(self):
        self.assertEqual(self.out["unset"], -1)


if __name__ == "__main__":
    unittest.main()
