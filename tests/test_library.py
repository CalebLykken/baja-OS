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
from unittest import mock

# Qt's FFmpeg backend prints every file's tags (main.py does the same).
os.environ.setdefault("QT_LOGGING_RULES", "qt.multimedia.ffmpeg*=false")

try:
    from PyQt6.QtCore import QCoreApplication, QEventLoop, QTimer
    from backend import library
    from backend.library import LibraryPlayer, group_albums, resume_point, scan
except ImportError as e:
    raise unittest.SkipTest(f"PyQt6 or mutagen isn't installed ({e})")

app = QCoreApplication.instance() or QCoreApplication([])


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
        self.player.restore({"album": None, "path": self.tracks[0]["path"], "index": 0, "position": 2})
        self.player.start()
        spin(200)
        self.player.togglePlay()
        spin(1500)
        # A second of the song's 3 was left: on into the next one.
        self.assertEqual(self.player.title, "Blue 2")


if __name__ == "__main__":
    unittest.main()
