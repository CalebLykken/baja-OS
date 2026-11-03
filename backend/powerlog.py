"""A flight recorder for power trouble in the truck.

Writes what the Pi sees every couple of seconds to a file of its own, so a
screen that blinks out on the road can be read about afterwards at home:

    ~/.local/share/baja-os/power/<boot>.log

One file per boot (a Pi reboot starts a new file, a dashboard restart adds an
"app started" line to the same one). `SAMPLE|` lines are the readings; `EVENT|`
lines are the moments something changed, and those go to the journal as well:

  - the firmware's power flags (under-voltage now, or since the last look);
  - the HDMI link to the screen dropping or coming back;
  - the kernel's USB, HDMI and power messages. The screen's power comes down
    its USB lead, so if the screen browns out, its touch controller drops off
    USB at the same moment.

`supply` and `lowest` (the Pi's 5 V input, as its power chip measures it) are
also on Settings > System, so it can be watched from the driver's seat.

Everything is forced to the SD card often, since the power can go any moment.
On a Mac there's no vcgencmd and it doesn't start.
"""

import os
import re
import shutil
import subprocess
import threading
import time
from glob import glob
from pathlib import Path

from PyQt6.QtCore import QObject, pyqtProperty, pyqtSignal

from backend import safe_emit
from backend.system import cpu_temp, fan_rpm, memory_mb

LOG_DIR = Path.home() / ".local/share/baja-os/power"
EVERY_S = 2.0
SYNC_EVERY = 5          # samples between forcing them to the card; events go at once
KEEP_BOOTS = 30         # log files kept (about 0.3 MB per hour of driving)
POWER_NODE = "/proc/device-tree/chosen/power"   # what the firmware decided at boot

FLAGS = {
    0x1: "under-voltage now",
    0x2: "CPU speed capped now",
    0x4: "throttled now",
    0x8: "soft temperature limit now",
    0x10000: "under-voltage since boot",
    0x20000: "CPU speed capped since boot",
    0x40000: "throttled since boot",
    0x80000: "soft temperature limit since boot",
}

KERNEL_WORTH_KEEPING = re.compile(
    r"undervolt|under-volt|over-?current|voltage|brownout|USB disconnect|new .*USB device"
    r"|hdmi|hotplug|\bhpd\b|\bdrm\b|\bvc4\b|flip_done|hwmon|thermal|Out of memory",
    re.IGNORECASE)


def flag_names(bits):
    return ", ".join(name for bit, name in FLAGS.items() if bits & bit) or "none"


def parse_pmic(text):
    """(input volts or None, Pi's own watts or None) from `vcgencmd
    pmic_read_adc`, which lists each rail's current and voltage, then EXT5V_V."""
    amps, volts = {}, {}
    for name, kind, value in re.findall(r"^\s*(\w+?)_([AV]) \w+\(\d+\)=([\d.]+)[AV]", text, re.M):
        (amps if kind == "A" else volts)[name] = float(value)
    watts = sum(a * volts[name] for name, a in amps.items() if name in volts)
    return volts.get("EXT5V"), round(watts, 2) if amps else None


def _run(*cmd):
    try:
        return subprocess.run(cmd, capture_output=True, text=True, timeout=2).stdout
    except (OSError, subprocess.SubprocessError):
        return ""


def read_throttled():
    try:
        return int(_run("vcgencmd", "get_throttled").strip().split("=")[1], 16)
    except (IndexError, ValueError):
        return None


def read_clock_mhz():
    try:
        return int(_run("vcgencmd", "measure_clock", "arm").strip().split("=")[1]) // 1000000
    except (IndexError, ValueError):
        return None


def hdmi_status():
    """Each HDMI output's state, 'HDMI-A-1=connected HDMI-A-2=disconnected'."""
    found = []
    for path in sorted(glob("/sys/class/drm/card*-HDMI-A-*/status")):
        name = Path(path).parent.name.split("-", 1)[1]
        try:
            found.append(f"{name}={Path(path).read_text().strip()}")
        except OSError:
            pass
    return " ".join(found)


def app_rss_mb():
    with open("/proc/self/statm") as f:
        return int(f.read().split()[1]) * os.sysconf("SC_PAGE_SIZE") // 1048576


def boot_facts():
    """What the Pi was told about its supply at boot: PSU_MAX_CURRENT and
    how much the USB ports may share. One line."""
    facts = []
    for f in sorted(glob(POWER_NODE + "/*")):
        try:
            data = Path(f).read_bytes()
        except OSError:
            continue
        if len(data) == 4:          # the numbers; the rest are binary tables
            facts.append(f"{Path(f).name}={int.from_bytes(data, 'big')}")
    psu = re.search(r"^PSU_MAX_CURRENT=.*$", _run("vcgencmd", "bootloader_config"), re.M)
    facts.append(psu.group(0) if psu else "PSU_MAX_CURRENT not set")
    return " ".join(facts)


def prune(folder, keep=KEEP_BOOTS):
    """Delete all but the newest `keep` logs. A file that vanishes or can't be
    read part-way is skipped; this never raises."""
    try:
        found = list(Path(folder).glob("*.log"))
    except OSError:
        return
    dated = []
    for p in found:
        try:
            dated.append((p.stat().st_mtime, p))
        except OSError:
            pass
    dated.sort(key=lambda d: d[0], reverse=True)
    for _, old in dated[keep:]:
        try:
            old.unlink(missing_ok=True)
        except OSError:
            pass


KERNEL_BACKOFF_FIRST = 5.0      # seconds before restarting the kernel follower
KERNEL_BACKOFF_MAX = 300.0
KERNEL_RUN_OK_S = 300.0         # a run this long counts as healthy: back-off resets


def kernel_cmd(first):
    """The journalctl command. The first run reads this boot from the start, so a
    dip during boot is in the file too; restarts only want what is new."""
    since = ["-n", "all"] if first else ["--since", "now"]
    return ["journalctl", "-k", "-b", "-f", *since, "-o", "short-monotonic", "--no-pager"]


def next_backoff(current, ran_for):
    """Seconds to wait before the next restart, given the wait just used and how
    long the last run lasted: doubles up to a cap, back to the start after a long run."""
    if ran_for > KERNEL_RUN_OK_S:
        return KERNEL_BACKOFF_FIRST
    return min(current * 2, KERNEL_BACKOFF_MAX)


class PowerLog(QObject):
    changed = pyqtSignal()

    def __init__(self, folder=LOG_DIR, parent=None):
        super().__init__(parent)
        self._folder = Path(folder)
        self._file = None
        self._lock = threading.Lock()   # two threads write
        self._battery = None          # the car's latest reading
        self._supply = None
        self._lowest = None
        self._throttled = None
        self._hdmi = None
        self._unsynced = 0

    def start(self):
        if not shutil.which("vcgencmd"):
            return
        threading.Thread(target=self._begin, daemon=True).start()

    def battery(self, volts):
        """The car's battery, from the OBD adapter. Any thread."""
        self._battery = volts

    def _begin(self):
        try:
            self._folder.mkdir(parents=True, exist_ok=True)
            try:
                boot = Path("/proc/sys/kernel/random/boot_id").read_text()[:8]
            except OSError:
                boot = time.strftime("%Y%m%d-%H%M%S")
            self._file = open(self._folder / f"{boot}.log", "a", buffering=1)
        except OSError as e:
            print(f"Power log: can't write to {self._folder} ({e})", flush=True)
            return
        prune(self._folder)
        restarts = _run("systemctl", "show", "baja-os", "-p", "NRestarts", "--value").strip()
        self.event(f"app started (service restarts this boot: {restarts or '?'})")
        self.event(f"supply at boot: {boot_facts()}")
        self._write("# SAMPLE|time|uptime s|supply V|Pi W|flags|CPU C|CPU MHz|fan rpm"
                    "|battery V|screen|free MB|app MB\n")
        threading.Thread(target=self._kernel, daemon=True).start()
        while True:
            try:
                self._sample()
            except Exception as e:      # the recorder must not take anything down
                self.event(f"sample failed: {type(e).__name__}: {e}")
            time.sleep(EVERY_S)

    def _sample(self):
        supply, watts = parse_pmic(_run("vcgencmd", "pmic_read_adc"))
        flags = read_throttled()
        hdmi = hdmi_status()
        if flags is not None and flags != self._throttled:
            if self._throttled is not None or flags:
                self.event(f"power flags {flags:#x}: {flag_names(flags)}")
            self._throttled = flags
        if hdmi != self._hdmi:
            if self._hdmi is not None:
                self.event(f"screen link changed: {self._hdmi or 'none'} -> {hdmi or 'none'}")
            self._hdmi = hdmi
        if supply is not None:
            self._supply = supply
            self._lowest = supply if self._lowest is None else min(self._lowest, supply)
            safe_emit(self, "changed")
        used, total = memory_mb()
        temp, battery = cpu_temp(), self._battery
        self._write("|".join(str(v) for v in (
            "SAMPLE", self._stamp(), "" if supply is None else f"{supply:.3f}",
            "" if watts is None else watts, "" if flags is None else f"{flags:#x}",
            "" if temp is None else f"{temp:.1f}", read_clock_mhz() or "", fan_rpm() or "",
            "" if battery is None else f"{battery:.1f}", hdmi, total - used, app_rss_mb(),
        )) + "\n")
        self._unsynced += 1
        if self._unsynced >= SYNC_EVERY:
            self._sync()

    def _stamp(self):
        return f"{time.strftime('%H:%M:%S')}|{time.monotonic():.1f}"

    def event(self, text):
        print(f"Power log: {text}", flush=True)
        self._write(f"EVENT|{self._stamp()}|{text}\n")
        self._sync()

    def _write(self, line):
        with self._lock:
            try:
                self._file.write(line)
            except (OSError, ValueError):
                pass

    def _sync(self):
        with self._lock:
            self._unsynced = 0
            try:
                os.fsync(self._file.fileno())
            except (OSError, ValueError):
                pass

    def _kernel(self):
        first, wait = True, KERNEL_BACKOFF_FIRST
        while True:
            started = time.monotonic()
            try:
                self._follow_kernel(first)
            except Exception as e:      # keep following whatever happens
                self.event(f"kernel log follower failed: {type(e).__name__}: {e}")
            first = False
            ran_for = time.monotonic() - started
            wait = KERNEL_BACKOFF_FIRST if ran_for > KERNEL_RUN_OK_S else wait
            self.event(f"the kernel log stopped; following again in {wait:.0f} s")
            time.sleep(wait)
            wait = next_backoff(wait, ran_for)
            self.event("following the kernel log again")

    def _follow_kernel(self, first):
        try:
            proc = subprocess.Popen(
                kernel_cmd(first), stdout=subprocess.PIPE, stderr=subprocess.DEVNULL,
                text=True, errors="replace")
        except OSError as e:
            self.event(f"can't follow the kernel log: {e}")
            return
        try:
            for line in proc.stdout:
                if KERNEL_WORTH_KEEPING.search(line):
                    self.event("kernel: " + line.strip())
        finally:
            try:
                proc.stdout.close()
                proc.wait(timeout=2)
            except (OSError, subprocess.SubprocessError):
                proc.kill()
                proc.wait()

    @pyqtProperty(float, notify=changed)
    def supply(self):
        """The Pi's 5 V input now, or -1 if unknown."""
        return -1.0 if self._supply is None else self._supply

    @pyqtProperty(float, notify=changed)
    def lowest(self):
        """The lowest `supply` since the dashboard started, or -1."""
        return -1.0 if self._lowest is None else self._lowest
