"""The Pi's own health for Settings > System: temperature, fan, power
warnings, memory, storage, uptime and the installed version, plus
restart, reboot and shut down.

Readings refresh every few seconds on a background thread. On a Mac most
of them are simply blank.
"""

import os
import shutil
import subprocess
import threading
from glob import glob
from pathlib import Path

from PyQt6.QtCore import QCoreApplication, QObject, QTimer, pyqtProperty, pyqtSignal, pyqtSlot

ROOT = Path(__file__).resolve().parent.parent
CHECK_EVERY_MS = 5000


def _read(path):
    try:
        return Path(path).read_text().strip()
    except OSError:
        return ""


def cpu_temp():
    t = _read("/sys/class/thermal/thermal_zone0/temp")
    return int(t) / 1000 if t.isdigit() else None


def fan_rpm():
    for f in glob("/sys/devices/platform/cooling_fan/hwmon/*/fan1_input"):
        v = _read(f)
        if v.isdigit():
            return int(v)
    return None


def power_state():
    """'' when fine, else what the firmware has noticed (under-voltage etc.)."""
    if not shutil.which("vcgencmd"):
        return ""
    try:
        out = subprocess.run(["vcgencmd", "get_throttled"], capture_output=True,
                             text=True, timeout=2).stdout
        bits = int(out.strip().split("=")[1], 16)
    except (OSError, subprocess.SubprocessError, IndexError, ValueError):
        return ""
    if bits & 0x1:
        return "Low power supply voltage right now"
    if bits & 0x4 or bits & 0x8:
        return "Slowed down to stay cool"
    if bits & 0x10000:
        return "Power supply dipped since starting"
    if bits & 0x40000 or bits & 0x80000:
        return "Got hot and slowed down since starting"
    return ""


def memory_mb():
    info = {}
    for line in _read("/proc/meminfo").splitlines():
        k, _, v = line.partition(":")
        info[k] = int(v.split()[0]) // 1024 if v.split() else 0
    total = info.get("MemTotal", 0)
    return total - info.get("MemAvailable", 0), total


def uptime_text():
    up = _read("/proc/uptime")
    if not up:
        return ""
    s = int(float(up.split()[0]))
    d, h, m = s // 86400, s % 86400 // 3600, s % 3600 // 60
    return f"{d} d {h} h" if d else (f"{h} h {m} min" if h else f"{m} min")


def version_text():
    """'abc1234, 14 Oct 2026' from the file deploy/push.sh writes, else git."""
    v = _read(ROOT / ".version")
    if v:
        return v
    try:
        return subprocess.run(["git", "-C", str(ROOT), "log", "-1", "--format=%h, %cd",
                               "--date=format:%-d %b %Y"],
                              capture_output=True, text=True, timeout=2).stdout.strip()
    except (OSError, subprocess.SubprocessError):
        return ""


def can_power():
    try:
        out = subprocess.run(["busctl", "--system", "call", "org.freedesktop.login1",
                              "/org/freedesktop/login1", "org.freedesktop.login1.Manager",
                              "CanReboot"], capture_output=True, text=True, timeout=2).stdout
    except (OSError, subprocess.SubprocessError):
        return False
    return '"yes"' in out


class SystemInfo(QObject):
    changed = pyqtSignal()
    _read_done = pyqtSignal(dict)

    def __init__(self, parent=None):
        super().__init__(parent)
        self._v = {"temp": None, "fan": None, "power": "", "memUsed": 0, "memTotal": 0,
                   "diskFree": 0.0, "diskTotal": 0.0, "uptime": "", "canPower": False}
        self._version = version_text()
        self._busy = False
        self._read_done.connect(self._apply)
        self._timer = QTimer(self, interval=CHECK_EVERY_MS, timeout=self._check)

    def start(self):
        self._check()
        self._timer.start()

    def _check(self):
        if self._busy:
            return
        self._busy = True

        def work():
            used, total = memory_mb()
            disk = shutil.disk_usage("/")
            self._read_done.emit({
                "temp": cpu_temp(), "fan": fan_rpm(), "power": power_state(),
                "memUsed": used, "memTotal": total,
                "diskFree": disk.free / 1e9, "diskTotal": disk.total / 1e9,
                "uptime": uptime_text(), "canPower": can_power(),
            })
        threading.Thread(target=work, daemon=True).start()

    def _apply(self, v):
        self._busy = False
        if v != self._v:
            self._v = v
            self.changed.emit()

    @pyqtProperty(float, notify=changed)
    def temp(self):
        """CPU temperature in °C, or -1 if unknown."""
        return -1.0 if self._v["temp"] is None else self._v["temp"]

    @pyqtProperty(int, notify=changed)
    def fan(self):
        """Fan speed in rpm, or -1 without a fan."""
        return -1 if self._v["fan"] is None else self._v["fan"]

    @pyqtProperty(str, notify=changed)
    def power(self):
        return self._v["power"]

    @pyqtProperty(int, notify=changed)
    def memUsed(self):
        return self._v["memUsed"]

    @pyqtProperty(int, notify=changed)
    def memTotal(self):
        return self._v["memTotal"]

    @pyqtProperty(float, notify=changed)
    def diskFree(self):
        return self._v["diskFree"]

    @pyqtProperty(float, notify=changed)
    def diskTotal(self):
        return self._v["diskTotal"]

    @pyqtProperty(str, notify=changed)
    def uptime(self):
        return self._v["uptime"]

    @pyqtProperty(str, constant=True)
    def version(self):
        return self._version

    @pyqtProperty(bool, notify=changed)
    def canPower(self):
        """True once setup-pi.sh's polkit rule allows reboot and shut down."""
        return self._v["canPower"]

    @pyqtSlot()
    def restartDashboard(self):
        # The service restarts the app whenever it exits.
        QCoreApplication.exit(0)

    @pyqtSlot()
    def reboot(self):
        subprocess.Popen(["systemctl", "reboot"])

    @pyqtSlot()
    def powerOff(self):
        subprocess.Popen(["systemctl", "poweroff"])
