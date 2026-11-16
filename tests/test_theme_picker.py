"""Off-Pi tests for the Style picker: ten themes wrap onto two rows inside the
card, every tile is a big enough touch target, and the picker is static. Runs
in a subprocess (other modules hold a QCoreApplication).

    python3 -m unittest tests.test_theme_picker
"""

import json
import os
import re
import subprocess
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
THEMES = ROOT / "qml/components/themes"

try:
    import PyQt6.QtQml  # noqa: F401
except ImportError:
    PyQt6 = None

SCRIPT = r'''
import json, sys
from pathlib import Path
from PyQt6.QtCore import QUrl
from PyQt6.QtGui import QGuiApplication
from PyQt6.QtQml import QQmlComponent, QQmlEngine

ROOT = Path(sys.argv[1])
app = QGuiApplication(sys.argv)
engine = QQmlEngine()
component = QQmlComponent(engine)
component.setData(b"""import QtQuick
import "qml/components"
import "qml/components/themes"
Item {
    width: 828; height: 600
    property alias picker: p
    property int gap: Theme.gap
    property var geo: []
    function walk(item, out) {
        for (var i = 0; i < item.children.length; i++) {
            var c = item.children[i]
            if (c.objectName && c.objectName.indexOf("tile_") === 0) {
                var pt = c.mapToItem(p, 0, 0)
                out.push([pt.x, pt.y, c.width, c.height])
            }
            walk(c, out)
        }
        return out
    }
    Component.onCompleted: geo = walk(p, [])
    StylePicker {
        id: p
        width: parent.width
        model: ["amber", "cluster", "trail", "rally", "atlantic",
                "amber", "cluster", "trail", "rally", "atlantic"]
    }
}""", QUrl.fromLocalFile(str(ROOT / "x.qml")))
root = component.create()
if root is None:
    print([e.toString() for e in component.errors()])
    sys.exit(1)
picker = root.property("picker")
print(json.dumps({
    "height": picker.property("height"),
    "gap": root.property("gap"),
    "tiles": root.property("geo").toVariant(),
    "width": picker.property("width"),
}))
'''


@unittest.skipIf(PyQt6 is None, "PyQt6 isn't installed")
class PickerLayoutTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        env = dict(os.environ, QT_QPA_PLATFORM="offscreen")
        result = subprocess.run([sys.executable, "-c", SCRIPT, str(ROOT)], cwd=ROOT,
                                capture_output=True, text=True, timeout=60, env=env)
        if result.returncode != 0:
            raise AssertionError(result.stdout + result.stderr)
        cls.out = json.loads(result.stdout.strip().splitlines()[-1])

    def test_ten_tiles(self):
        self.assertEqual(len(self.out["tiles"]), 10)

    def test_two_rows(self):
        # Two rows of tiles, the gaps, and the heading line above them.
        self.assertLess(self.out["height"], 2 * 112 + 3 * self.out["gap"] + 40)
        self.assertEqual(len({round(t[1]) for t in self.out["tiles"]}), 2)

    def test_tiles_inside_width(self):
        for x, _, w, _ in self.out["tiles"]:
            self.assertGreaterEqual(x, 0)
            self.assertLessEqual(x + w, self.out["width"])

    def test_touch_targets(self):
        for _, _, w, h in self.out["tiles"]:
            self.assertGreaterEqual(h, 56)
            self.assertGreaterEqual(w, 56)


class PickerSourceTest(unittest.TestCase):
    def test_nothing_moves(self):
        for name in ("StylePicker.qml", "StyleTile.qml"):
            text = (THEMES / name).read_text()
            for word in ("Timer", "Animation", "Behavior", "Canvas"):
                self.assertIsNone(re.search(r"\b" + word, text), (name, word))

    def test_qmldir(self):
        text = (THEMES / "qmldir").read_text()
        self.assertIn("StylePicker 1.0 StylePicker.qml", text)
        self.assertIn("StyleTile 1.0 StyleTile.qml", text)


if __name__ == "__main__":
    unittest.main()
