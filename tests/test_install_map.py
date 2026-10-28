"""Off-Pi tests for how a map update goes into place (deploy/maps/swap-in.sh):
it must only rename, in an order the dashboard can't be hurt by, and a
failure must leave the old map as it was, and the map server must tell an
open map that the file changed. Runs the real script on throwaway
folders, with a `mv` in front that logs where each rename lands.

    python3 -m unittest tests.test_install_map
"""

import os
import shutil
import subprocess
import tempfile
import threading
import unittest
import urllib.request
from pathlib import Path

from backend.maps import make_server

MAPS = Path(__file__).resolve().parent.parent / "deploy" / "maps"

MV = """#!/bin/sh
for last; do :; done
echo "$last" >> "$MVLOG"
if [ -n "${MV_FAILS:-}" ] && [ "${last##*/}" = "$MV_FAILS" ] && [ "${1##*/}" != "$MV_FAILS.old" ]; then
    exit 1
fi
exec %s "$@"
"""


def write(path, text):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text)


class SwapInTest(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        root = Path(tmp.name)
        self.live, self.new = root / "maps", root / "maps" / ".new"
        self.bin, self.log = root / "bin", root / "mv.log"
        write(self.bin / "mv", MV % shutil.which("mv"))
        os.chmod(self.bin / "mv", 0o755)
        self.log.write_text("")

    def installed(self):
        """A map from an earlier install."""
        write(self.live / "basemap.pmtiles", "old tiles")
        write(self.live / "region.json", "old region")
        write(self.live / "places.sqlite", "old index")
        write(self.live / "fonts" / "Noto Sans Regular" / "0-255.pbf", "old glyphs")
        write(self.live / "fonts" / "stale.txt", "gone in the new build")
        write(self.live / "sprites" / "v4" / "sprite.json", "old sprites")

    def built(self, skip=()):
        """What install-map.sh leaves in .new."""
        files = {"basemap.pmtiles": "new tiles", "region.json": "new region",
                 "places.sqlite": "new index",
                 "fonts/Noto Sans Regular/0-255.pbf": "new glyphs",
                 "sprites/v4/sprite.json": "new sprites"}
        for name, text in files.items():
            if name.split("/")[0] not in skip:
                write(self.new / name, text)

    def swap(self, **env):
        return subprocess.run(
            ["sh", str(MAPS / "swap-in.sh"), str(self.new), str(self.live)],
            capture_output=True, text=True,
            env=dict(os.environ, PATH=f"{self.bin}{os.pathsep}{os.environ['PATH']}",
                     MVLOG=str(self.log), **env))

    def read(self, name):
        return (self.live / name).read_text()

    def renames(self):
        return [Path(line).name for line in self.log.read_text().splitlines()]

    def test_an_update_puts_the_new_map_in_place(self):
        self.installed()
        self.built()
        done = self.swap()
        self.assertEqual(done.returncode, 0, done.stderr)
        self.assertEqual(self.read("basemap.pmtiles"), "new tiles")
        self.assertEqual(self.read("region.json"), "new region")
        self.assertEqual(self.read("places.sqlite"), "new index")
        self.assertEqual(self.read("fonts/Noto Sans Regular/0-255.pbf"), "new glyphs")
        self.assertEqual(self.read("sprites/v4/sprite.json"), "new sprites")

    def test_nothing_old_or_half_built_is_left_behind(self):
        self.installed()
        self.built()
        self.swap()
        self.assertFalse((self.live / "fonts" / "stale.txt").exists())
        self.assertEqual(sorted(p.name for p in self.live.iterdir() if p.name != ".new"),
                         ["basemap.pmtiles", "fonts", "places.sqlite", "region.json", "sprites"])
        self.assertEqual(list(self.new.iterdir()), [])

    def test_the_tiles_come_last_and_the_old_folders_are_never_deleted_first(self):
        self.installed()
        self.built()
        self.swap()
        # Each folder: the old one renamed aside, the new one renamed in.
        self.assertEqual(self.renames(), ["fonts.old", "fonts", "sprites.old", "sprites",
                                          "places.sqlite", "region.json", "basemap.pmtiles"])

    def test_a_first_install_works_and_the_tiles_still_come_last(self):
        self.live.mkdir()
        self.built()
        done = self.swap()
        self.assertEqual(done.returncode, 0, done.stderr)
        self.assertEqual(self.renames(), ["fonts", "sprites", "places.sqlite", "region.json",
                                          "basemap.pmtiles"])
        self.assertEqual(self.read("basemap.pmtiles"), "new tiles")

    def test_what_the_build_doesnt_have_stays_as_it_was(self):
        self.installed()
        self.built(skip=("sprites", "places.sqlite"))
        self.swap()
        self.assertEqual(self.read("sprites/v4/sprite.json"), "old sprites")
        self.assertEqual(self.read("places.sqlite"), "old index")
        self.assertEqual(self.read("basemap.pmtiles"), "new tiles")

    def test_a_leftover_from_an_interrupted_swap_doesnt_get_in_the_way(self):
        self.installed()
        write(self.live / "fonts.old" / "junk.txt", "from a swap that was cut off")
        self.built()
        done = self.swap()
        self.assertEqual(done.returncode, 0, done.stderr)
        self.assertFalse((self.live / "fonts.old").exists())
        self.assertEqual(self.read("fonts/Noto Sans Regular/0-255.pbf"), "new glyphs")

    def test_fonts_that_wont_move_in_leave_the_old_ones_and_the_old_tiles(self):
        self.installed()
        self.built()
        done = self.swap(MV_FAILS="fonts")
        self.assertNotEqual(done.returncode, 0)
        self.assertEqual(self.read("fonts/Noto Sans Regular/0-255.pbf"), "old glyphs")
        self.assertFalse((self.live / "fonts.old").exists())
        self.assertEqual(self.read("basemap.pmtiles"), "old tiles")      # never reached
        self.assertEqual(self.read("region.json"), "old region")

    def test_the_scripts_parse(self):
        for name in ("install-map.sh", "swap-in.sh"):
            done = subprocess.run(["sh", "-n", str(MAPS / name)], capture_output=True, text=True)
            self.assertEqual(done.returncode, 0, done.stderr)

    def test_the_build_is_next_to_the_live_files_not_in_tmp(self):
        script = (MAPS / "install-map.sh").read_text()
        self.assertIn('work="$MAPS_DIR/.new"', script)
        self.assertIn('export TMPDIR="$work"', script)
        self.assertNotIn("mktemp", script)


class MapServerTest(unittest.TestCase):
    """The map server while an update renames a new map over the old one."""

    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.data = Path(tmp.name)
        write(self.data / "basemap.pmtiles", "old tiles, old offsets")
        self.server = make_server(self.data)
        threading.Thread(target=self.server.serve_forever, daemon=True).start()
        self.addCleanup(self.server.server_close)
        self.addCleanup(self.server.shutdown)

    def get(self, byte_range):
        url = f"http://127.0.0.1:{self.server.server_port}/data/basemap.pmtiles"
        request = urllib.request.Request(url, headers={"Range": byte_range})
        with urllib.request.urlopen(request) as reply:
            return reply.read().decode(), reply.headers["ETag"]

    def test_the_tag_changes_when_a_new_map_is_renamed_in(self):
        # pmtiles.js keeps the header it read first and sends its tag with
        # every tile request after; a different tag makes it start over.
        before, tag = self.get("bytes=0-2")
        self.assertEqual(before, "old")
        self.assertEqual(self.get("bytes=4-8")[1], tag)
        write(self.data / "new.pmtiles", "new tiles, new offsets!")
        os.replace(self.data / "new.pmtiles", self.data / "basemap.pmtiles")
        after, new_tag = self.get("bytes=0-2")
        self.assertEqual(after, "new")
        self.assertNotEqual(new_tag, tag)
        self.assertFalse(new_tag.startswith("W/"))     # pmtiles.js ignores weak tags


if __name__ == "__main__":
    unittest.main()
