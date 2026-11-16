"""Off-Pi tests for LibraryPlayer.upNext: the songs that follow the current
one in the true play order, for the Up next tab and the Playing page's Next row.

    python3 -m unittest tests.test_library_up_next
"""

import os
import tempfile
import unittest
from pathlib import Path

os.environ.setdefault("QT_LOGGING_RULES", "qt.multimedia.ffmpeg*=false")

try:
    from PyQt6.QtCore import QCoreApplication
    from backend.library import LibraryPlayer, UP_NEXT_MAX
    from tests.test_library import track, write_wav
except ImportError as e:
    raise unittest.SkipTest(f"PyQt6 or mutagen isn't installed ({e})")

app = QCoreApplication.instance() or QCoreApplication([])


def set_repeat(player, mode):
    while player.repeat != mode:
        player.cycleRepeat()


def indexes(player):
    return [s["index"] for s in player.upNext]


class UpNextTest(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        tracks = []
        for n in range(1, 6):
            path = Path(tmp.name) / f"Red-{n}.wav"
            write_wav(path, 2)
            tracks.append(track(str(path), "Red", n))
        self.player = LibraryPlayer(tracks)
        self.addCleanup(self.player._engine._shutdown)
        set_repeat(self.player, "off")
        self.player.playIndex(1)

    def test_in_folder_order_after_the_current_song(self):
        self.assertEqual(indexes(self.player), [2, 3, 4])
        self.assertEqual(self.player.upNext[0]["title"], "Red 3")

    def test_repeat_all_wraps_round_to_the_start(self):
        p = self.player
        set_repeat(p, "all")
        self.assertEqual(indexes(p), [2, 3, 4, 0])

    def test_repeat_off_at_the_last_song_is_empty(self):
        p = self.player
        p.playIndex(4)
        self.assertEqual(indexes(p), [])

    def test_shuffle_follows_the_play_order(self):
        p = self.player
        p.toggleShuffle()
        self.assertTrue(p.shuffle)
        at = p._order.index(p.index)
        tail = p._order[at + 1:]
        self.assertEqual(indexes(p), tail)
        self.assertNotIn(p.index, indexes(p))

    def test_toggling_shuffle_and_moving_on_announce_the_change(self):
        p = self.player
        seen = []
        p.upNextChanged.connect(lambda: seen.append(1))
        p.toggleShuffle()
        self.assertTrue(seen)
        seen.clear()
        p.next()
        self.assertTrue(seen)
        seen.clear()
        p.cycleRepeat()
        self.assertTrue(seen)

    def test_never_more_than_the_cap(self):
        self.assertLessEqual(len(self.player.upNext), UP_NEXT_MAX)


if __name__ == "__main__":
    unittest.main()
