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

import bisect
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

from backend import errorlog, safe_emit

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
RATE_HZ = 5             # position reports per second the receiver is asked for
DYNMODEL = 4            # u-blox "automotive": a truck on a road, not a walker
SETUP_WAIT_S = 1.0      # how long to listen for the receiver's ACK/NAK replies


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


def ubx_frame(cls, msg_id, payload=b""):
    """A u-blox binary (UBX) message: sync B5 62, class, id, little-endian
    length, payload, then a Fletcher-8 checksum over class..payload."""
    body = bytes([cls, msg_id]) + len(payload).to_bytes(2, "little") + bytes(payload)
    a = b = 0
    for byte in body:
        a = (a + byte) & 0xFF
        b = (b + a) & 0xFF
    return b"\xb5\x62" + body + bytes([a, b])


def ubx_valset_frame():
    """M9N and newer: CFG-VALSET into RAM only (layer bit 0, so nothing is
    saved to flash): automotive dynamic model, a measurement every
    1000/RATE_HZ ms, one navigation solution per measurement."""
    items = (0x20110021).to_bytes(4, "little") + bytes([DYNMODEL])                          # CFG-NAVSPG-DYNMODEL
    items += (0x30210001).to_bytes(4, "little") + (1000 // RATE_HZ).to_bytes(2, "little")   # CFG-RATE-MEAS
    items += (0x30210002).to_bytes(4, "little") + (1).to_bytes(2, "little")                 # CFG-RATE-NAV
    return ubx_frame(0x06, 0x8A, bytes([0, 0x01, 0, 0]) + items)          # version 0, layers RAM


def ubx_nav5_frame():
    """u-blox 7 and 8: CFG-NAV5 with only the dynamic model set (mask bit 0)."""
    payload = bytearray(36)
    payload[0:2] = (0x0001).to_bytes(2, "little")
    payload[2] = DYNMODEL
    return ubx_frame(0x06, 0x24, bytes(payload))


def ubx_rate_frame():
    """u-blox 7 and 8: CFG-RATE, a measurement every 1000/RATE_HZ ms, one
    navigation solution per measurement, GPS time (timeRef 1)."""
    return ubx_frame(0x06, 0x08, (1000 // RATE_HZ).to_bytes(2, "little") + (1).to_bytes(2, "little")
                     + (1).to_bytes(2, "little"))


def ubx_replies(data):
    """The (acked, class, id) of each UBX-ACK-ACK / ACK-NAK found in `data`
    (the NMEA text around them is skipped)."""
    out, i = [], 0
    while True:
        i = data.find(b"\xb5\x62\x05", i)
        if i < 0 or i + 10 > len(data):
            return out
        if data[i + 3] in (0, 1) and data[i + 4:i + 6] == b"\x02\x00":
            if data[i:i + 10] == ubx_frame(5, data[i + 3], data[i + 6:i + 8]):
                out.append((data[i + 3] == 1, data[i + 6], data[i + 7]))
                i += 10
                continue
        i += 1


def is_ublox(path):
    """Only a u-blox is sent UBX commands: anything else on the port is not ours to configure."""
    return "u-blox" in os.path.basename(path).lower()


SETUP_TRIES = 3         # asks before giving up on an answer from the receiver
SETUP_RETRY_S = 3       # between those asks


def setup_frames():
    """Everything a u-blox is sent: the M9N's VALSET, then u-blox 7/8's NAV5 and RATE
    (a receiver NAKs the generation it doesn't know)."""
    return ubx_valset_frame() + ubx_nav5_frame() + ubx_rate_frame()


def setup_summary(data):
    """(ok, text) for what the receiver answered in `data`: ok when any
    setup frame was acked. One NAK per generation is expected (VALSET on a
    u-blox 7/8; NAV5 and RATE possibly on an M9)."""
    names = {(0x06, 0x8A): "VALSET", (0x06, 0x24): "NAV5", (0x06, 0x08): "RATE"}
    heard = [(names[(c, i)], ok) for ok, c, i in ubx_replies(data) if (c, i) in names]
    text = ", ".join(f"{n} " + ("ack" if ok else "nak") for n, ok in heard)
    if any(ok for _, ok in heard):
        return True, f"GPS: set automotive mode and {RATE_HZ} Hz (acked: {text})"
    return False, "GPS: receiver setup not acked (" + (text or "heard nothing") + ")"


def configure_fd(fd):
    """Send the setup frames on an open receiver port and listen for the
    replies. Returns ok (see setup_summary). Never raises."""
    try:
        os.write(fd, setup_frames())
        data, end = b"", time.monotonic() + SETUP_WAIT_S
        while time.monotonic() < end:
            if select.select([fd], [], [], 0.2)[0]:
                chunk = os.read(fd, 4096)
                if not chunk:
                    break
                data += chunk
    except (OSError, ValueError) as e:
        print(f"GPS: couldn't set the receiver up ({e})", flush=True)
        return False
    ok, text = setup_summary(data)
    print(text, flush=True)
    return ok


def configure_receiver(path, fd, tries=SETUP_TRIES, sleep=time.sleep):
    """Put a u-blox receiver in automotive mode at RATE_HZ, in RAM only (it
    is set again each time it's opened; nothing is saved to the receiver).
    `fd` is the reader's own open port, so no one else is reading the
    replies; this never opens the port itself. Asks up to `tries` times
    until something is acked. Returns whether it was. Never raises; other
    receivers are never written to."""
    if not path or fd is None or not is_ublox(path):
        return False
    for n in range(tries):
        if n:
            sleep(SETUP_RETRY_S)
        if configure_fd(fd):
            return True
    return False


def gpsd_setup(device):
    """The ?DEVICE command that sends the setup frames through gpsd (which
    holds the port exclusively), for a gpsd DEVICE/DEVICES entry that is a
    u-blox, else None. gpsd gives no ACK to check."""
    if not isinstance(device, dict) or not isinstance(device.get("path"), str):
        return None
    # gpsd only writes to a device whose type it knows ("Type of %s is unknown"
    # otherwise), and names the driver once it has: wait for that.
    if "u-blox" not in str(device.get("driver") or "").lower():
        return None
    cmd = {"path": device["path"], "hexdata": setup_frames().hex()}
    return ("?DEVICE=" + json.dumps(cmd) + ";\n").encode()


def nmea_fields(line):
    """A checked NMEA sentence's fields ('$GNRMC,...*hh' -> ['GNRMC', ...]), or None."""
    line = line.strip()
    # UBX replies end without a newline, so they can sit in front of the sentence on its line.
    line = line[line.rfind("$"):] if "$" in line else line
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
        if len(pts) < 2 or self.length <= 0:       # nothing to drive (and loop would divide by 0)
            raise ValueError("a demo route needs at least two distinct points")

    def at(self, distance):
        """(lon, lat, heading) at `distance` metres along the path."""
        d = distance % self.length if self.loop else min(distance, self.length - 0.01)
        lo = min(max(bisect.bisect_right(self.cum, d) - 1, 0), len(self.cum) - 2)
        a, b = self.points[lo], self.points[lo + 1]
        seg = self.cum[lo + 1] - self.cum[lo] or 1.0
        f = (d - self.cum[lo]) / seg
        # Head toward a point ~25 m ahead so corners turn smoothly.
        ahead = self._point(d + 25)
        here = (a[0] + (b[0] - a[0]) * f, a[1] + (b[1] - a[1]) * f)
        if _metres(here, ahead) < 1.0:             # at the end of a one-way route
            behind = self._point(max(0.0, d - 25))
            if _metres(behind, here) < 1.0:        # route shorter than that: last real segment
                behind, here = next(((p, q) for p, q in zip(reversed(self.points[:-1]), reversed(self.points[1:]))
                                     if _metres(p, q) >= 0.01), (behind, here))
            return here[0], here[1], _bearing(behind, here)
        return here[0], here[1], _bearing(here, ahead)

    def _point(self, distance):
        d = distance % self.length if self.loop else min(distance, self.length)
        i = bisect.bisect_left(self.cum, d)         # first point at or past d
        if i < len(self.cum):
            i = min(max(i - 1, 0), len(self.cum) - 2)
            a, b = self.points[i], self.points[i + 1]
            f = (d - self.cum[i]) / ((self.cum[i + 1] - self.cum[i]) or 1.0)
            return a[0] + (b[0] - a[0]) * f, a[1] + (b[1] - a[1]) * f
        return self.points[-1]


def _count(value):
    return value if isinstance(value, int) and not isinstance(value, bool) and value >= 0 else None


def sky_report(msg):
    """The {"sats", "view"} report for a gpsd SKY message, the same one the
    NMEA path makes: satellites used (uSat, else the ones marked used) and
    in view (nSat, else the length of the list). None for a SKY that doesn't
    count satellites: gpsd also sends one with only the DOPs."""
    sats = msg.get("satellites")
    sats = [s for s in sats if isinstance(s, dict)] if isinstance(sats, list) else None
    used, view = _count(msg.get("uSat")), _count(msg.get("nSat"))
    if used is None and sats is not None:
        used = sum(1 for s in sats if s.get("used") is True)
    if view is None and sats is not None:
        view = len(sats)
    return None if used is None or view is None else {"sats": used, "view": view}


def _number(value):
    """The value as a finite float, or None: not a number, a bool, or NaN and inf."""
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    try:
        value = float(value)
    except OverflowError:
        return None
    return value if math.isfinite(value) else None


def _on_earth(lat, lon):
    """Whether lat and lon are a position: finite, within 90 and 180 degrees."""
    return math.isfinite(lat) and math.isfinite(lon) and -90 <= lat <= 90 and -180 <= lon <= 180


def tpv_report(msg):
    """The {lat, lon, speed, heading, source} fix for a gpsd TPV message, or
    None when it has no 2D fix or no usable position. Odd values don't get
    through: a speed that isn't a number is 0.0, a track that isn't one is None."""
    mode = _number(msg.get("mode"))
    lat, lon = _number(msg.get("lat")), _number(msg.get("lon"))
    if mode is None or mode < 2 or lat is None or lon is None or not _on_earth(lat, lon):
        return None
    speed, track = _number(msg.get("speed")), _number(msg.get("track"))
    return {
        "lat": lat, "lon": lon,
        "speed": speed if speed is not None and speed >= 0 else 0.0,
        "heading": track % 360 if track is not None else None,
        "source": "gps",
    }


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
        speed = _number(report.get("speed"))
        report["speed"] = speed if speed is not None else 0.0      # never a non-number in the comparison
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
    """`changed` fires on any update (every property notifies on it): a new
    position, satellite counts, the receiver connecting or going, the demo
    drive giving way, the fix going stale. `fixChanged` fires once per new
    position only (a real report, or a step of the demo drive, just after
    `changed`), for listeners that count or record fixes."""
    changed = pyqtSignal()
    fixChanged = pyqtSignal()
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
            except (OSError, ValueError, termios.error) as e:
                print(f"GPS: gpsd read failed ({e}); retrying", flush=True)
            except Exception as e:            # anything else must not end the thread
                errorlog.log.report(type(e), e, e.__traceback__, label="GPS: reader error, retrying:")
            if not used:
                path = find_receiver()
                if path:
                    try:
                        self._read_receiver(path)
                    except (OSError, termios.error) as e:   # unplugged: look again
                        print(f"GPS: lost the receiver ({e}); retrying", flush=True)
                    except Exception as e:
                        errorlog.log.report(type(e), e, e.__traceback__, label="GPS: reader error, retrying:")
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
            # gpsd being up isn't a receiver being connected: "connected" waits
            # for gpsd to report a device (or a fix or satellites from one).
            talking = False
            active = set()                # paths of the devices gpsd has open
            configured = set()            # device paths already sent the setup
            last_sent = None              # the path an ERROR reply would be about

            def reports():
                try:
                    yield from s.makefile("r", encoding="utf-8", errors="replace")
                except TimeoutError:
                    if talking:
                        raise                 # a receiver gone quiet: reconnect
                    # gpsd with nothing attached has nothing to say: not a failure

            for line in reports():
                try:
                    msg = json.loads(line)
                except ValueError:
                    continue
                if not isinstance(msg, dict):
                    continue                      # null, a number, a list: not a report
                kind = msg.get("class")
                if kind in ("DEVICES", "DEVICE"):
                    listed = msg.get("devices") if kind == "DEVICES" else [msg]
                    if kind == "DEVICES":
                        active.clear()            # the full list
                    for device in listed if isinstance(listed, list) else []:
                        if isinstance(device, dict):
                            if "activated" in device and not device["activated"]:
                                active.discard(device.get("path"))
                            else:
                                active.add(device.get("path"))
                    if talking and not active:
                        talking = False           # unplugged: gpsd is on its own again
                        safe_emit(self, "_report", {"gpsd": False})
                if not talking and (kind in ("TPV", "SKY") or active):
                    talking = True                # a receiver, not just gpsd on its own
                    safe_emit(self, "_report", {"gpsd": True})
                    safe_emit(self, "_report", {"receiver": True})
                if kind in ("DEVICES", "DEVICE"):
                    for device in listed if isinstance(listed, list) else []:
                        if isinstance(device, dict) and "activated" in device and not device["activated"]:
                            configured.discard(device.get("path"))   # closed: send again when it's back
                            continue
                        cmd = gpsd_setup(device)
                        if cmd and device["path"] not in configured:
                            configured.add(device["path"])      # once per appearance
                            last_sent = device["path"]
                            try:
                                s.sendall(cmd)
                                print(f"GPS: sent automotive mode and {RATE_HZ} Hz to {device['path']} "
                                      "through gpsd (unverified: gpsd gives no ack)", flush=True)
                            except OSError as e:
                                print(f"GPS: couldn't set the receiver up through gpsd ({e})", flush=True)
                if kind == "ERROR":
                    # gpsd refused the setup (or something else): don't claim it went through
                    print(f"GPS: gpsd refused a command ({msg.get('message')})", flush=True)
                    configured.discard(last_sent)         # try again at the next DEVICE message
                    continue
                if kind == "SKY":
                    report = sky_report(msg)
                    if report:
                        safe_emit(self, "_report", report)
                    continue
                if kind != "TPV":
                    continue
                report = tpv_report(msg)
                if report is not None:
                    safe_emit(self, "_report", report)
        return True

    def _read_receiver(self, path):
        """Read the receiver's NMEA sentences straight from its serial port
        until it's unplugged or gpsd starts."""
        # Read-write only for a u-blox, which is sent its setup; the rest are only listened to.
        fd = os.open(path, (os.O_RDWR if is_ublox(path) else os.O_RDONLY) | os.O_NOCTTY | os.O_NONBLOCK)
        try:
            a = termios.tcgetattr(fd)
            a[0] = a[1] = a[3] = 0
            a[2] = termios.CS8 | termios.CREAD | termios.CLOCAL
            a[4] = a[5] = termios.B9600
            termios.tcsetattr(fd, termios.TCSANOW, a)
            safe_emit(self, "_report", {"gpsd": True})
            safe_emit(self, "_report", {"receiver": True})
            print(f"GPS: reading {os.path.basename(path)}", flush=True)
            configure_receiver(path, fd)          # before the loop: no one else reads, so the acks are seen
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
                    try:
                        found, used = self._sentence(f, found, used, in_view)
                    except ValueError as e:         # one bad sentence isn't a lost receiver
                        print(f"GPS: skipped a bad {f[0]} sentence ({e})", flush=True)
        finally:
            os.close(fd)

    def _sentence(self, f, found, used, in_view):
        """Act on one checked NMEA sentence's fields; the new (found, used)."""
        kind = f[0][2:]
        if kind == "RMC" and len(f) > 2 and (f[2] == "A") != found:
            found = f[2] == "A"
            print("GPS: " + (f"position found, {used} satellites" if found
                             else "lost the position"), flush=True)
        if kind == "RMC" and len(f) > 8 and f[2] == "A":
            lat, lon = nmea_coord(f[3], f[4]), nmea_coord(f[5], f[6])
            speed = float(f[7] or 0) * KNOTS_TO_MS
            heading = float(f[8]) if f[8] else None
            if not math.isfinite(speed):
                speed = 0.0                   # "nan" or "inf" in the sentence
            if heading is not None and not math.isfinite(heading):
                heading = None
            if lat is not None and lon is not None and _on_earth(lat, lon):
                safe_emit(self, "_report", {
                    "lat": lat, "lon": lon,
                    "speed": speed,
                    "heading": heading,
                    "source": "gps",
                })
        elif kind == "GSV" and len(f) > 3 and f[3].isdigit():
            in_view[f[0][:2]] = int(f[3])     # per system: GPS, GLONASS, BeiDou...
        elif kind == "GGA" and len(f) > 7:
            used = int(f[7]) if f[7].isdigit() else 0
            safe_emit(self, "_report", {"sats": used, "view": sum(in_view.values())})
        return found, used

    # ---- the simulated drive ----------------------------------------------------
    def _tick(self):
        # The demo drive goes with the simulated engine data: in a truck whose
        # car has answered it never runs, even with the key off.
        real = self._vehicle is not None and not self._vehicle.simulated
        if self._pos.check(time.monotonic(), real):
            self.changed.emit()
        if self._route and self._pos.demo_allowed(real):
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
        self.fixChanged.emit()

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
        self.fixChanged.emit()

    def followPath(self, points):
        """In demo mode, drive this route (from its start) instead of the loop."""
        if len(points) >= 2:
            try:
                route = DemoRoute(points=points, loop=False)
            except (TypeError, ValueError, IndexError):
                return                              # zero-length or malformed: keep the loop
            self._path = route
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
