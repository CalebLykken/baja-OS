"""Off-Pi tests for what the Playing card says when there is no song yet
(qml/pages/MusicPage.qml and the Home card, qml/components/NowPlaying.qml):
nothing on the Pi says Nothing playing with a hint on how to get music, the
Pi's music being read says so, a Spotify start with no title says it is
starting, and a real track shows its own artist. Both QML files run in their
own process with a fake media, like tests/test_music_mode_keys.py.

    python3 -m unittest tests.test_music_idle_hint
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
from PyQt6.QtCore import QEventLoop, QObject, QTimer, QUrl, pyqtProperty, pyqtSignal
from PyQt6.QtGui import QGuiApplication
from PyQt6.QtQml import QQmlComponent, QQmlEngine

app = QGuiApplication(sys.argv)
ROOT = Path.cwd()
which = sys.argv[1]          # "page" for MusicPage, "card" for the Home card


class Media(QObject):
    changed = pyqtSignal()

    def __init__(self):
        super().__init__()
        self.d = {"source": "local", "title": "", "artist": "", "albumTitle": "",
                  "scanning": False, "artCard": "", "duration": 0, "position": 0,
                  "playing": False, "shuffle": False, "repeat": "off", "album": -1,
                  "canSeek": False, "hasModes": False}

    @pyqtProperty(str, notify=changed)
    def source(self):
        return self.d["source"]

    @pyqtProperty(str, notify=changed)
    def title(self):
        return self.d["title"]

    @pyqtProperty(str, notify=changed)
    def artist(self):
        return self.d["artist"]

    @pyqtProperty(str, notify=changed)
    def albumTitle(self):
        return self.d["albumTitle"]

    @pyqtProperty(bool, notify=changed)
    def scanning(self):
        return self.d["scanning"]

    @pyqtProperty(str, notify=changed)
    def artCard(self):
        return self.d["artCard"]

    @pyqtProperty(int, notify=changed)
    def duration(self):
        return self.d["duration"]

    @pyqtProperty(int, notify=changed)
    def position(self):
        return self.d["position"]

    @pyqtProperty(bool, notify=changed)
    def playing(self):
        return self.d["playing"]

    @pyqtProperty(bool, notify=changed)
    def shuffle(self):
        return self.d["shuffle"]

    @pyqtProperty(str, notify=changed)
    def repeat(self):
        return self.d["repeat"]

    @pyqtProperty(int, notify=changed)
    def album(self):
        return self.d["album"]

    @pyqtProperty(bool, notify=changed)
    def canSeek(self):
        return self.d["canSeek"]

    @pyqtProperty(bool, notify=changed)
    def hasModes(self):
        return self.d["hasModes"]

    @pyqtProperty("QVariantList", notify=changed)
    def otherSources(self):
        return []

    @pyqtProperty("QVariantList", notify=changed)
    def upNext(self):
        return []

    @pyqtProperty("QVariantList", notify=changed)
    def albums(self):
        return []

    @pyqtProperty("QVariantList", notify=changed)
    def songs(self):
        return []

    def set(self, **kw):
        self.d.update(kw)
        self.changed.emit()


media = Media()
engine = QQmlEngine()
engine.rootContext().setContextProperty("media", media)
if which == "page":
    component = QQmlComponent(engine, QUrl.fromLocalFile(str(ROOT / "qml/pages/MusicPage.qml")))
else:
    component = QQmlComponent(engine)
    component.setData(b'import QtQuick\nimport "qml/components"\nNowPlaying { width: 560; height: 300 }\n',
                      QUrl.fromLocalFile(str(ROOT / "x.qml")))
obj = component.create()
if obj is None:
    for error in component.errors():
        print(error.toString(), file=sys.stderr)
    sys.exit(1)


def settle(ms):
    # The Home card's words slide in and out over a few hundred ms: let that finish.
    loop = QEventLoop()
    QTimer.singleShot(ms, loop.quit)
    loop.exec()


def read(name):
    label = obj.findChild(QObject, name)
    return label.property("text") if label is not None else None


states = {
    "idle": dict(source="local", title="", artist="", albumTitle="", scanning=False),
    "scanning": dict(source="local", title="", artist="", albumTitle="", scanning=True),
    "track": dict(source="local", title="Song", artist="Band", albumTitle="Record", scanning=False),
    "spotify_start": dict(source="spotify", title="", artist="", albumTitle="", scanning=False),
}
results = {}
for name, kw in states.items():
    media.set(**kw)
    settle(600)
    results[name] = {"title": read("nowTitle"), "artist": read("nowArtist")}
print(json.dumps(results))
sys.stdout.flush()
'''


def run(which):
    result = subprocess.run([sys.executable, "-c", SCRIPT, which], cwd=ROOT,
                            capture_output=True, text=True, timeout=60,
                            env={**os.environ, "QT_QPA_PLATFORM": "offscreen"})
    if result.returncode != 0:
        raise AssertionError(result.stderr)
    return json.loads(result.stdout.strip().splitlines()[-1])


class MusicIdleHintTest(unittest.TestCase):
    """The Playing page (MusicPage.qml) and the Home card (NowPlaying.qml) say the same things."""

    @classmethod
    def setUpClass(cls):
        cls.page = run("page")
        cls.card = run("card")

    def check(self, results, state, title=None, artist=None):
        r = results[state]
        if title is not None:
            self.assertEqual(r["title"], title)
        if artist is not None:
            self.assertIn(artist, r["artist"])

    def test_page_idle_says_how_to_get_music(self):
        self.check(self.page, "idle", title="Nothing playing", artist="Pair a phone")

    def test_page_scanning_says_songs_are_found(self):
        self.check(self.page, "scanning", title="Reading your music", artist="found")

    def test_page_track_shows_its_artist(self):
        self.check(self.page, "track", title="Song", artist="Band · Record")

    def test_page_spotify_start_says_starting(self):
        self.check(self.page, "spotify_start", title="Starting Spotify...")

    def test_card_idle_says_how_to_get_music(self):
        self.check(self.card, "idle", title="Nothing playing", artist="Pair a phone")

    def test_card_scanning_says_songs_are_found(self):
        self.check(self.card, "scanning", title="Reading your music", artist="found")

    def test_card_track_shows_its_artist(self):
        self.check(self.card, "track", title="Song", artist="Band · Record")

    def test_card_spotify_start_says_starting(self):
        self.check(self.card, "spotify_start", title="Starting Spotify...")


if __name__ == "__main__":
    unittest.main()
