"""Off-Pi test: the hub forwards the demo player's albums to the UI.

    python3 -m unittest tests.test_demo_albums
"""

import os
import unittest
from unittest import mock

os.environ.setdefault("QT_LOGGING_RULES", "qt.multimedia.ffmpeg*=false")

try:
    from PyQt6.QtCore import QCoreApplication, QObject, pyqtSignal
    from backend.hub import MediaHub
    from backend.media import DEMO_ALBUMS, MediaPlayer
    from tests.test_hub import FakeSettings, FakeSource, saved
except ImportError as e:
    raise unittest.SkipTest(f"PyQt6 isn't installed ({e})")

app = QCoreApplication.instance() or QCoreApplication([])


class HubDemoAlbumsTest(unittest.TestCase):
    def setUp(self):
        self.local = MediaPlayer()
        self.addCleanup(self.local._timer.stop)
        with mock.patch("backend.hub.shutil.which", return_value=None):
            self.hub = MediaHub(self.local, FakeSource(), FakeSource(),
                                settings=FakeSettings(music=saved("local", False)))
        self.hub.start()

    def test_albums_and_tracks_are_forwarded(self):
        self.assertEqual(len(self.hub.albums), len(DEMO_ALBUMS))
        self.assertEqual(self.hub.albumTracks(0), self.local.albumTracks(0))
        self.assertEqual(self.hub.albumTracks(9), [])

    def test_play_album_shows_as_playing_from_the_album(self):
        seen = []
        self.hub.queueChanged.connect(lambda: seen.append(1))
        self.hub.playAlbum(1)
        self.assertEqual(self.hub.album, 1)
        self.assertEqual(len(self.hub.queue), len(DEMO_ALBUMS[1]["tracks"]))
        self.assertTrue(seen)
        self.hub.playAll()
        self.assertEqual(self.hub.album, -1)


if __name__ == "__main__":
    unittest.main()
