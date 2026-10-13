"""Screen brightness exposed to the UI.

The Waveshare panel takes brightness over DDC/CI: standard monitor commands
sent on the HDMI cable's I2C line (VCP feature 0x10). `Display` finds that
I2C bus, reads the current level at startup, and writes changes on a
background thread so dragging the slider never stalls the UI.

When there is no DDC/CI screen (a Mac, or a panel that ignores it),
`hardware` is False and the QML dims with a black overlay instead.
"""

import fcntl
import glob
import os
import threading
import time

from PyQt6.QtCore import QObject, pyqtProperty, pyqtSignal, pyqtSlot

I2C_SLAVE = 0x0703
DDC_ADDR = 0x37
VCP_BRIGHTNESS = 0x10
DDC_DELAY = 0.05  # DDC/CI wants ~50 ms between a command and the next one


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

    def __init__(self, parent=None):
        super().__init__(parent)
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
        if value == self._brightness:
            return
        self._brightness = value
        self.brightnessChanged.emit()
        if self._ddc:
            with self._wake:
                self._pending = value
                self._wake.notify()
