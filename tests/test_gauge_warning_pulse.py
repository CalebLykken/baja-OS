"""Off-Pi tests for the warning cue on qml/components/Gauge.qml: the numeral
eases to the warning colour and pulses once (rate-limited, never while the
gauge is hidden), like the Home readouts. Runs in a subprocess because other
test modules hold a QCoreApplication.

    python3 -m unittest tests.test_gauge_warning_pulse
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
from PyQt6.QtCore import QEventLoop, QObject, QTimer, QUrl
from PyQt6.QtGui import QGuiApplication
from PyQt6.QtQml import QQmlComponent, QQmlEngine

ROOT = Path(sys.argv[1])
app = QGuiApplication(sys.argv)
engine = QQmlEngine()


def make(visible):
    component = QQmlComponent(engine)
    component.setData(
        ('import QtQuick\nimport "qml/components"\n'
         'Item { width: 400; height: 400; property alias g: gauge; '
         'property color warnColor: Theme.warn; '
         'Gauge { id: gauge; anchors.fill: parent; visible: %s; known: true; '
         'value: 50; minValue: 0; maxValue: 100; warnAbove: 80 } }'
         % ("true" if visible else "false")).encode(),
        QUrl.fromLocalFile(str(ROOT / "x.qml")))
    obj = component.create()
    if obj is None:
        print([e.toString() for e in component.errors()])
        sys.exit(1)
    return obj


def wait(ms):
    loop = QEventLoop()
    QTimer.singleShot(ms, loop.quit)
    loop.exec()


def num(obj):
    return obj.findChild(QObject, "gaugeNumber")


out = {}
obj = make(True)
gauge = obj.property("g")
n = num(obj)
wait(50)
out["idle_scale"] = n.property("scale")
gauge.setProperty("value", 90)
wait(120)
out["pulsing_scale"] = n.property("scale")
wait(700)
out["settled_scale"] = n.property("scale")
out["warn_colour"] = n.property("color").name()
out["theme_warn"] = obj.property("warnColor").name()

gauge.setProperty("value", 50)
gauge.setProperty("value", 90)
wait(120)
out["cooldown_scale"] = n.property("scale")

hidden = make(False)
hn = num(hidden)
hidden.property("g").setProperty("value", 90)
wait(120)
out["hidden_scale"] = hn.property("scale")
out["hidden_last_pulse"] = hidden.property("g").property("_lastPulse")

print(json.dumps(out))
'''


class GaugeWarningPulseTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        env = dict(os.environ, QT_QPA_PLATFORM="offscreen")
        result = subprocess.run([sys.executable, "-c", SCRIPT, str(ROOT)], cwd=ROOT,
                                capture_output=True, text=True, timeout=60, env=env)
        if result.returncode != 0:
            raise AssertionError(result.stdout + result.stderr)
        cls.out = json.loads(result.stdout.strip().splitlines()[-1])

    def test_numeral_rests_at_full_size(self):
        self.assertEqual(self.out["idle_scale"], 1)

    def test_crossing_the_limit_pulses_then_settles(self):
        self.assertNotEqual(self.out["pulsing_scale"], 1)
        self.assertEqual(self.out["settled_scale"], 1)

    def test_colour_eases_to_warning(self):
        self.assertEqual(self.out["warn_colour"], self.out["theme_warn"])

    def test_cooldown_holds_off_a_second_pulse(self):
        self.assertEqual(self.out["cooldown_scale"], 1)

    def test_hidden_gauge_does_not_pulse_or_spend_cooldown(self):
        self.assertEqual(self.out["hidden_scale"], 1)
        self.assertEqual(self.out["hidden_last_pulse"], 0)


if __name__ == "__main__":
    unittest.main()
