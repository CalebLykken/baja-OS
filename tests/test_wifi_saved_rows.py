"""Off-Pi test for Settings > Wi-Fi's "Saved, not in range" card: a scan that
brings the same names keeps the rows (so a half-done "Forget" stays armed),
and a changed list does rebuild them. Runs in a subprocess (other modules
hold a QCoreApplication).

    python3 -m unittest tests.test_wifi_saved_rows
"""

import json
import os
import subprocess
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent

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
from PyQt6.QtQuick import QQuickItem  # noqa: F401  (gives the items childItems())

ROOT = Path(sys.argv[1])
app = QGuiApplication(sys.argv)
engine = QQmlEngine()


class Wifi(QObject):
    """Just enough of the wifi backend for the page to load."""
    changed = pyqtSignal()
    passwordNeeded = pyqtSignal(str)
    def __init__(self):
        super().__init__()
        self.saved = [{"ssid": "Home"}, {"ssid": "Old hotspot"}]
    @pyqtProperty("QVariantList", notify=changed)
    def savedElsewhere(self): return [dict(s) for s in self.saved]   # a fresh list each time, like the backend
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


def forgets():
    # Repeater rows are visual children, not always QObject children, so walk the items.
    found, todo = [], [page]
    while todo:
        item = todo.pop(0)
        if item.objectName() == "savedForget":
            found.append(item)
        todo.extend(item.childItems())
    return found


out = {}
before = forgets()
out["count"] = len(before)
before[0].setProperty("armed", True)
wifi.changed.emit()                       # a scan with the same names
after = forgets()
out["same_rows"] = [id(a) for a in after] == [id(b) for b in before]
out["still_armed"] = after[0].property("armed")
wifi.saved = [{"ssid": "Home"}]
wifi.changed.emit()                       # one forgotten: the list really changed
out["count_after"] = len([f for f in forgets() if f.property("visible")])
print(json.dumps(out))
'''


@unittest.skipIf(PyQt6 is None, "PyQt6 isn't installed")
class SavedRowsRuntimeTest(unittest.TestCase):
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
            self.fail("SettingsPage didn't load: " + (self.result.stdout + self.result.stderr)[-300:])

    def test_one_row_per_saved_network(self):
        self.assertEqual(self.out["count"], 2)

    def test_a_scan_with_the_same_names_keeps_forget_armed(self):
        self.assertTrue(self.out["same_rows"])
        self.assertTrue(self.out["still_armed"])

    def test_a_changed_list_updates_the_rows(self):
        self.assertEqual(self.out["count_after"], 1)


if __name__ == "__main__":
    unittest.main()
