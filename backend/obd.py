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

Every 60 seconds it also asks whether the check-engine light is on (mode 01
PID 01) and, when the number of stored codes changed, reads them (mode 03)
and the pending ones (mode 07): the `codes` signal.

Read only: the only requests that can leave are modes 01, 03 and 07 (and the
adapter's own AT commands). `refuse_writes` stops anything else, mode 04
(clear codes) above all, before it reaches the serial port.
With no adapter, or the key off, it just keeps looking, and VehicleData
shows the engine values as unknown (backend/vehicle.py). While it waits for the car it still
reads the battery: the adapter measures that itself (ATRV), so it works
with the engine computer silent, and it tells key-off (backend/ignition.py)
whether the engine is still running.

`hold()` stops it for the shutdown (backend/ignition.py): no new step (a
poll, a wake attempt, a battery read) begins until `release()`, so the
adapter is quiet while the Pi powers off. At most the step in progress
finishes.
"""

import errno
import glob
import os
import re
import select
import termios
import threading
import time

from PyQt6.QtCore import QObject, pyqtSignal

from backend import errorlog, safe_emit

PORTS = ("/dev/serial/by-id/*OBDLink*", "/dev/serial/by-id/*ELM*", "/dev/ttyUSB*")
FAST = (0x0C, 0x0B, 0x0D)            # RPM, manifold pressure, speed: every round
SLOW = (0x05, 0x0F, "ATRV")          # coolant, intake air, battery: one per round
GIVE_UP_AFTER = 5                    # unanswered requests in a row: the car's gone
ROUND_MIN_S = 0.1                    # at most 10 updates a second, however fast the car
# Waiting for the car: often at first (key just turned off and on), then
# rarely, so a parked car's adapter can go to sleep instead of being woken
# every few seconds (it draws from the car's battery).
# After 10 minutes, every 2 minutes: a key-on after the truck sat parked that
# long waits at most 2 minutes for the dashboard to notice. The car going
# live resets the clock (`_since`). Not while the battery says the engine's
# running (only the K-line dropped): the key-off guard needs a battery
# reading every 30 s or so, so that stays at RETRY_SLOW_S.
RETRY_S, RETRY_SLOW_S, SLOW_AFTER_S = 3.0, 20.0, 60.0
RETRY_SLOWEST_S, SLOWEST_AFTER_S = 120.0, 600.0
# The battery over this: the alternator is charging, the engine's running.
# Not measured on this truck yet (see backend/ignition.py).
RUNNING_V = 13.3
HOLD_NAP_S = 0.5                     # how long a held reader sleeps between looks
# Waking the car: the first time the adapter searches for its protocol,
# which can take several seconds. Cut short, the next command stops it.
WAKE_TIMEOUT_S = 15.0
# The battery while waiting: every second for the first two minutes after
# the car goes quiet (past the power relay's hold time), then with each try.
VOLTS_EVERY_S, VOLTS_FOR_S = 1.0, 120.0
CODES_EVERY_S = 60.0                 # ask whether the check-engine light is on, and how many codes
READ_MODES = ("01", "03", "07")      # the only OBD modes ever sent: data, stored codes, pending codes
LOG_EVERY_S = 15.0                   # a one-line summary in the journal while live
BARO_PID = 0x33                      # barometric pressure, kPa (not every engine computer has it)
BARO_DEFAULT = 101.3                 # kPa at sea level, until measured
BARO_RANGE = (50.0, 110.0)           # kPa: from 18,000 ft up to a stormy sea level
BARO_STEADY = (3, 1.0)               # rounds at RPM 0, and kPa: how long and how still the manifold
                                     # must hold before it's taken as the outside air


# Short descriptions of common generic codes. Anything else (the Subaru P1xxx
# ones, say) shows just the code.
DTC_TEXT = {
    "P0030": "O2 heater circuit, bank 1 sensor 1",
    "P0101": "Mass airflow out of range",
    "P0102": "Mass airflow low",
    "P0103": "Mass airflow high",
    "P0105": "Manifold pressure circuit",
    "P0106": "Manifold pressure out of range",
    "P0107": "Manifold pressure low",
    "P0108": "Manifold pressure high",
    "P0112": "Intake air temp low",
    "P0113": "Intake air temp high",
    "P0117": "Coolant temp low",
    "P0118": "Coolant temp high",
    "P0121": "Throttle position out of range",
    "P0122": "Throttle position low",
    "P0123": "Throttle position high",
    "P0125": "Coolant too cold for closed loop",
    "P0128": "Thermostat: coolant below temp",
    "P0131": "O2 sensor low, bank 1 sensor 1",
    "P0132": "O2 sensor high, bank 1 sensor 1",
    "P0133": "O2 sensor slow, bank 1 sensor 1",
    "P0134": "O2 sensor no activity, bank 1 sensor 1",
    "P0135": "O2 heater, bank 1 sensor 1",
    "P0137": "O2 sensor low, bank 1 sensor 2",
    "P0138": "O2 sensor high, bank 1 sensor 2",
    "P0171": "Fuel mixture too lean",
    "P0172": "Fuel mixture too rich",
    "P0300": "Random misfire",
    "P0301": "Cylinder 1 misfire",
    "P0302": "Cylinder 2 misfire",
    "P0303": "Cylinder 3 misfire",
    "P0304": "Cylinder 4 misfire",
    "P0325": "Knock sensor circuit",
    "P0327": "Knock sensor low",
    "P0328": "Knock sensor high",
    "P0335": "Crankshaft sensor circuit",
    "P0340": "Camshaft sensor circuit",
    "P0420": "Catalyst efficiency low",
    "P0440": "Evap system fault",
    "P0441": "Evap purge flow wrong",
    "P0442": "Evap small leak",
    "P0446": "Evap vent circuit",
    "P0455": "Evap large leak",
    "P0456": "Evap very small leak",
    "P0500": "Vehicle speed sensor",
    "P0505": "Idle control system",
    "P0506": "Idle speed low",
    "P0507": "Idle speed high",
    "P0600": "Control module communication",
    "P0601": "Control module memory",
    "P0605": "Control module ROM",
}


def describe(code):
    """A short description of a trouble code, or '' for one not in the table."""
    return DTC_TEXT.get(str(code).upper(), "")


def refuse_writes(command):
    """Raises ValueError for any request that isn't read only: an OBD request
    (hex) in a mode other than READ_MODES, mode 04 (clear codes) above all.
    The adapter's own AT commands pass."""
    if "\r" in str(command) or "\n" in str(command):
        raise ValueError(f"refusing to send {command!r}: more than one request in a line")
    text = str(command).replace(" ", "").upper()
    if text.startswith("AT"):
        return
    if len(text) < 2 or text[:2] not in READ_MODES or re.fullmatch(r"[0-9A-F]+", text) is None:
        raise ValueError(f"refusing to send {command!r}: only OBD modes 01, 03 and 07 are read only")


def parse_dtcs(lines, head):
    """Trouble codes ('P0301') out of the reply `lines` to a mode 03 or 07
    request, whose answer starts with `head` ('43' or '47'). Each engine
    computer answers with its own line; a long CAN answer comes in frames
    ('0: 43 ...', '1: ...') that are joined. Two bytes a code, 0000 is
    padding. A CAN answer has a count byte after the head: always when it
    comes in frames, else when it leaves an odd number of bytes. Junk and NO DATA give none."""
    messages = []           # [text, in frames: the count byte then holds]
    for line in lines:
        text = line.replace(" ", "").upper()
        frame = re.fullmatch(r"([0-9A-F]):([0-9A-F]*)", text)
        if frame:
            if frame.group(1) == "0":
                messages.append([frame.group(2), True])
            elif messages:
                messages[-1][0] += frame.group(2)
        elif text.startswith(head):
            messages.append([text, False])
    found = []
    for message, framed in messages:
        body = message[len(head):] if message.startswith(head) else None
        if body is None or len(body) % 2 or re.fullmatch(r"[0-9A-F]*", body) is None:
            continue
        data = bytes.fromhex(body)
        if framed and data:
            data = data[1:1 + data[0] * 2]     # a count byte, then that many codes, then padding
        elif len(data) % 2:
            data = data[1:]
        for i in range(0, len(data) - 1, 2):
            if data[i] or data[i + 1]:
                code = "PCBU"[data[i] >> 6] + str(data[i] >> 4 & 3) + f"{data[i] & 15:X}{data[i + 1]:02X}"
                if code not in found:
                    found.append(code)
    return found


def retry_wait(since, charging=False):
    """Seconds between tries to wake the car, `since` it went quiet.
    `charging`: the battery's last reading says the engine's running."""
    quiet = time.monotonic() - since
    if quiet < SLOW_AFTER_S:
        return RETRY_S
    return RETRY_SLOW_S if quiet < SLOWEST_AFTER_S or charging else RETRY_SLOWEST_S


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
        try:
            a = termios.tcgetattr(self.fd)
            a[0] = a[1] = a[3] = 0
            a[2] = termios.CS8 | termios.CREAD | termios.CLOCAL
            a[4] = a[5] = termios.B115200
            a[6][termios.VMIN] = a[6][termios.VTIME] = 0
            termios.tcsetattr(self.fd, termios.TCSANOW, a)
            termios.tcflush(self.fd, termios.TCIOFLUSH)
        except BaseException:             # don't leak the port when it won't set up
            os.close(self.fd)
            raise

    def close(self):
        try:
            os.close(self.fd)
        except OSError:
            pass

    def send(self, command, timeout=3.0):
        """The reply's text (without the prompt), or raises OSError.
        Raises ValueError, sending nothing, for a request that isn't read only."""
        refuse_writes(command)
        return " ".join(self._io(command, timeout))

    def lines(self, command, timeout=3.0):
        """Like `send`, but the reply's lines apart (multi-frame answers)."""
        refuse_writes(command)
        return self._io(command, timeout)

    def _io(self, command, timeout):
        """The serial I/O behind `send`: only it touches the port, and only
        after `refuse_writes` has passed the command."""
        # Drop what's left of an earlier reply that came after its timeout:
        # read as this one's, it would shift every answer after it.
        termios.tcflush(self.fd, termios.TCIFLUSH)
        os.write(self.fd, (command + "\r").encode())
        buf, end = b"", time.monotonic() + timeout
        while time.monotonic() < end:
            if select.select([self.fd], [], [], 0.05)[0]:
                chunk = os.read(self.fd, 4096)
                if not chunk:
                    # A hung-up tty (adapter unplugged) is always readable and
                    # reads empty: without this the loop spins until timeout.
                    raise OSError(errno.EIO, "OBD adapter hung up")
                buf += chunk
                if b">" in buf:
                    break
        text = buf.decode(errors="replace").replace(">", "")
        return [line.strip() for line in re.split(r"[\r\n]", text) if line.strip()]

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

    def mil(self):
        """(lamp on, number of stored codes) from mode 01 PID 01, or None.
        Every engine computer that answers counts: the lamp is on if any
        says so, the counts add up (a transmission computer says 0)."""
        found = None
        for line in self.lines("0101"):
            text = line.replace(" ", "").upper()
            i = text.find("4101")
            if i < 0 or re.fullmatch(r"[0-9A-F]{2}", text[i + 4:i + 6]) is None:
                continue
            a = int(text[i + 4:i + 6], 16)
            on, count = found or (False, 0)
            found = (on or bool(a & 0x80), count + (a & 0x7F))
        return found

    def dtcs(self, mode):
        """The trouble codes of mode "03" (stored) or "07" (pending), as
        'P0301'. Empty when there are none or the car doesn't say."""
        if mode not in ("03", "07"):
            raise ValueError(f"no trouble codes in mode {mode!r}")
        return parse_dtcs(self.lines(mode), "43" if mode == "03" else "47")


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
    pressure (kPa) to keep for the next start. `codes` carries the check-engine
    lamp and the trouble codes: {"mil", "count", "stored", "pending"}, when
    the count of stored codes changed (and on the first read of a session)."""
    reading = pyqtSignal(dict)
    lost = pyqtSignal()
    quiet = pyqtSignal()
    voltage = pyqtSignal(float)
    baro = pyqtSignal(float)
    codes = pyqtSignal(dict)

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
        self._held = threading.Event()        # set: send nothing new
        self._volts_last = None               # the battery's latest reading

    def hold(self):
        """Stop sending: the Pi is about to power off. Thread safe."""
        self._held.set()

    def release(self):
        """Carry on after a hold (the shutdown didn't happen). Thread safe."""
        self._held.clear()

    def start(self):
        threading.Thread(target=self._run, name="obd", daemon=True).start()

    def _retry(self):
        charging = self._volts_last is not None and self._volts_last > RUNNING_V
        return retry_wait(self._since, charging)

    def _run(self):
        self._since = time.monotonic()        # when the car last went quiet
        self._protocol = "0"                  # search, until the car has answered
        while True:
            if self._held.is_set():
                time.sleep(HOLD_NAP_S)
                continue
            path = find_port()
            if path:
                try:
                    self._session(path)
                except (OSError, termios.error):
                    pass                      # unplugged mid-read: look again
                except Exception as e:        # a bad reply must not end the thread
                    errorlog.log.report(type(e), e, e.__traceback__, label="OBD: reader error, retrying:")
                safe_emit(self, "lost")
            # Looking for an adapter (or a plugged-back one) is never slower than RETRY_SLOW_S.
            self._nap(min(self._retry(), RETRY_SLOW_S))

    def _nap(self, seconds):
        """Sleeps, in short slices so a hold or release is noticed soon."""
        end = time.monotonic() + seconds
        while (left := end - time.monotonic()) > 0 and not self._held.is_set():
            time.sleep(min(1.0, left))

    def _session(self, path):
        elm = Elm(path)
        try:
            elm.send("ATZ", 4)
            time.sleep(0.5)
            for c in ("ATE0", "ATL0", "ATS0", "ATH0", "ATAT2", "ATSP" + self._protocol):
                elm.send(c)
            while self._wait(elm, path):
                print("OBD: the car answered", flush=True)
                if self._protocol == "0" and not self._held.is_set():
                    # The protocol the search found ("A5" is ISO 14230-4,
                    # KWP fast init), so a reconnect doesn't search again.
                    found = elm.send("ATDPN").lstrip("A")
                    if len(found) == 1 and found in "123456789ABC":
                        self._protocol = found
                self._poll(elm)
                if not os.path.exists(path):
                    # The adapter went, not the car: only `lost`, never `quiet`.
                    raise OSError(errno.ENODEV, "OBD adapter gone")
                self._since = time.monotonic()
                print("OBD: the car stopped answering", flush=True)
                safe_emit(self, "quiet")
                safe_emit(self, "lost")
                # Ask it the same way until it answers again: no search.
                if not self._held.is_set():
                    elm.send("ATSP" + self._protocol)
        finally:
            elm.close()

    def _wait(self, elm, path):
        """Wakes the engine computer (with the key off it doesn't answer):
        True once it answers, False if the adapter goes away. Reads the
        battery meanwhile."""
        ask_at = volts_at = time.monotonic()
        while os.path.exists(path):
            if self._held.is_set():
                time.sleep(HOLD_NAP_S)
                continue
            now = time.monotonic()
            live = now - self._since < VOLTS_FOR_S      # battery each second for a while
            if (live and now >= volts_at) or now >= ask_at:
                self._volts(elm)
                volts_at = now + VOLTS_EVERY_S
            if now >= ask_at and not self._held.is_set():
                if elm.pid(0x00, WAKE_TIMEOUT_S):
                    return True
                ask_at = time.monotonic() + self._retry()
            now = time.monotonic()
            time.sleep(min(1.0, max(0.0, (volts_at if live else ask_at) - now)))
        return False

    def _volts(self, elm):
        volts = elm.volts()
        if volts is not None:
            self._volts_last = volts
            safe_emit(self, "voltage", volts)
        return volts

    def _start_baro(self, elm):
        """Before the first round, the outside air pressure from the car
        itself if it has it. If not, boost starts from the last one kept,
        which is right unless the truck has climbed or dropped since (a
        key-on corrects it)."""
        if self._baro_pid is None:
            self._baro_pid = self._ask_baro_pid(elm)
        if self._baro_pid and not self._held.is_set():
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

    def _note_baro(self, kpa, keep=True):
        """A measured outside air pressure: boost zeroes from it, and if
        `keep` it's kept for the next start when it changed (every keeping
        is a write to the SD card). False if it can't be air pressure."""
        if not plausible_baro(kpa):
            return False
        self._baro = float(kpa)
        if keep and self._baro != self._saved:
            self._saved = self._baro
            safe_emit(self, "baro", self._baro)
        return True

    def _read_codes(self, elm, state):
        """Once CODES_EVERY_S (and on the first round), whether the lamp is
        on and how many codes are stored; the codes themselves only when
        either changed. The last result is said again each time, so the
        dashboard doesn't forget it. `state` is [when asked last, (lamp,
        count) the codes were read for, last result]. It never counts as
        the car not answering: one that has no PID 01 is fine."""
        if state[0] is not None and time.monotonic() - state[0] < CODES_EVERY_S:
            return
        if self._held.is_set():
            return
        state[0] = time.monotonic()
        lamp = elm.mil()
        if lamp is not None and lamp != state[1] and not self._held.is_set():
            on, count = lamp
            stored = elm.dtcs("03") if count else []
            pending = elm.dtcs("07")
            state[2] = {"mil": on, "count": count, "stored": stored, "pending": pending}
            # Stored codes it didn't give are asked for again next time.
            state[1] = lamp if stored or not count else None
        if state[2] is not None:
            safe_emit(self, "codes", dict(state[2]))

    def _poll(self, elm):
        """Reads the car until it stops answering."""
        while self._held.is_set():
            time.sleep(HOLD_NAP_S)
        self._start_baro(elm)
        misses, turn, logged, last = 0, 0, 0.0, {}
        still, kept = [], False         # manifold readings in this stop; one kept yet?
        codes = [None, None, None]
        while misses < GIVE_UP_AFTER:
            if self._held.is_set():
                time.sleep(HOLD_NAP_S)
                continue
            started = time.monotonic()
            self._read_codes(elm, codes)
            values = {}
            for item in FAST + (SLOW[turn % len(SLOW)],):
                if self._held.is_set():
                    break
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
            if self._held.is_set():
                continue                # partial round: say nothing, wait for the release
            # With the engine stopped (key on), the manifold settles to the
            # outside air pressure: the zero for boost from here on. Only once
            # it has held still, not on its way back up after a stall, and
            # kept once a stop, so a reading that flickers by a kPa isn't a
            # write every round.
            rounds, kpa = BARO_STEADY
            if values.get("rpm") == 0 and "map" in values:
                still = (still + [values["map"]])[-rounds:]
                if len(still) == rounds and max(still) - min(still) <= kpa:
                    kept = self._note_baro(values["map"], keep=not kept) or kept
            else:
                still, kept = [], False
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
