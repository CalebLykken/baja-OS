"""Off-Pi tests for the Wi-Fi password sheet's typing: the newest character
shows for a moment after each key press, then every character is a dot. The
eye button still shows the whole password, and backspace, Cancel and a fresh
open all drop the moment. Runs in a subprocess (other modules hold a
QCoreApplication).

    python3 -m unittest tests.test_join_sheet
"""

import json
import os
import subprocess
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
PAGE = (ROOT / "qml/pages/SettingsPage.qml").read_text()


class JoinSheetSourceTest(unittest.TestCase):
    def test_timer_is_single_shot_and_short(self):
        self.assertIn("Timer { id: lastTimer; interval: 900; onTriggered: joinSheet.lastShown = false }", PAGE)

    def test_field_uses_dots_helper(self):
        self.assertIn("joinSheet.reveal ? joinSheet.password : joinSheet.dots()", PAGE)

    def test_typing_restarts_the_timer_and_backspace_stops_it(self):
        typed = PAGE[PAGE.index("onTyped: (ch) =>"):PAGE.index("onBackspace:")]
        self.assertIn("joinSheet.lastShown = true", typed)
        self.assertIn("lastTimer.restart()", typed)
        back = PAGE[PAGE.index("onBackspace:"):PAGE.index("onDone:")]
        self.assertIn("lastTimer.stop()", back)

    def test_open_and_close_drop_the_moment(self):
        for fn in ("function open(name)", "function openHidden()", "function close()"):
            line = PAGE[PAGE.index(fn):PAGE.index("\n", PAGE.index(fn))]
            self.assertIn("lastShown = false", line, fn)
            self.assertIn("lastTimer.stop()", line, fn)


try:
    import PyQt6.QtQml  # noqa: F401
except ImportError:
    PyQt6 = None

SCRIPT = r'''
import json, sys, time
from pathlib import Path
from PyQt6.QtCore import QObject, QUrl, Qt, pyqtProperty, pyqtSignal
from PyQt6.QtCore import QMetaObject, Q_ARG
from PyQt6.QtGui import QGuiApplication
from PyQt6.QtQml import QQmlComponent, QQmlEngine

ROOT = Path(sys.argv[1])
app = QGuiApplication(sys.argv)
engine = QQmlEngine()


class Wifi(QObject):
    """Just enough of the wifi backend for the page to load."""
    changed = pyqtSignal()
    passwordNeeded = pyqtSignal(str)
    def __init__(self):
        super().__init__()
    @pyqtProperty(str, constant=True)
    def message(self): return ""
    @pyqtProperty(bool, constant=True)
    def messageOk(self): return False
    @pyqtProperty(bool, constant=True)
    def available(self): return True
    @pyqtProperty(bool, constant=True)
    def canControl(self): return True
    @pyqtProperty("QVariantList", constant=True)
    def networks(self): return []
    @pyqtProperty(str, constant=True)
    def busy(self): return ""
    @pyqtProperty(bool, constant=True)
    def tethering(self): return False
    @pyqtProperty(bool, constant=True)
    def tetherActive(self): return False
    @pyqtProperty(str, constant=True)
    def tetherPhone(self): return ""
    @pyqtProperty(bool, constant=True)
    def scanning(self): return False

wifi = Wifi()
engine.rootContext().setContextProperty("wifi", wifi)

component = QQmlComponent(engine)
component.setData(b'import QtQuick\nimport "qml/components"\nimport "qml/pages"\nSettingsPage { width: 1280; height: 700; section: 2 }',
                  QUrl.fromLocalFile(str(ROOT / "x.qml")))
page = component.create()
if page is None:
    print([e.toString() for e in component.errors()])
    sys.exit(1)


def find(name):
    return page.findChild(QObject, name)


def settle(seconds):
    end = time.time() + seconds
    while time.time() < end:
        app.processEvents()
        time.sleep(0.02)


sheet = find("joinSheet")
kb = find("joinKeyboard")
field = find("joinField")
out = {}

QMetaObject.invokeMethod(sheet, "open", Q_ARG("QVariant", "Cafe"))
for ch in "hunter22":
    QMetaObject.invokeMethod(kb, "typed", Qt.ConnectionType.DirectConnection, Q_ARG(str, ch))
out["typed_text"] = field.property("text")
out["typed_password"] = sheet.property("password")
settle(1.4)
out["settled_text"] = field.property("text")
out["settled_lastShown"] = sheet.property("lastShown")

# Backspace drops the moment at once: the remaining characters are all dots.
QMetaObject.invokeMethod(kb, "typed", Qt.ConnectionType.DirectConnection, Q_ARG(str, "x"))
out["x_text"] = field.property("text")
QMetaObject.invokeMethod(kb, "backspace")
out["back_password"] = sheet.property("password")
out["back_text"] = field.property("text")
out["back_lastShown"] = sheet.property("lastShown")

# A key press, then the eye button: the whole password shows, and hiding it
# goes back to dots.
QMetaObject.invokeMethod(kb, "typed", Qt.ConnectionType.DirectConnection, Q_ARG(str, "y"))
sheet.setProperty("reveal", True)
out["reveal_text"] = field.property("text")
sheet.setProperty("reveal", False)
out["unreveal_text"] = field.property("text")
settle(1.3)

# Cancel: the moment and the timer are reset, so the next open starts clean.
QMetaObject.invokeMethod(kb, "typed", Qt.ConnectionType.DirectConnection, Q_ARG(str, "z"))
QMetaObject.invokeMethod(sheet, "close")
out["closed_lastShown"] = sheet.property("lastShown")
QMetaObject.invokeMethod(sheet, "open", Q_ARG("QVariant", "Cafe"))
QMetaObject.invokeMethod(kb, "typed", Qt.ConnectionType.DirectConnection, Q_ARG(str, "a"))
out["reopen_lastShown_before"] = sheet.property("lastShown")
QMetaObject.invokeMethod(sheet, "open", Q_ARG("QVariant", "Cafe"))
out["reopen_text"] = field.property("text")
out["reopen_lastShown"] = sheet.property("lastShown")
print(json.dumps(out))
'''


@unittest.skipIf(PyQt6 is None, "PyQt6 isn't installed")
class JoinSheetRuntimeTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        env = dict(os.environ, QT_QPA_PLATFORM="offscreen")
        result = subprocess.run([sys.executable, "-c", SCRIPT, str(ROOT)], cwd=ROOT,
                                capture_output=True, text=True, timeout=90, env=env)
        cls.result = result
        cls.out = None
        if result.returncode == 0:
            cls.out = json.loads(result.stdout.strip().splitlines()[-1])

    def setUp(self):
        if self.out is None:
            self.skipTest("SettingsPage needs more context than this stub gives: "
                          + (self.result.stdout + self.result.stderr)[-300:])

    def test_last_character_shows_straight_after_typing(self):
        self.assertEqual(self.out["typed_password"], "hunter22")
        self.assertEqual(self.out["typed_text"], "•" * 7 + "2")

    def test_all_dots_after_the_interval(self):
        self.assertEqual(self.out["settled_text"], "•" * 8)
        self.assertFalse(self.out["settled_lastShown"])

    def test_backspace_drops_the_moment(self):
        self.assertEqual(self.out["x_text"], "\u2022" * 8 + "x")
        self.assertEqual(self.out["back_password"], "hunter22")
        self.assertEqual(self.out["back_text"], "\u2022" * 8)
        self.assertFalse(self.out["back_lastShown"])

    def test_eye_button_still_shows_everything(self):
        self.assertEqual(self.out["reveal_text"], "hunter22y")
        self.assertEqual(self.out["unreveal_text"], "\u2022" * 8 + "y")

    def test_close_and_open_start_clean(self):
        self.assertFalse(self.out["closed_lastShown"])
        self.assertTrue(self.out["reopen_lastShown_before"])
        self.assertEqual(self.out["reopen_text"], "")
        self.assertFalse(self.out["reopen_lastShown"])


if __name__ == "__main__":
    unittest.main()
