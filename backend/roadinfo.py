"""The speed limit (and name) of the road the truck is on, by matching its
last few positions to the road network with the offline Valhalla service
(trace_attributes). OpenStreetMap supplies the limits; where a road has
none, the sign is simply hidden.
"""

import collections
import json
import math
import threading
import time
import urllib.request

from PyQt6.QtCore import QObject, QTimer, pyqtProperty, pyqtSignal

from backend import safe_emit

ROUTER = "http://127.0.0.1:8002"
CHECK_EVERY_MS = 3000
MOVING_MS = 2.0           # below this the fixes are too close together to match
KEEP_S = 20               # a limit older than this (no match since) is dropped
HELD_AWAY_M = 80          # stopped, a limit is kept (a red light) until the truck is this far from where it was matched
GAP_S = 5.0               # a few missed fixes is still one drive; longer and the old points can't be trusted to join up
TRACE_EVERY_S = 0.8       # the trace keeps about one fix a second, however often they come
MAX_KMH = 200             # no posted limit is above this; a bigger number is a bad answer


def _limit_of(value):
    """A limit in km/h: 0 when the road has none, None when the value isn't a sane limit."""
    if value is None:
        return 0
    if isinstance(value, bool):
        return None
    if isinstance(value, str):
        try:
            value = float(value)
        except ValueError:
            return None
    if not isinstance(value, (int, float)):
        return None
    if value == 0:
        return 0
    # NaN and infinity fail this comparison too, so they never get past it
    if not 0 < value <= MAX_KMH:
        return None
    return round(value)


def parse_match(answer):
    """The (limit, name) of the road the truck is on, from Valhalla's answer,
    or None when the answer isn't the usual shape (the caller keeps the last match)."""
    if not isinstance(answer, dict):
        return None
    edges = answer.get("edges")
    if not isinstance(edges, list) or not edges or not isinstance(edges[-1], dict):
        return None
    last = edges[-1]                             # the road the truck is on now
    limit = _limit_of(last.get("speed_limit"))
    names = last.get("names")
    if limit is None or not (names is None or isinstance(names, list)):
        return None
    name = names[0] if names and isinstance(names[0], str) else ""
    return limit, name


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
        self._match_at_pos = None     # (lat, lon) of the fix the last match was asked about
        self._asked_pos = None
        self._busy = False
        self._matched.connect(self._on_matched)
        gps.fixChanged.connect(self._on_fix)
        self._timer = QTimer(self, interval=CHECK_EVERY_MS, timeout=self._check)

    def start(self):
        # the check timer only runs while the truck is moving (see _on_fix), so a parked truck costs nothing
        pass

    def _on_fix(self):
        now = time.monotonic()
        if self._gps.hasFix and not self._gps.stale and now - self._fix_at >= TRACE_EVERY_S:
            if now - self._fix_at > GAP_S:
                self._fixes.clear()       # after a gap, start the trace again
            self._fix_at = now
            self._fixes.append((self._gps.lat, self._gps.lon))
        if self._gps.speed >= MOVING_MS and not self._timer.isActive():
            self._timer.start()

    def _moved_away(self):
        """True when the truck is more than HELD_AWAY_M from where the last match was made."""
        if self._match_at_pos is None:
            return True
        lat0, lon0 = self._match_at_pos
        dy = math.radians(self._gps.lat - lat0) * 6371000
        dx = math.radians(self._gps.lon - lon0) * 6371000 * math.cos(math.radians(lat0))
        return math.hypot(dx, dy) > HELD_AWAY_M

    def _check(self):
        moving = self._gps.speed >= MOVING_MS
        # a limit is only dropped when the truck is driving on without a new match, or has
        # gone elsewhere; sitting at a light, matches stop but the road hasn't changed
        if (self._limit and time.monotonic() - self._at > KEEP_S
                and (moving or self._moved_away())):
            self._limit, self._name = 0, ""
            self.changed.emit()
        if not moving and not self._busy and not self._limit:
            self._timer.stop()        # parked with nothing to expire: the next moving fix restarts it
            return
        if self._busy or len(self._fixes) < 4 or not moving:
            return
        self._asked_pos = self._fixes[-1]
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
                    match = parse_match(json.loads(r.read()))
                if match is not None:
                    limit, name = match
            except Exception:
                # a worker must never leak an error: no match this time, keep the last one
                pass
            finally:
                safe_emit(self, "_matched", limit, name)    # always, or _busy would never clear
        threading.Thread(target=work, name="road-match", daemon=True).start()

    def _on_matched(self, limit, name):
        self._busy = False
        if limit < 0:
            return
        self._at = time.monotonic()
        self._match_at_pos = self._asked_pos
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
