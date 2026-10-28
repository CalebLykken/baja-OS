"""The speed limit (and name) of the road the truck is on, by matching its
last few positions to the road network with the offline Valhalla service
(trace_attributes). OpenStreetMap supplies the limits; where a road has
none, the sign is simply hidden.
"""

import collections
import json
import threading
import time
import urllib.error
import urllib.request

from PyQt6.QtCore import QObject, QTimer, pyqtProperty, pyqtSignal

from backend import safe_emit

ROUTER = "http://127.0.0.1:8002"
CHECK_EVERY_MS = 3000
MOVING_MS = 2.0           # below this the fixes are too close together to match
KEEP_S = 20               # a limit older than this (no match since) is dropped
TRACE_EVERY_S = 0.8       # the trace keeps about one fix a second, however often they come


class RoadInfo(QObject):
    changed = pyqtSignal()
    _matched = pyqtSignal(int, str)

    def __init__(self, gps, parent=None):
        super().__init__(parent)
        self._gps = gps
        self._fixes = collections.deque(maxlen=10)   # about the last 10 s of driving
        self._fix_at = float("-inf")  # when the last one was kept
        self._limit = 0               # km/h, 0 = unknown
        self._name = ""
        self._at = 0.0
        self._busy = False
        self._matched.connect(self._on_matched)
        gps.fixChanged.connect(self._on_fix)
        self._timer = QTimer(self, interval=CHECK_EVERY_MS, timeout=self._check)

    def start(self):
        self._timer.start()

    def _on_fix(self):
        now = time.monotonic()
        if self._gps.hasFix and not self._gps.stale and now - self._fix_at >= TRACE_EVERY_S:
            self._fix_at = now
            self._fixes.append((self._gps.lat, self._gps.lon))

    def _check(self):
        if self._limit and time.monotonic() - self._at > KEEP_S:
            self._limit, self._name = 0, ""
            self.changed.emit()
        if self._busy or len(self._fixes) < 4 or self._gps.speed < MOVING_MS:
            return
        shape = [{"lat": lat, "lon": lon} for lat, lon in self._fixes]
        body = json.dumps({
            "shape": shape, "costing": "auto", "shape_match": "map_snap",
            "filters": {"attributes": ["edge.speed_limit", "edge.names"], "action": "include"},
        }).encode()
        self._busy = True

        def work():
            limit, name = -1, ""
            try:
                req = urllib.request.Request(ROUTER + "/trace_attributes", data=body,
                                             headers={"Content-Type": "application/json"})
                with urllib.request.urlopen(req, timeout=5) as r:
                    edges = json.loads(r.read()).get("edges") or []
                if edges:
                    last = edges[-1]                 # the road the truck is on now
                    limit = int(last.get("speed_limit") or 0)
                    name = (last.get("names") or [""])[0]
            except (OSError, urllib.error.URLError, ValueError):
                pass                                  # no match this time: keep the last one
            safe_emit(self, "_matched", limit, name)
        threading.Thread(target=work, name="road-match", daemon=True).start()

    def _on_matched(self, limit, name):
        self._busy = False
        if limit < 0:
            return
        self._at = time.monotonic()
        if (limit, name) != (self._limit, self._name):
            self._limit, self._name = limit, name
            self.changed.emit()

    @pyqtProperty(int, notify=changed)
    def speedLimit(self):
        """The posted limit in km/h, or 0 when the road has none."""
        return self._limit

    @pyqtProperty(str, notify=changed)
    def roadName(self):
        return self._name
