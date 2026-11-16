"""Off-Pi tests for the seek bar's thumb and drag feedback on the Playing page
(qml/pages/MusicPage.qml). The page runs in its own process with a fake media:
the thumb shows only where seeking works, sits on the end of the fill, and while
a finger is on the bar it grows, the elapsed time turns accent and bold, and the
right side counts down the time left. A real press goes through a QQuickView so
the bar's MouseArea gets an actual mouse event.

    python3 -m unittest tests.test_music_seek_thumb
"""

import json
import os
import subprocess
import sys
import unittest
from pathlib import Path

try:
    import PyQt6.QtQml  # noqa: F401
    import PyQt6.QtTest  # noqa: F401
except ImportError:
    raise unittest.SkipTest("PyQt6 isn't installed")

ROOT = Path(__file__).resolve().parent.parent

SCRIPT = r'''
import json, sys
from pathlib import Path
from PyQt6.QtCore import QObject, QPoint, QUrl, Qt, pyqtProperty, pyqtSignal, pyqtSlot
from PyQt6.QtGui import QGuiApplication
from PyQt6.QtQml import QQmlComponent, QQmlEngine, QQmlExpression
from PyQt6.QtQuick import QQuickView
from PyQt6.QtTest import QTest

import time

app = QGuiApplication(sys.argv)
ROOT = Path.cwd()


class Media(QObject):
    changed = pyqtSignal()

    def __init__(self):
        super().__init__()
        self._canSeek = True
        self._position = 30
        self._duration = 120
        self.seeks = []

    @pyqtProperty(str, notify=changed)
    def source(self):
        return "local"

    @pyqtProperty(str, notify=changed)
    def title(self):
        return "Song"

    @pyqtProperty(bool, notify=changed)
    def canSeek(self):
        return self._canSeek

    @pyqtProperty(int, notify=changed)
    def position(self):
        return self._position

    @pyqtProperty(int, notify=changed)
    def duration(self):
        return self._duration

    @pyqtSlot(int)
    def seek(self, s):
        self.seeks.append(s)
        self._position = s
        self.changed.emit()

    def set(self, canSeek=None, position=None):
        if canSeek is not None:
            self._canSeek = canSeek
        if position is not None:
            self._position = position
        self.changed.emit()


class Eq(QObject):
    changed = pyqtSignal()

    @pyqtProperty(str, notify=changed)
    def preset(self):
        return "Flat"


media, eq = Media(), Eq()
engine = QQmlEngine()
engine.rootContext().setContextProperty("media", media)
engine.rootContext().setContextProperty("eq", eq)
url = QUrl.fromLocalFile(str(ROOT / "qml/pages/MusicPage.qml"))
component = QQmlComponent(engine, url)
obj = component.create()
if obj is None:
    for error in component.errors():
        print(error.toString(), file=sys.stderr)
    sys.exit(1)

view = QQuickView(engine, None)
view.setSource(url)
view.resize(1280, 800)
view.show()
for _ in range(20):
    app.processEvents()
root = view.rootObject()


def find(name):
    return root.findChild(QObject, name)


def js(item, expr):
    value = QQmlExpression(engine.rootContext(), item, expr).evaluate()
    if isinstance(value, tuple) and value[0] is None:
        value = QQmlExpression(engine.rootContext(), item, expr).evaluate()
    return value[0] if isinstance(value, tuple) else value


def label_info(item):
    f = item.property("font")
    return {"color": item.property("color").name(), "weight": f.weight(), "text": item.property("text")}


def state(tag):
    seek = find("seekArea")
    thumb = find("seekThumb")
    return {
        "tag": tag,
        "seekW": seek.property("width"),
        "thumbVisible": thumb.property("visible"),
        "thumbX": thumb.property("x"),
        "thumbW": thumb.property("width"),
        "thumbH": thumb.property("height"),
        "thumbColor": thumb.property("color").name(),
        "dragging": seek.property("dragging"),
        "thumbCentre": thumb.property("x") + thumb.property("width") / 2,
    }


out = {}
out["playing"] = state("playing")

# Position 30 of 120: the thumb's centre sits at a quarter of the bar.
media.set(position=30)
app.processEvents()
out["quarter"] = state("quarter")
media.set(position=90)
app.processEvents()
out["threeQuarter"] = state("threeQuarter")
media.set(position=30)
app.processEvents()

# A phone (no seeking): the thumb is hidden.
media.set(canSeek=False)
app.processEvents()
out["noSeek"] = state("noSeek")
media.set(canSeek=True)
app.processEvents()

# A real press at the middle of the bar, then a check while dragging.
seek = find("seekArea")
sx = js(seek, "mapToItem(null, 0, 0).x")
sy = js(seek, "mapToItem(null, 0, 0).y")
w = seek.property("width")
h = seek.property("height")
point = QPoint(int(sx + w * 0.5), int(sy + h / 2))
QTest.mousePress(view, Qt.MouseButton.LeftButton, Qt.KeyboardModifier.NoModifier, point)
def settle(ms=400):
    end = time.monotonic() + ms / 1000
    while time.monotonic() < end:
        app.processEvents()
        time.sleep(0.01)


settle()
out["pressed"] = state("pressed")
labels = [find("seekElapsed"), find("seekRemaining")]
out["labels"] = [label_info(c) for c in labels]

QTest.mouseMove(view, QPoint(int(sx + w * 0.75), int(sy + h / 2)))
QTest.mouseRelease(view, Qt.MouseButton.LeftButton, Qt.KeyboardModifier.NoModifier, QPoint(int(sx + w * 0.75), int(sy + h / 2)))
settle()
out["released"] = state("released")
out["seeks"] = media.seeks
out["labelsAfter"] = [label_info(c) for c in labels]
print(json.dumps(out))
sys.stdout.flush()
'''


class SeekThumbTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        result = subprocess.run([sys.executable, "-c", SCRIPT], cwd=ROOT,
                                capture_output=True, text=True, timeout=120,
                                env={**os.environ, "QT_QPA_PLATFORM": "offscreen"})
        cls.stderr, cls.returncode = result.stderr, result.returncode
        cls.r = json.loads(result.stdout.strip().splitlines()[-1]) if result.returncode == 0 else {}

    def setUp(self):
        self.assertEqual(self.returncode, 0, self.stderr)

    def test_thumb_hidden_without_seeking(self):
        self.assertFalse(self.r["noSeek"]["thumbVisible"])

    def test_thumb_shown_when_seeking(self):
        self.assertTrue(self.r["playing"]["thumbVisible"])

    def test_thumb_is_round_and_accent(self):
        t = self.r["playing"]
        self.assertEqual(t["thumbW"], 28)
        self.assertEqual(t["thumbH"], 28)
        self.assertEqual(t["thumbColor"], self.r["pressed"]["thumbColor"])

    def test_thumb_tracks_position(self):
        w = self.r["playing"]["seekW"]
        self.assertAlmostEqual(self.r["quarter"]["thumbCentre"], w * 0.25, delta=1.0)
        self.assertAlmostEqual(self.r["threeQuarter"]["thumbCentre"], w * 0.75, delta=1.0)
        self.assertLess(self.r["quarter"]["thumbX"], self.r["threeQuarter"]["thumbX"])

    def test_press_grows_thumb_and_marks_drag(self):
        self.assertTrue(self.r["pressed"]["dragging"])
        self.assertEqual(self.r["pressed"]["thumbW"], 36)
        self.assertFalse(self.r["playing"]["dragging"])

    def test_elapsed_turns_accent_and_bold_while_dragging(self):
        elapsed = self.r["labels"][0]
        self.assertEqual(elapsed["color"], self.r["pressed"]["thumbColor"])
        self.assertGreater(elapsed["weight"], 400)
        self.assertNotEqual(self.r["labelsAfter"][0]["color"], elapsed["color"])
        self.assertLess(self.r["labelsAfter"][0]["weight"], elapsed["weight"])

    def test_remaining_time_counts_down_while_dragging(self):
        right = self.r["labels"][1]
        self.assertTrue(right["text"].startswith("−"), right["text"])

    def test_release_seeks_and_restores_size(self):
        self.assertFalse(self.r["released"]["dragging"])
        self.assertEqual(self.r["released"]["thumbW"], 28)
        self.assertEqual(len(self.r["seeks"]), 1)


if __name__ == "__main__":
    unittest.main()
