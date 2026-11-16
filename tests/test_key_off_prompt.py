"""Off-Pi tests for the key-off prompt body (qml/components/KeyOffCountdown.qml)
inside a Prompt, driven by a stub `keyOff` context object: big seconds, a bar
that drains, a warning colour in the last 3 s, hidden when the countdown is -1.
Runs in a subprocess because other test modules hold a QCoreApplication.

    python3 -m unittest tests.test_key_off_prompt
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
from PyQt6.QtCore import QEventLoop, QObject, QTimer, QUrl, pyqtProperty, pyqtSignal
from PyQt6.QtGui import QGuiApplication
from PyQt6.QtQml import QQmlComponent, QQmlEngine
from PyQt6.QtQuick import QQuickItem

ROOT = Path(sys.argv[1])
SHOT = sys.argv[2] if len(sys.argv) > 2 else ""
app = QGuiApplication(sys.argv)
engine = QQmlEngine()


class KeyOff(QObject):
    changed = pyqtSignal()

    def __init__(self):
        super().__init__()
        self._n = 10

    @pyqtProperty(int, notify=changed)
    def countdown(self):
        return self._n

    def set(self, n):
        self._n = n
        self.changed.emit()

    @pyqtProperty(str, constant=True)
    def error(self):
        return ""


stub = KeyOff()
engine.rootContext().setContextProperty("keyOff", stub)

QML = """import QtQuick
import "qml/components"
Item {
    width: 1280; height: 800
    Prompt {
        id: p; objectName: "p"; anchors.fill: parent
        readonly property int secondsLeft: keyOff.countdown
        shown: secondsLeft >= 0
        title: "The truck is off"
        KeyOffCountdown { seconds: p.secondsLeft; total: 10 }
    }
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


def find(name):
    return root.findChild(QQuickItem, name)


def rgba(c):
    return [round(c.red()), round(c.green()), round(c.blue())]


from PyQt6.QtQuick import QQuickWindow
win = QQuickWindow()
win.resize(1280, 800)
root.setParentItem(win.contentItem())

out = {}
theme = engine.singletonInstance("Qt.qmlmodule", "Theme") if False else None
for n in (10, 5, 2, -1):
    stub.set(n)
    wait(400)
    out[str(n)] = {
        "text": find("countNumber").property("text"),
        "value": find("countBar").property("value"),
        "fill": find("countBar").property("fill").name(),
        "visible": find("p").property("visible"),
        "px": find("countNumber").property("font").pixelSize(),
    }
    if SHOT and n in (10, 2):
        stub.set(n)
        wait(100)
        win.show()
        wait(100)
        win.grabWindow().save(SHOT + "-%d.png" % n)
print(json.dumps(out))
'''


class KeyOffPromptTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        env = dict(os.environ, QT_QPA_PLATFORM="offscreen")
        args = [sys.executable, "-c", SCRIPT, str(ROOT)]
        if os.environ.get("KEYOFF_SHOT"):
            args.append(os.environ["KEYOFF_SHOT"])
        result = subprocess.run(args, cwd=ROOT, capture_output=True, text=True,
                                timeout=60, env=env)
        if result.returncode != 0:
            raise AssertionError(result.stdout + result.stderr)
        cls.out = json.loads(result.stdout.strip().splitlines()[-1])

    def test_number_matches_countdown(self):
        for n in (10, 5, 2):
            self.assertEqual(self.out[str(n)]["text"], str(n))

    def test_number_is_huge(self):
        self.assertEqual(self.out["10"]["px"], 88)

    def test_bar_drains_with_countdown(self):
        for n in (10, 5, 2):
            self.assertAlmostEqual(self.out[str(n)]["value"], n / 10)

    def test_fill_warns_in_last_seconds_only(self):
        self.assertNotEqual(self.out["2"]["fill"], self.out["5"]["fill"])
        self.assertEqual(self.out["5"]["fill"], self.out["10"]["fill"])

    def test_nothing_visible_when_off(self):
        self.assertTrue(self.out["10"]["visible"])
        self.assertFalse(self.out["-1"]["visible"])

    def test_main_wires_it_up(self):
        main = (ROOT / "qml" / "Main.qml").read_text()
        self.assertIn("KeyOffCountdown {", main)
        self.assertIn("warnSeconds: 10", main)
        self.assertIn("WARN_S", main)
        self.assertIn("WARN_S = 10.0", (ROOT / "backend" / "ignition.py").read_text())


if __name__ == "__main__":
    unittest.main()
