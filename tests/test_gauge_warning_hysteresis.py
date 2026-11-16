"""Off-Pi tests for the latched warning on qml/components/Gauge.qml: once a
reading goes past its limit the warning stays on until the reading is back
inside by warnMargin, so the numeral's colour doesn't flip on every sample
around a limit. With warnMargin 0 it clears at the limit, as it always did.
Runs in a subprocess because other test modules hold a QCoreApplication.

    python3 -m unittest tests.test_gauge_warning_hysteresis
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


def make(margin, limit):
    component = QQmlComponent(engine)
    component.setData(
        ('import QtQuick\nimport "qml/components"\n'
         'Item { width: 400; height: 400; property alias g: gauge; '
         'property color warnColor: Theme.warn; '
         'Gauge { id: gauge; anchors.fill: parent; known: true; '
         'value: 50; minValue: 0; maxValue: 100; %s; warnMargin: %s } }'
         % (limit, margin)).encode(),
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


def settle(obj, value):
    obj.property("g").setProperty("value", value)
    wait(400)  # the numeral's colour eases over 180 ms
    return {
        "warning": obj.property("g").property("warning"),
        "colour": num(obj).property("color").name(),
    }


out = {}

# High limit (coolant style) with a 5 unit margin.
high = make(5, "warnAbove: 80")
out["theme_warn"] = high.property("warnColor").name()
out["high_start"] = settle(high, 50)
out["high_over"] = settle(high, 90)
out["high_just_inside"] = settle(high, 78)      # 78 > 80 - 5: still warning
out["high_back_over"] = settle(high, 90)        # over again: still warning
out["high_cleared"] = settle(high, 74)          # 74 <= 75: clears
out["high_inside"] = settle(high, 79)           # 79 < 80 but not by the margin of an old warning: stays clear
out["high_over_again"] = settle(high, 81)       # over the limit: warning on

high.property("g").setProperty("known", False)
wait(400)
out["unknown"] = {
    "warning": high.property("g").property("warning"),
    "colour": num(high).property("color").name(),
}
high.property("g").setProperty("known", True)
wait(400)
out["known_again"] = {
    "warning": high.property("g").property("warning"),
    "colour": num(high).property("color").name(),
}

# No margin: a reading at the limit clears, as it always did.
plain = make(0, "warnAbove: 80")
out["plain_over"] = settle(plain, 90)
out["plain_at_limit"] = settle(plain, 80)       # 80 is not beyond 80
out["plain_just_below"] = settle(plain, 79.9)

# Low limit (battery style) with a 0.3 margin.
low = make(0.3, "warnBelow: 10")
out["low_start"] = settle(low, 12)
out["low_under"] = settle(low, 9)
out["low_hover"] = settle(low, 10.2)            # 10.2 < 10 + 0.3: still warning
out["low_cleared"] = settle(low, 10.4)          # clear by the margin: clears
out["low_back_under"] = settle(low, 9.5)
out["low_hover_again"] = settle(low, 10.2)      # latched again: still warning

print(json.dumps(out))
'''


class GaugeWarningHysteresisTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        env = dict(os.environ, QT_QPA_PLATFORM="offscreen")
        result = subprocess.run([sys.executable, "-c", SCRIPT, str(ROOT)], cwd=ROOT,
                                capture_output=True, text=True, timeout=60, env=env)
        if result.returncode != 0:
            raise AssertionError(result.stdout + result.stderr)
        cls.out = json.loads(result.stdout.strip().splitlines()[-1])

    def assertWarn(self, key, on):
        state = self.out[key]
        self.assertEqual(state["warning"], on, key)
        # The numeral follows the latched warning, colour and all.
        if on:
            self.assertEqual(state["colour"], self.out["theme_warn"], key)
        else:
            self.assertNotEqual(state["colour"], self.out["theme_warn"], key)

    def test_high_limit_latches_through_the_margin(self):
        self.assertWarn("high_start", False)
        self.assertWarn("high_over", True)
        self.assertWarn("high_just_inside", True)
        self.assertWarn("high_back_over", True)
        self.assertWarn("high_cleared", False)
        self.assertWarn("high_inside", False)
        self.assertWarn("high_over_again", True)

    def test_unknown_reading_clears_and_known_again_reapplies(self):
        self.assertWarn("unknown", False)
        self.assertWarn("known_again", True)

    def test_zero_margin_clears_at_the_limit(self):
        self.assertWarn("plain_over", True)
        self.assertWarn("plain_at_limit", False)
        self.assertWarn("plain_just_below", False)

    def test_low_limit_latches_through_the_margin(self):
        self.assertWarn("low_start", False)
        self.assertWarn("low_under", True)
        self.assertWarn("low_hover", True)
        self.assertWarn("low_cleared", False)
        self.assertWarn("low_back_under", True)
        self.assertWarn("low_hover_again", True)


if __name__ == "__main__":
    unittest.main()
