"""Off-Pi tests for the art cache's size bookkeeping (backend/artcache.py):
writes must not walk the whole folder each time. Pure Python, no PyQt.

    python3 -m unittest tests.test_artcache_budget
"""

import os
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from backend import artcache


class ArtCacheBudgetTest(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.tmp = Path(tmp.name)
        p = mock.patch.dict(os.environ, {"XDG_CACHE_HOME": str(self.tmp / "cache")})
        p.start()
        self.addCleanup(p.stop)
        self.dir = self.tmp / "cache" / "baja-os" / "art"
        for name, val in (("_total", None), ("_made", None)):
            q = mock.patch.object(artcache, name, val)
            q.start()
            self.addCleanup(q.stop)

    def test_writes_under_cap_walk_once(self):
        with mock.patch.object(artcache, "_prune_locked",
                               wraps=artcache._prune_locked) as walk:
            for i in range(30):
                artcache.store(f"{i}.bin", b"x" * 10)
        self.assertEqual(walk.call_count, 1)
        self.assertEqual(len(list(self.dir.iterdir())), 30)

    def test_stat_count_for_300_writes(self):
        real = Path.stat
        calls = []
        def counting(self, *a, **k):
            calls.append(1)
            return real(self, *a, **k)
        with mock.patch.object(Path, "stat", counting):
            for i in range(300):
                artcache.store(f"{i}.bin", b"x" * 10)
        # Before this change: ~46k stats; now about two per write.
        self.assertLess(len(calls), 300 * 3)

    def test_over_cap_drops_oldest_keeps_newest(self):
        with mock.patch.object(artcache, "MAX_BYTES", 150):
            for i in range(20):
                path = artcache.store(f"{i:02}.bin", b"x" * 10)
                os.utime(path, (1000 + i, 1000 + i))
        left = sorted(f.name for f in self.dir.iterdir())
        self.assertIn("19.bin", left)
        self.assertNotIn("00.bin", left)
        self.assertLessEqual(sum(f.stat().st_size for f in self.dir.iterdir()), 150 + 10)

    def test_direct_prune_still_trims(self):
        for i in range(5):
            p = artcache.store(f"{i}.bin", b"x" * 100)
            os.utime(p, (1000 + i, 1000 + i))
        artcache.prune(limit=250)
        self.assertEqual(sorted(f.name for f in self.dir.iterdir()), ["3.bin", "4.bin"])

    def test_folder_deleted_between_writes(self):
        import shutil
        artcache.store("a.bin", b"x")
        shutil.rmtree(self.dir)
        path = artcache.store("b.bin", b"y")
        self.assertTrue(path.is_file())

    def test_xdg_change_gives_new_folder(self):
        first = artcache.cache_dir()
        with mock.patch.dict(os.environ, {"XDG_CACHE_HOME": str(self.tmp / "other")}):
            second = artcache.cache_dir()
            self.assertNotEqual(first, second)
            self.assertTrue(second.is_dir())


if __name__ == "__main__":
    unittest.main()
