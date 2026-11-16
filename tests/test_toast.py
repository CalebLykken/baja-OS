"""Off-Pi tests for qml/components/Toast.qml: hidden until shown, shows the
text, hides at once on hide(), is replaced by a second show() and ends by
itself. Runs in a subprocess because other test modules hold a
QCoreApplication.

    python3 -m unittest tests.test_toast
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
TOAST = ROOT / "qml" / "components" / "Toast.qml"

SCRIPT = r'''
import json, sys
from pathlib import Path
from PyQt6.QtCore import QEventLoop, QTimer, QUrl
from PyQt6.QtGui import QGuiApplication
from PyQt6.QtQml import QQmlComponent, QQmlEngine
from PyQt6.QtQuick import QQuickItem

ROOT = Path(sys.argv[1])
app = QGuiApplication(sys.argv)
engine = QQmlEngine()

QML = """import QtQuick
import QtQuick.Window
import "qml/components"
Window {
    width: 1280; height: 800; visible: true
    Toast { objectName: "t"; holdMs: 600 }
    Toast { objectName: "d" }
    Toast { objectName: "w" }
}
"""

component = QQmlComponent(engine)
component.setData(QML.encode(), QUrl.fromLocalFile(str(ROOT / "x.qml")))
root = component.create()
if root is None:
    print([e.toString() for e in component.errors()])
    sys.exit(1)


def wait(ms):
    loop = QEventLoop()
    QTimer.singleShot(ms, loop.quit)
    loop.exec()


def invoke(item, name, *args):
    from PyQt6.QtCore import QMetaObject, Q_ARG, Qt
    QMetaObject.invokeMethod(item, name, Qt.ConnectionType.DirectConnection,
                             *[Q_ARG("QVariant", a) for a in args])


t = root.findChild(QQuickItem, "t")
d = root.findChild(QQuickItem, "d")
out = {}
wait(50)
out["hidden_visible"] = t.property("visible")
out["hidden_opacity"] = t.property("opacity")
invoke(t, "show", "x", "")
wait(400)
out["shown_visible"] = t.property("visible")
out["shown_text"] = t.property("text")
out["shown_opacity"] = t.property("opacity")
invoke(t, "show", "second", "check")
out["second_text"] = t.property("text")
out["second_icon"] = t.property("icon")
invoke(t, "hide")
out["hide_opacity"] = t.property("opacity")
out["hide_visible"] = t.property("visible")
wait(900)
out["stays_hidden"] = t.property("visible")
invoke(t, "show", "again", "")
wait(300)
out["again_visible"] = t.property("visible")
wait(1500)
out["ended_visible"] = t.property("visible")
out["default_hold"] = d.property("holdMs")
# A 60-character device name (with the "Phone connected: " prefix) stays
# within 520 px, and a short message is no wider than its text.
w = root.findChild(QQuickItem, "w")
long_name = "Caleb's very long phone name that keeps going on and on and!"
invoke(w, "show", "Phone connected: " + long_name, "bluetooth")
wait(50)
out["long_len"] = len(long_name)
out["long_width"] = w.property("width")
out["long_max"] = w.property("maxWidth")
invoke(w, "show", "GPS locked", "gps_fixed")
wait(50)
out["short_width"] = w.property("width")
print(json.dumps(out))
'''


class ToastTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        env = dict(os.environ, QT_QPA_PLATFORM="offscreen")
        result = subprocess.run([sys.executable, "-c", SCRIPT, str(ROOT)], cwd=ROOT,
                                capture_output=True, text=True, timeout=60, env=env)
        if result.returncode != 0:
            raise AssertionError(result.stdout + result.stderr)
        cls.out = json.loads(result.stdout.strip().splitlines()[-1])

    def test_hidden_at_creation(self):
        self.assertFalse(self.out["hidden_visible"])
        self.assertEqual(self.out["hidden_opacity"], 0)

    def test_show_makes_it_visible_with_the_text(self):
        self.assertTrue(self.out["shown_visible"])
        self.assertEqual(self.out["shown_text"], "x")
        self.assertAlmostEqual(self.out["shown_opacity"], 1.0)

    def test_second_show_replaces_the_text_and_icon(self):
        self.assertEqual(self.out["second_text"], "second")
        self.assertEqual(self.out["second_icon"], "check")

    def test_hide_is_immediate_and_stays_hidden(self):
        self.assertEqual(self.out["hide_opacity"], 0)
        self.assertFalse(self.out["hide_visible"])
        self.assertFalse(self.out["stays_hidden"])

    def test_it_hides_itself_after_the_hold(self):
        self.assertTrue(self.out["again_visible"])
        self.assertFalse(self.out["ended_visible"])
        self.assertEqual(self.out["default_hold"], 4000)

    def test_a_long_name_stays_within_520_px(self):
        self.assertEqual(self.out["long_len"], 60)
        self.assertEqual(self.out["long_max"], 520)
        self.assertLessEqual(self.out["long_width"], 520)
        self.assertGreater(self.out["long_width"], 300)

    def test_a_short_message_is_narrower_than_the_cap(self):
        self.assertLess(self.out["short_width"], self.out["long_width"])

    def test_source_has_no_timer_and_takes_no_taps(self):
        src = TOAST.read_text()
        self.assertNotIn("Timer", src)
        self.assertNotIn("running: true", src)
        self.assertNotIn("MouseArea", src)
        self.assertNotIn("loops", src)


MAIN = ROOT / "qml" / "Main.qml"

PHONE_SCRIPT = r'''
import json, sys
from PyQt6.QtCore import QObject, QUrl, pyqtProperty, pyqtSignal
from PyQt6.QtGui import QGuiApplication
from PyQt6.QtQml import QQmlComponent, QQmlEngine


class Bluetooth(QObject):
    changed = pyqtSignal()

    def __init__(self, name):
        super().__init__()
        self._name = name

    @pyqtProperty(str, notify=changed)
    def deviceName(self):
        return self._name

    def set(self, name):
        self._name = name
        self.changed.emit()


app = QGuiApplication(sys.argv)
QML = "import QtQuick\nItem {\n id: root\n property var toasts: []\n" \
      " function notify(t, i) { toasts = toasts.concat([t]) }\n" + sys.argv[1] + "\n}\n"


def run(start, steps):
    engine = QQmlEngine()
    bt = Bluetooth(start)
    engine.rootContext().setContextProperty("bluetooth", bt)
    comp = QQmlComponent(engine)
    comp.setData(QML.encode(), QUrl())
    root = comp.create()
    if root is None:
        print([e.toString() for e in comp.errors()])
        sys.exit(1)
    for name in steps:
        bt.set(name)
    return [str(t) for t in root.property("toasts").toVariant()] \
        if hasattr(root.property("toasts"), "toVariant") else list(root.property("toasts"))


print(json.dumps({
    "first": run("", ["Baja phone"]),
    "later": run("", ["Baja phone", "", "Baja phone", "Baja phone"]),
    "already": run("Baja phone", ["Baja phone", "Renamed"]),
}))
'''


class PhoneAndGpsToasts(unittest.TestCase):
    """Main.qml: the phone's connect and the first GPS lock each get one toast."""

    @classmethod
    def setUpClass(cls):
        cls.src = MAIN.read_text()

    def test_phone_toast_fires_on_connect_only(self):
        body = self.src.split("Connections {\n        target: typeof bluetooth", 1)[1].split("\n    }", 1)[0]
        self.assertIn('root.lastPhone === ""', body)
        self.assertIn('name !== ""', body)
        self.assertIn('root.notify("Phone connected: " + name, "bluetooth")', body)
        self.assertIn("root.lastPhone = name", body)
        self.assertNotIn("disconnect", body.lower())

    def test_gps_toast_is_once_per_run_from_the_receiver(self):
        self.assertIn("property bool gpsLockShown: false", self.src)
        body = self.src.split("Connections {\n        target: typeof gps", 1)[1].split("\n    }", 1)[0]
        self.assertIn("!root.gpsLockShown", body)
        self.assertIn("gps.realFix", body)
        self.assertIn('gps.source === "gps"', body)
        self.assertIn("root.gpsLockShown = true", body)
        self.assertIn('root.notify("GPS locked", "gps_fixed")', body)

    def test_phone_start_is_not_a_binding(self):
        # A binding on deviceName updates before the handler runs, so the
        # handler would see lastPhone already set and never toast.
        self.assertIn('property string lastPhone: ""\n', self.src)
        self.assertNotIn("lastPhone: typeof bluetooth", self.src)

    def test_phone_toast_runs_on_first_connect(self):
        # The real Main.qml block, against a fake bluetooth object.
        start = self.src.index("    property string lastPhone")
        end = self.src.index("    // The GPS finding its first fix")
        block = self.src[start:end]
        result = subprocess.run([sys.executable, "-c", PHONE_SCRIPT, block], cwd=ROOT,
                                capture_output=True, text=True, timeout=60,
                                env=dict(os.environ, QT_QPA_PLATFORM="offscreen"))
        self.assertEqual(result.returncode, 0, result.stderr + result.stdout)
        out = json.loads(result.stdout.strip().splitlines()[-1])
        self.assertEqual(out["first"], ["Phone connected: Baja phone"])
        # A drop-out and reconnect toasts again; a rename while connected doesn't.
        self.assertEqual(out["later"], ["Phone connected: Baja phone"] * 2)
        self.assertEqual(out["already"], [])

    def test_both_go_through_the_toast_gating(self):
        body = self.src.split("function notify", 1)[1].split("}", 1)[0]
        self.assertIn("splash.visible", body)
        self.assertIn("root.onMaps", body)
        self.assertIn("root.routeActive", body)


if __name__ == "__main__":
    unittest.main()
