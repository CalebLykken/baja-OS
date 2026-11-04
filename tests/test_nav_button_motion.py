"""Off-Pi tests for the nav rail entry's one-shot motion (qml/components/
NavButton.qml): the marker grows in and the icon pops when the entry becomes
active, nothing animates at load, and everything settles by itself.

The QML runs in its own process, like tests/test_source_badge.py.

    python3 -m unittest tests.test_nav_button_motion
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
from PyQt6.QtQml import QQmlComponent, QQmlEngine

app = QGuiApplication(sys.argv)
ROOT = Path.cwd()


def wait(ms):
    loop = QEventLoop()
    QTimer.singleShot(ms, loop.quit)
    loop.exec()


engine = QQmlEngine()
component = QQmlComponent(engine)
component.setData(b'import QtQuick\nimport "qml/components"\n'
                  b'Item { width: 112; height: 400; '
                  b'NavButton { objectName: "nb"; icon: "home"; label: "HOME"; active: true } }',
                  QUrl.fromLocalFile(str(ROOT / "x.qml")))
obj = component.create()
if obj is None:
    for error in component.errors():
        print(error.toString(), file=sys.stderr)
    sys.exit(1)
nb = obj.findChild(object, "nb")


def snap(prefix, r):
    r[prefix + "_marker"] = nb.property("markerHeight")
    r[prefix + "_card"] = nb.property("cardHeight")
    r[prefix + "_scale"] = nb.property("glyphScale")
    r[prefix + "_pop"] = nb.property("popRunning")


r = {}
snap("load", r)
wait(60)
snap("load60", r)
nb.setProperty("active", False)
wait(300)
snap("off", r)
nb.setProperty("active", True)
wait(40)
snap("on40", r)
wait(400)
snap("on400", r)
print(json.dumps(r))
sys.stdout.flush()
'''

PRESS_SCRIPT = r'''
import json, sys, time
from pathlib import Path
from PyQt6.QtCore import QPoint, Qt, QUrl
from PyQt6.QtGui import QGuiApplication
from PyQt6.QtQuick import QQuickView
from PyQt6.QtTest import QTest

app = QGuiApplication(sys.argv[:1])
ROOT = Path.cwd()
view = QQuickView()
view.setResizeMode(QQuickView.ResizeMode.SizeRootObjectToView)
view.setSource(QUrl.fromLocalFile(str(ROOT / "qml" / "components" / "NavButton.qml")))
view.resize(112, 96)
view.show()
deadline = time.monotonic() + 10
while not view.isExposed() and time.monotonic() < deadline:
    app.processEvents()
    time.sleep(0.01)
nb = view.rootObject()
if nb is None:
    print(json.dumps({"error": "NavButton did not load"}))
    sys.exit(0)
centre = QPoint(56, 48)


def sample(ms):
    values = []
    end = time.monotonic() + ms / 1000.0
    while time.monotonic() < end:
        app.processEvents()
        values.append(float(nb.property("cardScale")))
        time.sleep(0.002)
    return values


press, release = [], []
for _ in range(2):
    QTest.mousePress(view, Qt.MouseButton.LeftButton, Qt.KeyboardModifier.NoModifier, centre)
    press += sample(250)
    QTest.mouseRelease(view, Qt.MouseButton.LeftButton, Qt.KeyboardModifier.NoModifier, centre)
    release += sample(250)
print(json.dumps({"press_min": min(press), "release_max": max(release)}))
sys.stdout.flush()
'''


class NavButtonMotionTest(unittest.TestCase):
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

    def test_load_does_not_animate(self):
        for key in ("load", "load60"):
            self.assertAlmostEqual(self.r[key + "_marker"], self.r[key + "_card"] * 0.5, places=3)
            self.assertFalse(self.r[key + "_pop"])
            self.assertEqual(self.r[key + "_scale"], 1.0)

    def test_deactivating_removes_marker_and_resets_icon(self):
        self.assertEqual(self.r["off_marker"], 0)
        self.assertEqual(self.r["off_scale"], 1.0)
        self.assertFalse(self.r["off_pop"])

    def test_activating_pops_then_settles(self):
        self.assertTrue(self.r["on40_pop"] or self.r["on40_scale"] > 1.0)
        self.assertAlmostEqual(self.r["on400_scale"], 1.0, delta=1e-3)
        self.assertAlmostEqual(self.r["on400_marker"], self.r["on400_card"] * 0.5, places=3)
        self.assertFalse(self.r["on400_pop"])

    def test_press_dips_shallowly_and_release_springs_past_rest(self):
        result = subprocess.run([sys.executable, "-c", PRESS_SCRIPT], cwd=ROOT,
                                capture_output=True, text=True, timeout=120,
                                env={**os.environ, "QT_QPA_PLATFORM": "offscreen"})
        self.assertEqual(result.returncode, 0, result.stderr)
        data = json.loads(result.stdout.strip().splitlines()[-1])
        self.assertNotIn("error", data, data.get("error"))
        # The press runs the 70 ms OutQuad dip: it moves and never undershoots 0.97.
        self.assertLess(data["press_min"], 1.0)
        self.assertGreaterEqual(data["press_min"], 0.97 - 1e-3)
        # The release runs the 180 ms OutBack spring, which crosses 1.0.
        self.assertGreater(data["release_max"], 1.001)

    def test_press_timing_is_keyed_on_the_behaviors_target(self):
        source = (ROOT / "qml" / "components" / "NavButton.qml").read_text()
        self.assertIn("id: pressSpring", source)
        self.assertIn("pressSpring.targetValue < 1 ? 70 : 180", source)
        self.assertIn("easing.overshoot: 2.5", source)

    def test_no_idle_cost_constructs(self):
        source = (ROOT / "qml" / "components" / "NavButton.qml").read_text()
        for pattern in (r"\bTimer\b", r"loops:", r"layer\.enabled"):
            self.assertIsNone(re.search(pattern, source), pattern)


if __name__ == "__main__":
    unittest.main()
