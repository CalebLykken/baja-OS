"""Screen brightness exposed to the UI.

The Waveshare panel takes brightness over DDC/CI: standard monitor commands
sent on the HDMI cable's I2C line (VCP feature 0x10). `Display` finds that
I2C bus, reads the current level at startup, and writes changes on a
background thread so dragging the slider never stalls the UI.

When there is no DDC/CI screen (a Mac, or a panel that ignores it),
`hardware` is False and the QML dims with a black overlay instead.

There are two saved levels, daylight and night, and with `autoNight` on
the screen switches between them by the sun's position where the truck is
(after sunset it uses the night level). The slider sets whichever level
is in use.
"""

import fcntl
import glob
import os
import threading
import time

from PyQt6.QtCore import QObject, QTimer, pyqtProperty, pyqtSignal, pyqtSlot

from backend import sun

I2C_SLAVE = 0x0703
DDC_ADDR = 0x37
VCP_BRIGHTNESS = 0x10
DDC_DELAY = 0.05  # DDC/CI wants ~50 ms between a command and the next one
SEATTLE = (47.6062, -122.3321)
DUSK = -2.0       # sun this far below the horizon counts as night (screen dimming)
MAP_DARK = -4.0   # the map goes dark a little later (between sunset and civil dusk) ...
MAP_LIGHT = -3.0  # ... and light again a little earlier, so it never flickers


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
        fcntl.ioctl(self._fd, I2C_SLAVE, DDC_ADDR)

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

    def __init__(self, settings=None, location=None, parent=None):
        super().__init__(parent)
        self._settings = settings
        self._location = location or (lambda: SEATTLE)
        self._night = False
        self._screen_off = False  # never saved: the screen is on after a restart
        self._sun_down = False
        self._auto = settings is None or str(settings.get("autoNight", "true")) == "true"
        self._sun_check = QTimer(self, interval=60000, timeout=self._check_sun)
        self._brightness = 80
        self._ddc = None
        self._max = 100
        self._pending = None
        self._wake = threading.Condition()

        path = find_ddc_bus()
        if path:
            try:
                self._ddc = DdcBrightness(path)
                current, self._max = self._ddc.get()
                self._brightness = round(current * 100 / self._max)
            except OSError as e:
                print(f"Brightness: no DDC/CI on {path} ({e}); dimming in software")
                self._ddc = None

        if self._ddc:
            threading.Thread(target=self._writer, daemon=True).start()
        else:
            self._brightness = 100  # software dimming starts undimmed
        self._levels = {
            False: self._saved("brightnessDay", self._brightness),
            True: self._saved("brightnessNight", 40),
        }

    def _saved(self, key, default):
        if self._settings is None:
            return default
        try:
            return max(5, min(100, int(self._settings.get(key, default))))
        except (TypeError, ValueError):
            return default

    def start(self):
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
            self._apply(self._levels[night])
            self.nightChanged.emit()

    def _writer(self):
        # Only the newest value matters, so a burst of slider moves collapses
        # into one write per DDC round trip.
        while True:
            with self._wake:
                while self._pending is None:
                    self._wake.wait()
                value, self._pending = self._pending, None
            try:
                self._ddc.set(round(value * self._max / 100))
            except OSError as e:
                print(f"Brightness: DDC/CI write failed ({e})")

    @pyqtProperty(bool, constant=True)
    def hardware(self):
        """True when brightness drives the panel backlight, not an overlay."""
        return self._ddc is not None

    @pyqtProperty(int, notify=brightnessChanged)
    def brightness(self):
        return self._brightness

    @pyqtSlot(int)
    def setBrightness(self, value):
        value = max(5, min(100, int(value)))
        self._levels[self._night] = value
        if self._settings is not None:
            self._settings.set("brightnessNight" if self._night else "brightnessDay", value)
        self._apply(value)

    def _apply(self, value):
        if value == self._brightness:
            return
        self._brightness = value
        self.brightnessChanged.emit()
        if self._ddc:
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
        self.screenOffChanged.emit()
        try:
            self._drive_panel(off)
        except Exception as e:  # the screen state must never depend on hardware
            print(f"Display: panel backlight control failed ({e})")

    @pyqtSlot()
    def wake(self):
        self.setScreenOff(False)

    def _drive_panel(self, off):
        """Turn the panel's real backlight off or on. Does nothing yet.

        How to do that on the Waveshare panel is not known: the candidates are
        DDC/CI (after loading i2c-dev), the panel's USB HID interface, or
        DPMS/KMS. It has to be tried on the Pi. Until then the QML only draws
        a black layer and the backlight stays lit.
        """

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
