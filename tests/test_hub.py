"""Off-Pi tests for what the media hub (backend/hub.py) saves and picks up
after a restart, with the demo playlist as local music and stand-ins for
the phone and Spotify.

    python3 -m unittest tests.test_hub
"""

import json
import unittest
from unittest import mock

try:
    from PyQt6.QtCore import QCoreApplication, QObject, pyqtSignal
    from backend.hub import MediaHub, plays_on_start, read_state
    from backend.media import MediaPlayer
except ImportError as e:
    raise unittest.SkipTest(f"PyQt6 isn't installed ({e})")

app = QCoreApplication.instance() or QCoreApplication([])


class FakeSettings:
    def __init__(self, **values):
        self.values = dict(values)

    def get(self, key, default=None):
        return self.values.get(key, default)

    def set(self, key, value):
        self.values[key] = value


class FakeSource(QObject):
    """The phone or Spotify, as far as the hub looks."""
    trackChanged = pyqtSignal()
    positionChanged = pyqtSignal()
    playingChanged = pyqtSignal()
    volumeChanged = pyqtSignal()
    changed = pyqtSignal()
    queueChanged = pyqtSignal()
    recentsChanged = pyqtSignal()
    deviceName = art = title = artist = ""
    duration = position = 0
    volume = 50
    hasVolume = hasPlayer = available = active = True
    recents = upNext = []

    def __init__(self):
        super().__init__()
        self.playing = False

    def start(self):
        pass

    def play(self):
        self.playing = True
        self.playingChanged.emit()

    def pause(self):
        self.playing = False
        self.playingChanged.emit()

    def setVolume(self, value):
        pass


def saved(source, playing, index=3, position=50):
    return json.dumps({"source": source, "playing": playing,
                       "local": {"album": None, "path": "", "index": index, "position": position}})


class HubTest(unittest.TestCase):
    def make(self, **values):
        self.settings = FakeSettings(**values)
        self.local, self.phone, self.spotify = MediaPlayer(), FakeSource(), FakeSource()
        with mock.patch("backend.hub.shutil.which", return_value=None):   # never the Pi's real volume
            hub = MediaHub(self.local, self.phone, self.spotify, settings=self.settings)
        hub.start()
        self.addCleanup(self.local._timer.stop)
        return hub

    def state(self):
        return json.loads(self.settings.values["music"])

    def test_after_spotify_local_music_waits(self):
        hub = self.make(music=saved("spotify", True))
        self.assertFalse(self.local.playing)
        self.assertEqual((hub.source, hub.index, hub.position), ("local", 3, 50))

    def test_after_the_phone_local_music_waits(self):
        self.make(music=saved("phone", True))
        self.assertFalse(self.local.playing)

    def test_local_music_that_was_playing_plays_on(self):
        hub = self.make(music=saved("local", True))
        self.assertTrue(hub.playing)
        self.assertEqual((hub.index, hub.position), (3, 50))

    def test_local_music_that_was_paused_stays_paused(self):
        self.make(music=saved("local", False))
        self.assertFalse(self.local.playing)

    def test_saves_the_source_and_where_local_music_is(self):
        hub = self.make(music=saved("local", False, index=2, position=10))
        hub.togglePlay()
        self.assertEqual(self.state()["playing"], True)
        self.spotify.play()                          # Spotify takes over: local music pauses
        self.assertEqual(hub.source, "spotify")
        self.assertEqual(self.state(), {"source": "spotify", "playing": True,
                                        "local": {"album": None, "path": "", "index": 2, "position": 10}})

    def test_every_few_seconds(self):
        hub = self.make(music=saved("local", True, position=10))
        self.local._tick()
        self.local._tick()
        self.assertEqual(self.state()["local"]["position"], 10)     # not on every tick
        hub._save_timer.timeout.emit()
        self.assertEqual(self.state()["local"]["position"], 12)

    def test_reading_what_was_saved(self):
        self.assertIsNone(read_state(""))
        self.assertIsNone(read_state("{"))
        self.assertIsNone(read_state("[]"))
        self.assertTrue(plays_on_start(read_state(saved("local", True))))
        for source, playing in (("local", False), ("spotify", True), ("phone", True)):
            self.assertFalse(plays_on_start(read_state(saved(source, playing))), source)


if __name__ == "__main__":
    unittest.main()
