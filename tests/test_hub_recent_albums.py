"""Off-Pi tests for the recently played albums (MediaHub.recentAlbums): kept
by artist and title in the 'recentAlbums' setting, newest first, at most 8.

    python3 -m unittest tests.test_hub_recent_albums
"""

import json
import unittest
from unittest import mock

try:
    from PyQt6.QtCore import QCoreApplication, QObject, pyqtSignal
    from backend.hub import MediaHub
    from tests.test_hub import FakeSettings, FakeSource
except ImportError as e:
    raise unittest.SkipTest(f"PyQt6 isn't installed ({e})")

app = QCoreApplication.instance() or QCoreApplication([])


class FakeLocal(FakeSource):
    """The Pi's own music, with albums."""
    libraryChanged = pyqtSignal()
    scanningChanged = pyqtSignal()
    album = -1

    def __init__(self, count=10):
        super().__init__()
        self.albums = [{"title": f"Album {i}", "artist": f"Artist {i}", "art": "", "count": 3,
                        "duration": 600} for i in range(count)]
        self.played = []

    def playAlbum(self, album, start=0):
        self.played.append(album)
        self.album = album

    def set_modes(self, shuffle, repeat):
        pass

    def restore(self, state, play=False):
        pass


def make(settings=None, local=None):
    local = local or FakeLocal()
    settings = settings if settings is not None else FakeSettings()
    with mock.patch("backend.hub.shutil.which", return_value=None):
        hub = MediaHub(local, FakeSource(), FakeSource(), settings=settings)
    return hub, local, settings


def titles(hub):
    return [a["index"] for a in hub.recentAlbums]


class RecentAlbumsTest(unittest.TestCase):
    def test_newest_first_without_duplicates(self):
        hub, local, _ = make()
        for i in (0, 2, 0):
            hub.playAlbum(i)
        self.assertEqual(titles(hub), [0, 2])
        self.assertEqual(hub.recentAlbums[0]["title"], "Album 0")

    def test_capped_at_eight(self):
        hub, local, _ = make()
        for i in range(10):
            hub.playAlbum(i)
        self.assertEqual(titles(hub), [9, 8, 7, 6, 5, 4, 3, 2])

    def test_gone_albums_are_skipped(self):
        hub, local, settings = make(FakeSettings(recentAlbums=json.dumps(
            [["Artist 1", "Album 1"], ["Nobody", "Nothing"], ["artist 3", "ALBUM 3"]])))
        self.assertEqual(titles(hub), [1, 3])

    def test_a_rescan_that_renumbers_does_not_break_it(self):
        hub, local, _ = make()
        hub.playAlbum(2)
        local.albums.insert(0, {"title": "New", "artist": "New", "art": "", "count": 1, "duration": 1})
        self.assertEqual(titles(hub), [3])

    def test_corrupt_values_are_ignored(self):
        for bad in ("not json", "{}", '[1, ["a"], ["Artist 1", 5]]', 7):
            hub, _, _ = make(FakeSettings(recentAlbums=bad))
            self.assertEqual(hub.recentAlbums, [], bad)

    def test_saved_json_survives_a_new_hub(self):
        hub, local, settings = make()
        hub.playAlbum(4)
        hub.playAlbum(1)
        again, _, _ = make(settings)
        self.assertEqual(titles(again), [1, 4])

    def test_the_resumed_album_counts(self):
        local = FakeLocal()
        local.album = 5
        settings = FakeSettings(music=json.dumps({"local": {}}))
        with mock.patch("backend.hub.read_state", return_value={"local": {}}):
            hub, _, _ = make(settings, local)
        self.assertEqual(titles(hub), [5])

    def test_signal_on_change_only(self):
        hub, local, _ = make()
        seen = []
        hub.recentAlbumsChanged.connect(lambda: seen.append(1))
        hub.playAlbum(1)
        hub.playAlbum(1)
        self.assertEqual(len(seen), 1)


if __name__ == "__main__":
    unittest.main()
