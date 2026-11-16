"""Off-Pi tests for the music library (backend/library.py) and its gapless
engine, with short silent WAV files. The player really plays (silence).
Also where it picks up after a restart.

    python3 -m unittest tests.test_library
"""

import json
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
    from PyQt6.QtCore import QCoreApplication, QEventLoop, QObject, QThread, QTimer, QUrl, pyqtSignal
    from PyQt6.QtMultimedia import QAudio
    from backend import gapless, library
    from backend.library import (LibraryPlayer, LibraryScanner, _listing, _number, _walk, cached_tracks, group_albums,
                                 play_order, resume_point, scan, signature, step)
except ImportError as e:
    raise unittest.SkipTest(f"PyQt6 or mutagen isn't installed ({e})")

app = QCoreApplication.instance() or QCoreApplication([])


class FakeSink(QObject):
    """Stands in for QAudioSink, so nothing here depends on the Mac's (or CI's)
    audio device: it never takes any samples."""
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

    def start(self):
        return None             # no device to write to: nothing plays by itself

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


class ScanBase(unittest.TestCase):
    """A temporary folder to make songs in, and a cache dir that isn't the real one."""

    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.root = Path(tmp.name)
        env = mock.patch.dict(os.environ, {"XDG_CACHE_HOME": str(self.root / "cache")})
        env.start()
        self.addCleanup(env.stop)

    def songs(self, count, per_folder):
        """`count` tiny songs, `per_folder` to a folder; returns the folder."""
        top = self.root / f"{count}-{per_folder}"
        for i in range(count):
            folder = top / f"album {i // per_folder:03}"
            folder.mkdir(parents=True, exist_ok=True)
            write_wav(folder / f"{i:05}.wav", 0.001)
        return top


class ScanTest(ScanBase):
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


class ScanCacheTest(ScanBase):
    """The tag cache: unchanged files aren't read again."""

    def setUp(self):
        super().setUp()
        self.top = self.songs(4, 2)
        self.file = self.top / "album 000" / "00000.wav"

    def reads(self):
        """How many files a scan opens with mutagen."""
        with mock.patch.object(library.mutagen, "File", wraps=library.mutagen.File) as read:
            self.tracks = scan(self.top)
        return read.call_count

    def test_the_second_scan_reads_nothing(self):
        self.assertEqual(self.reads(), 4)
        first = self.tracks
        self.assertEqual(self.reads(), 0)
        self.assertEqual(self.tracks, first)

    def test_a_changed_file_is_read_again_and_a_new_one_too(self):
        self.reads()
        write_wav(self.file, 0.002)              # other size and time
        write_wav(self.top / "album 000" / "new.wav", 0.001)
        self.assertEqual(self.reads(), 2)
        self.assertEqual(len(self.tracks), 5)

    def test_a_vanished_file_drops_out_for_good(self):
        self.reads()
        self.file.unlink()
        self.assertEqual(self.reads(), 0)
        self.assertEqual(len(self.tracks), 3)
        self.assertEqual(len(cached_tracks(self.top)), 3)

    def test_a_failed_read_doesnt_hide_a_song_for_good(self):
        with mock.patch.object(library, "_extract_art", side_effect=OSError("disk full")), \
                mock.patch("builtins.print"):
            self.assertEqual(scan(self.top), [])
        self.assertEqual(self.reads(), 4)
        self.assertEqual(len(self.tracks), 4)

    def test_a_cover_that_cant_be_saved_costs_the_cover_not_the_song(self):
        (self.top / "album 000" / "cover.jpg").write_bytes(b"jpeg")
        audio = SimpleNamespace(tags={}, pictures=[SimpleNamespace(data=b"img")],
                                info=SimpleNamespace(length=1.0))
        with mock.patch.object(library.mutagen, "File", return_value=audio), \
                mock.patch.object(library.artcache, "store_pinned", side_effect=OSError("disk full")), \
                mock.patch("builtins.print"):
            tracks = scan(self.top)
        self.assertEqual(len(tracks), 4)
        self.assertTrue(tracks[0]["art"].endswith("/album 000/cover.jpg"))   # the folder's picture
        self.assertEqual(tracks[3]["art"], "")

    def test_an_art_folder_that_cant_be_made_on_a_rescan_keeps_the_songs(self):
        audio = SimpleNamespace(tags={}, pictures=[SimpleNamespace(data=b"img")],
                                info=SimpleNamespace(length=1.0))
        with mock.patch.object(library.mutagen, "File", return_value=audio):
            self.assertEqual(len(scan(self.top)), 4)          # covers cached in the art folder
            with mock.patch.object(library.artcache, "pinned_dir",
                                   side_effect=OSError("read-only")), \
                    mock.patch("builtins.print"):
                tracks = scan(self.top)
        self.assertEqual(len(tracks), 4)

    def test_an_unreadable_folder_has_no_folder_art(self):
        with mock.patch.object(Path, "iterdir", side_effect=PermissionError("denied")):
            self.assertEqual(library._folder_art(self.top), "")
        self.assertEqual(len(scan(self.top)), 4)

    def test_an_unreadable_file_is_read_again_each_scan(self):
        self.reads()
        self.file.write_bytes(b"this is no song")
        self.assertEqual(self.reads(), 1)
        self.assertEqual(self.reads(), 1)
        self.assertEqual(len(self.tracks), 3)

    def test_saving_clears_temp_files_a_crash_left(self):
        self.reads()
        stale, fresh = (library.cache_file().parent / n for n in (".tmp-old", ".tmp-new"))
        stale.write_text("{")
        fresh.write_text("{")
        os.utime(stale, (0, 0))
        write_wav(self.file, 0.002)              # so there's something to save
        self.reads()
        self.assertFalse(stale.exists())
        self.assertTrue(fresh.exists())          # another save may be under way

    def test_a_corrupt_cache_is_ignored_and_replaced(self):
        self.reads()
        library.cache_file().write_text("{not json")
        self.assertEqual(cached_tracks(self.top), [])
        self.assertEqual(self.reads(), 4)
        self.assertEqual(len(cached_tracks(self.top)), 4)
        library.cache_file().write_text('{"version": 99, "folder": "x", "files": 3}')
        self.assertEqual(self.reads(), 4)

    def test_the_cache_is_for_one_folder(self):
        self.reads()
        self.assertEqual(cached_tracks(self.root), [])
        self.assertEqual(len(cached_tracks(self.top)), 4)

    def test_a_missing_embedded_cover_is_extracted_again(self):
        self.reads()
        cover = self.root / "cache" / "baja-os" / "library-art" / "x.img"
        cover.parent.mkdir(parents=True, exist_ok=True)
        cover.write_bytes(b"img")
        cache = library._load_cache(self.top)
        entry = cache[str(self.file)]
        entry["embedded"], entry["track"]["art"] = True, cover.as_uri()
        library._save_cache(self.top, cache)
        self.assertEqual(self.reads(), 0)        # picture still there: reused
        cover.unlink()
        self.assertEqual(self.reads(), 1)        # gone: this file is read again

    def test_an_empty_embedded_cover_is_written_again_on_a_rescan(self):
        audio = SimpleNamespace(tags={}, pictures=[SimpleNamespace(data=b"img")],
                                info=SimpleNamespace(length=1.0))
        with mock.patch.object(library.mutagen, "File", return_value=audio):
            tracks = scan(self.top)
            cover = Path(QUrl(tracks[0]["art"]).toLocalFile())
            self.assertEqual(cover.read_bytes(), b"img")
            cover.write_bytes(b"")               # a power cut after the rename, before the data
            tracks = scan(self.top)
        self.assertEqual(cover.read_bytes(), b"img")
        self.assertEqual(QUrl(tracks[0]["art"]).toLocalFile(), str(cover))

    def test_a_cover_added_later_reaches_cached_songs(self):
        self.reads()
        (self.top / "album 000" / "cover.jpg").write_bytes(b"jpeg")
        self.assertEqual(self.reads(), 0)
        self.assertTrue(self.tracks[0]["art"].endswith("/album 000/cover.jpg"))
        self.assertTrue(cached_tracks(self.top)[0]["art"].endswith("/album 000/cover.jpg"))   # and saved

    def test_an_empty_scan_doesnt_wipe_the_cache(self):
        self.reads()
        moved = self.root / "away"
        self.top.rename(moved)                   # the card is gone
        self.assertEqual(scan(self.top), [])
        moved.rename(self.top)
        self.assertEqual(len(cached_tracks(self.top)), 4)

    def test_cached_tracks_need_the_folder_and_its_songs(self):
        self.reads()
        self.assertEqual(len(cached_tracks(self.top)), 4)
        moved = self.root / "away"
        self.top.rename(moved)
        self.assertEqual(cached_tracks(self.top), [])         # not mounted: honestly empty
        moved.rename(self.top)
        for f in self.top.rglob("*.wav"):
            f.unlink()
        self.assertEqual(cached_tracks(self.top), [])         # mounted but no songs

    def test_a_cached_entry_of_the_wrong_kind_is_dropped_and_read_again(self):
        self.reads()
        cache = library._load_cache(self.top)
        entries = [cache[str(self.file)]["track"], cache[str(self.file.parent / "00001.wav")]["track"]]
        entries[0]["duration"] = "3"
        entries[1]["title"] = 7
        library._save_cache(self.top, cache)
        self.assertEqual(len(cached_tracks(self.top)), 2)
        self.assertEqual(self.reads(), 2)
        self.assertEqual(len(cached_tracks(self.top)), 4)

    def test_signature_changes_with_the_files(self):
        before = signature(self.top)
        self.assertEqual(signature(self.top), before)
        write_wav(self.file, 0.002)
        self.assertNotEqual(signature(self.top), before)


class WalkTest(ScanBase):
    def make_tree(self):
        top = self.root / "tree"
        for d in ("b", "a", "a.x", "a/deep"):
            (top / d).mkdir(parents=True, exist_ok=True)
        for name in ("b/2.mp3", "a/1.WAV", "a.x/3.flac", "a/deep/4.ogg", "a/cover.JPG",
                     "a/notes.txt", "a/x.nfo", "b/no_suffix", "top.png"):
            (top / name).write_bytes(b"x")
        (top / "a" / "folder.mp3").mkdir()              # a folder named like a song
        return top

    def test_walk_yields_only_audio_and_covers_in_path_order(self):
        top = self.make_tree()
        got = [p for p, st in _walk(top)]
        want = sorted(p for p in top.rglob("*") if p.is_file()
                      and p.suffix.lower() in (".mp3", ".wav", ".flac", ".ogg", ".jpg", ".png"))
        self.assertEqual(got, want)
        self.assertEqual(len(got), 6)
        self.assertTrue(all(st.st_size == 1 for _, st in _walk(top)))

    def test_symlinked_files_are_listed_and_symlinked_folders_are_not_entered(self):
        top = self.make_tree()
        (top / "link.mp3").symlink_to(top / "b" / "2.mp3")
        (top / "linkdir").symlink_to(top / "a", target_is_directory=True)
        (top / "dangling.mp3").symlink_to(top / "missing.mp3")
        got = [str(p.relative_to(top)) for p, _ in _walk(top)]
        self.assertIn("link.mp3", got)
        self.assertNotIn("dangling.mp3", got)
        self.assertFalse(any(g.startswith("linkdir") for g in got))

    def test_an_unreadable_or_missing_folder_is_skipped(self):
        top = self.make_tree()
        self.assertEqual(list(_walk(self.root / "nope")), [])
        real = os.scandir

        def scandir(path):
            if str(path).endswith("deep"):
                raise PermissionError(path)
            return real(path)
        with mock.patch.object(library.os, "scandir", scandir):
            got = [p.name for p, _ in _walk(top)]
        self.assertNotIn("4.ogg", got)
        self.assertIn("1.WAV", got)

    def test_signature_and_scan_with_a_listing_match_the_plain_calls(self):
        top = self.songs(6, 3)
        listing = _listing(top)
        self.assertEqual(signature(top), {str(p): (st.st_mtime_ns, st.st_size) for p, st in listing})
        with mock.patch.object(library, "_walk", side_effect=AssertionError("walked again")):
            given = scan(top, listing)
        self.assertEqual(given, scan(top))


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
        engine._joined(1, engine._gen, engine._epoch, 50)         # the long album's song 2 takes over...
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
        engine._joined(6, engine._gen, engine._epoch, 50)
        spin(200)
        self.assertEqual(self.player.index, 6)
        self.assertEqual(self.player.title, "Long 7")


def track(path, album, n, artist="Band"):
    return {"path": path, "title": f"{album} {n}", "artist": artist, "duration": 3, "art": "",
            "album": album, "albumArtist": "", "disc": 0, "track": n}


class ResumePointTest(unittest.TestCase):
    """Finding the saved album and song again, with nothing playing."""

    def setUp(self):
        # Long enough that the saved positions below are inside the song.
        self.tracks = [dict(track(f"/m/{a}-{n}.wav", a, n), duration=200)
                       for a in ("Blue", "Red") for n in (1, 2, 3)]
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

    def test_a_damaged_position_is_zero_and_never_raises(self):
        # json.loads turns NaN, Infinity and 1e999 into floats; a bool is not a number.
        for position in (float("nan"), float("inf"), float("-inf"), json.loads("1e999"),
                         json.loads("NaN"), json.loads("Infinity"), True, False, -5, -0.5):
            state = {"album": ["Band", "Red"], "path": "/m/Red-2.wav", "index": 1, "position": position}
            self.assertEqual(resume_point(self.albums, self.tracks, state), (self.red, 1, 0), position)

    def test_a_position_past_the_end_is_clamped_to_the_last_second(self):
        # The test songs are 200 s long, so the last second they can start at is 199.
        for position in (10 ** 9, 200, 199.9, json.loads("1" + "0" * 400)):
            state = {"album": ["Band", "Red"], "path": "/m/Red-2.wav", "index": 1, "position": position}
            self.assertEqual(resume_point(self.albums, self.tracks, state), (self.red, 1, 199), position)

    def test_a_song_with_no_known_length_keeps_its_saved_position(self):
        # mutagen reports 0 for some playable files; that must not force 0:00.
        tracks = [dict(t, duration=0) for t in self.tracks]
        albums = group_albums(tracks)
        red = next(i for i, a in enumerate(albums) if a["title"] == "Red")
        for position, want in ((125, 125), (125.9, 125), (10 ** 6, 10 ** 6), (-3, 0),
                               (float("nan"), 0), (float("inf"), 0)):
            state = {"album": ["Band", "Red"], "path": "/m/Red-2.wav", "index": 1, "position": position}
            self.assertEqual(resume_point(albums, tracks, state), (red, 1, want), position)

    def test_a_position_within_the_song_is_kept(self):
        state = {"album": ["Band", "Red"], "path": "/m/Red-2.wav", "index": 1, "position": 1.9}
        self.assertEqual(resume_point(self.albums, self.tracks, state), (self.red, 1, 1))

    def test_index_true_is_treated_as_a_missing_index(self):
        missing = {"album": ["Band", "Red"], "index": None}
        as_true = {"album": ["Band", "Red"], "index": True}
        self.assertEqual(resume_point(self.albums, self.tracks, as_true),
                         resume_point(self.albums, self.tracks, missing))
        self.assertEqual(resume_point(self.albums, self.tracks, as_true), (self.red, 0, 0))


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
        # A FakeSink: with a real device the position is what has been heard,
        # so until the device drains its buffer it reads under the saved place
        # (0 for a song restored 1 s in). That made this test depend on the
        # audio device's timing.
        state = {"album": None, "path": self.tracks[1]["path"], "index": 1, "position": 1}
        with mock.patch.object(gapless, "QAudioSink", FakeSink):
            player = LibraryPlayer(self.tracks)
            self.addCleanup(player._engine._shutdown)
            player.restore(state, play=True)
            player.start()
            spin(300)
            self.assertTrue(player.playing)
            self.assertEqual(player.title, "Blue 2")
            self.assertGreaterEqual(player.position, 1)

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


class SetTracksTest(unittest.TestCase):
    """Swapping in a scan's songs while playing, and starting from nothing."""

    def setUp(self):
        patch = mock.patch.object(gapless, "QAudioSink", FakeSink)
        patch.start()
        self.addCleanup(patch.stop)
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.tracks = []
        for album in ("Blue", "Red"):
            for n in range(1, 4):
                path = Path(tmp.name) / f"{album}-{n}.wav"
                write_wav(path, 1)
                self.tracks.append(track(str(path), album, n))

    def player(self, tracks, **kw):
        player = LibraryPlayer(tracks, **kw)
        self.addCleanup(player._engine._shutdown)
        return player

    def test_the_song_keeps_playing_when_songs_are_added_before_it(self):
        player = self.player(self.tracks[3:])             # Red only
        player.playAll()
        player.playIndex(1)
        path = player._queue[1]["path"]
        seen = []
        player.libraryChanged.connect(lambda: seen.append("albums"))
        with mock.patch.object(player._engine, "play_from") as restart:
            player.set_tracks(self.tracks)                # Blue arrives, sorts first
        restart.assert_not_called()
        self.assertEqual(seen, ["albums"])
        self.assertEqual(player._queue[player.index]["path"], path)
        self.assertEqual(len(player.queue), 6)
        self.assertEqual(len(player.albums), 2)
        self.assertEqual(player._engine._songs[0].index, player.index)
        self.assertEqual(player._order, list(range(6)))

    def test_an_album_stays_the_queue_and_its_index_follows(self):
        player = self.player(self.tracks[3:])
        player.playAlbum(0, 1)
        path = player._queue[1]["path"]
        player.set_tracks(self.tracks)
        self.assertEqual(player.albums[player.album]["title"], "Red")
        self.assertEqual(len(player.queue), 3)
        self.assertEqual(player._queue[player.index]["path"], path)

    def test_a_song_that_vanishes_but_isnt_playing_just_goes(self):
        player = self.player(self.tracks)
        player.playIndex(4)
        path = player._queue[4]["path"]
        player.set_tracks(self.tracks[:2] + self.tracks[3:])
        self.assertEqual(player._queue[player.index]["path"], path)
        self.assertEqual(len(player.queue), 5)

    def hear(self, player):
        """Spin until the song playing has audio decoded (it is being heard)."""
        for _ in range(50):
            if player._engine.sounding():
                return
            spin(20)
        self.fail("the song never decoded")

    def test_when_the_song_playing_vanishes_the_queue_is_left_alone(self):
        player = self.player(self.tracks)
        player.playIndex(1)
        self.hear(player)
        player.set_tracks(self.tracks[3:])
        self.assertEqual((player.index, len(player.queue)), (1, 6))
        self.assertEqual(len(player.albums), 1)
        self.assertEqual(player.album, -1)                 # the queue is no longer the new albums
        self.assertEqual(player.title, "Blue 2")

    def test_when_nothing_is_heard_a_vanished_song_restarts_from_the_new_songs(self):
        player = self.player(self.tracks)
        player.restore({"album": None, "path": self.tracks[1]["path"], "index": 1, "position": 0})
        player.start()                                     # restored, paused
        self.assertFalse(player._engine.sounding())
        player.set_tracks(self.tracks[3:])                 # all of Blue deleted
        paths = [t["path"] for t in self.tracks[3:]]
        self.assertEqual([t["path"] for t in player._queue], paths)
        self.assertEqual((player.index, player.playing), (1, False))   # its place in the queue
        self.assertEqual(player.title, "Red 2")
        self.assertEqual(player._engine._songs[0].index, 1)
        self.assertEqual(len(player.albums), 1)

    def test_a_vanished_paused_song_keeps_its_album_when_that_still_exists(self):
        player = self.player(self.tracks)
        player.playAlbum(1, 1)                             # Red 2
        player._engine.set_playing(False)                  # paused
        player.set_tracks([t for t in self.tracks if not t["path"].endswith("Red-2.wav")])
        self.assertEqual(player.albums[player.album]["title"], "Red")
        self.assertEqual((player.index, player.playing, player.title), (1, False, "Red 3"))
        self.assertEqual(len(player.queue), 2)

    def test_the_same_songs_or_none_change_nothing(self):
        player = self.player(self.tracks)
        seen = []
        player.libraryChanged.connect(lambda: seen.append(1))
        player.set_tracks(list(self.tracks))
        player.set_tracks([])                              # the card went
        self.assertEqual((seen, len(player.albums)), ([], 2))

    def test_an_empty_player_starts_from_the_saved_state(self):
        player = self.player([], scanning=True)
        player.set_modes(True, "off")
        state = {"album": ["Band", "Red"], "path": self.tracks[4]["path"], "index": 1, "position": 2}
        player.restore(state, play=True)
        player.start()                                     # nothing yet
        self.assertEqual((player.index, player.state()["path"]), (-1, state["path"]))
        seen = []
        names = ("libraryChanged", "queueChanged", "trackChanged", "scanningChanged")
        for name in names:
            getattr(player, name).connect(lambda n=name: seen.append(n))
        player.set_tracks(self.tracks)
        self.assertFalse(player.scanning)
        self.assertEqual(player.albums[player.album]["title"], "Red")
        self.assertEqual((player.index, player.title, player.playing), (1, "Red 2", True))
        self.assertEqual(player._engine._songs[0].index, 1)
        self.assertEqual(player._order[0], 1)
        for name in names:
            self.assertIn(name, seen)

    def test_songs_found_after_another_source_took_over_dont_play(self):
        player = self.player([], scanning=True)
        player.restore({"album": None, "path": self.tracks[1]["path"], "index": 1, "position": 0}, play=True)
        player.cancel_autoplay()                           # the hub moved to Spotify or the phone
        player.set_tracks(self.tracks)
        self.assertEqual((player.index, player.playing), (1, False))

    def test_a_retagged_playing_song_is_announced(self):
        player = self.player(self.tracks)
        player.playIndex(1)
        seen = []
        player.trackChanged.connect(lambda: seen.append(player.title))
        changed = [dict(t) for t in self.tracks]
        changed[1]["title"] = "Blue Two"
        player.set_tracks(changed)
        self.assertEqual((player.index, seen), (1, ["Blue Two"]))

    def joined_after_swap(self, pending):
        """A song's "now playing" is on its way (50 ms) when songs arrive
        before it: the number it reports must be the new one."""
        player = self.player(self.tracks[3:])
        engine = player._engine
        if pending:
            engine._gain = 1.0                             # sounding: a switch waits for the fade
        player.playIndex(1)
        if pending:
            self.assertIsNotNone(engine._pending)
        started = []
        engine.trackStarted.connect(started.append)
        engine._joined(1, engine._gen, engine._epoch, 50)
        player.set_tracks(self.tracks)                     # Blue arrives first: song 1 is now 4
        spin(200)
        self.assertEqual(started, [4])
        engine._gain = 0.0

    def test_a_join_on_its_way_follows_the_renumbering(self):
        self.joined_after_swap(pending=False)

    def test_a_join_on_its_way_follows_a_pending_switch(self):
        self.joined_after_swap(pending=True)

    def test_the_new_list_is_swapped_in_under_the_engine_lock(self):
        player = self.player(self.tracks[3:])
        engine = player._engine
        held = []
        real = player._reorder
        player._reorder = lambda: (held.append(engine._lock.locked()), real())
        player.set_tracks(self.tracks)
        self.assertEqual(held, [True])

    def test_an_empty_player_with_no_saved_state_waits_paused(self):
        player = self.player([], scanning=True)
        player.set_tracks(self.tracks)
        self.assertEqual((player.index, player.playing, len(player.queue)), (0, False, 6))

    def test_scanning_ends_even_when_nothing_is_found(self):
        player = self.player([], scanning=True)
        player.set_tracks([])
        self.assertFalse(player.scanning)
        self.assertEqual(player.index, -1)


class ScannerTest(ScanBase):
    def setUp(self):
        super().setUp()
        self.top = self.songs(3, 3)
        self.got = []
        self.threads = []

    def scanner(self, **kw):
        s = LibraryScanner(self.top, **kw)

        def got(tracks):
            self.got.append(len(tracks))
            self.threads.append(QThread.currentThread())
        s.found.connect(got)
        self.addCleanup(s.stop)
        return s

    def wait_for(self, count):
        end = time.monotonic() + 5
        while len(self.got) < count and time.monotonic() < end:
            spin(20)

    def test_delivers_once_on_the_ui_thread_and_not_again_while_nothing_changes(self):
        s = self.scanner(interval=0.05)
        s.start()
        self.wait_for(1)
        spin(300)                                          # several unchanged passes
        self.assertEqual(self.got, [3])
        self.assertIs(self.threads[0], app.thread())

    def test_a_pass_walks_the_folder_once(self):
        s = self.scanner(interval=3600)
        with mock.patch.object(library, "_walk", wraps=library._walk) as walk:
            s.start()
            self.wait_for(1)
        self.assertEqual(self.got, [3])
        self.assertEqual(walk.call_count, 1)

    def test_a_change_is_picked_up(self):
        s = self.scanner(interval=0.05)
        s.start()
        self.wait_for(1)
        write_wav(self.top / "album 000" / "extra.wav", 0.001)
        self.wait_for(2)
        self.assertEqual(self.got, [3, 4])

    def test_stops_cleanly_and_delivers_nothing_after(self):
        s = self.scanner(interval=0.05)
        s.start()
        self.wait_for(1)
        s.stop()
        self.assertFalse(s._thread.is_alive())
        write_wav(self.top / "album 000" / "late.wav", 0.001)
        spin(300)
        self.assertEqual(self.got, [3])

    def test_a_failing_scan_is_logged_and_the_worker_goes_on(self):
        s = self.scanner(interval=0.05)
        with mock.patch.object(library, "scan", side_effect=[OSError("boom"), [{}]]), \
                mock.patch("builtins.print") as log:
            s.start()
            self.wait_for(1)
        self.assertEqual(self.got, [1])
        self.assertTrue(any("scan failed" in str(c) for c in log.call_args_list))


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

    def test_seek_shows_where_it_is_going_and_stays_inside_the_song(self):
        self.player.playIndex(0)
        self.player.seek(-3)                         # clamped to the start
        self.assertEqual(self.player.position, 0)
        with mock.patch.object(self.engine, "seek") as seek:
            self.player.seek(99)
            seek.assert_called_once_with(max(0, self.player.duration - 1))

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
