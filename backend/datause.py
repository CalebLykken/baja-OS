"""Data use this month on Wi-Fi and the Bluetooth tether.

Adds up the bytes sent and received on wlan0 and the bnep* (Bluetooth
tether) interfaces, read from /sys/class/net, and keeps a total per calendar
month. The kernel's counters start over at every boot, so each sample adds
the change since the last one (or the whole reading, if it went down). The
last readings are saved too, so a restart doesn't lose or double count.

When a month ends, its total is kept and shown as a small fact next to the
new month's ("120 MB (2.1 GB last month)"), but only while it is the month just
before the current one.

It doesn't tell the phone's hotspot from home Wi-Fi, so it counts all Wi-Fi
use and says so. Without those interfaces (a Mac) nothing is shown.
"""

import json
import os
import time

from PyQt6.QtCore import QObject, QTimer, pyqtProperty, pyqtSignal, pyqtSlot

SAMPLE_EVERY_MS = 60000
FIRST_SAMPLE_MS = 5000     # keeps the settings write off the startup path; well under SAMPLE_EVERY_MS
SYS_NET = "/sys/class/net"
SETTING = "dataUse"
LIMIT_SETTING = "dataLimitGb"  # 0 = no warning
MAX_LIMIT_GB = 500
MAX_PREV_BYTES = 10 ** 15     # anything bigger in the saved setting is garbage


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


def read_limit(value):
    """The saved warning limit in GB, 0 (off) for anything that isn't a whole number, clamped to 0-500."""
    try:
        gb = int(str(value).strip())
    except (ValueError, TypeError):
        return 0
    return max(0, min(MAX_LIMIT_GB, gb))


def format_bytes(n):
    if n < 1_000_000:
        return f"{n / 1000:.0f} KB"
    if n < 1_000_000_000:
        return f"{n / 1_000_000:.0f} MB"
    return f"{n / 1_000_000_000:.1f} GB"


def month_before(month):
    """The 'YYYY-MM' before this one (January goes back to the last year's December), or '' if it isn't one."""
    try:
        y, m = int(month[:4]), int(month[5:7])
    except (ValueError, TypeError):
        return ""
    if len(month) != 7 or month[4] != "-" or not 1 <= m <= 12:
        return ""
    return f"{y - 1:04d}-12" if m == 1 else f"{y:04d}-{m - 1:02d}"


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
        self._prev_month, self._prev_bytes = "", 0
        try:
            prev = json.loads(str(settings.get(SETTING, "{}")))["prev"]
            month, nbytes = str(prev["month"]), prev["bytes"]
            if isinstance(nbytes, int) and not isinstance(nbytes, bool) and 0 < nbytes < MAX_PREV_BYTES and month_before(month):
                self._prev_month, self._prev_bytes = month, nbytes
        except (ValueError, KeyError, TypeError, AttributeError, OverflowError):
            self._prev_month, self._prev_bytes = "", 0
        self._limit = read_limit(settings.get(LIMIT_SETTING, 0))
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
            if self._month and month_before(month) == self._month and self._bytes > 0:
                self._prev_month, self._prev_bytes = self._month, self._bytes
            else:
                self._prev_month, self._prev_bytes = "", 0
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
            saved = {"month": self._month, "bytes": self._bytes, "last": self._last}
            if self._prev_month:
                saved["prev"] = {"month": self._prev_month, "bytes": self._prev_bytes}
            self._settings.set(SETTING, json.dumps(saved))
        self.changed.emit()

    @pyqtProperty(bool, notify=changed)
    def available(self):
        return self._present

    @pyqtProperty('qlonglong', notify=changed)
    def bytesThisMonth(self):
        return self._bytes

    def _last_month(self):
        """The finished month's bytes, only while it is the month just before this one."""
        return self._prev_bytes if self._prev_month and self._prev_month == month_before(self._month) else 0

    @pyqtProperty('qlonglong', notify=changed)
    def lastMonthBytes(self):
        return self._last_month()

    @pyqtProperty(str, notify=changed)
    def text(self):
        # The limit sits right after this month's figure, so it can't be read
        # as applying to last month's.
        now = format_bytes(self._bytes)
        if self._limit:
            now += f" of {self._limit} GB"
        prev = self._last_month()
        if not prev:
            return now
        return f"{now} ({format_bytes(prev)} last month)"

    @pyqtProperty(int, notify=changed)
    def limitGb(self):
        return self._limit

    @pyqtProperty(bool, notify=changed)
    def overLimit(self):
        """True once this month's use reaches the limit. Only a warning; nothing is switched off."""
        return self._limit > 0 and self._bytes >= self._limit * 1_000_000_000

    @pyqtSlot(int)
    def setLimit(self, gb):
        gb = read_limit(gb)
        if gb == self._limit:
            return
        self._limit = gb
        self._settings.set(LIMIT_SETTING, gb)
        self.changed.emit()
