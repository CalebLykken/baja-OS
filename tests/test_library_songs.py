"""Off-Pi tests for the Songs tab (LibraryPlayer.songs / playSong).

    python3 -m unittest tests.test_library_songs
"""

import os
import tempfile
import unittest
from pathlib import Path

os.environ.setdefault("QT_LOGGING_RULES", "qt.multimedia.ffmpeg*=false")

try:
    from PyQt6.QtCore import QCoreApplication
    from backend.library import LibraryPlayer
    from tests.test_library import spin, track, write_wav
except ImportError as e:
    raise unittest.SkipTest(f"PyQt6 or mutagen isn't installed ({e})")

app = QCoreApplication.instance() or QCoreApplication([])


class SongsTest(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        tracks = []
        for album, titles in (("Red", ["zebra", "Apple", "mango"]), ("Blue", ["Banana", "apricot"])):
            for n, title in enumerate(titles, 1):
                path = Path(tmp.name) / f"{album}-{n}.wav"
                write_wav(path, 2)
                t = track(str(path), album, n)
                t["title"] = title
                tracks.append(t)
        self.player = LibraryPlayer(tracks)
        self.addCleanup(self.player._engine._shutdown)

    def test_sorted_by_title_ignoring_case(self):
        titles = [s["title"] for s in self.player.songs]
        self.assertEqual(titles, ["Apple", "apricot", "Banana", "mango", "zebra"])

    def test_each_index_points_at_its_track(self):
        p = self.player
        for s in p.songs:
            self.assertEqual(p._all[s["index"]]["title"], s["title"])
            self.assertEqual(p._all[s["index"]]["artist"], s["artist"])

    def test_play_song_queues_every_song_from_it(self):
        p = self.player
        want = p.songs[3]
        p.playSong(want["index"])
        spin(100)
        self.assertEqual(p.album, -1)
        self.assertEqual(len(p.queue), 5)
        self.assertEqual(p.index, want["index"])
        self.assertEqual(p.title, want["title"])

    def test_play_song_while_an_album_was_playing(self):
        p = self.player
        p.playAlbum(0, 0)
        self.assertNotEqual(p.album, -1)
        p.playSong(2)
        spin(100)
        self.assertEqual((p.album, len(p.queue), p.index), (-1, 5, 2))

    def test_out_of_range_does_nothing(self):
        p = self.player
        p.playAlbum(0, 0)
        before = (p.album, len(p.queue), p.index)
        p.playSong(-1)
        p.playSong(5)
        self.assertEqual((p.album, len(p.queue), p.index), before)

    def test_no_songs(self):
        p = LibraryPlayer([])
        self.addCleanup(p._engine._shutdown)
        p.playSong(0)
        self.assertEqual((p.songs, p.queue), ([], []))


if __name__ == "__main__":
    unittest.main()
