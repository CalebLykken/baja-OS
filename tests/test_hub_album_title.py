"""Off-Pi tests for the album under the artist (MediaHub.albumTitle, and the
players it reads): the Pi's own songs and the demo carry it, the phone and
Spotify don't. The artist line on the Playing page and the Home card
(qml/components/NowPlaying.qml) shows it, and leaves out "Unknown artist".

    python3 -m unittest tests.test_hub_album_title
"""

import json
import os
import subprocess
import sys
import tempfile
import unittest
import wave
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parent.parent

try:
    from PyQt6.QtCore import QCoreApplication
    from backend import gapless
    from backend.hub import MediaHub
    from backend.library import LibraryPlayer
    from backend.media import MediaPlayer
    from tests.test_hub import FakeSettings, FakeSink, FakeSource
except ImportError as e:
    raise unittest.SkipTest(f"PyQt6 or mutagen isn't installed ({e})")

app = QCoreApplication.instance() or QCoreApplication([])


def write_wav(path):
    with wave.open(str(path), "wb") as w:
        w.setnchannels(2)
        w.setsampwidth(2)
        w.setframerate(48000)
        w.writeframes(bytes(48000 * 4))


class HubAlbumTitleTest(unittest.TestCase):
    """The hub passes on the album of the Pi's song, and only while the Pi is the source."""

    def make(self, tracks):
        patch = mock.patch.object(gapless, "QAudioSink", FakeSink)
        patch.start()
        self.addCleanup(patch.stop)
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        for t in tracks:
            path = Path(tmp.name) / (t["title"] + ".wav")
            write_wav(path)
            t.setdefault("path", str(path))
        self.local = LibraryPlayer(tracks)
        self.addCleanup(self.local._engine._shutdown)
        self.phone, self.spotify = FakeSource(), FakeSource()
        with mock.patch("backend.hub.shutil.which", return_value=None):
            self.hub = MediaHub(self.local, self.phone, self.spotify, settings=FakeSettings())
        self.hub.start()
        self.addCleanup(self.hub._save_timer.stop)
        return self.hub

    def song(self, title="Tailgate Down", artist="Boxer Rebellion", album="Bed Liner Sessions"):
        return {"title": title, "artist": artist, "album": album, "art": "",
                "duration": 1, "albumArtist": "", "disc": 0, "track": 1}

    def test_local_song_gives_its_album(self):
        hub = self.make([self.song()])
        self.assertEqual(hub.source, "local")
        self.assertEqual(hub.albumTitle, "Bed Liner Sessions")

    def test_phone_gives_no_album(self):
        hub = self.make([self.song()])
        hub._set_source("phone")
        self.assertEqual(hub.albumTitle, "")

    def test_spotify_gives_no_album(self):
        hub = self.make([self.song()])
        hub._set_source("spotify")
        self.assertEqual(hub.albumTitle, "")

    def test_back_on_the_pi_the_album_returns(self):
        hub = self.make([self.song()])
        hub._set_source("phone")
        hub._set_source("local")
        self.assertEqual(hub.albumTitle, "Bed Liner Sessions")

    def test_no_songs_gives_no_album(self):
        hub = self.make([])
        self.assertEqual(hub.albumTitle, "")


class DemoAlbumTitleTest(unittest.TestCase):
    """The demo playlist: each song names the demo album that holds it."""

    def test_song_from_all_songs_names_its_album(self):
        player = MediaPlayer()
        player.playIndex(9)                       # "Tailgate Down", first of Bed Liner Sessions
        self.assertEqual(player.title, "Tailgate Down")
        self.assertEqual(player.albumTitle, "Bed Liner Sessions")

    def test_album_playing_names_that_album(self):
        player = MediaPlayer()
        player.playAlbum(1, 2)                    # Cascade Crossing, its third song
        self.assertEqual(player.albumTitle, "Cascade Crossing")

    def test_a_queue_passed_in_has_no_album(self):
        player = MediaPlayer(queue=[{"title": "A", "artist": "B", "duration": 1}])
        self.assertEqual(player.albumTitle, "")


# The artist line itself: NowPlaying.qml in its own process, like
# tests/test_now_playing_direction.py, with a stand-in for `media`.
SCRIPT = r'''
import json, sys
from pathlib import Path
from PyQt6.QtCore import QEventLoop, QObject, QTimer, QUrl, pyqtProperty, pyqtSignal, pyqtSlot
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
        self._title, self._artist, self._album = "Tailgate Down", "", ""

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

    @pyqtProperty(str, notify=trackChanged)
    def albumTitle(self):
        return self._album

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
        pass

    @pyqtSlot()
    def next(self):
        pass

    @pyqtSlot()
    def togglePlay(self):
        pass

    def set(self, artist, album):
        self._artist, self._album = artist, album
        self.trackChanged.emit()


def wait(ms):
    loop = QEventLoop()
    QTimer.singleShot(ms, loop.quit)
    loop.exec()


cases = [
    ["Boxer Rebellion", "Bed Liner Sessions"],
    ["Unknown artist", ""],
    ["Unknown artist", "Bed Liner Sessions"],
    ["Boxer Rebellion", ""],
]
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

results = []
for artist, album in cases:
    media.set(artist, album)
    wait(100)
    results.append(obj.property("shownArtist"))
print(json.dumps(results))
sys.stdout.flush()
'''


class ArtistLineTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        env = {**os.environ, "QT_QPA_PLATFORM": "offscreen"}
        result = subprocess.run([sys.executable, "-c", SCRIPT], cwd=ROOT, capture_output=True,
                                text=True, timeout=60, env=env)
        cls.returncode, cls.stderr = result.returncode, result.stderr
        cls.lines = json.loads(result.stdout.strip().splitlines()[-1]) if result.returncode == 0 else []

    def setUp(self):
        self.assertEqual(self.returncode, 0, self.stderr)

    def test_artist_then_album(self):
        self.assertEqual(self.lines[0], "Boxer Rebellion · Bed Liner Sessions")

    def test_unknown_artist_with_no_album_is_empty(self):
        self.assertEqual(self.lines[1], "")

    def test_unknown_artist_shows_only_the_album(self):
        self.assertEqual(self.lines[2], "Bed Liner Sessions")

    def test_artist_alone_when_no_album(self):
        self.assertEqual(self.lines[3], "Boxer Rebellion")


if __name__ == "__main__":
    unittest.main()
