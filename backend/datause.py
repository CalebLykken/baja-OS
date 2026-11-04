"""Data use this month on Wi-Fi and the Bluetooth tether.

Adds up the bytes sent and received on wlan0 and the bnep* (Bluetooth
tether) interfaces, read from /sys/class/net, and keeps a total per calendar
month. The kernel's counters start over at every boot, so each sample adds
the change since the last one (or the whole reading, if it went down). The
last readings are saved too, so a restart doesn't lose or double count.

It doesn't tell the phone's hotspot from home Wi-Fi, so it counts all Wi-Fi
use and says so. Without those interfaces (a Mac) nothing is shown.
"""

import json
import os
import time

from PyQt6.QtCore import QObject, QTimer, pyqtProperty, pyqtSignal

SAMPLE_EVERY_MS = 60000
FIRST_SAMPLE_MS = 5000     # keeps the settings write off the startup path; well under SAMPLE_EVERY_MS
SYS_NET = "/sys/class/net"
SETTING = "dataUse"


def counted(name):
    return name == "wlan0" or name.startswith("bnep")


def read_total(root, name):
    """Bytes sent plus received on one interface, or None if unreadable."""
    try:
        total = 0
        for f in ("rx_bytes", "tx_bytes"):
            with open(os.path.join(root, name, "statistics", f)) as fh:
                total += int(fh.read().strip())
        return total
    except (OSError, ValueError):
        return None


def format_bytes(n):
    if n < 1_000_000:
        return f"{n / 1000:.0f} KB"
    if n < 1_000_000_000:
        return f"{n / 1_000_000:.0f} MB"
    return f"{n / 1_000_000_000:.1f} GB"


class DataUse(QObject):
    changed = pyqtSignal()

    def __init__(self, settings, root=SYS_NET, clock=time.time, parent=None):
        super().__init__(parent)
        self._settings = settings
        self._root = root
        self._clock = clock
        self._month, self._bytes, self._last = "", 0, {}
        try:
            saved = json.loads(str(settings.get(SETTING, "{}")))
            self._month = str(saved["month"])
            self._bytes = int(saved["bytes"])
            self._last = {str(k): int(v) for k, v in saved["last"].items()}
        except (ValueError, KeyError, TypeError, AttributeError, OverflowError):
            self._month, self._bytes, self._last = "", 0, {}
        self._present = False
        self._first = QTimer(self, singleShot=True, interval=FIRST_SAMPLE_MS, timeout=self.sample)
        self._timer = QTimer(self, interval=SAMPLE_EVERY_MS, timeout=self.sample)

    def start(self):
        # Not sampled here: start() runs before the event loop, and the first
        # sample writes the settings file. A few seconds later it's off the startup path.
        self._first.start()
        self._timer.start()

    def sample(self):
        try:
            names = [n for n in os.listdir(self._root) if counted(n)]
        except OSError:
            names = None
        month = time.strftime("%Y-%m", time.localtime(self._clock()))
        if month > self._month:     # an earlier month is a clock not yet set: keep counting
            self._month, self._bytes = month, 0
        readings = {n: t for n in names or [] if (t := read_total(self._root, n)) is not None}
        for n, t in readings.items():
            last = self._last.get(n)
            # No earlier reading: it's all new since boot. A lower one: the counter restarted.
            self._bytes += t if last is None or t < last else t - last
        self._last.update(readings)
        # An interface that's gone comes back a new one, its counter from zero.
        # (Unreadable for a moment is different: it keeps its place.)
        gone = [] if names is None else [n for n in self._last if n not in names]
        for n in gone:
            del self._last[n]
        self._present = bool(readings)
        if self._present or gone:        # nothing to save on a Mac
            self._settings.set(SETTING, json.dumps({"month": self._month, "bytes": self._bytes, "last": self._last}))
        self.changed.emit()

    @pyqtProperty(bool, notify=changed)
    def available(self):
        return self._present

    @pyqtProperty('qlonglong', notify=changed)
    def bytesThisMonth(self):
        return self._bytes

    @pyqtProperty(str, notify=changed)
    def text(self):
        return format_bytes(self._bytes)
