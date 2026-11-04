"""Off-Pi tests for the level bar's end-stop bump (qml/components/LevelBar.qml):
a one-shot pop of the end segment when the value arrives at full or zero, and
nothing at load, on a repeat, on small moves or while the bar is hidden.

The QML runs in its own process, like tests/test_source_badge.py.

    python3 -m unittest tests.test_level_bar_end_stop
"""

import json
import os
import re
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
from PyQt6.QtCore import QEventLoop, QTimer, QUrl
from PyQt6.QtGui import QGuiApplication
from PyQt6.QtQml import QQmlComponent, QQmlEngine, QQmlExpression

app = QGuiApplication(sys.argv)
ROOT = Path.cwd()


def wait(ms):
    loop = QEventLoop()
    QTimer.singleShot(ms, loop.quit)
    loop.exec()


engine = QQmlEngine()
component = QQmlComponent(engine)
component.setData(b'import QtQuick\nimport "qml/components"\n'
                  b'LevelBar { width: 400; height: 28; value: 1.0; segments: 10 }',
                  QUrl.fromLocalFile(str(ROOT / "x.qml")))
obj = component.create()
if obj is None:
    for error in component.errors():
        print(error.toString(), file=sys.stderr)
    sys.exit(1)


def js(code):
    return QQmlExpression(engine.contextForObject(obj), obj, code).evaluate()[0]


def rest():
    return all(js("popAt(%d)" % i) == 1 for i in range(10))


r = {}
r["a_bumping"] = obj.property("bumping")

obj.setProperty("value", 0.5)
obj.setProperty("value", 0.6)
r["b_bumping"] = obj.property("bumping")

obj.setProperty("value", 1.0)
r["c_bumping"] = obj.property("bumping")
r["c_index"] = obj.property("bumpIndex")
wait(400)
r["c_done"] = obj.property("bumping")
r["c_rest"] = rest()

obj.setProperty("value", 1.0)
r["d_bumping"] = obj.property("bumping")

obj.setProperty("value", 0.3)
wait(50)
obj.setProperty("value", 0.0)
r["e_bumping"] = obj.property("bumping")
r["e_index"] = obj.property("bumpIndex")
wait(400)
r["e_rest"] = rest()

obj.setProperty("value", 0.5)
obj.setProperty("visible", False)
obj.setProperty("value", 1.0)
r["f_bumping"] = obj.property("bumping")

print(json.dumps(r))
sys.stdout.flush()
'''


class LevelBarEndStopTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        result = subprocess.run([sys.executable, "-c", SCRIPT], cwd=ROOT,
                                capture_output=True, text=True, timeout=60,
                                env={**os.environ, "QT_QPA_PLATFORM": "offscreen"})
        cls.stderr = result.stderr
        cls.returncode = result.returncode
        cls.r = json.loads(result.stdout.strip().splitlines()[-1]) if result.returncode == 0 else {}

    def setUp(self):
        self.assertEqual(self.returncode, 0, self.stderr)

    def test_no_bump_at_load(self):
        self.assertFalse(self.r["a_bumping"])

    def test_small_moves_do_not_bump(self):
        self.assertFalse(self.r["b_bumping"])

    def test_reaching_full_bumps_last_segment_then_rests(self):
        self.assertTrue(self.r["c_bumping"])
        self.assertEqual(self.r["c_index"], 9)
        self.assertFalse(self.r["c_done"])
        self.assertTrue(self.r["c_rest"])

    def test_staying_at_full_does_not_bump(self):
        self.assertFalse(self.r["d_bumping"])

    def test_reaching_zero_bumps_first_segment(self):
        self.assertTrue(self.r["e_bumping"])
        self.assertEqual(self.r["e_index"], 0)
        self.assertTrue(self.r["e_rest"])

    def test_hidden_bar_does_not_bump(self):
        self.assertFalse(self.r["f_bumping"])

    def test_source_has_no_timer_loops_or_layers(self):
        src = (ROOT / "qml/components/LevelBar.qml").read_text()
        code = "\n".join(line.split("//")[0] for line in src.splitlines())
        self.assertIsNone(re.search(r"\bTimer\b|loops:|layer\.enabled|Canvas", code))


if __name__ == "__main__":
    unittest.main()
