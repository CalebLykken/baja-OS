"""Off-Pi tests for the nav rail's status strip (qml/components/StatusStrip.qml):
each of the four icons follows its own flag and nothing else, and with no
backend objects at all it still loads with every icon unlit.

The QML runs in its own process, like tests/test_nav_button_motion.py.

    python3 -m unittest tests.test_status_strip
"""

import json
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
from PyQt6.QtCore import QObject, QUrl, pyqtProperty, pyqtSignal
from PyQt6.QtGui import QGuiApplication
from PyQt6.QtQml import QQmlComponent, QQmlEngine

app = QGuiApplication(sys.argv)
ROOT = Path.cwd()
with_stubs = sys.argv[1] == "stubs"


def stub(prop, kind, initial):
    class S(QObject):
        changed = pyqtSignal()

        def __init__(self):
            super().__init__()
            self._v = initial

        def get(self):
            return self._v

        def set(self, v):
            self._v = v
            self.changed.emit()
    S.__name__ = prop
    setattr(S, prop, pyqtProperty(kind, S.get, notify=S.changed))
    return S()


engine = QQmlEngine()
stubs = {
    "gps": stub("hasFix", bool, False),
    "bluetooth": stub("deviceName", str, ""),
    "network": stub("online", bool, False),
    "vehicle": stub("live", bool, False),
}
if with_stubs:
    for k, v in stubs.items():
        engine.rootContext().setContextProperty(k, v)
component = QQmlComponent(engine)
component.setData(b'import QtQuick\nimport "qml/components"\nItem { StatusStrip { objectName: "s" } }',
                  QUrl.fromLocalFile(str(ROOT / "x.qml")))
obj = component.create()
if obj is None:
    for error in component.errors():
        print(error.toString(), file=sys.stderr)
    sys.exit(1)
strip = obj.findChild(object, "s")


def snap():
    out = {}
    for n in ("gps", "phone", "wifi", "car"):
        i = obj.findChild(object, n)
        out[n] = [i.property("name"), i.property("color").name(), i.property("opacity")]
    return out


result = {"start": snap()}
if with_stubs:
    for label, key, value in (("gps", "gps", True), ("phone", "bluetooth", "Pixel"),
                              ("wifi", "network", True), ("car", "vehicle", True)):
        stubs[key].set(value)
        result[label] = snap()
        stubs[key].set(False if value is True else "")
print(json.dumps(result))
'''


def run(mode):
    p = subprocess.run([sys.executable, "-c", SCRIPT, mode], cwd=ROOT, capture_output=True, text=True,
                       env={**__import__("os").environ, "QT_QPA_PLATFORM": "offscreen"}, timeout=60)
    if p.returncode:
        raise AssertionError(p.stderr)
    return json.loads(p.stdout.strip().splitlines()[-1])


class StatusStripTest(unittest.TestCase):
    def test_each_flag_moves_only_its_icon(self):
        r = run("stubs")
        start = r["start"]
        self.assertEqual(start["gps"][0], "gps_off")
        self.assertEqual(start["wifi"][0], "wifi_off")
        for n in start:
            self.assertEqual(start[n][2], 0.5)
        for flag in ("gps", "phone", "wifi", "car"):
            for n in start:
                if n == flag:
                    self.assertNotEqual(r[flag][n][1], start[n][1], n)
                    self.assertEqual(r[flag][n][2], 1)
                else:
                    self.assertEqual(r[flag][n], start[n], f"{flag} changed {n}")
        self.assertEqual(r["gps"]["gps"][0], "gps_fixed")
        self.assertEqual(r["wifi"]["wifi"][0], "wifi")

    def test_loads_without_backends(self):
        r = run("none")["start"]
        self.assertEqual(r["gps"][0], "gps_off")
        for n in r:
            self.assertEqual(r[n][2], 0.5)
            self.assertEqual(r[n][1], r["car"][1])


if __name__ == "__main__":
    unittest.main()
