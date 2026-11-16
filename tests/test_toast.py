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
import "qml/components"
Item {
    width: 1280; height: 800
    Toast { objectName: "t"; holdMs: 600 }
    Toast { objectName: "d" }
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

    def test_source_has_no_timer_and_takes_no_taps(self):
        src = TOAST.read_text()
        self.assertNotIn("Timer", src)
        self.assertNotIn("running: true", src)
        self.assertNotIn("MouseArea", src)
        self.assertNotIn("loops", src)


if __name__ == "__main__":
    unittest.main()
