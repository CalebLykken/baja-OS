"""Off-Pi tests for the demo playlist and the empty player (backend/media.py),
and for which of them (or the real one) main.make_media_player hands out.

    python3 -m unittest tests.test_media
"""

import contextlib
import io
import os
import sys
import tempfile
import unittest
import wave
from pathlib import Path
from unittest import mock

os.environ.setdefault("QT_LOGGING_RULES", "qt.multimedia.ffmpeg*=false")

try:
    from PyQt6.QtCore import QCoreApplication
    from backend.media import DEMO_ALBUMS, DEMO_QUEUE, MediaPlayer
except ImportError as e:
    raise unittest.SkipTest(f"PyQt6 isn't installed ({e})")

try:
    import main
    from backend.library import LibraryPlayer
except ImportError:                 # mutagen or QtMultimedia missing: the decision tests skip
    main = LibraryPlayer = None

app = QCoreApplication.instance() or QCoreApplication([])


class EmptyMediaPlayerTest(unittest.TestCase):
    """MediaPlayer([]): the fallback when the real player can't load."""
    SAVED = {"album": None, "path": "/m/a.wav", "index": 4, "position": 30}

    def setUp(self):
        self.player = MediaPlayer([])
        self.addCleanup(self.player._timer.stop)

    def test_what_the_screen_reads(self):
        p = self.player
        self.assertEqual((p.title, p.artist, p.art), ("", "", ""))
        self.assertEqual((p.duration, p.position, p.index, p.album), (0, 0, -1, -1))
        self.assertEqual((p.queue, p.albums, p.albumTracks(0)), ([], [], []))
        self.assertFalse(p.playing)

    def test_every_key_does_nothing(self):
        p = self.player
        p.start()
        for key in (p.togglePlay, p.next, p.previous, p.playAll, p.togglePlay):
            key()
        p.playIndex(2)
        p.playAlbum(0, 0)
        p._tick()
        self.assertFalse(p.playing)
        self.assertFalse(p._timer.isActive())
        self.assertEqual((p.title, p.index, p.position), ("", -1, 0))

    def test_state_is_what_restore_was_given(self):
        self.assertEqual(self.player.state(), {"album": None, "path": "", "index": 0, "position": 0})
        self.player.restore(self.SAVED, play=True)
        self.assertEqual(self.player.state(), self.SAVED)
        self.assertFalse(self.player.playing)

    def test_junk_given_to_restore_is_a_blank_resume_point(self):
        for junk in (None, [], "x"):
            self.player.restore(junk)
            self.assertEqual(self.player.state(), {"album": None, "path": "", "index": 0, "position": 0}, junk)

    def test_volume_still_works(self):
        self.player.setVolume(70)
        self.assertEqual(self.player.volume, 70)


class DemoMediaPlayerTest(unittest.TestCase):
    def test_the_demo_still_plays_its_playlist(self):
        p = self.player = MediaPlayer()
        self.addCleanup(p._timer.stop)
        self.assertTrue(p.playing)
        self.assertEqual((p.title, p.index, p.position), (DEMO_QUEUE[0]["title"], 0, 37))
        self.assertEqual(len(p.queue), len(DEMO_QUEUE))
        p.next()
        self.assertEqual(p.index, 1)


class DemoAlbumsTest(unittest.TestCase):
    """The demo's small fake library, for the Albums tab."""

    def make(self, *args):
        p = MediaPlayer(*args)
        self.players.append(p)          # kept alive until the cleanups have run
        self.addCleanup(p._timer.stop)
        return p

    def setUp(self):
        self.players = []

    def test_albums_in_the_library_players_shape(self):
        albums = self.make().albums
        self.assertGreaterEqual(len(albums), 2)
        for a, src in zip(albums, DEMO_ALBUMS):
            self.assertEqual(a, {"title": src["title"], "artist": src["artist"], "art": "",
                                 "count": len(src["tracks"]),
                                 "duration": sum(t["duration"] for t in src["tracks"])})

    def test_the_default_queue_is_every_song_in_album_order(self):
        p = self.make()
        self.assertEqual([t["title"] for t in p.queue],
                         [t["title"] for a in DEMO_ALBUMS for t in a["tracks"]])
        self.assertEqual(p.album, -1)

    def test_album_tracks_and_bounds(self):
        p = self.make()
        tracks = p.albumTracks(1)
        self.assertEqual(len(tracks), p.albums[1]["count"])
        self.assertEqual(set(tracks[0]), {"title", "artist", "duration"})
        for bad in (-1, len(p.albums), 99):
            self.assertEqual(p.albumTracks(bad), [])

    def test_play_album_switches_the_queue(self):
        p = self.make()
        seen = []
        p.queueChanged.connect(lambda: seen.append("queue"))
        p.trackChanged.connect(lambda: seen.append("track"))
        p.playAlbum(1)
        self.assertEqual(p.album, 1)
        self.assertEqual([t["title"] for t in p.queue], [t["title"] for t in p.albumTracks(1)])
        self.assertEqual((p.title, p.index, p.position), (p.queue[0]["title"], 0, 0))
        self.assertTrue(p.playing)
        self.assertEqual(seen[:2], ["queue", "track"])

    def test_play_album_from_a_song_and_clamps(self):
        p = self.make()
        p.playAlbum(0, 2)
        self.assertEqual(p.index, 2)
        p.playAlbum(0, 99)
        self.assertEqual(p.index, len(p.queue) - 1)

    def test_out_of_range_album_is_a_no_op(self):
        p = self.make()
        seen = []
        p.queueChanged.connect(lambda: seen.append(1))
        for bad in (-1, 50):
            p.playAlbum(bad)
        self.assertEqual((seen, p.album, len(p.queue), p.index), ([], -1, len(DEMO_QUEUE), 0))

    def test_play_all_goes_back_to_the_whole_queue(self):
        p = self.make()
        p.playAlbum(1)
        p.playAll()
        self.assertEqual((p.album, len(p.queue), p.index), (-1, len(DEMO_QUEUE), 0))
        self.assertEqual(p.title, DEMO_QUEUE[0]["title"])

    def test_next_wraps_within_the_album(self):
        p = self.make()
        p.playAlbum(2)
        n = len(p.queue)
        titles = {p.title}
        for _ in range(n):
            p.next()
            titles.add(p.title)
        self.assertEqual((p.index, p.album), (0, 2))
        self.assertEqual(titles, {t["title"] for t in p.albumTracks(2)})

    def test_restore_clamps_inside_an_album(self):
        p = self.make()
        p.playAlbum(2)
        p.restore({"index": 40, "position": 5})
        self.assertLess(p.index, len(p.queue))

    def test_explicit_queues_have_no_albums(self):
        custom = [{"title": "X", "artist": "Y", "duration": 100}]
        for q in ([], custom):
            p = self.make(q)
            self.assertEqual((p.albums, p.album, p.albumTracks(0)), ([], -1, []))
            seen = []
            p.queueChanged.connect(lambda: seen.append(1))
            p.playAlbum(0)
            p.playAll()
            self.assertEqual((seen, p.album, p.queue), ([], -1, q))


def write_wav(path):
    with wave.open(str(path), "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(8000)
        w.writeframes(bytes(1600))


@unittest.skipIf(main is None, "main.py or the real player can't be imported here")
class MakeMediaPlayerTest(unittest.TestCase):
    """The demo playlist only where demo data is allowed AND there's no
    music; otherwise an honest empty player. (flag, on_pi) are args.demo
    (--demo True, --no-demo False, neither None) and whether this is a Pi,
    so none of it needs a Pi."""

    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.players = []                   # kept alive until the cleanups have run
        env = mock.patch.dict(os.environ, {"XDG_CACHE_HOME": str(Path(tmp.name) / "cache")})
        env.start()
        self.addCleanup(env.stop)
        self.empty = Path(tmp.name) / "empty"
        self.empty.mkdir()
        self.songs = Path(tmp.name) / "songs"
        self.songs.mkdir()
        write_wav(self.songs / "one.wav")
        write_wav(self.songs / "two.wav")

    def make(self, folder, flag, on_pi):
        with contextlib.redirect_stdout(io.StringIO()):
            player = main.make_media_player(str(folder), flag, on_pi)
        self.players.append(player)
        if isinstance(player, LibraryPlayer):
            self.addCleanup(player._engine._shutdown)
        else:
            self.addCleanup(player._timer.stop)
        return player

    def assertDemo(self, player):
        self.assertIsInstance(player, MediaPlayer)
        self.assertEqual(len(player.queue), len(DEMO_QUEUE))
        self.assertTrue(player.playing)

    def assertEmpty(self, player):
        self.assertEqual((player.queue, player.albums, player.title, player.index), ([], [], "", -1))
        self.assertFalse(player.playing)

    def test_no_music_on_a_mac_is_the_demo(self):
        self.assertDemo(self.make(self.empty, None, False))

    def test_no_music_on_the_pi_is_empty(self):
        player = self.make(self.empty, None, True)
        self.assertIsInstance(player, LibraryPlayer)
        self.assertEmpty(player)

    def test_no_demo_on_a_mac_is_empty(self):
        self.assertEmpty(self.make(self.empty, False, False))

    def test_demo_on_the_pi_is_the_demo(self):
        self.assertDemo(self.make(self.empty, True, True))

    def test_a_folder_that_isnt_there_is_no_music_too(self):
        self.assertEmpty(self.make(self.empty / "missing", None, True))
        self.assertDemo(self.make(self.empty / "missing", None, False))

    def test_music_is_always_played(self):
        from backend.library import scan
        # First run: nothing is read here, the player waits for the scanner.
        for flag in (None, True, False):
            for on_pi in (True, False):
                player = self.make(self.songs, flag, on_pi)
                self.assertIsInstance(player, LibraryPlayer, (flag, on_pi))
                self.assertEqual((player.queue, player.scanning), ([], True), (flag, on_pi))
        scan(self.songs)                    # what the scanner leaves behind
        for flag in (None, True, False):
            for on_pi in (True, False):
                player = self.make(self.songs, flag, on_pi)
                self.assertEqual(len(player.queue), 2, (flag, on_pi))
                self.assertFalse(player.scanning)

    def test_asks_whether_this_is_a_pi_unless_told(self):
        with mock.patch("backend.demo.on_pi", return_value=True):
            self.assertEmpty(self.make(self.empty, None, None))
        with mock.patch("backend.demo.on_pi", return_value=False):
            self.assertDemo(self.make(self.empty, None, None))

    def test_without_the_real_player(self):
        # QtMultimedia or mutagen not installed: the demo where it's allowed,
        # else empty, never the made-up songs on the truck.
        with mock.patch.dict(sys.modules, {"backend.library": None}):
            self.assertDemo(self.make(self.songs, None, False))
            player = self.make(self.songs, None, True)
            self.assertIsInstance(player, MediaPlayer)
            self.assertEmpty(player)
            self.assertEmpty(self.make(self.songs, False, False))
            self.assertDemo(self.make(self.songs, True, True))


if __name__ == "__main__":
    unittest.main()
