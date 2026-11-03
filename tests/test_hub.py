"""Off-Pi tests for what the media hub (backend/hub.py) saves and picks up
after a restart, with the demo playlist as local music and stand-ins for
the phone and Spotify.

    python3 -m unittest tests.test_hub
"""

import json
import tempfile
import time
import unittest
import wave
from pathlib import Path
from unittest import mock

try:
    from PyQt6.QtCore import QCoreApplication, QObject, pyqtSignal
    from PyQt6.QtMultimedia import QAudio
    from backend import gapless
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
    modesChanged = pyqtSignal()
    deviceName = art = title = artist = ""
    duration = position = 0
    volume = 50
    hasVolume = hasPlayer = available = active = canSeek = linked = hasModes = True
    sought = None
    recents = upNext = []
    resumeUri = "spotify:album:now"
    shuffle = False
    repeat = "off"

    def __init__(self):
        super().__init__()
        self.playing = False
        self.resumed = []
        self.shuffled = self.repeats = self.queued = 0

    def resume(self, uri):
        self.resumed.append(uri)

    def cancel_resume(self):
        self.cancelled = getattr(self, "cancelled", 0) + 1

    def toggleShuffle(self):
        self.shuffled += 1

    def cycleRepeat(self):
        self.repeats += 1

    def addToQueue(self, uri):
        self.queued += 1

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

    def seek(self, seconds):
        self.sought = seconds


def saved(source, playing, index=3, position=50):
    return json.dumps({"source": source, "playing": playing,
                       "local": {"album": None, "path": "", "index": index, "position": position}})


class SpotifyResumeTest(unittest.TestCase):
    """Spotify carrying on by itself, and its shuffle and repeat."""

    URI = "spotify:album:saved"

    def make(self, **values):
        self.settings = FakeSettings(music=saved("spotify", False), **values)   # local music waits
        self.local, self.phone, self.spotify = MediaPlayer(), FakeSource(), FakeSource()
        with mock.patch("backend.hub.shutil.which", return_value=None):
            self.hub = MediaHub(self.local, self.phone, self.spotify, settings=self.settings)
        self.hub.start()
        self.addCleanup(self.local._timer.stop)
        return self.hub

    def signs_in(self):
        self.spotify.available = self.spotify.linked = True
        self.spotify.changed.emit()

    def drops_out(self):
        self.spotify.available = self.spotify.linked = self.spotify.active = False
        self.spotify.playing = False
        self.spotify.changed.emit()
        self.spotify.playingChanged.emit()

    def saved(self):
        return self.settings.values.get("spotifyResumeUri", "")

    def test_it_carries_on_once_signed_in(self):
        self.make(spotifyResumeUri=self.URI)
        self.signs_in()
        self.assertEqual(self.spotify.resumed, [self.URI])

    def test_only_once(self):
        self.make(spotifyResumeUri=self.URI)
        self.signs_in()
        self.signs_in()
        self.assertEqual(len(self.spotify.resumed), 1)

    def test_nothing_saved_means_nothing_starts(self):
        self.make()
        self.signs_in()
        self.assertEqual(self.spotify.resumed, [])

    def test_the_settings_switch_stops_it_and_is_saved(self):
        self.make(spotifyResumeUri=self.URI).setSpotifyResume(False)
        self.assertEqual(self.settings.values["spotifyResume"], "false")
        self.signs_in()
        self.assertEqual(self.spotify.resumed, [])

    def test_it_doesnt_cut_in_on_the_phone(self):
        self.make(spotifyResumeUri=self.URI)
        self.phone.play()
        self.signs_in()
        self.assertEqual(self.spotify.resumed, [])

    def test_playing_is_remembered(self):
        self.make()
        self.spotify.play()
        self.assertEqual(self.saved(), self.spotify.resumeUri)

    def test_a_lost_connection_keeps_it_and_carries_on_after(self):
        self.make()
        self.spotify.play()
        self.signs_in()
        self.drops_out()
        self.assertEqual(self.hub.source, "local")
        self.assertEqual(self.saved(), self.spotify.resumeUri)
        self.spotify.active = True
        self.signs_in()
        self.assertEqual(self.spotify.resumed, [self.spotify.resumeUri])

    def test_pausing_forgets_it(self):
        self.make()
        self.spotify.play()
        self.spotify.pause()
        self.assertEqual(self.saved(), "")

    def test_moving_to_another_device_forgets_it(self):
        self.make()
        self.spotify.play()
        self.spotify.active = False
        self.spotify.changed.emit()
        self.assertEqual((self.hub.source, self.saved()), ("local", ""))

    def test_playing_something_else_forgets_it(self):
        hub = self.make()
        self.spotify.play()
        self.phone.play()
        self.assertEqual((hub.source, self.saved()), ("phone", ""))

    def test_shuffle_and_repeat_go_to_spotify_while_it_plays(self):
        hub = self.make()
        self.spotify.play()
        self.spotify.shuffle, self.spotify.repeat = True, "one"
        self.assertEqual((hub.hasModes, hub.shuffle, hub.repeat), (True, True, "one"))
        hub.toggleShuffle()
        hub.cycleRepeat()
        self.assertEqual((self.spotify.shuffled, self.spotify.repeats), (1, 1))

    def test_the_phone_has_no_modes(self):
        hub = self.make()
        self.phone.play()
        self.assertFalse(hub.hasModes)

    def test_adding_to_the_queue_reaches_spotify(self):
        self.make().queueSpotify("spotify:track:t")
        self.assertEqual(self.spotify.queued, 1)


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

    def test_another_source_taking_over_stops_late_songs_autoplaying(self):
        hub = self.make(music=saved("local", True))
        self.local.cancel_autoplay = mock.Mock()
        self.spotify.play()
        self.assertEqual(hub.source, "spotify")
        self.local.cancel_autoplay.assert_called_once_with()

    def test_a_phone_auto_resuming_after_reconnecting_is_paused(self):
        hub = self.make(music=saved("local", False))
        self.spotify.play()
        hub._phone_connected_at = time.monotonic()      # the phone just reconnected
        self.phone.play()                               # and resumes by itself
        self.assertEqual((hub.source, self.spotify.playing, self.phone.playing),
                         ("spotify", True, False))

    def test_a_phone_playing_well_after_reconnecting_takes_over(self):
        hub = self.make(music=saved("local", False))
        self.spotify.play()
        hub._phone_connected_at = time.monotonic() - 60
        self.phone.play()
        self.assertEqual((hub.source, self.spotify.playing, self.phone.playing),
                         ("phone", False, True))

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
                                        "local": {"album": None, "path": "", "index": 2, "position": 10},
                                        "modes": {"shuffle": False, "repeat": "all"}})

    def test_every_few_seconds(self):
        hub = self.make(music=saved("local", True, position=10))
        self.local._tick()
        self.local._tick()
        self.assertEqual(self.state()["local"]["position"], 10)     # not on every tick
        hub._save_timer.timeout.emit()
        self.assertEqual(self.state()["local"]["position"], 12)

    def test_seek_goes_to_the_source_that_can(self):
        hub = self.make(music=saved("local", False))
        self.phone.canSeek = False
        self.spotify.play()
        self.assertEqual((hub.source, hub.canSeek), ("spotify", True))
        hub.seek(42)
        self.assertEqual(self.spotify.sought, 42)
        self.phone.play()
        self.assertEqual((hub.source, hub.canSeek), ("phone", False))
        hub.seek(10)                                 # AVRCP has no seek: ignored
        self.assertIsNone(self.phone.sought)

    def test_reading_what_was_saved(self):
        self.assertIsNone(read_state(""))
        self.assertIsNone(read_state("{"))
        self.assertIsNone(read_state("[]"))
        self.assertTrue(plays_on_start(read_state(saved("local", True))))
        for source, playing in (("local", False), ("spotify", True), ("phone", True)):
            self.assertFalse(plays_on_start(read_state(saved(source, playing))), source)


class SwitchTest(unittest.TestCase):
    """Local music's output is low, the phone's and Spotify's is 100%: the
    level must go through silence, never straight up."""

    def setUp(self):
        with mock.patch("shutil.which", return_value="/usr/bin/wpctl"), \
                mock.patch("subprocess.run"):
            self.local = MediaPlayer()
            self.spotify = FakeSource()
            # The hub's real volume-writer thread drains _pending_level as
            # soon as it is woken, racing any test that reads it. Start it as
            # a no-op so _pending_level holds what _apply_volume set.
            with mock.patch.object(MediaHub, "_level_writer", lambda self: None):
                self.hub = MediaHub(self.local, FakeSource(), self.spotify, volume=20)
        self.levels = []
        real_apply = self.hub._apply_volume

        def recording():
            real_apply()
            self.levels.append(self.hub._fade * (1.0 if self.hub._remote_volume else 0.2))
        self.hub._apply_volume = recording

    def tearDown(self):
        self.hub._switching.stop()
        self.hub._fade_timer.stop()

    def test_the_level_never_jumps_up(self):
        self.spotify.play()
        self.assertEqual(self.hub._source, "spotify")
        self.assertEqual(self.hub._fade, 0.0)
        self.assertEqual(max(self.levels), 0.0)
        self.assertTrue(self.hub._switching.isActive())

    def test_it_comes_back_up_after_settling(self):
        self.spotify.play()
        self.hub._switching.stop()
        self.hub._fade_in_after_switch()
        while self.hub._fade_timer.isActive():
            self.hub._fade_tick()
        self.assertEqual(self.hub._fade, 1.0)
        self.assertEqual(self.levels[-1], 1.0)
        rising = [v for v in self.levels if v]
        self.assertEqual(rising, sorted(rising))

    def test_comes_back_even_if_the_source_stopped_meanwhile(self):
        self.spotify.play()
        self.spotify.pause()
        self.hub._switching.stop()
        self.hub._fade_in_after_switch()
        while self.hub._fade_timer.isActive():
            self.hub._fade_tick()
        self.assertEqual(self.hub._fade, 1.0)

    def test_output_returns_to_local_volume_when_the_phone_loses_absolute_volume(self):
        phone = self.hub._sources["phone"]
        self.hub._source = "phone"
        self.hub._apply_volume()
        self.assertEqual(self.hub._pending_level, 1.0)      # held at the ceiling
        phone.hasVolume = False
        phone.volumeChanged.emit()
        self.assertAlmostEqual(self.hub._pending_level, 0.2)

    def test_another_source_cancels_a_pending_spotify_resume(self):
        self.hub._pause_others(keep="local")
        self.assertEqual(self.spotify.cancelled, 1)
        self.hub._pause_others(keep="spotify")
        self.assertEqual(self.spotify.cancelled, 1)

    def test_the_knob_starting_local_music_cancels_the_resume(self):
        self.assertEqual(self.hub._source, "local")
        self.local._queue = [{"title": "a", "artist": "b", "duration": 1}]
        self.local._playing = False
        self.hub.togglePlay()
        self.assertTrue(self.local.playing)
        self.assertEqual(self.spotify.cancelled, 1)

    def test_spotify_playing_does_not_cancel_its_own_resume(self):
        self.spotify.playing = True
        self.hub._source_playing_changed("spotify")
        self.assertFalse(getattr(self.spotify, "cancelled", 0))

    def test_no_hush_without_a_switch(self):
        self.hub._pause_others(keep="local")
        self.assertEqual(self.hub._fade, 1.0)
        self.assertFalse(self.hub._switching.isActive())


class FakeSink(QObject):
    """Stands in for QAudioSink: no audio device needed, nothing asks the feed for data."""
    stateChanged = pyqtSignal(object)

    def __init__(self, device, fmt, parent=None):
        super().__init__(parent)
        self._device, self._size = device, 0

    def setBufferSize(self, n):
        self._size = n

    def bufferSize(self):
        return self._size

    def bytesFree(self):
        return self._size

    def setVolume(self, v):
        pass

    def start(self, feed):
        pass

    def stop(self):
        pass

    def error(self):
        return QAudio.Error.NoError

    def device(self):
        return self._device


class ModesTest(unittest.TestCase):
    """Shuffle and repeat: the Pi's own music only, kept between runs."""

    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.tracks = []
        for n in range(1, 5):
            path = Path(tmp.name) / f"t{n}.wav"
            with wave.open(str(path), "wb") as w:
                w.setnchannels(2)
                w.setsampwidth(2)
                w.setframerate(48000)
                w.writeframes(bytes(48000 * 4))
            self.tracks.append({"path": str(path), "title": f"T{n}", "artist": "Band", "duration": 1,
                                "art": "", "album": "A", "albumArtist": "", "disc": 0, "track": n})

    def make(self, **values):
        from backend.library import LibraryPlayer
        patch = mock.patch.object(gapless, "QAudioSink", FakeSink)
        patch.start()
        self.addCleanup(patch.stop)          # undone after the engine is shut down
        self.settings = FakeSettings(**values)
        self.local = LibraryPlayer(self.tracks)
        self.addCleanup(self.local._engine._shutdown)
        with mock.patch("backend.hub.shutil.which", return_value=None):
            hub = MediaHub(self.local, FakeSource(), FakeSource(), settings=self.settings)
        hub.start()
        self.addCleanup(hub._save_timer.stop)
        return hub

    def test_the_keys_set_and_save_them(self):
        hub = self.make()
        self.assertEqual((hub.hasModes, hub.shuffle, hub.repeat), (True, False, "all"))
        hub.toggleShuffle()
        hub.cycleRepeat()
        self.assertEqual((hub.shuffle, hub.repeat), (True, "one"))
        self.assertEqual(json.loads(self.settings.values["music"])["modes"],
                         {"shuffle": True, "repeat": "one"})

    def test_they_come_back_after_a_restart(self):
        state = json.loads(saved("local", False))
        state["modes"] = {"shuffle": True, "repeat": "off"}
        hub = self.make(music=json.dumps(state))
        self.assertEqual((hub.shuffle, hub.repeat), (True, "off"))

    def test_junk_saved_leaves_the_defaults(self):
        for modes in ("x", {"shuffle": "yes", "repeat": "sideways"}, None):
            state = json.loads(saved("local", False))
            state["modes"] = modes
            hub = self.make(music=json.dumps(state))
            self.assertEqual((hub.shuffle, hub.repeat), (False, "all"), modes)

    def test_not_on_other_sources(self):
        hub = self.make()
        self.assertTrue(hub.hasModes)
        hub._set_source("phone")
        self.assertFalse(hub.hasModes)
        hub.toggleShuffle()
        hub.cycleRepeat()
        self.assertEqual((self.local.shuffle, self.local.repeat), (False, "all"))

    def test_the_demo_player_has_none(self):
        demo = MediaPlayer()
        self.assertFalse(demo.hasModes)
        demo.toggleShuffle()
        demo.cycleRepeat()
        self.assertEqual((demo.shuffle, demo.repeat), (False, "all"))


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
