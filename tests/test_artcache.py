"""Off-Pi tests for the cover-art cache (backend/artcache.py) and the two
places that use it: embedded art (library.py) and downloaded/rounded covers
(hub.py). The cache folder is a temp dir set through $XDG_CACHE_HOME, never
the real home.

    python3 -m unittest tests.test_artcache
"""

import os
import tempfile
import threading
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest import mock

try:
    from PyQt6.QtCore import QUrl
    from PyQt6.QtGui import QColor, QImage
    from backend import artcache, hub, library
except ImportError as e:
    raise unittest.SkipTest(f"PyQt6 isn't installed ({e})")


def png(path, color="red", size=40):
    img = QImage(size, size, QImage.Format.Format_RGB32)
    img.fill(QColor(color))
    assert img.save(str(path))
    return Path(path)


class ArtCacheTest(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.tmp = Path(tmp.name)
        p = mock.patch.dict(os.environ, {"XDG_CACHE_HOME": str(self.tmp / "cache")})
        p.start()
        self.addCleanup(p.stop)
        self.dir = self.tmp / "cache" / "baja-os" / "art"

    def names(self):
        return sorted(f.name for f in self.dir.iterdir())

    def test_the_cache_is_under_the_cache_home(self):
        self.assertEqual(artcache.cache_dir(), self.dir)
        self.assertTrue(self.dir.is_dir())

    def test_the_default_is_the_home_cache(self):
        with mock.patch.dict(os.environ, {"HOME": str(self.tmp)}):
            os.environ.pop("XDG_CACHE_HOME")
            self.assertEqual(artcache.cache_dir(), self.tmp / ".cache" / "baja-os" / "art")

    def test_names_are_hashes_never_the_title_or_path(self):
        name = artcache.digest("/music/Band/Greatest Hits/01 Song.mp3")
        self.assertRegex(name, r"^[0-9a-f]{32}$")
        self.assertNotIn("Song", name)

    def test_a_write_leaves_the_whole_file_and_no_temp_files(self):
        path = artcache.store("abc.img", b"image bytes")
        self.assertEqual(path.read_bytes(), b"image bytes")
        self.assertEqual(self.names(), ["abc.img"])

    def test_a_failed_write_leaves_nothing_behind(self):
        dest = artcache.cache_dir() / "abc.img"
        with self.assertRaises(RuntimeError):
            with artcache.writing(dest) as tmp:
                tmp.write_bytes(b"half an im")
                raise RuntimeError("crashed mid-write")
        self.assertEqual(self.names(), [])

    def test_a_stored_file_is_not_written_twice(self):
        path = artcache.store("abc.img", b"first")
        artcache.store("abc.img", b"second")
        self.assertEqual(path.read_bytes(), b"first")

    def test_the_least_recently_used_files_go_first(self):
        for i, name in enumerate(["a.img", "b.img", "c.img"]):
            p = artcache.store(name, b"x" * 100)
            os.utime(p, (1000 + i, 1000 + i))
        artcache.touch(self.dir / "a.img")                  # a was used just now
        artcache.prune(limit=250)
        self.assertEqual(self.names(), ["a.img", "c.img"])  # b was the oldest

    def test_a_write_prunes_but_keeps_the_new_file(self):
        with mock.patch.object(artcache, "MAX_BYTES", 150):
            for i in range(4):
                p = artcache.store(f"{i}.img", b"x" * 100)
                os.utime(p, (1000 + i, 1000 + i))
            artcache.store("new.img", b"x" * 100)
        self.assertIn("new.img", self.names())
        self.assertLessEqual(sum(f.stat().st_size for f in self.dir.iterdir()), 150)

    def test_stale_temp_files_from_a_crash_are_removed(self):
        stale = artcache.cache_dir() / ".tmp-crashed.png"
        stale.write_bytes(b"half")
        os.utime(stale, (1000, 1000))
        artcache.prune()
        self.assertEqual(self.names(), [])

    def test_two_threads_storing_the_same_image_leave_one_good_file(self):
        data = b"y" * 100000
        ts = [threading.Thread(target=artcache.store, args=("same.img", data)) for _ in range(8)]
        for t in ts:
            t.start()
        for t in ts:
            t.join()
        self.assertEqual(self.names(), ["same.img"])
        self.assertEqual((self.dir / "same.img").read_bytes(), data)

    # ---- the callers ------------------------------------------------------------
    def test_an_albums_tracks_share_one_embedded_cover(self):
        tags = {"APIC:": SimpleNamespace(data=b"cover bytes")}
        audio = SimpleNamespace(tags=tags)
        a = library._extract_art(Path("/m/Album/01 One.mp3"), audio)
        b = library._extract_art(Path("/m/Album/02 Two.mp3"), audio)
        self.assertEqual(a, b)
        self.assertTrue(a.startswith("file://"))
        self.assertEqual(len(self.names()), 1)
        self.assertEqual(Path(QUrl(a).toLocalFile()).read_bytes(), b"cover bytes")
        self.assertEqual(library._extract_art(Path("/m/x.mp3"), SimpleNamespace(tags={})), "")

    def test_a_download_is_cached_and_used_again_offline(self):
        url = "https://i.scdn.co/image/abc123"
        fake = mock.MagicMock()
        fake.__enter__.return_value.read.return_value = b"downloaded"
        with mock.patch.object(hub.urllib.request, "urlopen", return_value=fake) as get:
            first = hub.cached_art(url)
        self.assertEqual(Path(QUrl(first).toLocalFile()).read_bytes(), b"downloaded")
        with mock.patch.object(hub.urllib.request, "urlopen", side_effect=OSError("offline")):
            self.assertEqual(hub.cached_art(url), first)            # e.g. after a reboot
        get.assert_called_once()
        self.assertEqual(hub.cached_art("file:///x.jpg"), "file:///x.jpg")

    def test_a_failed_download_leaves_no_broken_file(self):
        fake = mock.MagicMock()
        fake.__enter__.return_value.read.side_effect = OSError("connection dropped")
        with mock.patch.object(hub.urllib.request, "urlopen", return_value=fake):
            with self.assertRaises(OSError):
                hub.cached_art("https://i.scdn.co/image/def")
        self.assertEqual(self.names(), [])

    def test_the_card_is_a_whole_png_in_the_cache_and_reused(self):
        src = png(self.tmp / "cover.png")
        url = QUrl.fromLocalFile(str(src)).toString()
        card = hub.art_card(url)
        out = Path(QUrl(card).toLocalFile())
        self.assertEqual(out.parent, self.dir)
        self.assertFalse(QImage(str(out)).isNull())
        self.assertEqual(QImage(str(out)).width(), 600)
        self.assertEqual(hub.art_card(url), card)
        self.assertEqual(len(self.names()), 1)
        self.assertEqual(hub.art_card("file:///no/such.png"), "")

    def test_a_cached_cover_gets_one_card_however_often_it_is_shown(self):
        src = artcache.store("abc.img", Path(png(self.tmp / "c.png")).read_bytes())
        url = QUrl.fromLocalFile(str(src)).toString()
        first = hub.art_card(url)
        os.utime(src, (5000, 5000))                          # the cache touches it on every use
        self.assertEqual(hub.art_card(url), first)
        self.assertEqual(len(self.names()), 2)               # the cover and its one card

    def test_a_card_that_cannot_be_saved_is_not_cached(self):
        src = png(self.tmp / "cover.png")
        url = QUrl.fromLocalFile(str(src)).toString()
        with mock.patch.object(QImage, "save", return_value=False):
            with self.assertRaises(OSError):
                hub.art_card(url)
        self.assertEqual(self.names(), [])                   # no empty card left to be reused
        self.assertTrue(hub.art_card(url))

    def test_a_changed_cover_file_gets_a_new_card(self):
        src = png(self.tmp / "cover.png", "red")
        url = QUrl.fromLocalFile(str(src)).toString()
        first = hub.art_card(url)
        png(src, "blue", size=80)
        os.utime(src, (2000, 2000))
        self.assertNotEqual(hub.art_card(url), first)


if __name__ == "__main__":
    unittest.main()
