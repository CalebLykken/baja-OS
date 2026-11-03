"""Off-Pi tests for the map file server (backend/maps.py): what it answers to
a Range request (the map page reads the tile archive a piece at a time),
and that it only serves its two folders. A real server on loopback, with a
ten-byte file.

    python3 -m unittest tests.test_maps
"""

import http.client
import tempfile
import threading
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest import mock

try:
    from backend import maps as maps_module
    from backend.maps import MapService, make_server
except ImportError as e:
    raise unittest.SkipTest(f"PyQt6 isn't installed ({e})")

DIGITS = b"0123456789"


class RangeTest(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.data = Path(tmp.name)
        (self.data / "basemap.pmtiles").write_bytes(DIGITS)
        (self.data / "empty.txt").write_bytes(b"")
        (self.data / "region.json").write_text("{}")
        self.server = make_server(self.data)
        threading.Thread(target=self.server.serve_forever, args=(0.02,), daemon=True).start()
        self.addCleanup(self.server.server_close)
        self.addCleanup(self.server.shutdown)

    def get(self, path="/data/basemap.pmtiles", range_=None, method="GET"):
        conn = http.client.HTTPConnection("127.0.0.1", self.server.server_port, timeout=5)
        self.addCleanup(conn.close)
        conn.request(method, path, headers={"Range": range_} if range_ is not None else {})
        reply = conn.getresponse()
        return reply.status, reply.read(), reply

    def ranged(self, header, **kw):
        status, body, reply = self.get(range_=header, **kw)
        return status, body, reply.getheader("Content-Range")

    def test_no_range_is_the_whole_file(self):
        status, body, reply = self.get()
        self.assertEqual((status, body), (200, DIGITS))
        self.assertEqual(reply.getheader("Accept-Ranges"), "bytes")
        self.assertEqual(reply.getheader("Content-Length"), "10")
        self.assertIsNone(reply.getheader("Content-Range"))

    def test_open_ended_from_the_start_is_the_whole_file_as_206(self):
        self.assertEqual(self.ranged("bytes=0-"), (206, DIGITS, "bytes 0-9/10"))

    def test_open_ended_from_the_middle(self):
        self.assertEqual(self.ranged("bytes=6-"), (206, b"6789", "bytes 6-9/10"))

    def test_a_closed_range(self):
        self.assertEqual(self.ranged("bytes=2-4"), (206, b"234", "bytes 2-4/10"))
        self.assertEqual(self.ranged("bytes=0-0"), (206, b"0", "bytes 0-0/10"))
        self.assertEqual(self.ranged("bytes=9-9"), (206, b"9", "bytes 9-9/10"))

    def test_the_last_bytes(self):
        self.assertEqual(self.ranged("bytes=-3"), (206, b"789", "bytes 7-9/10"))

    def test_the_last_bytes_of_more_than_there_are_is_the_whole_file(self):
        self.assertEqual(self.ranged("bytes=-500"), (206, DIGITS, "bytes 0-9/10"))

    def test_an_end_past_the_file_is_cut_off_there(self):
        self.assertEqual(self.ranged("bytes=5-500"), (206, b"56789", "bytes 5-9/10"))

    def test_a_start_past_the_end_is_416(self):
        for header in ("bytes=10-", "bytes=10-12", "bytes=20-30"):
            self.assertEqual(self.ranged(header), (416, b"", "bytes */10"), header)

    def test_backwards_empty_and_unusable_ranges_are_416(self):
        for header in ("bytes=5-2", "bytes=-0", "bytes=abc", "items=0-5", "0-5", "bytes=0-1,3-4"):
            status, body, content_range = self.ranged(header)
            self.assertEqual((status, body, content_range), (416, b"", "bytes */10"), header)

    def test_a_range_with_neither_end_is_ignored(self):
        self.assertEqual(self.get(range_="bytes=-")[:2], (200, DIGITS))

    def test_spaces_around_the_header_are_fine(self):
        self.assertEqual(self.ranged("  bytes=2-4 "), (206, b"234", "bytes 2-4/10"))

    def test_any_range_of_an_empty_file_is_416(self):
        self.assertEqual(self.ranged("bytes=0-", path="/data/empty.txt"), (416, b"", "bytes */0"))
        self.assertEqual(self.get("/data/empty.txt")[:2], (200, b""))

    def test_head_has_the_sizes_and_no_body(self):
        status, body, reply = self.get(range_="bytes=2-4", method="HEAD")
        self.assertEqual((status, body), (206, b""))
        self.assertEqual(reply.getheader("Content-Length"), "3")
        self.assertEqual(reply.getheader("Content-Range"), "bytes 2-4/10")

    def test_the_type_comes_from_the_name(self):
        self.assertEqual(self.get("/data/basemap.pmtiles")[2].getheader("Content-Type"), "application/octet-stream")
        self.assertEqual(self.get("/data/region.json")[2].getheader("Content-Type"), "application/json")


class FolderTest(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.data = Path(tmp.name) / "maps"
        self.data.mkdir()
        (self.data / "basemap.pmtiles").write_bytes(DIGITS)
        (Path(tmp.name) / "secret.txt").write_text("secret")
        self.server = make_server(self.data)
        threading.Thread(target=self.server.serve_forever, args=(0.02,), daemon=True).start()
        self.addCleanup(self.server.server_close)
        self.addCleanup(self.server.shutdown)

    def status(self, path):
        conn = http.client.HTTPConnection("127.0.0.1", self.server.server_port, timeout=5)
        self.addCleanup(conn.close)
        conn.request("GET", path)
        reply = conn.getresponse()
        reply.read()
        return reply.status

    def test_a_file_in_the_data_folder(self):
        self.assertEqual(self.status("/data/basemap.pmtiles"), 200)

    def test_missing_files_and_folders_are_404(self):
        for path in ("/data/nope.pmtiles", "/data/", "/data", "/nope.html", "/fonts/x/0-255.pbf"):
            self.assertEqual(self.status(path), 404, path)

    def test_nothing_outside_the_folders(self):
        for path in ("/data/../secret.txt", "/data/%2e%2e/secret.txt", "/data/..%2fsecret.txt",
                     "/../secret.txt", "/%2e%2e/%2e%2e/etc/passwd"):
            self.assertEqual(self.status(path), 404, path)

    def test_it_listens_on_loopback_only(self):
        self.assertEqual(self.server.server_address[0], "127.0.0.1")


class SearchAlongTest(unittest.TestCase):
    def test_junk_shapes_dont_raise(self):
        with tempfile.TemporaryDirectory() as d:
            maps = MapService(d)
            for shape in ([], [[1]], [["a", "b"]], [None], None, 5, [[1.0, 2.0], [3.0, 4.0]]):
                maps.searchAlong("gas", shape, 0, 0.0)
            self.assertEqual(maps._query, "along:gas")


class RobustnessTest(unittest.TestCase):
    """A damaged region.json or a failing place search must not break the UI."""

    class InlineThread:
        def __init__(self, target=None, name=None, daemon=None):
            self.target = target

        def start(self):
            self.target()

    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.dir = Path(tmp.name)
        self.addCleanup(mock.patch.stopall)

    def test_a_region_file_of_the_wrong_shape_gives_no_region(self):
        (self.dir / "basemap.pmtiles").write_bytes(b"x")
        (self.dir / "region.json").write_text('["x"]')
        maps = MapService(self.dir)
        maps.refresh()
        self.assertEqual((maps.region, maps.build), ("", ""))
        self.assertFalse(maps.ready)

    def test_getters_survive_odd_values(self):
        maps = MapService(self.dir)
        maps._info = {"region": 5, "build": None}
        self.assertEqual((maps.region, maps.build), ("", ""))

    def test_a_failing_search_still_clears_the_results(self):
        mock.patch.object(maps_module, "threading", SimpleNamespace(Thread=self.InlineThread)).start()
        mock.patch("builtins.print").start()
        (self.dir / "places.sqlite").write_bytes(b"")
        maps = MapService(self.dir)
        maps._results = [{"name": "old"}]
        with mock.patch("backend.maps.places.search", side_effect=TypeError("odd row")):
            maps.search("gas", 0.0, 0.0)
        self.assertEqual(maps.results, [])

    def test_a_failing_nearby_search_still_answers(self):
        mock.patch.object(maps_module, "threading", SimpleNamespace(Thread=self.InlineThread)).start()
        mock.patch("builtins.print").start()
        maps = MapService(self.dir)
        maps._results = [{"name": "old"}]
        with mock.patch("backend.maps.places.nearby", side_effect=KeyError("x")):
            maps.searchNearby("gas", 0.0, 0.0)
        self.assertEqual(maps.results, [])


class UpdateTest(unittest.TestCase):
    """The map update's busy flag must always clear, however the script's
    output goes. The worker runs inline and install-map.sh is faked."""

    class InlineThread:
        def __init__(self, target=None, name=None, daemon=None):
            self.target = target

        def start(self):
            self.target()

    class BrokenOutput:
        def __iter__(self):
            raise UnicodeDecodeError("utf-8", b"\xff", 0, 1, "bad")

    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.maps = MapService(tmp.name)
        self.addCleanup(mock.patch.stopall)
        mock.patch.object(maps_module, "threading", SimpleNamespace(Thread=self.InlineThread)).start()
        mock.patch("builtins.print").start()

    def popen(self, stdout, code=0):
        proc = mock.MagicMock()
        proc.stdout = stdout
        proc.wait.return_value = code
        return proc

    def test_a_bad_byte_in_the_output_still_ends_the_update(self):
        proc = self.popen(self.BrokenOutput())
        with mock.patch("backend.maps.subprocess.Popen", return_value=proc) as popen:
            self.maps.update()
            self.assertFalse(self.maps._updating)
            self.assertEqual(self.maps._update_message, "Couldn't update the map; is the Pi online?")
            proc.kill.assert_called_once_with()
            self.maps.update()                   # not stuck: it starts again
            self.assertEqual(popen.call_count, 2)
            self.assertFalse(self.maps._updating)
        self.assertEqual(popen.call_args.kwargs["errors"], "replace")

    def test_a_good_run_says_the_map_is_updated(self):
        proc = self.popen(["Cutting the map\n", "Getting fonts\n"])
        with mock.patch("backend.maps.subprocess.Popen", return_value=proc):
            self.maps.update()
        self.assertFalse(self.maps._updating)
        self.assertEqual(self.maps._update_message, "Map updated")
        proc.kill.assert_not_called()


class StaleBuildTest(unittest.TestCase):
    """A power cut mid-update leaves install-map.sh's half-built map in .new;
    the dashboard clears it at startup (on a worker thread)."""

    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.dir = Path(tmp.name)
        (self.dir / ".new" / "fonts").mkdir(parents=True)
        (self.dir / ".new" / "basemap.pmtiles").write_text("half")
        (self.dir / "basemap.pmtiles").write_text("live tiles")
        self.maps = MapService(self.dir)
        self.addCleanup(mock.patch.stopall)

    def test_start_clears_it_off_the_calling_thread(self):
        started = []

        class Recorder:
            def __init__(self, target=None, name=None, daemon=None):
                self.target, self.name = target, name

            def start(self):
                started.append(self)

        with mock.patch.object(maps_module, "make_server"), \
                mock.patch.object(maps_module, "threading", SimpleNamespace(Thread=Recorder)):
            self.maps.start()
        self.assertTrue((self.dir / ".new").exists())     # nothing ran on this thread
        cleanup = [t for t in started if t.name == "map-cleanup"]
        self.assertEqual(len(cleanup), 1)
        with mock.patch("backend.maps._install_script_running", return_value=False):
            cleanup[0].target()
        self.assertFalse((self.dir / ".new").exists())
        self.assertEqual((self.dir / "basemap.pmtiles").read_text(), "live tiles")

    def test_a_running_install_keeps_its_build(self):
        with mock.patch("backend.maps._install_script_running", return_value=True):
            self.maps._remove_stale_build()
        self.assertTrue((self.dir / ".new" / "basemap.pmtiles").exists())

    def test_nothing_to_clear_is_fine(self):
        (self.dir / ".new" / "basemap.pmtiles").unlink()
        (self.dir / ".new" / "fonts").rmdir()
        (self.dir / ".new").rmdir()
        with mock.patch("backend.maps._install_script_running", return_value=False):
            self.maps._remove_stale_build()

    def test_a_failing_check_does_not_escape(self):
        with mock.patch("backend.maps._install_script_running", side_effect=RuntimeError), \
                mock.patch("builtins.print"):
            self.maps._remove_stale_build()


if __name__ == "__main__":
    unittest.main()
