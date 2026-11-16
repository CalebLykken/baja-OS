"""Off-Pi tests for the Style preview tiles in Settings > Display > Look: the
picker is a grid of tiles, the tiles are static, follow day/night and
pick their style on a tap. Runs in a subprocess (other modules hold a
QCoreApplication).

    python3 -m unittest tests.test_style_swatches
"""

import json
import os
import re
import subprocess
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
PAGE = (ROOT / "qml/pages/SettingsPage.qml").read_text()


TILE = (ROOT / "qml/components/themes/StyleTile.qml").read_text()


class SwatchSourceTest(unittest.TestCase):
    def test_picker_replaces_joined_control(self):
        self.assertRegex(PAGE, r"StylePicker \{")
        self.assertNotIn("options: Theme.styleNames", PAGE)
        self.assertIn('import "../components/themes"', PAGE)

    def test_tile_has_ring_and_name(self):
        self.assertIn("Rectangle {\n", TILE)
        self.assertIn('objectName: "ring"', TILE)
        self.assertIn('Accessible.name: title + " style"', TILE)

    def test_nothing_moves(self):
        for word in ("Animation", "Behavior", "Timer", "Canvas", "layer.", "ShaderEffect", "Image"):
            self.assertIsNone(re.search(r"\b" + re.escape(word), TILE), word)


try:
    import PyQt6.QtQml  # noqa: F401
except ImportError:
    PyQt6 = None

SCRIPT = r'''
import json, sys
from pathlib import Path
from PyQt6.QtCore import QPointF, QUrl, Qt
from PyQt6.QtGui import QEventPoint, QGuiApplication
from PyQt6.QtQml import QQmlComponent, QQmlEngine

ROOT = Path(sys.argv[1])
app = QGuiApplication(sys.argv)
engine = QQmlEngine()


def make(src):
    component = QQmlComponent(engine)
    component.setData(src.encode(), QUrl.fromLocalFile(str(ROOT / "x.qml")))
    obj = component.create()
    if obj is None:
        print([e.toString() for e in component.errors()])
        sys.exit(1)
    return obj


holder = make('import QtQuick\nimport "qml/components"\nItem { property var th: Theme }')
theme = holder.property("th")
names = list(theme.property("styleNames").toVariant())
styles = theme.property("styles").toVariant()
light = theme.property("lightStyles").toVariant()
out = {"names": names, "dark": {}, "light": {}, "tap": {}, "picked": {}}
out["style_count"] = len(list(styles.keys()))
out["expect_dark"] = {n: styles[n]["bg"] for n in names}
out["expect_light"] = {n: {**styles[n], **light.get(n, {})}["bg"] for n in names}

for n in names:
    sw = make('import QtQuick\nimport "qml/components/themes"\n'
              'StyleTile { styleName: "%s" }' % n)
    theme.setProperty("dark", True)
    out["dark"][n] = sw.property("color").name()
    theme.setProperty("dark", False)
    out["light"][n] = sw.property("color").name()
    theme.setProperty("dark", True)
    theme.setProperty("style", "amber" if n != "amber" else "trail")
    out["picked"][n] = sw.property("picked")
    handlers = [c for c in sw.children() if c.metaObject().className().startswith("QQuickTapHandler")]
    handlers[0].tapped.emit(QEventPoint(0, QEventPoint.State.Released, QPointF(), QPointF()), Qt.MouseButton.LeftButton)
    out["tap"][n] = theme.property("style")

print(json.dumps(out))
'''


@unittest.skipIf(PyQt6 is None, "PyQt6 isn't installed")
class SwatchRuntimeTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        env = dict(os.environ, QT_QPA_PLATFORM="offscreen")
        result = subprocess.run([sys.executable, "-c", SCRIPT, str(ROOT)], cwd=ROOT,
                                capture_output=True, text=True, timeout=60, env=env)
        if result.returncode != 0:
            raise AssertionError(result.stdout + result.stderr)
        cls.out = json.loads(result.stdout.strip().splitlines()[-1])

    def test_one_swatch_per_style(self):
        self.assertEqual(len(self.out["names"]), len(self.out["expect_dark"]))
        self.assertEqual(len(self.out["names"]), self.out["style_count"])

    def test_dark_uses_style_bg(self):
        for n in self.out["names"]:
            self.assertEqual(self.out["dark"][n].lower(), self.out["expect_dark"][n].lower())

    def test_light_uses_light_bg(self):
        for n in self.out["names"]:
            self.assertEqual(self.out["light"][n].lower(), self.out["expect_light"][n].lower())

    def test_not_picked_when_another_style_is_active(self):
        self.assertFalse(any(self.out["picked"].values()))

    def test_tap_picks_style(self):
        for n in self.out["names"]:
            self.assertEqual(self.out["tap"][n], n)


if __name__ == "__main__":
    unittest.main()
