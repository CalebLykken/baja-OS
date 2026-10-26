"""Where the truck is: position, speed and heading from the GPS receiver,
or a simulated drive around Seattle in demo mode.

The receiver (a u-blox on USB) is read through gpsd when gpsd is running
(127.0.0.1:2947), else straight from its serial port: it reports in NMEA,
the standard text sentences (RMC for position, speed and course; GGA and
GSV for satellites). It switches to gpsd if that starts later.

When the receiver loses the sky (a tunnel, a garage), its last position is
held and marked stale until it's back. The demo drive (the loop in
demo_route.json at the simulated speed, so the map has something to
follow) only runs while no receiver has been seen since start and the
vehicle data is simulated: on a Mac, or a Pi on the bench.
"""

import glob
import json
import math
import os
import select
import socket
import termios
import threading
import time
from pathlib import Path

from PyQt6.QtCore import QObject, QTimer, pyqtProperty, pyqtSignal

from backend import safe_emit

GPSD = ("127.0.0.1", 2947)
# Only devices that say they're GPS receivers: other USB serial devices
# (the OBD adapter, a Pico) must be left alone.
RECEIVERS = ("/dev/serial/by-id/*u-blox*", "/dev/serial/by-id/*[Gg][Nn][Ss][Ss]*",
             "/dev/serial/by-id/*[Gg][Pp][Ss]*")
KNOTS_TO_MS = 0.514444
CHECK_GPSD_S = 60       # reading the receiver directly: look for gpsd this often
LOG_EVERY_S = 60        # while looking for satellites: a line in the journal this often
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


def find_receiver():
    for pattern in RECEIVERS:
        found = sorted(glob.glob(pattern))
        if found:
            return found[0]
    return None


def nmea_fields(line):
    """A checked NMEA sentence's fields ('$GNRMC,...*hh' -> ['GNRMC', ...]), or None."""
    line = line.strip()
    if not line.startswith("$") or "*" not in line:
        return None
    body, _, check = line[1:].partition("*")
    total = 0
    for ch in body:
        total ^= ord(ch)
    try:
        if int(check[:2], 16) != total:
            return None
    except ValueError:
        return None
    return body.split(",")


def nmea_coord(value, hemisphere):
    """'4736.37200', 'N' -> 47.6062 (degrees and minutes to degrees)."""
    if not value or "." not in value:
        return None
    dot = value.index(".")
    degrees = float(value[:dot - 2] or 0)
    minutes = float(value[dot - 2:])
    d = degrees + minutes / 60
    return -d if hemisphere in ("S", "W") else d


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


class Position:
    """Which position to show, without Qt: the receiver's while it's fresh,
    its last one held (stale) once it stops, and the demo drive only while
    no receiver has been seen and the car's data is simulated. Tests drive
    it with a fake clock."""

    def __init__(self, demo=False, stale_s=STALE_S):
        self.demo = demo
        self.stale_s = stale_s
        self.fix = None                 # dict: lat, lon, speed (m/s), heading, source
        self.real_at = None             # when the last real fix arrived
        self.receiver_seen = False      # a receiver has talked since start
        self.was_fresh = False          # what the last check found

    def receiver(self):
        """A receiver is talking, with or without a position: no more demo."""
        self.receiver_seen = True
        if self.fix and self.fix["source"] == "demo":
            self.fix = None

    def real(self, report, now):
        self.receiver()
        # Below walking pace the receiver's track is noise; keep the last.
        if report["heading"] is None or report["speed"] < 1.0:
            report["heading"] = self.fix["heading"] if self.fix else 0.0
        self.fix = report
        self.real_at = now
        self.was_fresh = True

    def simulated(self, report):
        self.fix = report

    def fresh(self, now):
        return self.real_at is not None and now - self.real_at < self.stale_s

    def stale(self, now):
        """The receiver's last position is held: it hasn't had a new one lately."""
        return self.real_at is not None and not self.fresh(now)

    def demo_allowed(self, live):
        """Whether the demo drive may run (`live`: the car's data is real)."""
        return self.demo and not self.receiver_seen and not live

    def check(self, now, live):
        """Once a second: True when what's shown has changed (the fix went
        stale, or the demo drive stopped)."""
        changed = False
        if self.fix and self.fix["source"] == "demo" and not self.demo_allowed(live):
            self.fix = None
            changed = True
        fresh = self.fresh(now)
        if fresh != self.was_fresh:
            self.was_fresh = fresh
            changed = True
        return changed


class Gps(QObject):
    changed = pyqtSignal()
    _report = pyqtSignal(dict)

    def __init__(self, vehicle=None, demo=False, parent=None):
        super().__init__(parent)
        self._vehicle = vehicle
        self._pos = Position(demo)
        self._gpsd = False               # a receiver is connected (through gpsd or directly)
        self._sats = 0                   # satellites used for the fix
        self._in_view = 0                # satellites the receiver can see
        self._report.connect(self._apply)
        self._route = None
        self._travelled = 0.0
        self._path = None                # a one-way route to drive instead (navigation demo)
        self._path_travelled = 0.0
        # Once a second: notice a fix going stale, and step the demo drive.
        self._timer = QTimer(self, interval=1000, timeout=self._tick)

    def start(self):
        threading.Thread(target=self._receiver_loop, name="gps", daemon=True).start()
        if self._pos.demo:
            try:
                self._route = DemoRoute()
            except (OSError, ValueError, KeyError):
                self._route = None
        self._timer.start()

    # ---- the receiver -----------------------------------------------------
    def _receiver_loop(self):
        while True:
            used = False
            try:
                used = self._read_gpsd()
            except OSError:
                pass
            if not used:
                path = find_receiver()
                if path:
                    try:
                        self._read_receiver(path)
                    except OSError:
                        pass                      # unplugged: look again
            safe_emit(self, "_report", {"gpsd": False})
            time.sleep(5)

    def _read_gpsd(self):
        """Read gpsd's reports until it goes away. False if it isn't running."""
        try:
            s = socket.create_connection(GPSD, timeout=2)
        except OSError:
            return False
        with s:
            s.sendall(b'?WATCH={"enable":true,"json":true}\n')
            s.settimeout(30)
            safe_emit(self, "_report", {"gpsd": True})
            talking = False
            for line in s.makefile("r", encoding="utf-8", errors="replace"):
                try:
                    msg = json.loads(line)
                except ValueError:
                    continue
                kind = msg.get("class")
                if not talking and (kind == "TPV" or kind == "DEVICES" and msg.get("devices")):
                    talking = True                # a receiver, not just gpsd on its own
                    safe_emit(self, "_report", {"receiver": True})
                if kind != "TPV":
                    continue
                if msg.get("mode", 0) >= 2 and "lat" in msg and "lon" in msg:
                    safe_emit(self, "_report", {
                        "lat": msg["lat"], "lon": msg["lon"],
                        "speed": msg.get("speed", 0.0),
                        "heading": msg.get("track"),
                        "source": "gps",
                    })
        return True

    def _read_receiver(self, path):
        """Read the receiver's NMEA sentences straight from its serial port
        until it's unplugged or gpsd starts."""
        fd = os.open(path, os.O_RDONLY | os.O_NOCTTY | os.O_NONBLOCK)
        try:
            a = termios.tcgetattr(fd)
            a[0] = a[1] = a[3] = 0
            a[2] = termios.CS8 | termios.CREAD | termios.CLOCAL
            a[4] = a[5] = termios.B9600
            termios.tcsetattr(fd, termios.TCSANOW, a)
            safe_emit(self, "_report", {"gpsd": True})
            safe_emit(self, "_report", {"receiver": True})
            print(f"GPS: reading {os.path.basename(path)}", flush=True)
            buf, in_view, checked = b"", {}, time.monotonic()
            found, used, logged = False, 0, time.monotonic()
            while True:
                if not found and time.monotonic() - logged > LOG_EVERY_S:
                    logged = time.monotonic()
                    print(f"GPS: looking for satellites, {sum(in_view.values())} in view", flush=True)
                if time.monotonic() - checked > CHECK_GPSD_S:
                    checked = time.monotonic()
                    try:
                        socket.create_connection(GPSD, timeout=1).close()
                        return                    # gpsd's running now: use it
                    except OSError:
                        pass
                if not select.select([fd], [], [], 2)[0]:
                    continue
                chunk = os.read(fd, 4096)
                if not chunk:
                    return                        # unplugged
                buf += chunk
                *lines, buf = buf.split(b"\n")
                for raw in lines:
                    f = nmea_fields(raw.decode("ascii", "replace"))
                    if not f or len(f[0]) < 5:
                        continue
                    kind = f[0][2:]
                    if kind == "RMC" and len(f) > 2 and (f[2] == "A") != found:
                        found = f[2] == "A"
                        print("GPS: " + (f"position found, {used} satellites" if found
                                         else "lost the position"), flush=True)
                    if kind == "RMC" and len(f) > 8 and f[2] == "A":
                        lat, lon = nmea_coord(f[3], f[4]), nmea_coord(f[5], f[6])
                        if lat is not None and lon is not None:
                            safe_emit(self, "_report", {
                                "lat": lat, "lon": lon,
                                "speed": float(f[7] or 0) * KNOTS_TO_MS,
                                "heading": float(f[8]) if f[8] else None,
                                "source": "gps",
                            })
                    elif kind == "GSV" and len(f) > 3 and f[3].isdigit():
                        in_view[f[0][:2]] = int(f[3])     # per system: GPS, GLONASS, BeiDou...
                    elif kind == "GGA" and len(f) > 7:
                        used = int(f[7]) if f[7].isdigit() else 0
                        safe_emit(self, "_report", {"sats": used, "view": sum(in_view.values())})
        finally:
            os.close(fd)

    # ---- the simulated drive ----------------------------------------------------
    def _tick(self):
        live = self._vehicle is not None and self._vehicle.live
        if self._pos.check(time.monotonic(), live):
            self.changed.emit()
        if self._route and self._pos.demo_allowed(live):
            self._demo_step()

    def _demo_step(self):
        mph = self._vehicle.speed if self._vehicle is not None else 30.0
        speed = mph * MPH_TO_MS
        step = speed * self._timer.interval() / 1000
        if self._path:
            # Driving a navigation route: stop at the end of it.
            if self._path_travelled >= self._path.length:
                speed = 0.0
            self._path_travelled = min(self._path.length, self._path_travelled + step)
            lon, lat, heading = self._path.at(self._path_travelled)
        else:
            self._travelled += step
            lon, lat, heading = self._route.at(self._travelled)
        self._pos.simulated({"lat": lat, "lon": lon, "speed": speed, "heading": heading, "source": "demo"})
        self.changed.emit()

    def _apply(self, report):
        if "gpsd" in report:
            if report["gpsd"] != self._gpsd:
                self._gpsd = report["gpsd"]
                if not self._gpsd:
                    self._sats = self._in_view = 0
                self.changed.emit()
            return
        if "sats" in report:
            if (report["sats"], report["view"]) != (self._sats, self._in_view):
                self._sats, self._in_view = report["sats"], report["view"]
                self.changed.emit()
            return
        if "receiver" in report:
            had = self._pos.fix
            self._pos.receiver()
            if self._pos.fix is not had:
                self.changed.emit()              # the demo drive gave way
            return
        self._pos.real(report, time.monotonic())
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
        """There's a position: the receiver's (maybe stale) or the demo drive's."""
        return self._pos.fix is not None

    @pyqtProperty(float, notify=changed)
    def lat(self):
        return self._pos.fix["lat"] if self._pos.fix else 0.0

    @pyqtProperty(float, notify=changed)
    def lon(self):
        return self._pos.fix["lon"] if self._pos.fix else 0.0

    @pyqtProperty(float, notify=changed)
    def speed(self):
        """Metres per second (0 while the position is stale: it isn't known)."""
        if not self._pos.fix or self._pos.stale(time.monotonic()):
            return 0.0
        return self._pos.fix["speed"]

    @pyqtProperty(float, notify=changed)
    def heading(self):
        """Degrees clockwise from north."""
        return self._pos.fix["heading"] if self._pos.fix else 0.0

    @pyqtProperty(str, notify=changed)
    def source(self):
        """'gps', 'demo' or '' (no position)."""
        return self._pos.fix["source"] if self._pos.fix else ""

    @pyqtProperty(bool, notify=changed)
    def receiverConnected(self):
        """True while a receiver is connected (it may still be finding satellites)."""
        return self._gpsd

    @pyqtProperty(bool, notify=changed)
    def realFix(self):
        """True while the receiver's position is fresh."""
        return self._pos.fresh(time.monotonic())

    @pyqtProperty(bool, notify=changed)
    def stale(self):
        """True while the receiver's last position is held because it has
        lost the sky (a tunnel, a garage): the truck stays where it was,
        and directions wait."""
        return self._pos.stale(time.monotonic())

    @pyqtProperty(int, notify=changed)
    def satellites(self):
        """Satellites used for the fix (when read directly from the receiver)."""
        return self._sats

    @pyqtProperty(int, notify=changed)
    def satellitesInView(self):
        return self._in_view
