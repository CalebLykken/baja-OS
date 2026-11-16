"""Off-Pi tests for the cover grids on the Music page (qml/pages/MusicPage.qml):
the Albums and Spotify grids and the song lists reuse their delegates instead
of creating and destroying them while flicking, and covers decode at the size
a tile shows (256 px, not 360). The page runs in its own process with a fake
media of 300 albums with no art; it is scrolled to the end and back, and the
number of cover tiles that exist at once stays small.

    python3 -m unittest tests.test_music_grid_perf
"""

import json
import os
import re
import subprocess
import sys
import unittest
from pathlib import Path

try:
    import PyQt6.QtQml  # noqa: F401
    import PyQt6.QtQuick  # noqa: F401
except ImportError:
    raise unittest.SkipTest("PyQt6 isn't installed")

ROOT = Path(__file__).resolve().parent.parent
QML = ROOT / "qml" / "pages" / "MusicPage.qml"

SCRIPT = r'''
import json, sys, time
from pathlib import Path
from PyQt6.QtCore import QObject, QUrl, pyqtProperty, pyqtSignal
from PyQt6.QtGui import QGuiApplication
from PyQt6.QtQml import QQmlEngine, QQmlExpression
from PyQt6.QtQuick import QQuickView

app = QGuiApplication(sys.argv)
ROOT = Path.cwd()
COUNT = 300


class Media(QObject):
    changed = pyqtSignal()

    def __init__(self):
        super().__init__()
        self._albums = [{"title": "Album %03d" % i, "artist": "Artist %d" % (i % 17), "art": "",
                         "index": i, "duration": 600} for i in range(COUNT)]

    @pyqtProperty(str, notify=changed)
    def source(self):
        return "local"

    @pyqtProperty(str, notify=changed)
    def title(self):
        return ""

    @pyqtProperty(str, notify=changed)
    def artist(self):
        return ""

    @pyqtProperty(int, notify=changed)
    def album(self):
        return -1

    @pyqtProperty(int, notify=changed)
    def index(self):
        return -1

    @pyqtProperty(bool, notify=changed)
    def playing(self):
        return False

    @pyqtProperty(bool, notify=changed)
    def scanning(self):
        return False

    @pyqtProperty("QVariantList", notify=changed)
    def albums(self):
        return self._albums

    @pyqtProperty("QVariantList", notify=changed)
    def recentAlbums(self):
        return []

    @pyqtProperty("QVariantList", notify=changed)
    def songs(self):
        return []

    @pyqtProperty("QVariantList", notify=changed)
    def upNext(self):
        return []

    @pyqtProperty(str, notify=changed)
    def artCard(self):
        return ""


class Eq(QObject):
    @pyqtProperty(str, constant=True)
    def preset(self):
        return "Flat"


class Spotify(QObject):
    @pyqtProperty(bool, constant=True)
    def available(self):
        return False

    @pyqtProperty(bool, constant=True)
    def linked(self):
        return False

    @pyqtProperty(str, constant=True)
    def error(self):
        return ""

    @pyqtProperty(str, constant=True)
    def statusText(self):
        return ""


media = Media()
engine = QQmlEngine()
engine.rootContext().setContextProperty("media", media)
engine.rootContext().setContextProperty("eq", Eq())
engine.rootContext().setContextProperty("spotify", Spotify())
url = QUrl.fromLocalFile(str(ROOT / "qml/pages/MusicPage.qml"))
view = QQuickView(engine, None)
view.setResizeMode(QQuickView.ResizeMode.SizeRootObjectToView)
view.setSource(url)
view.resize(1280, 800)
view.show()
root = view.rootObject()


def settle(ms=300):
    end = time.monotonic() + ms / 1000
    while time.monotonic() < end:
        app.processEvents()
        time.sleep(0.005)


def js(item, expr):
    value = QQmlExpression(engine.rootContext(), item, expr).evaluate()
    if isinstance(value, tuple):
        value = value[0]
    return value


def grid_with(count):
    # QML ids aren't object names, so find the GridView by its class.
    for o in root.findChildren(QObject):
        if o.inherits("QQuickGridView") and o.property("count") == count:
            return o
    return None


def tiles(grid):
    # Each CoverTile has a `placeholder`. A tile that scrolled away may stay
    # in the pool (still a child of the grid), so count the ones in the
    # viewport only.
    top, bottom = grid.property("contentY"), grid.property("contentY") + grid.property("height")
    shown = []
    for c in grid.property("contentItem").childItems():
        if c.property("placeholder") is None or not c.property("visible"):
            continue
        if c.property("y") + c.property("height") > top and c.property("y") < bottom:
            shown.append(c)
    return shown


out = {}
js(root, 'show("albums")')
settle(600)
grid = grid_with(300)
out["count"] = grid.property("count")
out["top"] = [t.property("title") for t in tiles(grid)]
counts = [len(tiles(grid))]
js(grid, "positionViewAtEnd()")
settle(600)
counts.append(len(tiles(grid)))
out["endTitles"] = [t.property("title") for t in tiles(grid)]
js(grid, "positionViewAtBeginning()")
settle(600)
counts.append(len(tiles(grid)))
out["backTitles"] = [t.property("title") for t in tiles(grid)]
out["counts"] = counts
out["cellW"] = grid.property("cellWidth")
out["cellH"] = grid.property("cellHeight")
out["cacheBuffer"] = grid.property("cacheBuffer")
print(json.dumps(out))
sys.stdout.flush()
'''


class MusicGridPerfTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        result = subprocess.run([sys.executable, "-c", SCRIPT], cwd=ROOT,
                                capture_output=True, text=True, timeout=180,
                                env={**os.environ, "QT_QPA_PLATFORM": "offscreen"})
        cls.stderr, cls.returncode = result.stderr, result.returncode
        cls.r = {}
        if result.returncode == 0 and result.stdout.strip():
            cls.r = json.loads(result.stdout.strip().splitlines()[-1])

    def setUp(self):
        self.assertEqual(self.returncode, 0, self.stderr)

    def test_all_300_albums_are_in_the_grid(self):
        self.assertEqual(self.r["count"], 300)

    def test_live_tiles_stay_few_while_scrolling(self):
        # Five columns of about three rows on screen, plus two rows of buffer
        # either side: a few dozen at most, not one per album.
        self.assertLess(max(self.r["counts"]), 40, self.r["counts"])

    def test_reused_tiles_show_the_right_album_after_scrolling(self):
        self.assertIn("Album 000", self.r["top"])
        self.assertIn("Album 299", self.r["endTitles"])
        self.assertNotIn("Album 000", self.r["endTitles"])
        self.assertIn("Album 000", self.r["backTitles"])
        self.assertNotIn("Album 299", self.r["backTitles"])

    def test_grid_sizes_match_the_tiles(self):
        self.assertEqual(self.r["cellH"], self.r["cellW"] + 80)
        self.assertEqual(self.r["cacheBuffer"], self.r["cellH"] * 2)


class MusicGridSourceTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.src = QML.read_text()

    def block(self, kind, ident):
        # The text from `Kind { id: ident` up to its delegate, where the grid
        # and list settings sit.
        m = re.search(r"%s \{\s*id: %s\b(.*?)\bdelegate:" % (kind, ident), self.src, re.S)
        self.assertIsNotNone(m, ident)
        return m.group(1)

    def test_cover_grids_reuse_delegates_with_a_two_row_buffer(self):
        for ident in ("albumGrid", "spotifyGrid"):
            body = self.block("GridView", ident)
            self.assertIn("reuseItems: true", body, ident)
            self.assertIn("cacheBuffer: cellHeight * 2", body, ident)

    def test_song_lists_reuse_delegates(self):
        for ident in ("queue", "songList", "albumSongs", "likedList", "resultList"):
            self.assertIn("reuseItems: true", self.block("ListView", ident), ident)

    def test_covers_decode_at_tile_size(self):
        m = re.search(r"sourceSize:\s*Qt\.size\((\d+),\s*(\d+)\)", self.src)
        self.assertIsNotNone(m)
        self.assertLessEqual(int(m.group(1)), 256)
        self.assertLessEqual(int(m.group(2)), 256)
        self.assertIn("asynchronous: true", self.src)


if __name__ == "__main__":
    unittest.main()
