"""Off-Pi tests for qml/components/PageHost.qml: the outgoing page leaves
quickly, the incoming one settles into place, and lazy pages still build.
Runs in a subprocess because other test modules hold a QCoreApplication.

    python3 -m unittest tests.test_page_host
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
from PyQt6.QtCore import QEventLoop, QObject, QTimer, QUrl
from PyQt6.QtGui import QGuiApplication
from PyQt6.QtQml import QQmlComponent, QQmlEngine
from PyQt6.QtQuick import QQuickItem

ROOT = Path(sys.argv[1])
app = QGuiApplication(sys.argv)
engine = QQmlEngine()

QML = """import QtQuick
import "qml/components"
Item {
    width: 400; height: 300
    property int cur: 0
    PageHost { objectName: "a"; anchors.fill: parent; index: 0; current: parent.cur
        Rectangle { anchors.fill: parent } }
    PageHost { objectName: "b"; anchors.fill: parent; index: 1; current: parent.cur
        Rectangle { anchors.fill: parent } }
    PageHost { objectName: "c"; anchors.fill: parent; index: 2; current: parent.cur
        lazy: Component { Rectangle { objectName: "built" } } }
}
"""


def make():
    component = QQmlComponent(engine)
    component.setData(QML.encode(), QUrl.fromLocalFile(str(ROOT / "x.qml")))
    obj = component.create()
    if obj is None:
        print([e.toString() for e in component.errors()])
        sys.exit(1)
    return obj


def wait(ms):
    loop = QEventLoop()
    QTimer.singleShot(ms, loop.quit)
    loop.exec()


def state(root, name):
    host = root.findChild(QQuickItem, name)
    holder = host.childItems()[0]
    return {"opacity": host.property("opacity"), "visible": host.property("visible"),
            "x": holder.property("x")}


out = {}
root = make()
out["init_a"] = state(root, "a")
out["init_b"] = state(root, "b")

root.setProperty("cur", 1)
xs = []
t0 = time.monotonic()
for _ in range(45):
    wait(10)
    xs.append(state(root, "b")["x"])
    if "mid_a" not in out and time.monotonic() - t0 >= 0.2:
        out["mid_elapsed"] = time.monotonic() - t0
        out["mid_a"] = state(root, "a")
        out["mid_b"] = state(root, "b")
wait(100)
out["end_a"] = state(root, "a")
out["end_b"] = state(root, "b")
out["min_x"] = min(xs)

# Reverse transition (1 -> 0): a comes in from -40, b leaves toward +40.
def sample(inc, outg, key):
    xi, xo = [], []
    t0 = time.monotonic()
    while time.monotonic() - t0 < 0.45:
        wait(10)
        xi.append(state(root, inc)["x"])
        xo.append(state(root, outg)["x"])
        if key + "_out" not in out and time.monotonic() - t0 >= 0.2:
            out[key + "_out"] = state(root, outg)
    out[key + "_in_x"] = xi
    out[key + "_out_x"] = xo

root.setProperty("cur", 0)
sample("a", "b", "rev")
# Second forward transition (0 -> 1).
root.setProperty("cur", 1)
sample("b", "a", "fwd2")

# Switch back mid-animation.
root.setProperty("cur", 0)
wait(100)
root.setProperty("cur", 1)
wait(60)
root.setProperty("cur", 0)
wait(450)
out["back_a"] = state(root, "a")
out["back_b"] = state(root, "b")

# built: true for a child page, false for a lazy one until it is loaded.
out["built_plain"] = root.findChild(QQuickItem, "a").property("built")
out["built_before"] = root.findChild(QQuickItem, "c").property("built")
out["lazy_before"] = root.findChild(QObject, "built") is not None
root.setProperty("cur", 2)
wait(100)
out["lazy_after"] = root.findChild(QObject, "built") is not None
out["built_after"] = root.findChild(QQuickItem, "c").property("built")

print(json.dumps(out))
'''


class PageHostTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        env = dict(os.environ, QT_QPA_PLATFORM="offscreen")
        result = subprocess.run([sys.executable, "-c", SCRIPT, str(ROOT)], cwd=ROOT,
                                capture_output=True, text=True, timeout=60, env=env)
        if result.returncode != 0:
            raise AssertionError(result.stdout + result.stderr)
        cls.out = json.loads(result.stdout.strip().splitlines()[-1])

    def test_initial_state_has_no_animation(self):
        a, b = self.out["init_a"], self.out["init_b"]
        self.assertEqual((a["opacity"], a["visible"], a["x"]), (1, True, 0))
        self.assertEqual((b["opacity"], b["visible"]), (0, False))

    def test_outgoing_page_is_gone_before_incoming_finishes(self):
        a, b = self.out["mid_a"], self.out["mid_b"]
        self.assertEqual(a["opacity"], 0)
        self.assertFalse(a["visible"])
        self.assertTrue(b["visible"])
        if self.out["mid_elapsed"] < 0.235:
            self.assertLess(b["opacity"], 1)

    def test_incoming_page_settles_exactly(self):
        b = self.out["end_b"]
        self.assertEqual(b["opacity"], 1)
        self.assertEqual(b["x"], 0)
        self.assertFalse(self.out["end_a"]["visible"])

    def test_overshoot_is_small(self):
        self.assertGreaterEqual(self.out["min_x"], -8)

    def test_reverse_and_second_forward_transitions_keep_timing(self):
        for key, sign in (("rev", 1), ("fwd2", -1)):
            outgoing = self.out[key + "_out"]
            self.assertEqual(outgoing["opacity"], 0, key)
            self.assertFalse(outgoing["visible"], key)
            xi = self.out[key + "_in_x"]
            self.assertEqual(xi[-1], 0, key)
            # Overshoot goes past 0 in the direction of travel, by under 8 px.
            # rev: from -40, so positive; fwd2: from +40, so negative.
            past = max(sign * x for x in xi)
            self.assertGreater(past, 0, key)
            self.assertLess(past, 8, key)

    def test_outgoing_page_never_overshoots(self):
        for key in ("rev", "fwd2"):
            for x in self.out[key + "_out_x"]:
                self.assertLessEqual(abs(x), 40, key)

    def test_switching_back_mid_animation_restores_first_page(self):
        a, b = self.out["back_a"], self.out["back_b"]
        self.assertEqual((a["opacity"], a["visible"], a["x"]), (1, True, 0))
        self.assertFalse(b["visible"])

    def test_lazy_page_builds_when_first_shown(self):
        self.assertFalse(self.out["lazy_before"])
        self.assertTrue(self.out["lazy_after"])

    def test_built_reports_whether_the_page_exists(self):
        self.assertTrue(self.out["built_plain"])
        self.assertFalse(self.out["built_before"])
        self.assertTrue(self.out["built_after"])

    def test_main_chains_preloads_without_fixed_timers(self):
        text = (ROOT / "qml" / "Main.qml").read_text()
        # The clock's own 5 s repeating timer is the only one allowed to repeat.
        text = text.replace("Timer { interval: 5000; running: true; repeat: true; onTriggered: clock.now", "")
        for ms in ("4000", "5000", "7000"):
            self.assertNotIn("interval: " + ms, text)
        self.assertEqual(text.count("interval: 6000"), 1)   # the Music fallback
        self.assertNotIn("repeat: true", text)
        for host in ("musicHost", "settingsHost", "gaugesHost"):
            self.assertIn("id: " + host, text)
        self.assertIn("onBuiltChanged", text)


if __name__ == "__main__":
    unittest.main()
