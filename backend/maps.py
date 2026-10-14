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

import json
import os
import re
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import unquote, urlsplit

from PyQt6.QtCore import QObject, pyqtProperty, pyqtSignal, pyqtSlot

ROOT = Path(__file__).resolve().parent.parent
DEFAULT_DATA_DIR = Path(os.environ.get("BAJA_MAPS_DIR", "~/.local/share/baja-os/maps")).expanduser()

TYPES = {
    ".html": "text/html; charset=utf-8",
    ".js": "text/javascript",
    ".mjs": "text/javascript",      # module scripts must be served as JavaScript
    ".css": "text/css",
    ".json": "application/json",
    ".png": "image/png",
    ".pbf": "application/x-protobuf",
    ".pmtiles": "application/octet-stream",
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

    def _serve(self, send_body):
        target = self._target()
        if target is None:
            self.send_error(404)
            return
        size = target.stat().st_size
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
        if status == 206:
            self.send_header("Content-Range", f"bytes {start}-{end}/{size}")
        self.end_headers()
        if not send_body:
            return
        try:
            with open(target, "rb") as f:
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


class MapService(QObject):
    """What QML needs for the Maps page: the page URL and whether a map is
    installed. `webEngine` says whether Qt WebEngine could be loaded at all."""

    changed = pyqtSignal()

    def __init__(self, data_dir=DEFAULT_DATA_DIR, web_engine=False, parent=None):
        super().__init__(parent)
        self._data_dir = Path(data_dir).expanduser()
        self._web_engine = web_engine
        self._server = None
        self._info = {}
        self.refresh()

    def start(self):
        self._server = make_server(self._data_dir)
        threading.Thread(target=self._server.serve_forever, name="map-server",
                         daemon=True).start()
        self.changed.emit()

    @pyqtSlot()
    def refresh(self):
        """Re-read region.json, e.g. after install-map.sh ran."""
        try:
            info = json.loads((self._data_dir / "region.json").read_text())
        except (OSError, ValueError):
            info = {}
        if not (self._data_dir / "basemap.pmtiles").is_file():
            info = {}
        if info != self._info:
            self._info = info
            self.changed.emit()

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
        return self._info.get("region", "")

    @pyqtProperty(str, notify=changed)
    def build(self):
        """The OpenStreetMap data date as YYYYMMDD."""
        return self._info.get("build", "")

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
