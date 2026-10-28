"""Real engine data from the OBD-II adapter (an OBDLink EX on USB, which
speaks the ELM327 command set over a serial port).

A background thread finds the adapter, wakes the car's engine computer and
polls it: RPM, manifold pressure (for boost) and speed every round, and
coolant, intake air and the battery a little less often. The car answers
about ten questions a second over its K-line (ISO 14230), so the gauges
update a few times a second.

Boost is manifold pressure minus the outside air pressure (baro). Baro comes
from the engine computer (PID 0x33) when it has one, else from the manifold
with the engine stopped (key on), and the last one measured is kept (the
`baro` signal) so a restart with the engine running starts from it.

Read only: it never sends mode 04 (clear codes) or anything that writes.
With no adapter, or the key off, it just keeps looking, and VehicleData
shows the engine values as unknown (backend/vehicle.py). While it waits for the car it still
reads the battery: the adapter measures that itself (ATRV), so it works
with the engine computer silent, and it tells key-off (backend/ignition.py)
whether the engine is still running.
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
# Waking the car: the first time the adapter searches for its protocol,
# which can take several seconds. Cut short, the next command stops it.
WAKE_TIMEOUT_S = 15.0
# The battery while waiting: every second for the first two minutes after
# the car goes quiet (past the power relay's hold time), then with each try.
VOLTS_EVERY_S, VOLTS_FOR_S = 1.0, 120.0
LOG_EVERY_S = 15.0                   # a one-line summary in the journal while live
BARO_PID = 0x33                      # barometric pressure, kPa (not every engine computer has it)
BARO_DEFAULT = 101.3                 # kPa at sea level, until measured
BARO_RANGE = (50.0, 110.0)           # kPa: from 18,000 ft up to a stormy sea level
BARO_SAVE_KPA = 1.0                  # keep a new baro only if it moved further than this


def retry_wait(since):
    return RETRY_S if time.monotonic() - since < SLOW_AFTER_S else RETRY_SLOW_S


def pid_supported(bitmap, base, pid):
    """Whether `bitmap` (the 4 data bytes answering PID `base`: 0x00, 0x20,
    ...) says the car answers `pid`: one bit per PID after `base`, from the
    top bit of the first byte."""
    i = pid - base - 1
    return bool(bitmap) and len(bitmap) >= 4 and 0 <= i < 32 and bool(bitmap[i // 8] & (0x80 >> i % 8))


def plausible_baro(kpa):
    return kpa is not None and BARO_RANGE[0] <= kpa <= BARO_RANGE[1]


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
        # Drop what's left of an earlier reply that came after its timeout:
        # read as this one's, it would shift every answer after it.
        termios.tcflush(self.fd, termios.TCIFLUSH)
        os.write(self.fd, (command + "\r").encode())
        buf, end = b"", time.monotonic() + timeout
        while time.monotonic() < end:
            if select.select([self.fd], [], [], 0.05)[0]:
                buf += os.read(self.fd, 4096)
                if b">" in buf:
                    break
        return buf.decode(errors="replace").replace(">", "").replace("\r", " ").strip()

    def volts(self):
        """The adapter's supply voltage (the car's battery), or None."""
        try:
            return float(self.send("ATRV").rstrip("V"))
        except ValueError:
            return None

    def pid(self, pid, timeout=3.0):
        """Mode 01 data bytes, e.g. 0x0C -> [0x1A, 0xF8], or None."""
        reply = self.send(f"01{pid:02X}", timeout).replace(" ", "")
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


def convert(pid, d):
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
    says the readings stopped (key off, unplugged). `quiet` says the car
    itself stopped answering with the adapter still there: the key going
    off (backend/ignition.py). `voltage` carries the battery whenever it's
    read, with the car answering or not. `baro` carries a new outside air
    pressure (kPa) to keep for the next start."""
    reading = pyqtSignal(dict)
    lost = pyqtSignal()
    quiet = pyqtSignal()
    voltage = pyqtSignal(float)
    baro = pyqtSignal(float)

    def __init__(self, baro=None, parent=None):
        """`baro`: the outside air pressure kept from the last drive (kPa,
        from the settings), what boost zeroes from until a new one is read."""
        super().__init__(parent)
        self._baro = BARO_DEFAULT
        self._saved = None                    # the baro that was last kept
        try:
            kept = float(baro)
        except (TypeError, ValueError):
            kept = None
        if plausible_baro(kept):
            self._baro = self._saved = kept
        self._baro_pid = None                 # does the car answer PID 0x33? None: not asked yet

    def start(self):
        threading.Thread(target=self._run, name="obd", daemon=True).start()

    def _run(self):
        self._since = time.monotonic()        # when the car last went quiet
        self._protocol = "0"                  # search, until the car has answered
        while True:
            path = find_port()
            if path:
                try:
                    self._session(path)
                except (OSError, termios.error):
                    pass                      # unplugged mid-read: look again
                safe_emit(self, "lost")
            time.sleep(retry_wait(self._since))

    def _session(self, path):
        elm = Elm(path)
        try:
            elm.send("ATZ", 4)
            time.sleep(0.5)
            for c in ("ATE0", "ATL0", "ATS0", "ATH0", "ATAT2", "ATSP" + self._protocol):
                elm.send(c)
            while self._wait(elm, path):
                print("OBD: the car answered", flush=True)
                if self._protocol == "0":
                    # The protocol the search found ("A5" is ISO 14230-4,
                    # KWP fast init), so a reconnect doesn't search again.
                    found = elm.send("ATDPN").lstrip("A")
                    if len(found) == 1 and found in "123456789ABC":
                        self._protocol = found
                self._poll(elm)
                self._since = time.monotonic()
                print("OBD: the car stopped answering", flush=True)
                safe_emit(self, "quiet")
                safe_emit(self, "lost")
                # Ask it the same way until it answers again: no search.
                elm.send("ATSP" + self._protocol)
        finally:
            elm.close()

    def _wait(self, elm, path):
        """Wakes the engine computer (with the key off it doesn't answer):
        True once it answers, False if the adapter goes away. Reads the
        battery meanwhile."""
        ask_at = time.monotonic()
        while os.path.exists(path):
            self._volts(elm)
            if time.monotonic() >= ask_at:
                if elm.pid(0x00, WAKE_TIMEOUT_S):
                    return True
                ask_at = time.monotonic() + retry_wait(self._since)
            if time.monotonic() - self._since < VOLTS_FOR_S:
                time.sleep(VOLTS_EVERY_S)
            else:
                time.sleep(max(0.0, ask_at - time.monotonic()))
        return False

    def _volts(self, elm):
        volts = elm.volts()
        if volts is not None:
            safe_emit(self, "voltage", volts)
        return volts

    def _start_baro(self, elm):
        """Before the first round, the outside air pressure from the car
        itself if it has it. If not, boost starts from the last one kept,
        which is right unless the truck has climbed or dropped since (a
        key-on corrects it)."""
        if self._baro_pid is None:
            self._baro_pid = self._ask_baro_pid(elm)
        if self._baro_pid:
            d = elm.pid(BARO_PID)
            if d:
                self._note_baro(d[0])

    def _ask_baro_pid(self, elm):
        """Whether the car answers PID 0x33, from its support bitmaps (PID
        0x00 for 0x01-0x20, PID 0x20 for 0x21-0x40); None if it didn't
        say. Prints them once, to see what this engine computer has."""
        low = elm.pid(0x00)
        if not low:
            return None
        high = None
        if pid_supported(low, 0x00, 0x20):    # it has a second bitmap
            high = elm.pid(0x20)
            if not high:
                return None
        found = pid_supported(high, 0x20, BARO_PID)
        print("OBD: PIDs 01-20 " + bytes(low).hex(" ") + ", 21-40 "
              + (bytes(high).hex(" ") if high else "none")
              + ("; barometric pressure: yes" if found else "; barometric pressure: no"), flush=True)
        return found

    def _note_baro(self, kpa):
        """A measured outside air pressure: boost zeroes from it, and it's
        kept for the next start once it has moved enough to matter (every
        keeping is a write to the SD card)."""
        if not plausible_baro(kpa):
            return
        self._baro = float(kpa)
        if self._saved is None or abs(kpa - self._saved) > BARO_SAVE_KPA:
            self._saved = float(kpa)
            safe_emit(self, "baro", float(kpa))

    def _poll(self, elm):
        """Reads the car until it stops answering."""
        self._start_baro(elm)
        misses, turn, logged, last = 0, 0, 0.0, {}
        while misses < GIVE_UP_AFTER:
            started = time.monotonic()
            values = {}
            for item in FAST + (SLOW[turn % len(SLOW)],):
                if item == "ATRV":
                    volts = self._volts(elm)
                    if volts is not None:
                        values["voltage"] = volts
                    continue
                d = elm.pid(item)
                if not d:
                    misses += 1
                    continue
                misses = 0
                try:
                    key, value = convert(item, d)
                except IndexError:
                    continue
                if key:
                    values[key] = value
            # With the engine stopped (key on), the manifold sits at the
            # outside air pressure: the zero for boost from here on.
            if values.get("rpm") == 0 and "map" in values:
                self._note_baro(values["map"])
            if "map" in values:
                values["boost"] = (values.pop("map") - self._baro) * 0.145038
            if values:
                safe_emit(self, "reading", values)
                last.update(values)
            if time.monotonic() - logged > LOG_EVERY_S and last:
                logged = time.monotonic()
                print("OBD: " + ", ".join(f"{k} {v:.1f}" for k, v in sorted(last.items())), flush=True)
            turn += 1
            time.sleep(max(0.0, ROUND_MIN_S - (time.monotonic() - started)))
