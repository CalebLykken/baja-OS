"""Off-Pi tests for qml/components/IdleReturn.qml: emits idle() once after the
timeout while active, poke() delays it, and inactive never emits. Runs in a
subprocess because other test modules hold a QCoreApplication.

    python3 -m unittest tests.test_idle_return
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
IDLE = ROOT / "qml" / "components" / "IdleReturn.qml"

SCRIPT = r'''
import json, sys
from pathlib import Path
from PyQt6.QtCore import QEventLoop, QMetaObject, Qt, QTimer, QUrl
from PyQt6.QtGui import QGuiApplication
from PyQt6.QtQml import QQmlComponent, QQmlEngine

ROOT = Path(sys.argv[1])
app = QGuiApplication(sys.argv)
engine = QQmlEngine()

QML = """import QtQuick
import "qml/components"
Item {
    width: 400; height: 300
    property int a: 0
    property int b: 0
    property int c: 0
    IdleReturn { objectName: "a"; active: true; timeout: 60; onIdle: parent.a++ }
    IdleReturn { objectName: "b"; active: true; timeout: 120; onIdle: parent.b++ }
    IdleReturn { objectName: "c"; active: false; timeout: 60; onIdle: parent.c++ }
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


from PyQt6.QtQuick import QQuickItem
b = root.findChildren(QQuickItem)
by = {i.objectName(): i for i in b if i.objectName()}
out = {}
wait(30)
by["b"].metaObject()  # keep a reference
QMetaObject.invokeMethod(by["b"], "poke", Qt.ConnectionType.DirectConnection)
wait(110)   # a fired at 60; b was poked at 30 so would fire at 150
out["a_once"] = root.property("a")
out["b_delayed"] = root.property("b")
wait(150)
out["b_fired"] = root.property("b")
out["a_after"] = root.property("a")
out["c"] = root.property("c")
print(json.dumps(out))
'''


class IdleReturnTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        env = dict(os.environ, QT_QPA_PLATFORM="offscreen")
        result = subprocess.run([sys.executable, "-c", SCRIPT, str(ROOT)], cwd=ROOT,
                                capture_output=True, text=True, timeout=60, env=env)
        if result.returncode != 0:
            raise AssertionError(result.stdout + result.stderr)
        cls.out = json.loads(result.stdout.strip().splitlines()[-1])

    def test_active_emits_idle_once(self):
        self.assertEqual(self.out["a_once"], 1)
        self.assertEqual(self.out["a_after"], 1)

    def test_poke_delays_it(self):
        self.assertEqual(self.out["b_delayed"], 0)
        self.assertEqual(self.out["b_fired"], 1)

    def test_inactive_never_emits(self):
        self.assertEqual(self.out["c"], 0)

    def test_source_shape(self):
        src = IDLE.read_text()
        self.assertIn("PointHandler", src)
        self.assertRegex(src, r"Timer\s*\{[^}]*running:\s*root\.active")
        self.assertNotIn("repeat: true", src)

    def test_main_uses_it_on_settings_and_truck_only(self):
        main = (ROOT / "qml" / "Main.qml").read_text()
        self.assertRegex(main, r"IdleReturn\s*\{[^}]*root\.page === 4 \|\| root\.page === 5")


if __name__ == "__main__":
    unittest.main()
