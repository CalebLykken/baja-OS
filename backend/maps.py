"""The offline map: a tiny local web server for the map page and its data,
plus what the Maps page needs to know to show it.

The map is MapLibre GL JS running in Qt WebEngine (web/map). It reads tiles
straight out of one PMTiles file with HTTP range requests, which file:// URLs
can't do, so this serves two folders on 127.0.0.1 with Range support:

    /         web/map in the repo: the page and the vendored libraries
    /data/    the map data from deploy/maps/install-map.sh

Run it on its own to work on the map in a desktop browser:

    python3 -m backend.maps --port 8765    # then open http://127.0.0.1:8765/
"""

import contextlib
import json
import os
import re
import shutil
import sqlite3
import subprocess
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import unquote, urlsplit

from PyQt6.QtCore import QObject, pyqtProperty, pyqtSignal, pyqtSlot

from backend import safe_emit

from backend import places

ROOT = Path(__file__).resolve().parent.parent
DEFAULT_DATA_DIR = Path(os.environ.get("BAJA_MAPS_DIR", "~/.local/share/baja-os/maps")).expanduser()

TYPES = {
    ".html": "text/html; charset=utf-8",
    ".js": "text/javascript",
    ".mjs": "text/javascript",      # module scripts must be served as JavaScript
    ".css": "text/css",
    ".json": "application/json",
    ".png": "image/png",
    ".webp": "image/webp",
    ".glb": "model/gltf-binary",
    ".pbf": "application/x-protobuf",
    ".pmtiles": "application/octet-stream",
    ".geojson": "application/geo+json",
    ".txt": "text/plain; charset=utf-8",
}


class _Handler(BaseHTTPRequestHandler):
    def log_message(self, *args):
        pass

    def do_HEAD(self):
        self._serve(send_body=False)

    def do_GET(self):
        self._serve(send_body=True)

    def _target(self):
        path = unquote(urlsplit(self.path).path)
        if path.startswith("/fonts/"):
            return self._glyphs(path[len("/fonts/"):])
        if path.startswith("/data/"):
            root, rel = self.server.data_dir, path[len("/data/"):]
        else:
            root, rel = self.server.app_dir, path.lstrip("/") or "index.html"
        root = root.resolve()
        target = (root / rel).resolve()
        # Nothing outside the two folders, whatever the URL says.
        if root not in target.parents or not target.is_file():
            return None
        return target

    # The map's labels use Overpass (web/map/fonts, made with
    # tools/make_glyphs.py); characters outside its Latin ranges come from
    # the stock Noto glyphs installed with the map.
    NOTO = {"Overpass Regular": "Noto Sans Regular", "Overpass SemiBold": "Noto Sans Medium",
            "Overpass Italic": "Noto Sans Italic"}

    def _glyphs(self, rel):
        stack, _, name = rel.partition("/")
        if "/" in name or not name.endswith(".pbf"):
            return None
        for font in [f.strip() for f in stack.split(",") if f.strip()]:
            for root, folder in ((self.server.app_dir / "fonts", font),
                                 (self.server.data_dir / "fonts", self.NOTO.get(font, font))):
                root = root.resolve()
                target = (root / folder / name).resolve()
                if root in target.parents and target.is_file():
                    return target
        return None

    def _serve(self, send_body):
        target = self._target()
        if target is None:
            self.send_error(404)
            return
        try:
            f = open(target, "rb")
        except OSError:
            self.send_error(404)
            return
        with f:
            # Size and tag from the open file, not the path: a map update can
            # rename a new file over it between the two.
            info = os.fstat(f.fileno())
            size = info.st_size
            start, end, status = 0, size - 1, 200

            header = self.headers.get("Range")
            if header:
                m = re.fullmatch(r"bytes=(\d*)-(\d*)", header.strip())
                if m and (m[1] or m[2]):
                    if m[1]:
                        start = int(m[1])
                        end = min(int(m[2]), size - 1) if m[2] else size - 1
                    else:                       # "bytes=-N": the last N bytes
                        start = max(0, size - int(m[2]))
                    status = 206
                if not m or start > end:
                    self.send_response(416)
                    self.send_header("Content-Range", f"bytes */{size}")
                    self.end_headers()
                    return

            self.send_response(status)
            self.send_header("Content-Type", TYPES.get(target.suffix, "application/octet-stream"))
            self.send_header("Content-Length", str(end - start + 1))
            self.send_header("Accept-Ranges", "bytes")
            self.send_header("Cache-Control", "no-cache")   # deploys and map updates replace files
            # A map update renames a new file over this one. The tag changes
            # with it, so the page's pmtiles reader starts over instead of
            # reading the new file at the old file's offsets.
            self.send_header("ETag", f'"{info.st_ino:x}-{info.st_size:x}-{info.st_mtime_ns:x}"')
            if status == 206:
                self.send_header("Content-Range", f"bytes {start}-{end}/{size}")
            self.end_headers()
            if not send_body:
                return
            try:
                f.seek(start)
                left = end - start + 1
                while left > 0:
                    chunk = f.read(min(256 * 1024, left))
                    if not chunk:
                        break
                    self.wfile.write(chunk)
                    left -= len(chunk)
            except (BrokenPipeError, ConnectionResetError):
                pass                            # the page moved on; nothing to do


def make_server(data_dir, port=0):
    """A threaded server for web/map and data_dir on 127.0.0.1."""
    server = ThreadingHTTPServer(("127.0.0.1", port), _Handler)
    server.daemon_threads = True
    server.app_dir = ROOT / "web" / "map"
    server.data_dir = Path(data_dir)
    return server


# Plain words for the map's feature kinds where the tag isn't one.
KIND_WORDS = {
    "doityourself": "Hardware store", "fast_food": "Fast food", "locality": "Town",
    "macrohood": "District", "neighbourhood": "Neighbourhood", "place_of_worship": "Place of worship",
    "wholesale": "Warehouse store", "fuel": "Gas station", "charging_station": "EV charging",
    "car_repair": "Car repair", "car_wash": "Car wash", "parking": "Parking",
    "parking_entrance": "Parking", "stop": "Transit stop", "station": "Station",
    "townhall": "Town hall", "social_facility": "Social services", "pitch": "Sports field",
    "address": "Address",
    "supermarket": "Grocery store", "convenience": "Convenience store", "greengrocer": "Produce market",
    "alcohol": "Liquor store", "aerodrome": "Airport", "doctors": "Doctor", "dentist": "Dentist",
    "camp_site": "Campground", "caravan_site": "RV park", "picnic_site": "Picnic area",
    "slipway": "Boat launch", "marina": "Marina", "halt": "Train stop", "tram_stop": "Streetcar stop",
    "ferry_terminal": "Ferry terminal", "bicycle": "Bike shop", "outdoor": "Outdoor store",
    "car_rental": "Car rental", "car_parts": "Auto parts", "tyres": "Tire shop", "bbq": "Barbecue",
    "viewpoint": "Viewpoint", "theme_park": "Theme park", "dog_park": "Dog park",
    "nature_reserve": "Nature reserve", "national_park": "National park", "beach": "Beach",
    "fire_station": "Fire station", "police": "Police", "post_office": "Post office",
    "library": "Library", "hospital": "Hospital", "pharmacy": "Pharmacy", "cafe": "Coffee shop",
    "pub": "Pub", "bar": "Bar", "ice_cream": "Ice cream", "motel": "Motel", "hotel": "Hotel",
    "hostel": "Hostel", "golf_course": "Golf course", "trailhead": "Trailhead", "zoo": "Zoo",
    "museum": "Museum",
}


def _describe(kind, area):
    """'Park in Eastlake', 'Street in Belltown', 'Neighbourhood'."""
    words = KIND_WORDS.get(kind, kind.replace("_", " ").capitalize())
    return f"{words} in {area}" if area else words


def _install_script_running():
    """Is an install-map.sh running, e.g. started over ssh? Without pgrep,
    assume not."""
    try:
        return subprocess.run(["pgrep", "-f", r"install-map\.sh"], capture_output=True,
                              timeout=5).returncode == 0
    except (OSError, subprocess.SubprocessError):
        return False


class MapService(QObject):
    """What QML needs for the Maps page: the page URL and whether a map is
    installed. `webEngine` says whether Qt WebEngine could be loaded at all.
    `update()` re-runs install-map.sh to fetch fresh OpenStreetMap data."""

    changed = pyqtSignal()
    resultsChanged = pyqtSignal()
    searchingChanged = pyqtSignal()
    _progress = pyqtSignal(str, bool)      # message, still running
    _found = pyqtSignal(str, object)       # query, results

    def __init__(self, data_dir=DEFAULT_DATA_DIR, web_engine=False, parent=None):
        super().__init__(parent)
        self._data_dir = Path(data_dir).expanduser()
        self._web_engine = web_engine
        self._server = None
        self._info = {}
        self._updating = False
        # Held while install-map.sh runs and while a left-over build is cleared
        self._install_lock = threading.Lock()
        self._update_message = ""
        self._query = ""
        self._results = []
        self._searching = False             # a search is out and its answer hasn't come
        self._progress.connect(self._on_progress)
        self._found.connect(self._on_found)
        self.refresh()

    def start(self):
        self._server = make_server(self._data_dir)
        threading.Thread(target=self._server.serve_forever, name="map-server",
                         daemon=True).start()
        threading.Thread(target=self._remove_stale_build, name="map-cleanup",
                         daemon=True).start()
        self.changed.emit()

    def _remove_stale_build(self):
        """A power cut during a map update skips install-map.sh's cleanup and
        leaves its half-built map (up to a gigabyte) in .new. Nothing is
        installing at startup, so clear it. Runs on a worker thread."""
        work = self._data_dir / ".new"
        try:
            with self._install_lock:
                if work.exists() and not _install_script_running():
                    shutil.rmtree(work, ignore_errors=True)
        except Exception as e:
            print(f"Couldn't clear the old map build ({type(e).__name__})", flush=True)

    @pyqtSlot()
    def refresh(self):
        """Re-read region.json, e.g. after install-map.sh ran."""
        info = places.read_region(self._data_dir)
        if not (self._data_dir / "basemap.pmtiles").is_file():
            info = {}
        if info != self._info:
            self._info = info
            self.changed.emit()

    @pyqtSlot()
    def update(self):
        """Download fresh map data for the same area (needs internet)."""
        if self._updating:
            return
        self._updating = True
        safe_emit(self, "_progress", "Starting", True)
        try:
            bbox = ",".join(str(v) for v in self._info.get("bbox", [])) or None
        except Exception:
            bbox = None
        region = self._info.get("region")
        if not isinstance(region, str):
            region = "Seattle area"

        def work():
            env = dict(os.environ, BAJA_MAPS_DIR=str(self._data_dir))
            if bbox:
                env.update(BBOX=bbox, REGION=region)
            steps = {"Getting the pmtiles": "Getting the download tool",
                     "Cutting": "Downloading the map", "Getting fonts": "Getting fonts and icons",
                     "Indexing places": "Indexing places for search",
                     "Indexing street": "Indexing street addresses",
                     "Finding traffic": "Finding traffic lights and signs"}
            ok = False
            proc = None
            self._install_lock.acquire()
            try:
                proc = subprocess.Popen(["sh", str(ROOT / "deploy" / "maps" / "install-map.sh")],
                                        stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                                        text=True, errors="replace", env=env)
                for line in proc.stdout:
                    for prefix, message in steps.items():
                        if line.startswith(prefix):
                            safe_emit(self, "_progress", message, True)
                ok = proc.wait() == 0
            except Exception as e:
                # Always reach the final message below, or _updating would stay set
                print(f"Map update failed ({type(e).__name__})", flush=True)
                if proc is not None:
                    try:
                        proc.kill()
                    except OSError:
                        pass
            finally:
                self._install_lock.release()
                safe_emit(self, "_progress", "Map updated" if ok else "Couldn't update the map; is the Pi online?", False)
        threading.Thread(target=work, name="map-update", daemon=True).start()

    def _on_progress(self, message, running):
        self._update_message = message
        if not running:
            self._updating = False
            self.refresh()
        self.changed.emit()

    # ---- place search -------------------------------------------------------
    def _begin(self, key, notify=True):
        """A search for `key` has started: the last search's rows go, and the
        list says Searching until this one's answer comes. `notify` False
        keeps the rows signal quiet (the along-route card reads it)."""
        self._query = key
        self._results = []
        self._searching = True
        self.searchingChanged.emit()
        if notify:
            self.resultsChanged.emit()

    @pyqtSlot(str, float, float)
    def search(self, text, lon, lat):
        """Look `text` up in the offline place index, nearest to (lon, lat)
        among equally good matches (0, 0 for no position)."""
        if not text.strip():
            self._query = text
            self._on_found(text, [])
            return
        self._begin(text)
        index = self._data_dir / places.INDEX_NAME
        near = (lon, lat) if (lon or lat) else None

        addresses = self._data_dir / places.ADDRESS_INDEX

        def work():
            rows = []
            try:
                # "123 Main St": street addresses first, then any places too.
                if places.looks_like_address(text) and addresses.is_file():
                    try:
                        with contextlib.closing(sqlite3.connect(f"file:{addresses}?mode=ro", uri=True)) as db:
                            rows += places.search_addresses(db, text, near=near)
                    except sqlite3.Error:
                        pass
                try:
                    with contextlib.closing(sqlite3.connect(f"file:{index}?mode=ro", uri=True)) as db:
                        rows += places.search_with_categories(db, text, near=near)
                        if not rows and places.looks_like_address(text):
                            # The house number isn't mapped: offer the street itself.
                            rows += [r for r in places.search(db, places.street_part(text), near=near)
                                     if r["kind"] == "street"]
                except sqlite3.Error:
                    pass
            except Exception as e:
                print(f"Place search failed ({type(e).__name__})", flush=True)
                rows = []
            finally:
                safe_emit(self, "_found", text, rows[:12])
        threading.Thread(target=work, name="place-search", daemon=True).start()

    @pyqtSlot(str, float, float)
    def searchNearby(self, category, lon, lat):
        """The nearest places of a category ("gas", "coffee", "food", ...)."""
        key = "category:" + category
        self._begin(key)
        index = self._data_dir / places.INDEX_NAME

        def work():
            rows = []
            try:
                with contextlib.closing(sqlite3.connect(f"file:{index}?mode=ro", uri=True)) as db:
                    rows = places.nearby(db, category, (lon, lat))
            except sqlite3.Error:
                rows = []
            except Exception as e:
                print(f"Nearby search failed ({type(e).__name__})", flush=True)
                rows = []
            finally:
                safe_emit(self, "_found", key, rows)
        threading.Thread(target=work, name="place-nearby", daemon=True).start()

    @pyqtSlot(str, "QVariantList", int, float)
    def searchAlong(self, category, shape, start_seg, into_seg):
        """Places of a category along the route ahead (from `into_seg` metres
        along segment `start_seg`), in the order reached."""
        key = "along:" + category
        self._begin(key, notify=False)      # the along card shows rows only once they're its own
        index = self._data_dir / places.INDEX_NAME
        try:
            line = [(float(p[0]), float(p[1])) for p in shape]
        except (TypeError, ValueError, IndexError):
            line = []

        def work():
            rows = []
            try:
                with contextlib.closing(sqlite3.connect(f"file:{index}?mode=ro", uri=True)) as db:
                    rows = places.along_route(db, category, line, start_seg, into_seg)
            except sqlite3.Error:
                rows = []
            except Exception as e:
                print(f"Along-route search failed ({type(e).__name__})", flush=True)
                rows = []
            finally:
                safe_emit(self, "_found", key, rows)
        threading.Thread(target=work, name="place-along", daemon=True).start()

    def _on_found(self, text, rows):
        if text != self._query:
            return                          # an older search finishing late
        self._results = [dict(r, label=_describe(r["kind"], r["area"])) for r in rows]
        self._searching = False
        self.searchingChanged.emit()
        self.resultsChanged.emit()

    @pyqtProperty("QVariantList", notify=resultsChanged)
    def results(self):
        """[{name, label, lon, lat, distance (m, or -1)}] for the last search."""
        return self._results

    @pyqtProperty(bool, notify=searchingChanged)
    def searching(self):
        """True from the start of a search until its answer arrives."""
        return self._searching

    @pyqtProperty(bool, notify=changed)
    def canSearch(self):
        return (self._data_dir / places.INDEX_NAME).is_file()

    @pyqtProperty(bool, notify=changed)
    def updating(self):
        return self._updating

    @pyqtProperty(str, notify=changed)
    def updateMessage(self):
        return self._update_message

    @pyqtProperty(float, notify=changed)
    def sizeMb(self):
        try:
            return (self._data_dir / "basemap.pmtiles").stat().st_size / 1e6
        except OSError:
            return 0.0

    @pyqtProperty(bool, constant=True)
    def webEngine(self):
        return self._web_engine

    @pyqtProperty(str, notify=changed)
    def pageUrl(self):
        if not self._server:
            return ""
        return f"http://127.0.0.1:{self._server.server_address[1]}/index.html"

    @pyqtProperty(bool, notify=changed)
    def ready(self):
        return bool(self._info)

    @pyqtProperty(str, notify=changed)
    def region(self):
        """What the installed map covers, e.g. 'Seattle area'."""
        value = self._info.get("region", "")
        return value if isinstance(value, str) else ""

    @pyqtProperty(str, notify=changed)
    def build(self):
        """The OpenStreetMap data date as YYYYMMDD."""
        value = self._info.get("build", "")
        return value if isinstance(value, str) else ""

    @pyqtProperty(str, constant=True)
    def dataDir(self):
        return str(self._data_dir)


if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser(description="Serve the Baja OS map for a desktop browser")
    parser.add_argument("--port", type=int, default=8765)
    parser.add_argument("--maps-dir", default=str(DEFAULT_DATA_DIR))
    args = parser.parse_args()
    server = make_server(Path(args.maps_dir).expanduser(), args.port)
    print(f"Map at http://127.0.0.1:{args.port}/index.html (data: {args.maps_dir})")
    server.serve_forever()
