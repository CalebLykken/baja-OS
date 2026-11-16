"""Off-Pi tests for the Albums tab's Shuffle all and Play all keys
(LibraryPlayer.shuffleAll / playAll).

    python3 -m unittest tests.test_library_play_all
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


class PlayAllTest(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        tracks = []
        for album, count in (("Red", 4), ("Blue", 3)):
            for n in range(1, count + 1):
                path = Path(tmp.name) / f"{album}-{n}.wav"
                write_wav(path, 2)
                tracks.append(track(str(path), album, n))
        self.player = LibraryPlayer(tracks)
        self.addCleanup(self.player._engine._shutdown)

    def test_shuffle_all_leaves_the_album_for_every_song(self):
        p = self.player
        p.playAlbum(0, 0)
        self.assertEqual(len(p.queue), 3 if p.albums[0]["title"] == "Blue" else 4)
        p.shuffleAll()
        spin(100)
        self.assertEqual(p.album, -1)
        self.assertEqual(len(p.queue), 7)
        self.assertTrue(p.shuffle)
        self.assertTrue(0 <= p.index < 7)

    def test_play_all_starts_from_the_first_and_keeps_the_modes(self):
        p = self.player
        p.playAlbum(0, 0)
        p.playAll()
        spin(100)
        self.assertEqual((p.album, p.index, p.shuffle), (-1, 0, False))
        self.assertEqual(len(p.queue), 7)
        p.toggleShuffle()
        p.playAlbum(1, 0)
        p.playAll()
        self.assertEqual((p.album, p.index, p.shuffle), (-1, 0, True))

    def test_both_do_nothing_with_no_songs(self):
        p = LibraryPlayer([])
        self.addCleanup(p._engine._shutdown)
        p.shuffleAll()
        p.playAll()
        self.assertEqual((p.album, p.index, p.queue, p.shuffle), (-1, -1, [], False))


if __name__ == "__main__":
    unittest.main()
