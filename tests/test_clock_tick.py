"""Off-Pi tests for qml/components/ClockTick.qml, the once-a-minute time behind
the rail clock. Checks the milliseconds to the next minute, that a fresh
ClockTick has a valid time and a single-shot timer, and that Main.qml shows
the time from ClockTick with no 5-second repeating timer left. Runs in a
subprocess because other test modules hold a QCoreApplication.

    python3 -m unittest tests.test_clock_tick
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
TICK = ROOT / "qml" / "components" / "ClockTick.qml"
MAIN = ROOT / "qml" / "Main.qml"

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
    b'import QtQuick\nimport "qml/components"\nQtObject { property var tick: ClockTick { } '
    b'function ms(d) { return tick.msToNextMinute(d) } '
    b'function nowValid() { return tick.now instanceof Date && !isNaN(tick.now.getTime()) } '
    b' }',
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

# (expression, check) where check is a function of the decoded result.
CASES = [
    ("obj.ms(new Date(2026,0,1,12,0,0,0))", lambda v: 60000 <= v <= 60100),  # top of the minute: a full minute
    ("obj.ms(new Date(2026,0,1,12,0,59,500))", lambda v: 1 <= v <= 600),      # half a second before: about 520 ms
    ("obj.ms(new Date(2026,0,1,12,0,59,980))", lambda v: 1 <= v <= 100),      # almost there
    ("obj.ms(new Date(2026,0,1,12,0,30,0))", lambda v: v == 30020),
    ("obj.ms(new Date(2026,0,1,12,0,59,999))", lambda v: 1 <= v <= 100),
    ("obj.ms(new Date(2026,0,1,12,0,0,999))", lambda v: 59000 <= v <= 60100),
    ("obj.nowValid()", lambda v: v is True),
]


class ClockTickTest(unittest.TestCase):
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
        for (expr, check), got in zip(CASES, self.out):
            with self.subTest(expr=expr):
                self.assertTrue(check(got), got)

    def test_exact_value_at_second_30(self):
        # 30 s and 0 ms into the minute: 30 s left, plus the 20 ms margin.
        self.assertEqual(self.out[3], 30020)

    def test_timer_is_single_shot_and_minute_sized(self):
        text = TICK.read_text()
        self.assertNotIn("repeat: true", text)
        self.assertNotIn("5000", text)
        self.assertIn("running: true", text)
        self.assertIn("interval: tick.msToNextMinute(new Date())", text)
        self.assertIn("msToNextMinute(tick.now)", text)

    def test_main_shows_time_from_tick(self):
        text = MAIN.read_text()
        self.assertIn("text: Units.timeText(tick.now)", text)
        self.assertIn("ClockTick { id: tick }", text)
        # The rail's clock Label no longer owns a 5-second repeating timer.
        label = re.search(r"Label \{\s*id: clock\b.*?\n\s*\}", text, re.S)
        self.assertIsNotNone(label)
        self.assertNotIn("Timer", label.group(0))
        self.assertNotIn("5000", label.group(0))
        # The 12/24-hour setting still comes from Settings.
        self.assertIn("Units.clock24 = ", text)


if __name__ == "__main__":
    unittest.main()
