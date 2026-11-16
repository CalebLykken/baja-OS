"""Screen brightness exposed to the UI.

The Waveshare panel takes brightness over DDC/CI: standard monitor commands
sent on the HDMI cable's I2C line (VCP feature 0x10). `Display` finds that
I2C bus, reads the current level once at startup (off the UI thread), and writes changes on a
background thread so dragging the slider never stalls the UI.

When there is no DDC/CI screen (a Mac, or a panel that ignores it),
`hardware` is False and the QML dims with a black overlay instead.

There are two saved levels, daylight and night, and with `autoNight` on
the screen switches between them by the sun's position where the truck is
(after sunset it uses the night level). The slider sets whichever level
is in use.

Screen off (Settings) draws a black layer and, on a DDC/CI panel, also writes
brightness 0 so the backlight stops glowing in a dark cab. The saved levels and
the slider are untouched; waking writes the current day or night level back. A
panel that ignores 0 is still covered by the black layer.
"""

import fcntl
import glob
import math
import os
import threading
import time

from PyQt6.QtCore import QObject, QTimer, pyqtProperty, pyqtSignal, pyqtSlot

from backend import FailureLog, safe_emit, sun
from backend.prefs import as_bool

I2C_SLAVE = 0x0703
DDC_ADDR = 0x37
VCP_BRIGHTNESS = 0x10
DDC_DELAY = 0.05  # DDC/CI wants ~50 ms between a command and the next one
DDC_TRIES = 3     # a write the panel NAKs is retried ...
DDC_RETRY_S = 0.15  # ... after this pause
# A panel still waking on car power can miss the first probe. When a bus was
# found but the probe failed, the writer thread tries again after each of
# these pauses (seconds), then stops: no polling for the rest of the drive.
PROBE_RETRY_S = (2, 5, 10, 30, 60)
SEATTLE = (47.6062, -122.3321)
DUSK = -2.0       # sun this far below the horizon counts as night (screen dimming)
MAP_DARK = -4.0   # the map goes dark a little later (between sunset and civil dusk) ...
MAP_LIGHT = -3.0  # ... and light again a little earlier, so it never flickers
RAMP_STEPS = 12   # the day/night flip fades the brightness in about this many steps ...
RAMP_MS = 500     # ... over about this long, so sunset is not a visible flash


def find_ddc_bus():
    """Return the /dev/i2c-N path wired to a connected HDMI output, if any."""
    for connector in sorted(glob.glob("/sys/class/drm/card*-HDMI-A-*")):
        try:
            with open(os.path.join(connector, "status")) as f:
                if f.read().strip() != "connected":
                    continue
            bus = os.path.basename(os.path.realpath(os.path.join(connector, "ddc")))
        except OSError:
            continue
        path = os.path.join("/dev", bus)
        if os.path.exists(path):
            return path
    return None


class DdcBrightness:
    """Minimal DDC/CI client for VCP 0x10 on one I2C bus."""

    def __init__(self, path):
        self._fd = os.open(path, os.O_RDWR)
        try:
            fcntl.ioctl(self._fd, I2C_SLAVE, DDC_ADDR)
        except BaseException:
            os.close(self._fd)
            raise

    def close(self):
        try:
            os.close(self._fd)
        except OSError:
            pass

    def _send(self, payload):
        msg = bytes([0x51, 0x80 | len(payload)]) + bytes(payload)
        checksum = 0x6E
        for b in msg:
            checksum ^= b
        os.write(self._fd, msg + bytes([checksum]))
        time.sleep(DDC_DELAY)

    def get(self):
        """Return (current, maximum)."""
        self._send([0x01, VCP_BRIGHTNESS])
        r = os.read(self._fd, 12)
        # r: source, length, 0x02 reply, result, vcp, type, max hi/lo, cur hi/lo
        if len(r) < 10 or r[2] != 0x02 or r[3] != 0x00 or r[4] != VCP_BRIGHTNESS:
            raise OSError("unexpected DDC/CI reply: " + r.hex())
        return (r[8] << 8) | r[9], (r[6] << 8) | r[7]

    def set(self, value):
        self._send([0x03, VCP_BRIGHTNESS, value >> 8, value & 0xFF])


class Display(QObject):
    brightnessChanged = pyqtSignal()
    nightChanged = pyqtSignal()
    screenOffChanged = pyqtSignal()
    hardwareChanged = pyqtSignal()
    _probe_done = pyqtSignal(bool, int, int)

    def __init__(self, settings=None, location=None, parent=None):
        super().__init__(parent)
        self._settings = settings
        self._location = location or (lambda: SEATTLE)
        self._night = False
        self._screen_off = False  # never saved: the screen is on after a restart
        self._sun_down = False
        self._auto = settings is None or as_bool(settings.get("autoNight"), True)
        self._sun_check = QTimer(self, interval=60000, timeout=self._check_sun)
        self._ramp = QTimer(self, singleShot=True, interval=RAMP_MS // RAMP_STEPS,
                            timeout=self._ramp_step)  # runs only during a fade
        self._ramp_to = 100
        self._brightness = 100  # software dimming starts undimmed (overlay clear)
        self._ddc = None
        self._max = 100
        self._pending = None
        self._written = None      # the level the panel last accepted (None: unknown)
        # A panel that stops answering logs once, not on every retry or every
        # sun check (each minute) that resends the level.
        self._write_logged = FailureLog("Brightness: DDC/CI writes failing",
                                        "Brightness: DDC/CI writes working again")
        self._wake = threading.Condition()

        self._hw = False          # True once the probe found a DDC/CI panel
        self._probing = False     # start() began the probe and it hasn't settled
        self._day_default = True  # the day level follows the panel until one is saved/set
        self._levels = {
            False: self._saved("brightnessDay", 100),
            True: self._saved("brightnessNight", 40),
        }
        if self._settings is not None and self._settings.get("brightnessDay") is not None:
            self._day_default = False
        self._probe_done.connect(self._probed)

    def _saved(self, key, default):
        if self._settings is None:
            return default
        try:
            return max(5, min(100, int(self._settings.get(key, default))))
        except (TypeError, ValueError):
            return default

    def start(self):
        # The DDC probe blocks on the panel's I2C bus, so it runs on the writer
        # thread. Until it settles the brightness stays at 100 (the software
        # overlay fully transparent) and level changes wait in _levels.
        self._probing = True
        threading.Thread(target=self._writer, daemon=True).start()
        self._check_sun(force=True)
        self._sun_check.start()

    def _check_sun(self, force=False):
        lat, lon = self._location()
        alt = sun.altitude(lat, lon)
        sun_down = alt < (MAP_LIGHT if self._sun_down else MAP_DARK)
        if sun_down != self._sun_down:
            self._sun_down = sun_down
            self.nightChanged.emit()
        night = self._auto and alt < DUSK
        if night != self._night or force:
            self._night = night
            self._stop_ramp()
            if force or self._probing or self._screen_off:
                self._apply(self._levels[night])
            else:
                self._start_ramp(self._levels[night])
            self.nightChanged.emit()
        elif not self._ramp.isActive():
            self._apply(self._levels[night])  # resend a level the panel never took

    def _start_ramp(self, target):
        """Fade from the current brightness to `target` in small steps."""
        self._ramp_to = target
        self._ramp_step()

    def _ramp_step(self):
        self._ramp.stop()
        gap = self._ramp_to - self._brightness
        if gap == 0:
            self._apply(self._ramp_to)  # also resends a level the panel never took
            return
        # Steps of at most ceil(gap / RAMP_STEPS); the last one lands exactly.
        step = max(1, math.ceil(abs(gap) / RAMP_STEPS))
        if abs(gap) <= step:
            self._apply(self._ramp_to)
        else:
            self._apply(self._brightness + (step if gap > 0 else -step))
        if self._brightness != self._ramp_to:
            self._ramp.start()

    def _stop_ramp(self):
        self._ramp.stop()

    def _probe(self, first=True, attempt=0):
        """Find the panel and read its brightness. Runs off the UI thread.
        Returns True when it is worth trying again: a bus was found but
        opening it or reading it failed. _probe_done goes out for a success
        and for the first failure only, so the QML sees no repeats."""
        current = 0
        retry = False
        try:
            path = find_ddc_bus()
            if path:
                try:
                    self._ddc = DdcBrightness(path)
                    current, self._max = self._ddc.get()
                    if self._max <= 0:
                        # A zeroed reply would scale every write to 0: a black screen.
                        raise OSError(f"panel reports a maximum of {self._max}")
                    current = max(0, min(self._max, current))
                    if attempt:
                        print(f"Brightness: DDC/CI found on retry {attempt}")
                except OSError as e:
                    if first:
                        print(f"Brightness: no DDC/CI on {path} ({e}); dimming in software")
                    self._give_up()
                    retry = True
        except Exception as e:
            if first:
                print(f"Brightness: DDC probe failed ({e}); dimming in software")
            self._give_up()
            retry = True
        finally:
            ok = self._ddc is not None
            if ok or first:
                safe_emit(self, "_probe_done", ok, current if ok else 0,
                          self._max if ok else 100)
        return retry

    def _give_up(self):
        """Drop a device the probe opened but can't use."""
        if self._ddc is not None:
            self._ddc.close()
        self._ddc = None
        self._max = 100

    def _probed(self, ok, current, maximum):
        self._probing = False
        if ok:
            self._hw = True
            self._brightness = round(current * 100 / maximum) if maximum else 100
            self._written = self._brightness
            # A panel left at 0 (a restart while the screen was off) must not
            # become the day level: keep 100, and _apply below sends the level.
            if self._day_default and self._brightness >= 5:
                self._levels[False] = min(100, self._brightness)
            self.hardwareChanged.emit()
            self.brightnessChanged.emit()
        self._apply(self._levels[self._night])
        if ok and self._screen_off:
            self._drive_panel(True)  # the screen went off before the probe settled

    def _writer(self):
        retry = self._probe()
        for n, delay in enumerate(PROBE_RETRY_S, 1):
            if not retry:
                break
            time.sleep(delay)
            retry = self._probe(first=False, attempt=n)
        if self._ddc is None:
            return
        # Only the newest value matters, so a burst of slider moves collapses
        # into one write per DDC round trip.
        while True:
            with self._wake:
                while self._pending is None:
                    self._wake.wait()
                value, self._pending = self._pending, None
            self._write(value)

    def _write(self, value):
        """Send a level to the panel, retrying a NAK. If it never goes through
        _written keeps the old level, so the next _apply sends it again."""
        error = None
        for attempt in range(DDC_TRIES):
            try:
                self._ddc.set(round(value * self._max / 100))
            except Exception as e:
                error = e
                if attempt + 1 < DDC_TRIES:
                    time.sleep(DDC_RETRY_S)
                continue
            self._written = value
            self._write_logged()  # clears a logged failure once writes work again
            return
        self._write_logged(error)  # every try failed: one line, not one per try

    @pyqtProperty(bool, notify=hardwareChanged)
    def hardware(self):
        """True when brightness drives the panel backlight, not an overlay.
        False until the startup probe finds the panel (the overlay is clear
        then, brightness reads 100)."""
        return self._hw

    @pyqtProperty(int, notify=brightnessChanged)
    def brightness(self):
        return self._brightness

    @pyqtSlot(int)
    def setBrightness(self, value):
        value = max(5, min(100, int(value)))
        self._levels[self._night] = value
        if not self._night:
            self._day_default = False
        if self._settings is not None:
            self._settings.set("brightnessNight" if self._night else "brightnessDay", value)
        self._stop_ramp()
        self._apply(value)

    def _apply(self, value):
        if self._probing:
            return  # _probed applies the level once the panel is known
        if value != self._brightness:
            self._brightness = value
            self.brightnessChanged.emit()
        elif not self._hw or value == self._written:
            return
        if self._hw and not self._screen_off:  # off: the panel stays at 0
            with self._wake:
                self._pending = value
                self._wake.notify()

    # ---- screen off -------------------------------------------------------------
    @pyqtProperty(bool, notify=screenOffChanged)
    def screenOff(self):
        """True while the screen is blacked out (the QML shows a black layer)."""
        return self._screen_off

    @pyqtSlot(bool)
    def setScreenOff(self, off):
        off = bool(off)
        if off == self._screen_off:
            return
        self._screen_off = off
        if self._ramp.isActive():
            self._stop_ramp()
            self._apply(self._ramp_to)  # settle on the target: nothing is written while off
        self.screenOffChanged.emit()
        try:
            self._drive_panel(off)
        except Exception as e:  # the screen state must never depend on hardware
            print(f"Display: panel backlight control failed ({e})")

    @pyqtSlot()
    def wake(self):
        self.setScreenOff(False)

    def _drive_panel(self, off):
        """Turn the panel's backlight down over DDC/CI, or back up on wake.

        Off writes brightness 0 through the writer thread, bypassing the 5%
        floor of setBrightness and leaving _brightness alone so the slider does
        not move. On wake the current day or night level is sent again. With no
        DDC/CI panel (software dim) nothing is written: the QML black layer
        alone covers the screen.
        """
        if not self._hw:
            return
        if off:
            with self._wake:
                self._pending = 0
                self._wake.notify()
        else:
            self._written = 0  # the panel is at 0, so the level really is sent
            self._apply(self._levels[self._night])

    # ---- day and night ----------------------------------------------------------
    @pyqtProperty(bool, notify=nightChanged)
    def night(self):
        """True while the night level is in use."""
        return self._night

    @pyqtProperty(bool, notify=nightChanged)
    def sunDown(self):
        """True from just after sunset to just before sunrise (the dark map)."""
        return self._sun_down

    @pyqtProperty(bool, notify=nightChanged)
    def autoNight(self):
        return self._auto

    @pyqtSlot(bool)
    def setAutoNight(self, on):
        if on != self._auto:
            self._auto = on
            if self._settings is not None:
                self._settings.set("autoNight", "true" if on else "false")
            self._check_sun(force=True)

    @pyqtProperty(float, notify=nightChanged)
    def sunrise(self):
        """Today's sunrise where the truck is, in ms since 1970 (0 if none)."""
        rise, _ = sun.rise_set(*self._location())
        return rise.timestamp() * 1000 if rise else 0.0

    @pyqtProperty(float, notify=nightChanged)
    def sunset(self):
        _, sset = sun.rise_set(*self._location())
        return sset.timestamp() * 1000 if sset else 0.0
