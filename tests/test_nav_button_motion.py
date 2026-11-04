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

    def test_no_idle_cost_constructs(self):
        source = (ROOT / "qml" / "components" / "NavButton.qml").read_text()
        for pattern in (r"\bTimer\b", r"loops:", r"layer\.enabled"):
            self.assertIsNone(re.search(pattern, source), pattern)


if __name__ == "__main__":
    unittest.main()
