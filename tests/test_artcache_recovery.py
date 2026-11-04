"""Off-Pi tests for healing the cover cache after a power cut: zero-byte files
are misses, writes are fsynced, and undecodable covers in the cache are
dropped so they're fetched again.

    python3 -m unittest tests.test_artcache_recovery
"""

import io
import os
import tempfile
import unittest
from pathlib import Path
from unittest import mock

try:
    from PyQt6.QtCore import QUrl
    from PyQt6.QtGui import QColor, QImage
    from backend import artcache, hub
except ImportError as e:
    raise unittest.SkipTest(f"PyQt6 isn't installed ({e})")


class FakeResponse(io.BytesIO):
    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False


class ArtCacheRecoveryTest(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.tmp = Path(tmp.name)
        p = mock.patch.dict(os.environ, {"XDG_CACHE_HOME": str(self.tmp / "cache")})
        p.start()
        self.addCleanup(p.stop)
        self.dir = self.tmp / "cache" / "baja-os" / "art"
        for name in ("_total", "_made"):
            q = mock.patch.object(artcache, name, None)
            q.start()
            self.addCleanup(q.stop)

    def png_bytes(self):
        img = QImage(40, 40, QImage.Format.Format_RGB32)
        img.fill(QColor("red"))
        p = self.tmp / "src.png"
        assert img.save(str(p))
        return p.read_bytes()

    def test_zero_byte_file_is_a_miss_and_is_rewritten(self):
        artcache.cache_dir()
        (self.dir / "a.bin").write_bytes(b"")
        path, hit = artcache.lookup("a.bin")
        self.assertFalse(hit)
        self.assertFalse(path.exists())
        artcache.store("a.bin", b"real")
        self.assertEqual((self.dir / "a.bin").read_bytes(), b"real")

    def test_non_empty_file_is_a_hit_and_touched(self):
        artcache.cache_dir()
        f = self.dir / "b.bin"
        f.write_bytes(b"data")
        os.utime(f, (1000, 1000))
        path, hit = artcache.lookup("b.bin")
        self.assertTrue(hit)
        self.assertGreater(f.stat().st_mtime, 1000)

    def test_pinned_zero_byte_file_is_rewritten(self):
        f = artcache.pinned_dir() / "c.bin"
        f.write_bytes(b"")
        artcache.store_pinned("c.bin", b"cover")
        self.assertEqual(f.read_bytes(), b"cover")

    def test_writing_fsyncs_once_per_write(self):
        with mock.patch.object(os, "fsync", wraps=os.fsync) as fs:
            artcache.store("d.bin", b"x")
            self.assertEqual(fs.call_count, 1)
            artcache.store("e.bin", b"y")
            self.assertEqual(fs.call_count, 2)

    def test_fsync_failure_still_replaces(self):
        with mock.patch.object(os, "fsync", side_effect=OSError("boom")):
            artcache.store("f.bin", b"kept")
        self.assertEqual((self.dir / "f.bin").read_bytes(), b"kept")

    def test_cached_art_redownloads_an_empty_file(self):
        url = "http://example.test/cover.png"
        artcache.cache_dir()
        (self.dir / (artcache.digest(url) + ".img")).write_bytes(b"")
        with mock.patch("urllib.request.urlopen",
                        return_value=FakeResponse(self.png_bytes())) as op:
            local = hub.cached_art(url)
        op.assert_called_once()
        card = hub.art_card(local)
        self.assertTrue(card)
        self.assertGreater(Path(QUrl(card).toLocalFile()).stat().st_size, 0)

    def test_art_card_drops_garbage_in_the_cache(self):
        artcache.cache_dir()
        f = self.dir / "junk.img"
        f.write_bytes(b"<html>nope</html>")
        self.assertEqual(hub.art_card(QUrl.fromLocalFile(str(f)).toString()), "")
        self.assertFalse(f.exists())

    def test_art_card_leaves_garbage_outside_the_cache(self):
        artcache.cache_dir()
        f = self.tmp / "cover.jpg"
        f.write_bytes(b"not an image")
        self.assertEqual(hub.art_card(QUrl.fromLocalFile(str(f)).toString()), "")
        self.assertTrue(f.exists())


if __name__ == "__main__":
    unittest.main()
