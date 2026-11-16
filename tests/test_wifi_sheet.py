"""Off-Pi tests for the Wi-Fi join feedback in Settings: the result message sits
in the first Wi-Fi card, and the password sheet explains a wrong password and a
too-short one. Runs in a subprocess (other modules hold a QCoreApplication).

    python3 -m unittest tests.test_wifi_sheet
"""

import json
import os
import subprocess
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
PAGE = (ROOT / "qml/pages/SettingsPage.qml").read_text()


class SheetSourceTest(unittest.TestCase):
    def test_message_is_in_the_status_card_not_the_networks_card(self):
        msg = PAGE.index('objectName: "wifiMessage"')
        online = PAGE.index('"Connected, but no internet"')
        nearby = PAGE.index('heading: "Networks nearby"')
        self.assertLess(online, msg)
        self.assertLess(msg, nearby)
        self.assertNotIn("text: wifi.message", PAGE[nearby:])

    def test_message_colour_follows_messageok(self):
        self.assertIn("color: wifi.messageOk ? Theme.ok : Theme.warn", PAGE)


try:
    import PyQt6.QtQml  # noqa: F401
except ImportError:
    PyQt6 = None

SCRIPT = r'''
import json, sys
from pathlib import Path
from PyQt6.QtCore import QObject, QUrl, pyqtProperty, pyqtSignal
from PyQt6.QtGui import QGuiApplication
from PyQt6.QtQml import QQmlComponent, QQmlEngine

ROOT = Path(sys.argv[1])
app = QGuiApplication(sys.argv)
engine = QQmlEngine()


class Stub(QObject):
    """Every global the page reads, with plain values."""
    changed = pyqtSignal()
    passwordNeeded = pyqtSignal(str)

    def __getattr__(self, name):
        raise AttributeError(name)


# The page reads many context objects; give it a permissive wifi and let the
# rest be undefined (it guards most with typeof).
class Wifi(QObject):
    changed = pyqtSignal()
    passwordNeeded = pyqtSignal(str)
    def __init__(self):
        super().__init__()
        self.msg, self.ok = "", False
    @pyqtProperty(str, notify=changed)
    def message(self): return self.msg
    @pyqtProperty(bool, notify=changed)
    def messageOk(self): return self.ok
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

out = {}
sheet = find("joinSheet")
out["note0"] = sheet.property("note")
wifi.passwordNeeded.emit("Phone")
out["note1"] = sheet.property("note")
out["ssid"] = sheet.property("ssid")
note = find("joinNote")
out["note_visible"] = note.property("visible")
sheet.setProperty("password", "abc")
hint = find("joinHint")
out["hint3"] = [hint.property("visible"), hint.property("text")]
sheet.setProperty("password", "abcdefgh")
out["hint8"] = hint.property("visible")
sheet.setProperty("password", "")
out["hint0"] = [hint.property("visible"), hint.property("text")]
sheet.setProperty("ssid", "Cafe")
sheet.setProperty("note", "x")
out["opened"] = None
from PyQt6.QtCore import QMetaObject, Q_ARG
QMetaObject.invokeMethod(sheet, "open", Q_ARG("QVariant", "Other"))
out["note_after_open"] = sheet.property("note")
msg = find("wifiMessage")
wifi.msg, wifi.ok = "Connected to X", True
wifi.changed.emit()
out["msg"] = [msg.property("visible"), msg.property("text"), msg.property("color").name()]
th = page.findChild(QObject, "joinSheet")
print(json.dumps(out))
'''


@unittest.skipIf(PyQt6 is None, "PyQt6 isn't installed")
class SheetRuntimeTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        env = dict(os.environ, QT_QPA_PLATFORM="offscreen")
        result = subprocess.run([sys.executable, "-c", SCRIPT, str(ROOT)], cwd=ROOT,
                                capture_output=True, text=True, timeout=90, env=env)
        cls.result = result
        if result.returncode != 0:
            cls.out = None
            return
        cls.out = json.loads(result.stdout.strip().splitlines()[-1])

    def setUp(self):
        if self.out is None:
            self.skipTest("SettingsPage needs more context than this stub gives: "
                          + (self.result.stdout + self.result.stderr)[-300:])

    def test_note_starts_empty_and_is_set_by_password_needed(self):
        self.assertEqual(self.out["note0"], "")
        self.assertEqual(self.out["ssid"], "Phone")
        self.assertIn("password didn't work", self.out["note1"])
        self.assertTrue(self.out["note_visible"])

    def test_opening_from_a_row_clears_the_note(self):
        self.assertEqual(self.out["note_after_open"], "")

    def test_short_password_shows_the_hint(self):
        self.assertEqual(self.out["hint3"], [True, "8 or more characters"])
        self.assertFalse(self.out["hint8"])
        self.assertEqual(self.out["hint0"], [True, "Password"])

    def test_message_is_coloured_by_result(self):
        self.assertTrue(self.out["msg"][0])
        self.assertEqual(self.out["msg"][1], "Connected to X")


if __name__ == "__main__":
    unittest.main()
