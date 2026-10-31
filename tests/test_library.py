"""Off-Pi tests for the music library (backend/library.py) and its gapless
engine, with short silent WAV files. The player really plays (silence).
Also where it picks up after a restart.

    python3 -m unittest tests.test_library
"""

import os
import tempfile
import time
import unittest
import wave
from pathlib import Path
from types import SimpleNamespace
from unittest import mock

# Qt's FFmpeg backend prints every file's tags (main.py does the same).
os.environ.setdefault("QT_LOGGING_RULES", "qt.multimedia.ffmpeg*=false")

try:
    from PyQt6.QtCore import QCoreApplication, QEventLoop, QObject, QTimer, pyqtSignal
    from PyQt6.QtMultimedia import QAudio
    from backend import gapless, library
    from backend.library import LibraryPlayer, _number, group_albums, play_order, resume_point, scan, step
except ImportError as e:
    raise unittest.SkipTest(f"PyQt6 or mutagen isn't installed ({e})")

app = QCoreApplication.instance() or QCoreApplication([])


class FakeSink(QObject):
    """Stands in for QAudioSink, so nothing here depends on the Mac's (or CI's)
    audio device: it never asks the feed for anything."""
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


def write_wav(path, seconds):
    with wave.open(str(path), "wb") as w:
        w.setnchannels(2)
        w.setsampwidth(2)
        w.setframerate(48000)
        w.writeframes(bytes(int(48000 * seconds) * 4))


def spin(ms):
    """Run the event loop for a while (timers, queued signals)."""
    loop = QEventLoop()
    QTimer.singleShot(ms, loop.quit)
    loop.exec()


class ScanTest(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.root = Path(tmp.name)

    def songs(self, count, per_folder):
        """`count` tiny songs, `per_folder` to a folder; returns the folder."""
        top = self.root / f"{count}-{per_folder}"
        for i in range(count):
            folder = top / f"album {i // per_folder:03}"
            folder.mkdir(parents=True, exist_ok=True)
            write_wav(folder / f"{i:05}.wav", 0.001)
        return top

    def test_folder_art_is_looked_up_once_per_folder(self):
        top = self.songs(60, 20)
        (top / "album 000" / "cover.jpg").write_bytes(b"jpeg")
        with mock.patch.object(library, "_folder_art", wraps=library._folder_art) as lookup:
            tracks = scan(top)
        self.assertEqual(len(tracks), 60)
        self.assertEqual(lookup.call_count, 3)
        self.assertTrue(all(t["art"].endswith("/album 000/cover.jpg") for t in tracks[:20]))
        self.assertTrue(all(t["art"] == "" for t in tracks[20:]))

    def test_one_big_folder_scans_as_fast_per_song_as_album_folders(self):
        # Listing the folder per song took 3.5 s for 1,000 songs in one
        # folder against 0.15 s in album folders.
        def timed(top):
            start = time.perf_counter()
            self.assertEqual(len(scan(top)), 1000)
            return time.perf_counter() - start
        one_folder = timed(self.songs(1000, 1000))
        albums = timed(self.songs(1000, 10))
        self.assertLess(one_folder, 3 * albums + 0.5,
                        f"one folder {one_folder:.2f} s, album folders {albums:.2f} s")


class TapAlbumAsSongEndsTest(unittest.TestCase):
    """A song running into the next says so up to ~0.3 s later. Tapping a
    shorter album in that window mustn't crash or show the wrong song."""

    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        tracks = []
        for album, count in (("Long", 7), ("Short", 2)):
            for n in range(1, count + 1):
                path = Path(tmp.name) / f"{album}-{n}.wav"
                write_wav(path, 2)
                tracks.append({"path": str(path), "title": f"{album} {n}", "artist": "Band",
                               "duration": 2, "art": "", "album": album, "albumArtist": "",
                               "disc": 0, "track": n})
        self.player = LibraryPlayer(tracks)
        self.addCleanup(self.player._engine._shutdown)
        self.short = next(i for i, a in enumerate(self.player.albums) if a["title"] == "Short")
        self.player.playIndex(5)

    def test_a_join_from_the_old_queue_is_dropped(self):
        engine = self.player._engine
        engine._joined(1, engine._gen, 50)         # the long album's song 2 takes over...
        self.player.playAlbum(self.short, 0)       # ...just as the short album is tapped
        spin(200)
        self.assertEqual(self.player.index, 0)
        self.assertEqual(self.player.title, "Short 1")

    def test_an_index_past_the_queue_is_ignored(self):
        self.player.playAlbum(self.short, 0)
        self.player._engine.trackStarted.emit(6)
        self.assertEqual(self.player.index, 0)
        self.assertEqual(self.player.title, "Short 1")

    def test_a_join_for_the_current_queue_still_shows(self):
        engine = self.player._engine
        engine._joined(6, engine._gen, 50)
        spin(200)
        self.assertEqual(self.player.index, 6)
        self.assertEqual(self.player.title, "Long 7")


def track(path, album, n, artist="Band"):
    return {"path": path, "title": f"{album} {n}", "artist": artist, "duration": 3, "art": "",
            "album": album, "albumArtist": "", "disc": 0, "track": n}


class ResumePointTest(unittest.TestCase):
    """Finding the saved album and song again, with nothing playing."""

    def setUp(self):
        self.tracks = [track(f"/m/{a}-{n}.wav", a, n) for a in ("Blue", "Red") for n in (1, 2, 3)]
        self.albums = group_albums(self.tracks)
        self.red = next(i for i, a in enumerate(self.albums) if a["title"] == "Red")

    def test_album_and_song(self):
        state = {"album": ["Band", "Red"], "path": "/m/Red-2.wav", "index": 1, "position": 81}
        self.assertEqual(resume_point(self.albums, self.tracks, state), (self.red, 1, 81))

    def test_album_names_ignore_case(self):
        state = {"album": ["BAND", "red"], "path": "/m/Red-3.wav", "index": 2, "position": 5}
        self.assertEqual(resume_point(self.albums, self.tracks, state), (self.red, 2, 5))

    def test_a_song_added_since_doesnt_shift_it(self):
        tracks = [track("/m/Red-0.wav", "Red", 0)] + self.tracks
        albums = group_albums(tracks)
        red = next(i for i, a in enumerate(albums) if a["title"] == "Red")
        state = {"album": ["Band", "Red"], "path": "/m/Red-2.wav", "index": 1, "position": 81}
        self.assertEqual(resume_point(albums, tracks, state), (red, 2, 81))

    def test_all_songs(self):
        state = {"album": None, "path": "/m/Red-1.wav", "index": 3, "position": 12}
        self.assertEqual(resume_point(self.albums, self.tracks, state), (-1, 3, 12))

    def test_a_song_thats_gone_keeps_its_place_from_the_start(self):
        state = {"album": ["Band", "Red"], "path": "/m/renamed.wav", "index": 2, "position": 81}
        self.assertEqual(resume_point(self.albums, self.tracks, state), (self.red, 2, 0))

    def test_an_album_thats_gone(self):
        state = {"album": ["Band", "Green"], "path": "/m/Green-2.wav", "index": 1, "position": 81}
        self.assertEqual(resume_point(self.albums, self.tracks, state), (-1, 0, 0))

    def test_nothing_or_junk(self):
        for state in (None, {}, [], {"album": "Red", "index": 99, "position": "x"},
                      {"album": [1], "index": -1, "position": None}):
            self.assertEqual(resume_point(self.albums, self.tracks, state), (-1, 0, 0), state)


class RestoreTest(unittest.TestCase):
    """The real player picking up after a restart."""

    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        tracks = []
        for album in ("Blue", "Red"):
            for n in (1, 2, 3):
                path = Path(tmp.name) / f"{album}-{n}.wav"
                write_wav(path, 3)
                tracks.append(track(str(path), album, n))
        self.tracks = tracks
        self.player = LibraryPlayer(tracks)
        self.addCleanup(self.player._engine._shutdown)

    def test_a_fresh_start_waits_on_the_first_song(self):
        self.player.start()
        spin(300)
        self.assertFalse(self.player.playing)
        self.assertEqual(self.player.title, "Blue 1")

    def test_picks_up_the_album_and_song_paused(self):
        red = next(i for i, a in enumerate(self.player.albums) if a["title"] == "Red")
        state = {"album": ["Band", "Red"], "path": self.tracks[4]["path"], "index": 1, "position": 2}
        self.player.restore(state)
        self.player.start()
        spin(300)
        self.assertFalse(self.player.playing)
        self.assertEqual((self.player.album, self.player.index, self.player.title), (red, 1, "Red 2"))
        self.assertEqual(self.player.position, 2)
        # Saved again as it is, so restarting while paused doesn't creep back.
        self.assertEqual(self.player.state(), state)

    def test_plays_on_if_it_was_playing(self):
        state = {"album": None, "path": self.tracks[1]["path"], "index": 1, "position": 1}
        self.player.restore(state, play=True)
        self.player.start()
        spin(1500)
        self.assertTrue(self.player.playing)
        self.assertEqual(self.player.title, "Blue 2")
        self.assertGreaterEqual(self.player.position, 1)

    def test_play_after_a_paused_restore_goes_on_from_there(self):
        # A FakeSink, pulled by hand: no audio device, no waiting on real time.
        with mock.patch.object(gapless, "QAudioSink", FakeSink):
            player = LibraryPlayer(self.tracks)
            self.addCleanup(player._engine._shutdown)
            player.restore({"album": None, "path": self.tracks[0]["path"], "index": 0, "position": 2})
            player.start()
            spin(300)
            player.togglePlay()
            engine = player._engine
            engine._out.wantDecode.disconnect()      # see test_the_feed_stops_after_the_last_song...
            for _ in range(40):                      # a second of the song's 3 was left
                engine._out.pull(48000 * 4)
                if player.title == "Blue 2":
                    break
                spin(50)
            spin(300)
            self.assertEqual(player.title, "Blue 2")


class EmptyPlayerTest(unittest.TestCase):
    """No songs (an empty folder, or the card not there yet): nothing
    playing, nothing raises, and the resume point it was given survives."""

    SAVED = {"album": ["Band", "Red"], "path": "/m/Red-2.wav", "index": 1, "position": 81}

    def setUp(self):
        self.player = LibraryPlayer([])
        self.addCleanup(self.player._engine._shutdown)
        self.events = []
        for name in ("trackChanged", "positionChanged", "playingChanged", "queueChanged"):
            getattr(self.player, name).connect(lambda n=name: self.events.append(n))

    def test_what_the_screen_reads(self):
        p = self.player
        self.assertEqual((p.title, p.artist, p.art), ("", "", ""))
        self.assertEqual((p.duration, p.position, p.index, p.album), (0, 0, -1, -1))
        self.assertEqual((p.queue, p.albums, p.albumTracks(0), p.albumTracks(-1)), ([], [], [], []))
        self.assertFalse(p.playing)

    def test_every_key_does_nothing(self):
        p = self.player
        p.start()
        for key in (p.togglePlay, p.next, p.previous, p.playAll, p.togglePlay):
            key()
        for index in (0, 3, -1):
            p.playIndex(index)
        for album, start in ((0, 0), (-1, 0), (2, 5)):
            p.playAlbum(album, start)
        spin(200)
        self.assertFalse(p.playing)
        self.assertEqual((p.title, p.index, p.album, p.queue, p.position), ("", -1, -1, [], 0))
        self.assertEqual(self.events, [])

    def test_volume_still_works(self):
        self.player.setVolume(70)
        self.assertEqual(self.player.volume, 70)

    def test_start_leaves_the_audio_engine_alone(self):
        self.player.restore(self.SAVED, play=True)
        with mock.patch.object(self.player._engine, "play_from") as play_from:
            self.player.start()
        play_from.assert_not_called()
        spin(200)
        self.assertFalse(self.player.playing)
        self.assertEqual(self.player.position, 0)

    def test_state_with_nothing_restored_is_a_blank_resume_point(self):
        self.assertEqual(self.player.state(),
                         {"album": None, "path": "", "index": 0, "position": 0})

    def test_state_hands_back_what_restore_was_given(self):
        self.player.restore(self.SAVED)
        self.player.start()
        self.assertEqual(self.player.state(), self.SAVED)
        self.player.state()["index"] = 99            # a copy: saving it can't change it
        self.assertEqual(self.player.state(), self.SAVED)

    def test_junk_given_to_restore_is_a_blank_resume_point(self):
        for junk in (None, [], "x"):
            self.player.restore(junk)
            self.assertEqual(self.player.state()["path"], "", junk)

    def test_no_songs_means_no_resume_point(self):
        self.assertEqual(resume_point([], [], self.SAVED), (-1, 0, 0))


class OrderTest(unittest.TestCase):
    """Which song follows which: shuffle and repeat."""

    def test_play_order(self):
        self.assertEqual(play_order(4, 2, False), [0, 1, 2, 3])
        for first in range(4):
            order = play_order(4, first, True)
            self.assertEqual((order[0], sorted(order)), (first, [0, 1, 2, 3]))
        self.assertEqual(play_order(0, 0, True), [])
        self.assertEqual(sorted(play_order(3, 9, True)), [0, 1, 2])      # a stale first position

    def test_step(self):
        order = [2, 0, 1]
        self.assertEqual((step(order, 2, 1, False), step(order, 0, 1, False)), (0, 1))
        self.assertIsNone(step(order, 1, 1, False))                      # the end, no wrap
        self.assertEqual(step(order, 1, 1, True), 2)                     # round to the first
        self.assertEqual(step(order, 2, -1, True), 1)                    # and back round
        self.assertIsNone(step(order, 2, -1, False))
        self.assertEqual(step(order, 7, 1, False), 2)                    # not in it: the first
        self.assertIsNone(step([], 0, 1, True))


class ModesTest(unittest.TestCase):
    """The real player: what plays after each song, and that the engine follows it.
    The stream is a FakeSink, so this runs the same with or without a working
    audio device."""

    def setUp(self):
        patch = mock.patch.object(gapless, "QAudioSink", FakeSink)
        patch.start()
        self.addCleanup(patch.stop)          # registered first: undone after the engine is shut down
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        tracks = []
        for n in range(1, 5):
            path = Path(tmp.name) / f"Blue-{n}.wav"
            write_wav(path, 1)
            tracks.append(track(str(path), "Blue", n))
        self.player = LibraryPlayer(tracks)
        self.addCleanup(self.player._engine._shutdown)
        self.engine = self.player._engine

    def queued(self):
        """The songs the engine has decoded or lined up, in order."""
        with self.engine._lock:
            return [s.index for s in self.engine._songs]

    def follows(self):
        return [self.player._after(i) for i in range(4)]

    def test_the_default_is_how_it_always_played(self):
        self.assertEqual((self.player.shuffle, self.player.repeat), (False, "all"))
        self.assertEqual(self.follows(), [1, 2, 3, 0])

    def test_repeat_cycles_and_changes_what_follows(self):
        self.player.cycleRepeat()
        self.assertEqual((self.player.repeat, self.follows()), ("one", [0, 1, 2, 3]))
        self.player.cycleRepeat()
        self.assertEqual((self.player.repeat, self.follows()), ("off", [1, 2, 3, None]))
        self.player.cycleRepeat()
        self.assertEqual((self.player.repeat, self.follows()), ("all", [1, 2, 3, 0]))

    def test_shuffle_plays_everything_once_starting_from_this_song(self):
        self.player.playIndex(2)
        self.player.toggleShuffle()
        seen, i = [2], self.player._after(2)
        while i != 2:
            seen.append(i)
            i = self.player._after(i)
        self.assertEqual(sorted(seen), [0, 1, 2, 3])          # all of them, then round again
        self.player.cycleRepeat()
        self.player.cycleRepeat()                             # off
        last = self.player._order[-1]
        self.assertIsNone(self.player._after(last))
        self.player.toggleShuffle()
        self.assertEqual(self.player._order, [0, 1, 2, 3])

    def test_the_keys_still_move_on_whatever_repeat_says(self):
        self.player.cycleRepeat()                             # one
        self.player.playIndex(1)
        self.player.next()
        self.assertEqual(self.player.index, 2)
        self.player.cycleRepeat()                             # off
        self.player.playIndex(3)
        self.player.next()
        self.assertEqual(self.player.index, 0)                # round, not stuck

    def test_next_and_back_follow_the_shuffle_order(self):
        self.player.toggleShuffle()
        order = list(self.player._order)
        self.player.playIndex(order[0])
        self.player._order = order = list(self.player._order)
        self.player.next()
        self.assertEqual(self.player.index, order[1])
        self.player.next()
        self.assertEqual(self.player.index, order[2])

    def test_a_changed_mode_replaces_the_song_lined_up_next(self):
        self.player.start()
        spin(500)                                             # song 0 decoded, song 1 lined up
        self.assertEqual(self.queued(), [0, 1])
        self.player.cycleRepeat()                             # one: 0 again
        spin(500)
        self.assertEqual(self.queued(), [0, 0])
        self.player.cycleRepeat()                             # off
        spin(500)
        self.assertEqual(self.queued(), [0, 1])

    def test_the_feed_stops_after_the_last_song_with_repeat_off(self):
        self.player.cycleRepeat()
        self.player.cycleRepeat()                             # off
        self.player.restore({"album": None, "path": self.player._queue[3]["path"],
                             "index": 3, "position": 0}, play=True)
        self.player.start()
        spin(500)
        self.assertEqual(self.queued(), [3])                  # nothing lined up after it
        ended = []
        self.engine.ended.connect(lambda: ended.append(True))
        # Nothing pulls from the FakeSink: pull here. Its wantDecode would run
        # straight back into the engine under the lock the pull holds (it's queued on the Pi).
        self.engine._out.wantDecode.disconnect()
        for _ in range(40):
            self.engine._out.pull(48000 * 4)
            if not self.queued():
                break
        spin(1500)                                            # until the last of it would be heard
        self.assertTrue(ended)
        self.assertFalse(self.player.playing)
        self.assertEqual(self.player.index, 0)                # back at the first, paused
        self.assertEqual(self.player.title, "Blue 1")

    def test_the_album_play_key_starts_a_shuffle_anywhere_but_a_tapped_song_leads(self):
        self.player.toggleShuffle()
        with mock.patch.object(library.random, "randrange", return_value=2):
            self.player.playAlbum(0, -1)
        self.assertEqual((self.player.index, self.player._order[0]), (2, 2))
        self.player.playAlbum(0, 0)
        self.assertEqual((self.player.index, self.player._order[0]), (0, 0))
        self.player.toggleShuffle()
        self.player.playAlbum(0, -1)
        self.assertEqual(self.player.index, 0)

    def test_a_failed_song_followed_by_a_bad_one_stops_the_feed(self):
        engine = self.engine
        engine._after = lambda i, failed=False: (i + 1) % 2   # two songs, round and round
        self.assertEqual(engine._next(0), 1)
        engine._bad.add(0)
        self.assertEqual(engine._next(0), 1)                  # 1 may still play
        engine._bad.add(1)
        self.assertIsNone(engine._next(0))                    # both failed: stop
        engine._after = lambda i, failed=False: i             # a one-song queue
        engine._bad = {0}
        self.assertIsNone(engine._next(0))

    def test_after_the_end_a_shuffle_starts_from_another_song(self):
        self.player.toggleShuffle()
        self.player.cycleRepeat()
        self.player.cycleRepeat()                             # off
        self.player.playIndex(3)
        with mock.patch.object(library.random, "randrange", return_value=1):
            self.player._ended()
        self.assertEqual((self.player.index, self.player._order[0]), (1, 1))
        self.assertEqual(sorted(self.player._order), [0, 1, 2, 3])
        self.assertFalse(self.player.playing)

    def test_repeat_one_on_a_song_that_will_not_play_moves_on(self):
        self.player.cycleRepeat()                             # one
        self.assertEqual(self.player._after(1), 1)
        self.assertEqual(self.player._after(1, failed=True), 2)
        self.assertEqual(self.player._after(3, failed=True), 0)

    def test_the_engine_does_not_loop_on_a_missing_file(self):
        os.remove(self.player._queue[1]["path"])
        self.player.cycleRepeat()                             # one
        self.player.restore({"album": None, "path": self.player._queue[1]["path"],
                             "index": 1, "position": 0}, play=True)
        self.player.start()
        spin(800)
        self.assertIn(1, self.engine._bad)
        self.assertNotIn(self.queued()[-1], (1,))             # not lined up after itself
        self.assertEqual(self.queued()[-1], 2)

    def test_repeat_one_goes_round_the_same_song(self):
        self.player.cycleRepeat()                             # one
        self.player.restore({"album": None, "path": self.player._queue[1]["path"],
                             "index": 1, "position": 0}, play=True)
        self.player.start()
        spin(500)
        self.assertEqual(self.queued(), [1, 1])

    def test_a_new_album_has_its_own_order(self):
        self.player.toggleShuffle()
        self.player.playAll()
        self.assertEqual(sorted(self.player._order), [0, 1, 2, 3])
        self.assertEqual(self.player._order[0], 0)

    def test_set_modes_ignores_junk(self):
        self.player.set_modes(True, "sideways")
        self.assertEqual((self.player.shuffle, self.player.repeat), (True, "all"))


def song(path, album="Album", track=0, disc=0, artist="Artist", album_artist="", art=""):
    return {"path": path, "title": path, "artist": artist, "album": album, "albumArtist": album_artist,
            "disc": disc, "track": track, "duration": 3, "art": art}


def order(songs):
    """The paths of the first album, in its play order."""
    album = group_albums(songs)[0]
    return [songs[i]["path"] for i in album["tracks"]]


class GroupAlbumsTest(unittest.TestCase):
    def test_numbered_songs_play_in_track_order(self):
        songs = [song("/m/a.mp3", track=3), song("/m/b.mp3", track=1), song("/m/c.mp3", track=2)]
        self.assertEqual(order(songs), ["/m/b.mp3", "/m/c.mp3", "/m/a.mp3"])

    def test_discs_come_before_track_numbers(self):
        songs = [song("/m/a.mp3", disc=2, track=1), song("/m/b.mp3", disc=1, track=2),
                 song("/m/c.mp3", disc=1, track=1), song("/m/d.mp3", disc=2, track=2)]
        self.assertEqual(order(songs), ["/m/c.mp3", "/m/b.mp3", "/m/a.mp3", "/m/d.mp3"])

    def test_no_disc_numbers_is_one_disc(self):
        songs = [song("/m/a.mp3", track=2), song("/m/b.mp3", track=1)]
        self.assertEqual(order(songs), ["/m/b.mp3", "/m/a.mp3"])

    def test_a_missing_track_number_means_the_file_names(self):
        songs = [song("/m/03 c.mp3", track=3), song("/m/01 a.mp3", track=0), song("/m/02 b.mp3", track=2)]
        self.assertEqual(order(songs), ["/m/01 a.mp3", "/m/02 b.mp3", "/m/03 c.mp3"])

    def test_no_numbers_at_all_means_the_file_names(self):
        songs = [song("/m/b.mp3"), song("/m/c.mp3"), song("/m/a.mp3")]
        self.assertEqual(order(songs), ["/m/a.mp3", "/m/b.mp3", "/m/c.mp3"])

    def test_repeated_numbers_mean_the_file_names(self):
        # A deluxe edition whose bonus songs start again at 1, with no disc number.
        songs = [song("/m/1.mp3", track=1), song("/m/2.mp3", track=2), song("/m/3.mp3", track=3),
                 song("/m/4 bonus.mp3", track=1), song("/m/5 bonus.mp3", track=2)]
        songs.reverse()
        self.assertEqual(order(songs), ["/m/1.mp3", "/m/2.mp3", "/m/3.mp3", "/m/4 bonus.mp3", "/m/5 bonus.mp3"])

    def test_the_same_track_numbers_on_two_discs_are_not_a_repeat(self):
        songs = [song("/m/a.mp3", disc=2, track=1), song("/m/b.mp3", disc=1, track=1),
                 song("/m/c.mp3", disc=2, track=2), song("/m/d.mp3", disc=1, track=2)]
        self.assertEqual(order(songs), ["/m/b.mp3", "/m/d.mp3", "/m/a.mp3", "/m/c.mp3"])

    def test_the_same_number_on_the_same_disc_twice_means_the_file_names(self):
        songs = [song("/m/b.mp3", disc=1, track=1), song("/m/a.mp3", disc=1, track=1)]
        self.assertEqual(order(songs), ["/m/a.mp3", "/m/b.mp3"])

    def test_equal_numbers_never_lose_a_song(self):
        songs = [song(f"/m/{n}.mp3", track=1) for n in "cab"]
        self.assertEqual(sorted(group_albums(songs)[0]["tracks"]), [0, 1, 2])

    def test_albums_are_sorted_by_artist_then_title_ignoring_case(self):
        songs = [song("/m/1.mp3", album="Zed", artist="bob"), song("/m/2.mp3", album="Alpha", artist="Bob"),
                 song("/m/3.mp3", album="Zed", artist="Al")]
        self.assertEqual([(a["artist"], a["title"]) for a in group_albums(songs)],
                         [("Al", "Zed"), ("Bob", "Alpha"), ("bob", "Zed")])

    def test_the_album_artist_groups_a_compilation(self):
        songs = [song("/m/1.mp3", album="Hits", artist="One", album_artist="Various"),
                 song("/m/2.mp3", album="Hits", artist="Two", album_artist="Various")]
        albums = group_albums(songs)
        self.assertEqual(len(albums), 1)
        self.assertEqual((albums[0]["artist"], albums[0]["tracks"]), ("Various", [0, 1]))

    def test_albums_with_the_same_name_by_different_artists_stay_apart(self):
        songs = [song("/m/1.mp3", album="Greatest Hits", artist="A"), song("/m/2.mp3", album="Greatest Hits", artist="B")]
        self.assertEqual(len(group_albums(songs)), 2)

    def test_the_cover_is_the_first_one_found(self):
        songs = [song("/m/1.mp3", art=""), song("/m/2.mp3", art="b.jpg"), song("/m/3.mp3", art="c.jpg")]
        self.assertEqual(group_albums(songs)[0]["art"], "b.jpg")

    def test_no_songs_no_albums(self):
        self.assertEqual(group_albums([]), [])


class NumberTest(unittest.TestCase):
    def test_plain_and_padded(self):
        self.assertEqual(_number({"TRCK": ["3"]}, "TRCK"), 3)
        self.assertEqual(_number({"TRCK": ["03"]}, "TRCK"), 3)
        self.assertEqual(_number({"TRCK": " 7"}, "TRCK"), 7)

    def test_of_a_total(self):
        self.assertEqual(_number({"track": ["3/12"]}, "track"), 3)

    def test_an_mp4_pair(self):
        self.assertEqual(_number({"trkn": [(3, 12)]}, "trkn"), 3)

    def test_an_id3_frame(self):
        self.assertEqual(_number({"TRCK": SimpleNamespace(text=["5/9"])}, "TRCK"), 5)

    def test_the_first_key_that_has_a_number(self):
        tags = {"tracknumber": [], "TRCK": ["4"]}
        self.assertEqual(_number(tags, "tracknumber", "TRCK"), 4)

    def test_no_number(self):
        for tags in ({}, {"TRCK": []}, {"TRCK": [""]}, {"TRCK": ["A1"]}, {"TRCK": ["/12"]}, {"TRCK": None}):
            self.assertEqual(_number(tags, "TRCK"), 0, tags)

    def test_a_key_the_tags_refuse(self):
        class Strict(dict):
            def get(self, key, default=None):
                raise ValueError(key)
        self.assertEqual(_number(Strict(), "TRCK"), 0)


if __name__ == "__main__":
    unittest.main()
