"""Off-Pi tests for the distance and duration wording in qml/components/Units.qml.
Runs in a subprocess because other test modules hold a QCoreApplication.

    python3 -m unittest tests.test_units_text
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
exprs = json.loads(sys.argv[2])
app = QGuiApplication(sys.argv)
engine = QQmlEngine()
component = QQmlComponent(engine)
component.setData(
    b'import QtQuick\nimport "qml/components"\nQtObject { function d(m, metric) { Units.metric = metric; return Units.distanceText(m) } function t(s) { return Units.durationText(s) } }',
    QUrl.fromLocalFile(str(ROOT / "x.qml")))
obj = component.create()
if obj is None:
    print([e.toString() for e in component.errors()])
    sys.exit(1)
engine.globalObject().setProperty("obj", engine.newQObject(obj))
result = engine.evaluate("JSON.stringify([" + ",".join(exprs) + "])")
if result.isError():
    print(result.toString())
    sys.exit(1)
print(result.toString())
'''

# (expression, expected text)
IMPERIAL = [
    ("obj.d(0, false)", "50 ft"),          # used to read "0 ft"
    ("obj.d(20, false)", "50 ft"),
    ("obj.d(100, false)", "350 ft"),
    ("obj.d(160, false)", "500 ft"),       # rounds past 500 ft but still under 0.1 mi
    ("obj.d(160.9, false)", "550 ft"),
    ("obj.d(161, false)", "0.1 mi"),
    ("obj.d(300, false)", "0.2 mi"),
    ("obj.d(1609.34, false)", "1.0 mi"),
    ("obj.d(16029.03, false)", "10 mi"),   # 9.96 mi: was "10.0 mi"
    ("obj.d(16045.12, false)", "10 mi"),   # 9.97 mi: was "10.0 mi"
    ("obj.d(15996.84, false)", "9.9 mi"),  # 9.94 mi
    ("obj.d(16093.4, false)", "10 mi"),
    ("obj.d(-1, false)", ""),
]

METRIC = [
    ("obj.d(0, true)", "10 m"),            # used to read "0 m"
    ("obj.d(4, true)", "10 m"),
    ("obj.d(250, true)", "250 m"),
    ("obj.d(994, true)", "990 m"),
    ("obj.d(995, true)", "1.0 km"),        # used to read "1000 m"
    ("obj.d(999, true)", "1.0 km"),
    ("obj.d(1049, true)", "1.0 km"),
    ("obj.d(1500, true)", "1.5 km"),
    ("obj.d(5000, true)", "5.0 km"),
    ("obj.d(9940, true)", "9.9 km"),
    ("obj.d(9950, true)", "10 km"),        # was "10.0 km"
    ("obj.d(9960, true)", "10 km"),
    ("obj.d(12000, true)", "12 km"),
    ("obj.d(-1, true)", ""),
]

DURATION = [
    ("obj.t(0)", "1 min"),
    ("obj.t(30)", "1 min"),
    ("obj.t(1500)", "25 min"),
    ("obj.t(3540)", "59 min"),
    ("obj.t(3570)", "1 h"),                # rounds to 60 min
    ("obj.t(3600)", "1 h"),                # used to read "1 h 0 min"
    ("obj.t(3660)", "1 h 1 min"),
    ("obj.t(5400)", "1 h 30 min"),
    ("obj.t(7200)", "2 h"),
]

CASES = IMPERIAL + METRIC + DURATION


class UnitsTextTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        env = dict(os.environ, QT_QPA_PLATFORM="offscreen")
        exprs = json.dumps([expr for expr, _ in CASES])
        result = subprocess.run([sys.executable, "-c", SCRIPT, str(ROOT), exprs], cwd=ROOT,
                                capture_output=True, text=True, timeout=60, env=env)
        if result.returncode != 0:
            raise AssertionError(result.stdout + result.stderr)
        cls.out = json.loads(result.stdout.strip().splitlines()[-1])

    def test_every_case(self):
        self.assertEqual(len(self.out), len(CASES))
        for (expr, want), got in zip(CASES, self.out):
            with self.subTest(expr=expr):
                self.assertEqual(got, want)


if __name__ == "__main__":
    unittest.main()
