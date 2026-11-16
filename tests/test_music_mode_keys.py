"""Off-Pi tests for the Playing page's mode keys (qml/pages/MusicPage.qml):
Shuffle, Repeat and the EQ key each say what they do, and show on or off by
a filled key. The page runs in its own process with a fake media and eq.

    python3 -m unittest tests.test_music_mode_keys
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
from PyQt6.QtCore import QObject, QUrl, pyqtProperty, pyqtSignal, pyqtSlot
from PyQt6.QtGui import QGuiApplication
from PyQt6.QtQml import QQmlComponent, QQmlEngine

app = QGuiApplication(sys.argv)
ROOT = Path.cwd()


class Media(QObject):
    changed = pyqtSignal()

    def __init__(self):
        super().__init__()
        self._repeat = "off"
        self._shuffle = False

    @pyqtProperty(str, notify=changed)
    def source(self):
        return "local"

    @pyqtProperty(str, notify=changed)
    def title(self):
        return "Song"

    @pyqtProperty(bool, notify=changed)
    def hasModes(self):
        return True

    @pyqtProperty(bool, notify=changed)
    def shuffle(self):
        return self._shuffle

    @pyqtProperty(str, notify=changed)
    def repeat(self):
        return self._repeat

    def set(self, shuffle, repeat):
        self._shuffle, self._repeat = shuffle, repeat
        self.changed.emit()


class Eq(QObject):
    changed = pyqtSignal()

    def __init__(self):
        super().__init__()
        self._preset = "Flat"

    @pyqtProperty(str, notify=changed)
    def preset(self):
        return self._preset

    def set(self, preset):
        self._preset = preset
        self.changed.emit()


media, eq = Media(), Eq()
engine = QQmlEngine()
engine.rootContext().setContextProperty("media", media)
engine.rootContext().setContextProperty("eq", eq)
component = QQmlComponent(engine, QUrl.fromLocalFile(str(ROOT / "qml/pages/MusicPage.qml")))
obj = component.create()
if obj is None:
    for error in component.errors():
        print(error.toString(), file=sys.stderr)
    sys.exit(1)


def key(name):
    k = obj.findChild(QObject, name)
    label = k.findChild(QObject, "modeKeyLabel")
    return {"text": label.property("text"), "active": k.property("active"),
            "icon": k.property("icon"), "visible": k.property("visible"),
            "height": k.property("height")}


results = {}
for name, shuffle, repeat, preset in (
        ("off", False, "off", "Flat"), ("one", True, "one", "Road"),
        ("all", False, "all", "Custom")):
    media.set(shuffle, repeat)
    eq.set(preset)
    results[name] = {k: key(k) for k in ("shuffleKey", "repeatKey", "eqKey")}
print(json.dumps(results))
sys.stdout.flush()
'''


class ModeKeysTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        result = subprocess.run([sys.executable, "-c", SCRIPT], cwd=ROOT,
                                capture_output=True, text=True, timeout=60,
                                env={**os.environ, "QT_QPA_PLATFORM": "offscreen"})
        cls.stderr, cls.returncode = result.stderr, result.returncode
        cls.r = json.loads(result.stdout.strip().splitlines()[-1]) if result.returncode == 0 else {}

    def setUp(self):
        self.assertEqual(self.returncode, 0, self.stderr)

    def test_repeat_off(self):
        k = self.r["off"]["repeatKey"]
        self.assertEqual(k["text"], "Repeat off")
        self.assertFalse(k["active"])
        self.assertEqual(k["icon"], "repeat")

    def test_repeat_one(self):
        k = self.r["one"]["repeatKey"]
        self.assertEqual(k["text"], "Repeat 1")
        self.assertTrue(k["active"])
        self.assertEqual(k["icon"], "repeat_one")

    def test_repeat_all(self):
        k = self.r["all"]["repeatKey"]
        self.assertEqual(k["text"], "Repeat")
        self.assertTrue(k["active"])
        self.assertEqual(k["icon"], "repeat")

    def test_shuffle(self):
        self.assertEqual(self.r["off"]["shuffleKey"]["text"], "Shuffle")
        self.assertFalse(self.r["off"]["shuffleKey"]["active"])
        self.assertTrue(self.r["one"]["shuffleKey"]["active"])

    def test_eq_key_shows_the_preset(self):
        self.assertFalse(self.r["off"]["eqKey"]["active"])
        self.assertEqual(self.r["off"]["eqKey"]["text"], "Flat")
        self.assertTrue(self.r["one"]["eqKey"]["active"])
        self.assertEqual(self.r["one"]["eqKey"]["text"], "Road")
        self.assertEqual(self.r["all"]["eqKey"]["text"], "Custom")
        self.assertTrue(self.r["all"]["eqKey"]["active"])


if __name__ == "__main__":
    unittest.main()
