"""Off-Pi tests for the music library (backend/library.py) and its gapless
engine, with short silent WAV files. The player really plays (silence).

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
    from backend.library import LibraryPlayer, scan
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


if __name__ == "__main__":
    unittest.main()
