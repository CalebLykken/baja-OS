"""Off-Pi tests for the caps lock bar on the Keyboard shift key. A one-shot
shift (shift 1) only lights the key; caps lock (shift 2) also shows a 4 px
accent bar along its bottom, and the bar is never shown on the number
layers. The static check reads the QML text; the runtime check loads
Keyboard.qml in a child process, sets shift to 0, 1 and 2, and reads the
bar's visibility.

    python3 -m unittest tests.test_keyboard_caps_lock
"""

import json
import os
import re
import subprocess
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
KEYBOARD = (ROOT / "qml/components/Keyboard.qml").read_text()

try:
    import PyQt6.QtQml  # noqa: F401
except ImportError:
    PyQt6 = None
else:
    PyQt6 = True

SCRIPT = r'''
import json, sys
from pathlib import Path
from PyQt6.QtCore import QUrl
from PyQt6.QtGui import QGuiApplication
from PyQt6.QtQml import QQmlComponent, QQmlEngine

ROOT = Path(sys.argv[1])
app = QGuiApplication(sys.argv)
engine = QQmlEngine()
engine.addImportPath(str(ROOT))

component = QQmlComponent(engine)
component.setData(b'import QtQuick\nimport "qml/components"\n'
                  b'Keyboard { width: 640; height: 300 }',
                  QUrl.fromLocalFile(str(ROOT / "x.qml")))
kb = component.create()
if kb is None:
    print([e.toString() for e in component.errors()])
    sys.exit(1)

# Each Key carries its own bar, hidden unless lockBar is set. Only the
# non-repeated keys are children here, so count the visible bars.
bars = kb.findChildren(object, "capsLockBar")
out = {"bars": len(bars), "states": {}}
for shift in (0, 1, 2):
    for mode in (0, 1):
        kb.setProperty("shift", shift)
        kb.setProperty("mode", mode)
        out["states"]["%d-%d" % (shift, mode)] = sum(1 for b in bars if b.property("visible"))
print(json.dumps(out))
'''


class CapsLockSourceTest(unittest.TestCase):
    def test_bar_is_named_and_accent(self):
        self.assertIn('objectName: "capsLockBar"', KEYBOARD)
        self.assertRegex(KEYBOARD, r'objectName: "capsLockBar"[\s\S]*?color: Theme\.accent')

    def test_shift_key_passes_lock_state(self):
        self.assertRegex(KEYBOARD, r"lockBar: kb\.mode === 0 && kb\.shift === 2")

    def test_bar_has_no_animation(self):
        bar = KEYBOARD.split('objectName: "capsLockBar"')[1].split("MouseArea {")[0]
        self.assertNotIn("Behavior", bar)
        self.assertNotIn("Animation", bar)


@unittest.skipIf(PyQt6 is None, "PyQt6 isn't installed")
class CapsLockRuntimeTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        env = dict(os.environ, QT_QPA_PLATFORM="offscreen")
        result = subprocess.run([sys.executable, "-c", SCRIPT, str(ROOT)], cwd=ROOT,
                                capture_output=True, text=True, timeout=60, env=env)
        if result.returncode != 0:
            raise AssertionError(result.stdout + result.stderr)
        cls.out = json.loads(result.stdout.strip().splitlines()[-1])

    def test_bars_exist(self):
        self.assertGreater(self.out["bars"], 0)

    def test_bar_only_for_caps_lock_on_letters(self):
        s = self.out["states"]
        self.assertEqual(s["0-0"], 0)
        self.assertEqual(s["1-0"], 0)
        self.assertEqual(s["2-0"], 1)

    def test_no_bar_on_number_layer(self):
        s = self.out["states"]
        for shift in ("0", "1", "2"):
            self.assertEqual(s[shift + "-1"], 0)


if __name__ == "__main__":
    unittest.main()
