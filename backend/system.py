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
import time
import traceback
from glob import glob
from pathlib import Path

from PyQt6.QtCore import QCoreApplication, QObject, QTimer, pyqtProperty, pyqtSignal, pyqtSlot

from backend import errorlog, safe_emit

ROOT = Path(__file__).resolve().parent.parent
CHECK_EVERY_MS = 5000
POWER_TIMEOUT_S = 10    # systemctl answers at once, either way
POWER_HOLD_S = 30       # an update's merge is seconds; the key-off relay holds for minutes


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
    """'abc1234, 14 Oct 2026' from git when this is a checkout (an in-app update
    or fall-back moves it, and a .version left by push.sh would go stale), else
    the file deploy/push.sh writes into copies that have no .git."""
    if (ROOT / ".git").exists():
        try:
            v = subprocess.run(["git", "-C", str(ROOT), "log", "-1", "--format=%h, %cd",
                                "--date=format:%-d %b %Y"],
                               capture_output=True, text=True, timeout=2).stdout.strip()
        except (OSError, subprocess.SubprocessError):
            v = ""
        if v:
            return v
    return _read(ROOT / ".version")


def power(action):
    """Ask systemd to 'reboot' or 'poweroff': '' once it has said yes, else
    why not (no polkit rule from setup-pi.sh, logind said no, not a Pi)."""
    try:
        r = subprocess.run(["systemctl", "--no-ask-password", action], capture_output=True,
                           text=True, timeout=POWER_TIMEOUT_S)
    except FileNotFoundError:
        return "systemctl isn't installed here"
    except subprocess.TimeoutExpired:
        return f"systemctl {action} didn't answer in {POWER_TIMEOUT_S} s"
    except (OSError, subprocess.SubprocessError) as e:
        return str(e)
    if r.returncode != 0:
        return (r.stderr or r.stdout).strip() or f"systemctl {action} failed ({r.returncode})"
    return ""


def can_power():
    """Whether logind will reboot for us, or None if it didn't answer."""
    try:
        out = subprocess.run(["busctl", "--system", "call", "org.freedesktop.login1",
                              "/org/freedesktop/login1", "org.freedesktop.login1.Manager",
                              "CanReboot"], capture_output=True, text=True, timeout=2).stdout
    except (OSError, subprocess.SubprocessError):
        return None
    return '"yes"' in out if out else None


class SystemInfo(QObject):
    changed = pyqtSignal()
    powerFailed = pyqtSignal(str)       # a reboot or shut down didn't happen, and why
    _read_done = pyqtSignal(dict)
    _power_done = pyqtSignal(str)
    _version_done = pyqtSignal(str)

    def __init__(self, parent=None):
        super().__init__(parent)
        self._v = {"temp": None, "fan": None, "power": "", "memUsed": 0, "memTotal": 0,
                   "diskFree": 0.0, "diskTotal": 0.0, "uptime": "", "canPower": False,
                   "errors": 0}
        self._version = ""         # read in the first check: it can run git
        self._version_read = False
        self._busy = False
        self._can_power = None     # asked once: it only changes with setup-pi.sh's polkit rule
        self._read_error = ""      # the error the last reading died of, while it keeps happening
        self._power_error = ""
        self._hold = lambda: False  # True while reboot and shut down should wait
        self._held = None           # (action, give up then) while one's waiting
        self._hold_timer = QTimer(self, interval=500, timeout=self._held_tick)
        self._read_done.connect(self._apply)
        self._power_done.connect(self._powered)
        self._version_done.connect(self._got_version)
        self._timer = QTimer(self, interval=CHECK_EVERY_MS, timeout=self._check)

    def start(self):
        self._check()
        self._timer.start()

    def _check(self):
        if self._busy:
            return
        self._busy = True

        def work():
            if not self._version_read:
                self._version_read = True
                try:
                    version = version_text()
                except Exception:
                    version = ""
                safe_emit(self, "_version_done", version)
            v = {}       # stays empty if a reading crashes, and _apply keeps the old values
            try:
                used, total = memory_mb()
                if self._can_power is None:
                    self._can_power = can_power()
                disk = shutil.disk_usage("/")
                v = {
                    "temp": cpu_temp(), "fan": fan_rpm(), "power": power_state(),
                    "memUsed": used, "memTotal": total,
                    "diskFree": disk.free / 1e9, "diskTotal": disk.total / 1e9,
                    "uptime": uptime_text(), "canPower": bool(self._can_power),
                    "errors": errorlog.log.count(),
                }
                self._logged()
            except Exception as e:
                self._logged(e)
            finally:
                safe_emit(self, "_read_done", v)      # always, or _busy would never clear
        threading.Thread(target=work, daemon=True).start()

    def _logged(self, error=None):
        """Log a reading that crashed (once, while the same error repeats), or
        that it's working again."""
        err = "" if error is None else f"{type(error).__name__}: {error}"
        if err and err != self._read_error:
            trace = "".join(traceback.format_exception(error)).rstrip()
            print(f"System: status check failed: {err}\n{trace}", flush=True)
        elif not err and self._read_error:
            print("System: status check working again", flush=True)
        self._read_error = err

    def _got_version(self, version):
        if version != self._version:
            self._version = version
            self.changed.emit()

    def _apply(self, v):
        self._busy = False
        if v and v != self._v:
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

    @pyqtProperty(int, notify=changed)
    def errors(self):
        """Uncaught errors since start (main.log_exception), as of the last check."""
        return self._v["errors"]

    @pyqtProperty(str, notify=changed)
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

    @pyqtProperty(str, notify=changed)
    def powerError(self):
        """Why the last reboot or shut down didn't happen, else ''."""
        return self._power_error

    def hold_power_while(self, busy):
        """Reboot and shut down wait while busy() is True, for at most
        POWER_HOLD_S: key-off has the relay's hold time to finish in, and
        what's cut off is put right on the next start (deploy/update-guard.sh)."""
        self._hold = busy

    def _held_tick(self):
        action, until = self._held
        if not self._hold() or time.monotonic() >= until:
            self._hold_timer.stop()
            self._held = None
            self._run_power(action)

    def _power(self, action):
        if self._power_error:
            self._power_error = ""
            self.changed.emit()
        if self._hold():
            until = self._held[1] if self._held else time.monotonic() + POWER_HOLD_S
            self._held = (action, until)
            self._hold_timer.start()
            print(f"System: {action} waits for the update, {POWER_HOLD_S} s at most", flush=True)
            return
        self._run_power(action)

    def _run_power(self, action):
        # On a worker thread: logind can take a moment to say no.
        threading.Thread(target=lambda: safe_emit(self, "_power_done", power(action)),
                         daemon=True).start()

    def _powered(self, why):
        if why:
            print(f"System: couldn't reboot or shut down: {why}", flush=True)
            self._power_error = why
            self.changed.emit()
            self.powerFailed.emit(why)

    @pyqtSlot()
    def reboot(self):
        self._power("reboot")

    @pyqtSlot()
    def powerOff(self):
        self._power("poweroff")
