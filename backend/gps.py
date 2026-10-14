"""Where the truck is: position, speed and heading from the GPS receiver
(through gpsd), or a simulated drive around Seattle in demo mode.

gpsd serves the GT-U7 on 127.0.0.1:2947. This connects, asks for JSON
reports, keeps the latest fix and reconnects if gpsd restarts. With no real
fix and simulated vehicle data, the truck drives the loop in
demo_route.json at the simulated speed, so the map has something to follow.
"""

import json
import math
import socket
import threading
import time
from pathlib import Path

from PyQt6.QtCore import QObject, QTimer, pyqtProperty, pyqtSignal

GPSD = ("127.0.0.1", 2947)
ROUTE = Path(__file__).with_name("demo_route.json")
EARTH_M = 6371000.0
MPH_TO_MS = 0.44704
STALE_S = 10            # a real fix older than this no longer counts


def _metres(a, b):
    """Rough distance in metres between two (lon, lat) points (fine for a city)."""
    lat = math.radians((a[1] + b[1]) / 2)
    dx = math.radians(b[0] - a[0]) * math.cos(lat) * EARTH_M
    dy = math.radians(b[1] - a[1]) * EARTH_M
    return math.hypot(dx, dy)


def _bearing(a, b):
    lat = math.radians((a[1] + b[1]) / 2)
    dx = math.radians(b[0] - a[0]) * math.cos(lat)
    dy = math.radians(b[1] - a[1])
    return math.degrees(math.atan2(dx, dy)) % 360


class DemoRoute:
    """A path of (lon, lat) points to drive: a closed loop (the demo drive
    around Seattle), or a one-way route that ends at its last point."""

    def __init__(self, path=ROUTE, points=None, loop=True):
        pts = [tuple(p) for p in (points or json.loads(Path(path).read_text())["coordinates"])]
        self.loop = loop
        if loop and pts[0] != pts[-1]:
            pts.append(pts[0])
        self.points = pts
        self.cum = [0.0]
        for a, b in zip(pts, pts[1:]):
            self.cum.append(self.cum[-1] + _metres(a, b))
        self.length = self.cum[-1]

    def at(self, distance):
        """(lon, lat, heading) at `distance` metres along the path."""
        d = distance % self.length if self.loop else min(distance, self.length - 0.01)
        lo, hi = 0, len(self.cum) - 1
        while lo < hi - 1:                         # binary search for the segment
            mid = (lo + hi) // 2
            if self.cum[mid] <= d:
                lo = mid
            else:
                hi = mid
        a, b = self.points[lo], self.points[lo + 1]
        seg = self.cum[lo + 1] - self.cum[lo] or 1.0
        f = (d - self.cum[lo]) / seg
        # Head toward a point ~25 m ahead so corners turn smoothly.
        ahead = self._point(d + 25)
        here = (a[0] + (b[0] - a[0]) * f, a[1] + (b[1] - a[1]) * f)
        return here[0], here[1], _bearing(here, ahead)

    def _point(self, distance):
        d = distance % self.length if self.loop else min(distance, self.length)
        for i in range(len(self.cum) - 1):
            if self.cum[i + 1] >= d:
                a, b = self.points[i], self.points[i + 1]
                f = (d - self.cum[i]) / ((self.cum[i + 1] - self.cum[i]) or 1.0)
                return a[0] + (b[0] - a[0]) * f, a[1] + (b[1] - a[1]) * f
        return self.points[-1]


class Gps(QObject):
    changed = pyqtSignal()
    _report = pyqtSignal(dict)

    def __init__(self, vehicle=None, demo=False, parent=None):
        super().__init__(parent)
        self._vehicle = vehicle
        self._demo = demo
        self._fix = None                 # dict: lat, lon, speed (m/s), heading, source
        self._real_at = None             # when the last real fix arrived (monotonic)
        self._gpsd = False               # connected to gpsd
        self._report.connect(self._apply)
        self._route = None
        self._travelled = 0.0
        self._path = None                # a one-way route to drive instead (navigation demo)
        self._path_travelled = 0.0
        self._demo_timer = QTimer(self, interval=1000, timeout=self._demo_tick)

    def start(self):
        threading.Thread(target=self._gpsd_loop, name="gpsd", daemon=True).start()
        if self._demo:
            try:
                self._route = DemoRoute()
            except (OSError, ValueError, KeyError):
                self._route = None
            if self._route:
                self._demo_timer.start()

    # ---- gpsd ---------------------------------------------------------------
    def _gpsd_loop(self):
        while True:
            try:
                with socket.create_connection(GPSD, timeout=5) as s:
                    s.sendall(b'?WATCH={"enable":true,"json":true}\n')
                    s.settimeout(30)
                    self._report.emit({"gpsd": True})
                    for line in s.makefile("r", encoding="utf-8", errors="replace"):
                        try:
                            msg = json.loads(line)
                        except ValueError:
                            continue
                        if msg.get("class") != "TPV":
                            continue
                        if msg.get("mode", 0) >= 2 and "lat" in msg and "lon" in msg:
                            self._report.emit({
                                "lat": msg["lat"], "lon": msg["lon"],
                                "speed": msg.get("speed", 0.0),
                                "heading": msg.get("track"),
                                "source": "gps",
                            })
            except OSError:
                pass
            self._report.emit({"gpsd": False})
            time.sleep(5)

    # ---- the simulated drive ----------------------------------------------------
    def _real_fresh(self):
        return self._real_at is not None and time.monotonic() - self._real_at < STALE_S

    def _demo_tick(self):
        if self._real_fresh():
            return                           # a real fix wins
        mph = self._vehicle.speed if self._vehicle is not None else 30.0
        speed = mph * MPH_TO_MS
        step = speed * self._demo_timer.interval() / 1000
        if self._path:
            # Driving a navigation route: stop at the end of it.
            if self._path_travelled >= self._path.length:
                speed = 0.0
            self._path_travelled = min(self._path.length, self._path_travelled + step)
            lon, lat, heading = self._path.at(self._path_travelled)
        else:
            self._travelled += step
            lon, lat, heading = self._route.at(self._travelled)
        self._apply({"lat": lat, "lon": lon, "speed": speed, "heading": heading, "source": "demo"})

    def _apply(self, report):
        if "gpsd" in report:
            if report["gpsd"] != self._gpsd:
                self._gpsd = report["gpsd"]
                self.changed.emit()
            return
        if report["source"] == "gps":
            self._real_at = time.monotonic()
            # Below walking pace the receiver's track is noise; keep the last.
            if report["heading"] is None or report["speed"] < 1.0:
                report["heading"] = self._fix["heading"] if self._fix else 0.0
        self._fix = report
        self.changed.emit()

    def followPath(self, points):
        """In demo mode, drive this route (from its start) instead of the loop."""
        if len(points) >= 2:
            self._path = DemoRoute(points=points, loop=False)
            self._path_travelled = 0.0

    def clearPath(self):
        self._path = None

    # ---- what QML sees ------------------------------------------------------
    @pyqtProperty(bool, notify=changed)
    def hasFix(self):
        if not self._fix:
            return False
        return self._fix["source"] == "demo" or self._real_fresh()

    @pyqtProperty(float, notify=changed)
    def lat(self):
        return self._fix["lat"] if self._fix else 0.0

    @pyqtProperty(float, notify=changed)
    def lon(self):
        return self._fix["lon"] if self._fix else 0.0

    @pyqtProperty(float, notify=changed)
    def speed(self):
        """Metres per second."""
        return self._fix["speed"] if self._fix else 0.0

    @pyqtProperty(float, notify=changed)
    def heading(self):
        """Degrees clockwise from north."""
        return self._fix["heading"] if self._fix else 0.0

    @pyqtProperty(str, notify=changed)
    def source(self):
        """'gps', 'demo' or '' (no position)."""
        return self._fix["source"] if self.hasFix else ""

    @pyqtProperty(bool, notify=changed)
    def receiverConnected(self):
        """True while gpsd is running (the receiver may still be finding satellites)."""
        return self._gpsd
