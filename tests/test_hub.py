"""Off-Pi tests for what the media hub (backend/hub.py) saves and picks up
after a restart, with the demo playlist as local music and stand-ins for
the phone and Spotify.

    python3 -m unittest tests.test_hub
"""

import json
import time
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


class NoMusicTest(unittest.TestCase):
    """Local music with no songs (an empty folder, the card not there yet):
    the hub says nothing's playing, carries on when Spotify takes over, and
    saves the place it was given rather than a blank one."""

    def setUp(self):
        self.kept = []                      # alive until the cleanups have run

    def local_players(self):
        yield MediaPlayer([])
        try:
            from backend.library import LibraryPlayer
        except ImportError:
            return
        player = LibraryPlayer([])
        self.addCleanup(player._engine._shutdown)
        yield player

    def make(self, local, wpctl=False, **values):
        """wpctl: the hub finds wpctl, as on the Pi (it's faked: nothing runs)."""
        self.settings = FakeSettings(**values)
        self.spotify = FakeSource()
        if wpctl:
            run = mock.patch("backend.hub.subprocess.run")
            self.wpctl = run.start()
            self.addCleanup(run.stop)
        with mock.patch("backend.hub.shutil.which", return_value="/usr/bin/wpctl" if wpctl else None):
            hub = MediaHub(local, FakeSource(), self.spotify, settings=self.settings)
        hub.start()
        self.kept.append((local, hub))
        self.addCleanup(hub._save_timer.stop)
        return hub

    def test_nothing_is_playing(self):
        for local in self.local_players():
            hub = self.make(local, music=saved("local", True))
            self.assertEqual((hub.source, hub.title, hub.artist, hub.art, hub.duration), ("local", "", "", "", 0))
            self.assertEqual((hub.index, hub.album, hub.queue, hub.albums, hub.albumTracks(0)), (-1, -1, [], [], []))
            self.assertFalse(hub.playing)
            for key in (hub.togglePlay, hub.next, hub.previous, hub.playAll):
                key()
            hub.playIndex(0)
            hub.playAlbum(0, 0)
            self.assertFalse(hub.playing, local)

    def test_the_saved_place_is_kept(self):
        for local in self.local_players():
            hub = self.make(local, music=saved("local", True, index=3, position=50))
            hub._save()
            self.assertEqual(json.loads(self.settings.values["music"])["local"],
                             {"album": None, "path": "", "index": 3, "position": 50}, local)

    def test_the_playing_flag_is_kept_until_there_is_music(self):
        for local in self.local_players():
            for was, source, kept in ((True, "local", True), (False, "local", False),
                                      (True, "spotify", False), (True, "phone", False)):
                hub = self.make(local, music=saved(source, was))
                hub._save()
                state = json.loads(self.settings.values["music"])
                self.assertEqual((state["source"], state["playing"]), ("local", kept), (was, source))
                self.assertFalse(hub.playing)

    def test_the_knob_does_not_mute_the_output(self):
        # The knob presses togglePlay. With no songs it fades the output to 0
        # and then nothing starts to bring it back (that takes a few seconds).
        for local in self.local_players():
            hub = self.make(local, wpctl=True, music=saved("local", True))
            hub.togglePlay()
            self.assertEqual((hub._fade, hub._resuming), (1.0, False))
            self.assertFalse(hub._give_up.isActive())
            time.sleep(0.1)                              # for the volume thread
            self.assertNotIn("0.000", [c.args[0][-1] for c in self.wpctl.call_args_list], local)

    def test_the_knob_still_fades_when_there_is_music(self):
        local = MediaPlayer()
        self.addCleanup(local._timer.stop)
        hub = self.make(local, wpctl=True)
        self.assertTrue(hub.playing)
        hub.togglePlay()
        self.assertTrue(hub._fade_timer.isActive())      # fading out to pause

    def test_spotify_still_takes_over(self):
        for local in self.local_players():
            hub = self.make(local, music=saved("local", False, index=3, position=50))
            self.spotify.play()
            self.assertEqual(hub.source, "spotify")
            state = json.loads(self.settings.values["music"])
            self.assertEqual((state["source"], state["playing"]), ("spotify", True))
            self.assertEqual(state["local"]["index"], 3, local)


if __name__ == "__main__":
    unittest.main()
