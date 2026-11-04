"""Off-Pi tests for the direction of the Home music card's slide
(qml/components/NowPlaying.qml): a new song slides the words out to the left
and in from the right; right after a tap on Previous it runs the other way.

The QML runs in its own process, like tests/test_source_badge.py.

    python3 -m unittest tests.test_now_playing_direction
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
from PyQt6.QtCore import (QEventLoop, QMetaObject, QObject, QTimer, QUrl,
                          pyqtProperty, pyqtSignal, pyqtSlot)
from PyQt6.QtGui import QGuiApplication
from PyQt6.QtQml import QQmlComponent, QQmlEngine

app = QGuiApplication(sys.argv)
ROOT = Path.cwd()


class Media(QObject):
    trackChanged = pyqtSignal()
    sourceChanged = pyqtSignal()
    scanningChanged = pyqtSignal()
    artCardChanged = pyqtSignal()
    durationChanged = pyqtSignal()
    positionChanged = pyqtSignal()
    playingChanged = pyqtSignal()

    def __init__(self):
        super().__init__()
        self._title = "Song A"
        self._artist = "Artist A"
        self.previous_calls = 0

    @pyqtProperty(str, notify=sourceChanged)
    def source(self):
        return "local"

    @pyqtProperty(str, notify=sourceChanged)
    def sourceName(self):
        return ""

    @pyqtProperty(str, notify=trackChanged)
    def title(self):
        return self._title

    @pyqtProperty(str, notify=trackChanged)
    def artist(self):
        return self._artist

    @pyqtProperty(bool, notify=scanningChanged)
    def scanning(self):
        return False

    @pyqtProperty(str, notify=artCardChanged)
    def artCard(self):
        return ""

    @pyqtProperty(int, notify=durationChanged)
    def duration(self):
        return 200

    @pyqtProperty(int, notify=positionChanged)
    def position(self):
        return 10

    @pyqtProperty(bool, notify=playingChanged)
    def playing(self):
        return True

    @pyqtSlot()
    def previous(self):
        self.previous_calls += 1

    @pyqtSlot()
    def next(self):
        pass

    @pyqtSlot()
    def togglePlay(self):
        pass

    def set(self, title, artist):
        self._title, self._artist = title, artist
        self.trackChanged.emit()


def wait(ms):
    loop = QEventLoop()
    QTimer.singleShot(ms, loop.quit)
    loop.exec()


media = Media()
engine = QQmlEngine()
engine.rootContext().setContextProperty("media", media)
component = QQmlComponent(engine)
component.setData(b'import QtQuick\nimport "qml/components"\nNowPlaying { width: 600; height: 400 }',
                  QUrl.fromLocalFile(str(ROOT / "x.qml")))
obj = component.create()
if obj is None:
    for error in component.errors():
        print(error.toString(), file=sys.stderr)
    sys.exit(1)
wait(100)

results = {}
n = [0]


def change():
    n[0] += 1
    media.set("Song %d" % n[0], "Artist")


def settled(prefix):
    wait(500)
    results[prefix + "_end_x"] = obj.property("slideX")
    results[prefix + "_end_title"] = obj.property("shownTitle")
    results[prefix + "_end_title_live"] = media._title


# (a) auto-advance: out to the left
change()
wait(60)
results["auto_x"] = obj.property("slideX")
settled("auto")

# (b) Previous tap, then the title changes: out to the right
QMetaObject.invokeMethod(obj, "tapPrevious")
results["previous_calls"] = media.previous_calls
change()
wait(60)
results["prev_x"] = obj.property("slideX")
settled("prev")

# the tap was used up: the next auto-advance is normal again
change()
wait(60)
results["after_prev_x"] = obj.property("slideX")
settled("after_prev")

# (c) Previous tap that is stale by the time the title changes
obj.setProperty("prevWindowMs", 100)
QMetaObject.invokeMethod(obj, "tapPrevious")
wait(250)
change()
wait(60)
results["stale_x"] = obj.property("slideX")
settled("stale")

print(json.dumps(results))
sys.stdout.flush()
'''


def run():
    return subprocess.run([sys.executable, "-c", SCRIPT], cwd=ROOT,
                          capture_output=True, text=True, timeout=60,
                          env={**os.environ, "QT_QPA_PLATFORM": "offscreen"})


class NowPlayingDirectionTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        result = run()
        cls.stderr = result.stderr
        cls.returncode = result.returncode
        cls.results = json.loads(result.stdout.strip().splitlines()[-1]) if result.returncode == 0 else {}

    def setUp(self):
        self.assertEqual(self.returncode, 0, self.stderr)

    def test_auto_advance_slides_left(self):
        self.assertLess(self.results["auto_x"], 0)
        self.assertEqual(self.results["auto_end_x"], 0)
        self.assertEqual(self.results["auto_end_title"], self.results["auto_end_title_live"])

    def test_previous_tap_slides_right(self):
        self.assertEqual(self.results["previous_calls"], 1)
        self.assertGreater(self.results["prev_x"], 0)
        self.assertEqual(self.results["prev_end_x"], 0)
        self.assertEqual(self.results["prev_end_title"], self.results["prev_end_title_live"])

    def test_tap_is_used_up_by_one_change(self):
        self.assertLess(self.results["after_prev_x"], 0)

    def test_stale_previous_tap_slides_normally(self):
        self.assertLess(self.results["stale_x"], 0)
        self.assertEqual(self.results["stale_end_x"], 0)


if __name__ == "__main__":
    unittest.main()
