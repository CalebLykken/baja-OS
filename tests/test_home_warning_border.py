"""Off-Pi tests for the Home readout strip's warning border (qml/pages/HomePage.qml):
the Card holding Boost, Coolant, Battery and Speed gets a steady Ember border
while the vehicle reports any warning, and goes back to the plain line colour
when they clear. The colour eases over 180 ms, so the tests pump the event
loop before reading it.

The QML runs in its own process, like tests/test_home_status.py, so the
QCoreApplication other test modules create at import time doesn't get in the way.

    python3 -m unittest tests.test_home_warning_border
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
import json, sys, time
from pathlib import Path
from PyQt6.QtCore import QObject, QUrl, pyqtProperty, pyqtSignal
from PyQt6.QtGui import QGuiApplication
from PyQt6.QtQml import QQmlComponent, QQmlEngine, QQmlExpression
from PyQt6.QtQuick import QQuickWindow

app = QGuiApplication(sys.argv)
ROOT = Path.cwd()


class Vehicle(QObject):
    changed = pyqtSignal()

    def __init__(self):
        super().__init__()
        self._warnings = []

    @pyqtProperty(bool, notify=changed)
    def engineKnown(self):
        return False

    @pyqtProperty(bool, notify=changed)
    def simulated(self):
        return True

    @pyqtProperty(bool, notify=changed)
    def live(self):
        return False

    @pyqtProperty(bool, notify=changed)
    def speedKnown(self):
        return False

    @pyqtProperty(bool, notify=changed)
    def voltageKnown(self):
        return False

    @pyqtProperty(float, notify=changed)
    def voltage(self):
        return 0.0

    @pyqtProperty(float, notify=changed)
    def speed(self):
        return 0.0

    @pyqtProperty(float, notify=changed)
    def boost(self):
        return 0.0

    @pyqtProperty(float, notify=changed)
    def coolant(self):
        return 0.0

    @pyqtProperty(list, notify=changed)
    def warnings(self):
        return self._warnings

    def set(self, warnings):
        self._warnings = list(warnings)
        self.changed.emit()


def settle(ms=400):
    # The colour eases over 180 ms, so pump the event loop past it before reading.
    end = time.time() + ms / 1000
    while time.time() < end:
        app.processEvents()
        time.sleep(0.01)


engine = QQmlEngine()
vehicle = Vehicle()
engine.rootContext().setContextProperty("vehicle", vehicle)

# The plain and Ember colours come from the same Theme singleton the page uses.
holder = QQmlComponent(engine)
holder.setData(b'import QtQuick\nimport "components"\nQtObject { property color line: Theme.line; property color warn: Theme.warn }',
               QUrl.fromLocalFile(str(ROOT / "qml" / "probe.qml")))
probe = holder.create()
if probe is None:
    for error in holder.errors():
        print(error.toString(), file=sys.stderr)
    sys.exit(1)

component = QQmlComponent(engine, QUrl.fromLocalFile(str(ROOT / "qml" / "pages" / "HomePage.qml")))
page = component.create()
if page is None:
    for error in component.errors():
        print(error.toString(), file=sys.stderr)
    sys.exit(1)
# A page with no window is never visible; put it in one so visible means something.
window = QQuickWindow()
page.setParentItem(window.contentItem())


def evaluate(scope, expression):
    # Grouped properties such as border.color aren't reachable with property(),
    # so read them with a QML expression. It returns (value, hadError).
    value, failed = QQmlExpression(engine.rootContext(), scope, expression).evaluate()
    if failed:
        raise RuntimeError("expression failed: " + expression)
    return value


def strip_border():
    card = page.findChild(QObject, "homeReadoutCard")
    return [evaluate(card, "String(border.color)"), evaluate(card, "border.width")]


results = {"line": evaluate(probe, "String(line)"), "warn": evaluate(probe, "String(warn)")}
for name, warnings in [
    ("none", []),
    ("coolant", ["coolant"]),
    ("mil", ["mil"]),
    ("cleared", []),
]:
    vehicle.set(warnings)
    settle()
    results[name] = strip_border()

# While Home is hidden the strip reads nothing, so a warning raised then shows
# only once the page is back on screen.
page.setProperty("visible", False)
vehicle.set(["coolant"])
settle()
results["hidden"] = strip_border()
page.setProperty("visible", True)
settle()
results["shown"] = strip_border()

print(json.dumps(results))
sys.stdout.flush()
'''


class HomeWarningBorderTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        result = subprocess.run([sys.executable, "-c", SCRIPT], cwd=ROOT,
                                capture_output=True, text=True, timeout=60,
                                env={**os.environ, "QT_QPA_PLATFORM": "offscreen"})
        cls.stderr = result.stderr
        cls.returncode = result.returncode
        cls.results = json.loads(result.stdout.strip().splitlines()[-1]) if result.returncode == 0 else {}

    def setUp(self):
        self.assertEqual(self.returncode, 0, self.stderr)

    def test_plain_line_colour_with_no_warnings(self):
        self.assertEqual(self.results["none"][0], self.results["line"])

    def test_coolant_warning_turns_the_border_ember(self):
        self.assertEqual(self.results["coolant"][0], self.results["warn"])

    def test_mil_warning_turns_the_border_ember(self):
        self.assertEqual(self.results["mil"][0], self.results["warn"])

    def test_border_goes_back_to_plain_when_cleared(self):
        self.assertEqual(self.results["cleared"][0], self.results["line"])

    def test_ember_border_is_one_pixel_wider(self):
        self.assertEqual(self.results["mil"][1], self.results["none"][1] + 1)

    def test_hidden_page_leaves_the_border_until_shown(self):
        self.assertEqual(self.results["hidden"][0], self.results["line"])
        self.assertEqual(self.results["shown"][0], self.results["warn"])


if __name__ == "__main__":
    unittest.main()
