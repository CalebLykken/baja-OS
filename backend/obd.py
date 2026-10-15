"""Real engine data from the OBD-II adapter (an OBDLink EX on USB, which
speaks the ELM327 command set over a serial port).

A background thread finds the adapter, wakes the car's engine computer and
polls it: RPM, manifold pressure (for boost) and speed every round, and
coolant, intake air and the battery a little less often. The car answers
about ten questions a second over its K-line (ISO 14230), so the gauges
update a few times a second.

Read only: it never sends mode 04 (clear codes) or anything that writes.
With no adapter, or the key off, it just keeps looking, and VehicleData
carries on with its simulated drive.
"""

import glob
import os
import select
import termios
import threading
import time

from PyQt6.QtCore import QObject, pyqtSignal

from backend import safe_emit

PORTS = ("/dev/serial/by-id/*OBDLink*", "/dev/serial/by-id/*ELM*", "/dev/ttyUSB*")
FAST = (0x0C, 0x0B, 0x0D)            # RPM, manifold pressure, speed: every round
SLOW = (0x05, 0x0F, "ATRV")          # coolant, intake air, battery: one per round
GIVE_UP_AFTER = 5                    # unanswered requests in a row: the car's gone
ROUND_MIN_S = 0.1                    # at most 10 updates a second, however fast the car
# Waiting for the car: often at first (key just turned off and on), then
# rarely, so a parked car's adapter can go to sleep instead of being woken
# every few seconds (it draws from the car's battery).
RETRY_S, RETRY_SLOW_S, SLOW_AFTER_S = 3.0, 20.0, 60.0


def retry_wait(since):
    return RETRY_S if time.monotonic() - since < SLOW_AFTER_S else RETRY_SLOW_S


def find_port():
    for pattern in PORTS:
        found = sorted(glob.glob(pattern))
        if found:
            return found[0]
    return None


class Elm:
    """The adapter's serial line: raw 115200 baud, prompt-terminated replies."""

    def __init__(self, path):
        self.fd = os.open(path, os.O_RDWR | os.O_NOCTTY | os.O_NONBLOCK)
        a = termios.tcgetattr(self.fd)
        a[0] = a[1] = a[3] = 0
        a[2] = termios.CS8 | termios.CREAD | termios.CLOCAL
        a[4] = a[5] = termios.B115200
        a[6][termios.VMIN] = a[6][termios.VTIME] = 0
        termios.tcsetattr(self.fd, termios.TCSANOW, a)
        termios.tcflush(self.fd, termios.TCIOFLUSH)

    def close(self):
        try:
            os.close(self.fd)
        except OSError:
            pass

    def send(self, command, timeout=3.0):
        """The reply's text (without the prompt), or raises OSError."""
        os.write(self.fd, (command + "\r").encode())
        buf, end = b"", time.monotonic() + timeout
        while time.monotonic() < end:
            if select.select([self.fd], [], [], 0.05)[0]:
                buf += os.read(self.fd, 4096)
                if b">" in buf:
                    break
        return buf.decode(errors="replace").replace(">", "").replace("\r", " ").strip()

    def pid(self, pid):
        """Mode 01 data bytes, e.g. 0x0C -> [0x1A, 0xF8], or None."""
        reply = self.send(f"01{pid:02X}").replace(" ", "")
        head = f"41{pid:02X}"
        i = reply.find(head)
        if i < 0:
            return None
        hexes = reply[i + 4:]
        out = []
        for j in range(0, len(hexes) - 1, 2):
            try:
                out.append(int(hexes[j:j + 2], 16))
            except ValueError:
                break
        return out or None


def convert(pid, d, baro):
    """A PID's bytes as the dashboard's units (mph, psi, °F)."""
    if pid == 0x0C:
        return "rpm", (d[0] * 256 + d[1]) / 4
    if pid == 0x0B:
        return "map", d[0]
    if pid == 0x0D:
        return "speed", d[0] / 1.609344
    if pid == 0x05:
        return "coolant", (d[0] - 40) * 9 / 5 + 32
    if pid == 0x0F:
        return "intake", (d[0] - 40) * 9 / 5 + 32
    return None, None


class ObdReader(QObject):
    """Feeds VehicleData. `reading` carries a dict of fresh values; `lost`
    says the car stopped answering (key off, unplugged)."""
    reading = pyqtSignal(dict)
    lost = pyqtSignal()

    def start(self):
        threading.Thread(target=self._run, name="obd", daemon=True).start()

    def _run(self):
        self._since = time.monotonic()        # when the car last went quiet
        while True:
            path = find_port()
            if path:
                try:
                    self._session(path)
                except OSError:
                    pass                      # unplugged mid-read: look again
                safe_emit(self, "lost")
            time.sleep(retry_wait(self._since))

    def _session(self, path):
        elm = Elm(path)
        try:
            elm.send("ATZ", 4)
            time.sleep(0.5)
            for c in ("ATE0", "ATL0", "ATS0", "ATH0", "ATAT2", "ATSP0"):
                elm.send(c)
            # Wake the engine computer; with the key off it doesn't answer.
            while not elm.pid(0x00):
                time.sleep(retry_wait(self._since))
                if not os.path.exists(path):
                    return
            baro = 101.3                      # kPa, until the car tells us
            misses, turn = 0, 0
            while misses < GIVE_UP_AFTER:
                started = time.monotonic()
                values = {}
                for item in FAST + (SLOW[turn % len(SLOW)],):
                    if item == "ATRV":
                        try:
                            values["voltage"] = float(elm.send("ATRV").rstrip("V"))
                        except ValueError:
                            pass
                        continue
                    d = elm.pid(item)
                    if not d:
                        misses += 1
                        continue
                    misses = 0
                    try:
                        key, value = convert(item, d, baro)
                    except IndexError:
                        continue
                    if key:
                        values[key] = value
                # With the engine stopped (key on), the manifold sits at the
                # outside air pressure: the zero for boost from here on.
                if values.get("rpm") == 0 and "map" in values:
                    baro = values["map"]
                if "map" in values:
                    values["boost"] = (values.pop("map") - baro) * 0.145038
                if values:
                    safe_emit(self, "reading", values)
                turn += 1
                time.sleep(max(0.0, ROUND_MIN_S - (time.monotonic() - started)))
            self._since = time.monotonic()
        finally:
            elm.close()
