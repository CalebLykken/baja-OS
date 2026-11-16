"""The equalizer: five bands in front of the speakers.

PipeWire does the filtering (deploy/audio/baja-eq.conf, run by the
baja-eq user service); this sets the band gains live with `pw-cli`, keeps
them in settings, and puts them back whenever the filter restarts. Without
PipeWire (a Mac) the controls still work but only remember their values.
"""

import re
import shutil
import subprocess
import threading

from PyQt6.QtCore import QObject, QTimer, pyqtProperty, pyqtSignal, pyqtSlot
from PyQt6.QtMultimedia import QMediaDevices

from backend import errorlog, safe_emit

NODE = "baja_eq"
LIMIT = 12                  # dB either way
# (filter node, label, centre frequency in Hz)
BANDS = [
    ("bass", "Bass", 80),
    ("low", "Low mid", 250),
    ("mid", "Mid", 1000),
    ("high", "Presence", 4000),
    ("treb", "Treble", 10000),
]
PRESETS = {
    "Flat": [0, 0, 0, 0, 0],
    # Road noise masks the lows and the top end; lift both a little.
    "Road": [4, 2, 0, 2, 3],
    "Bass": [7, 4, 0, 0, 1],
    "Vocal": [-2, -1, 2, 4, 1],
    "Bright": [0, 0, 0, 3, 6],
}
MINE = "Mine"               # the driver's own saved curve (settings key eqMine)
CHECK_EVERY_MS = 5000       # filter missing: look for it
FOUND_CHECK_MS = 30000      # filter running: only a PipeWire restart can change it


def _pw_cli(*args, timeout=3):
    try:
        return subprocess.run(["pw-cli", *args], capture_output=True, text=True,
                              errors="replace", timeout=timeout).stdout
    except (OSError, ValueError, subprocess.SubprocessError):
        return ""


def node_info():
    """(object id, object serial) of the running filter, or None.

    PipeWire hands out object ids from a small pool and reuses them, so a
    restarted filter can come back with the same id; the serial never repeats.
    The serial is None if pw-cli doesn't print one.
    """
    out = _pw_cli("i", NODE)
    m = re.search(r"^\s*id: (\d+)", out, re.M)
    if not m:
        return None
    s = re.search(r'object\.serial\D*(\d+)', out)
    return int(m[1]), (int(s[1]) if s else None)


def node_id():
    """The filter's PipeWire object id, or None if it isn't running."""
    info = node_info()
    return info[0] if info else None


class Equalizer(QObject):
    changed = pyqtSignal()
    _found = pyqtSignal(object)        # (id, serial) or None, from the watcher thread

    def __init__(self, settings, parent=None):
        super().__init__(parent)
        self._settings = settings
        self._gains = self._load()
        self._mine = self._load("eqMine")
        # A hand-tuned curve saved before 'Mine' existed would show as Custom
        # and be lost by tapping Mine: keep it as Mine now.
        if (not self._settings.get("eqMine", "")
                and self._gains not in PRESETS.values()):
            self._save_mine(self._gains)
        self._pw = bool(shutil.which("pw-cli"))
        self._node = None
        self._pending = None
        self._devices = None
        self._lock = threading.Lock()
        self._wake = threading.Event()
        self._found.connect(self._on_found)
        self._timer = QTimer(self)
        self._timer.setInterval(CHECK_EVERY_MS)
        self._timer.timeout.connect(self._check)

    def start(self):
        if not self._pw:
            return
        threading.Thread(target=self._writer, name="eq-writer", daemon=True).start()
        # The slow 30 s check would leave a crashed-and-restarted filter flat
        # for a while; its sink coming back shows up here at once.
        self._devices = QMediaDevices(self)
        self._devices.audioOutputsChanged.connect(self._check)
        self._check()
        self._timer.start()

    # ---- saved state --------------------------------------------------------
    def _load(self, key="eq"):
        raw = str(self._settings.get(key, "") or "")
        try:
            gains = [max(-LIMIT, min(LIMIT, int(v))) for v in raw.split(",")]
        except ValueError:
            gains = []
        return gains if len(gains) == len(BANDS) else [0] * len(BANDS)

    def _save(self):
        self._settings.set("eq", ",".join(str(g) for g in self._gains))

    def _save_mine(self, gains):
        """Remember the driver's own curve as the 'Mine' preset."""
        self._mine = list(gains)
        self._settings.set("eqMine", ",".join(str(g) for g in self._mine))

    # ---- talking to PipeWire ------------------------------------------------
    def _check(self):
        threading.Thread(target=self._find, daemon=True).start()

    def _find(self):
        try:
            info = node_info()
        except Exception:
            return                    # not found yet; the next check tries again
        safe_emit(self, "_found", info)

    def _on_found(self, info):
        was = self._node
        self._node = info
        if info is not None and info != was:
            self._push()              # (re)started, even under the same id: give it our gains
        if (info is None) != (was is None):
            self.changed.emit()
        wanted = FOUND_CHECK_MS if info is not None else CHECK_EVERY_MS
        if self._timer.interval() != wanted:
            self._timer.setInterval(wanted)   # restarts the countdown, so only when it changes

    def _push(self):
        """Queue the current gains for the writer thread (latest wins)."""
        if not self._pw:
            return
        # Lower the overall level by the biggest boost so loud passages
        # never clip after the EQ.
        pre = -max(0, max(self._gains))
        params = [("pre", pre)] + [(b[0], g) for b, g in zip(BANDS, self._gains)]
        with self._lock:
            self._pending = " ".join(f'"{name}:Gain" {gain:.1f}' for name, gain in params)
        self._wake.set()

    def _writer(self):
        while True:
            self._wake.wait()
            self._wake.clear()
            with self._lock:
                body, self._pending = self._pending, None
            if body:
                try:
                    _pw_cli("s", NODE, "Props", "{ params = [ " + body + " ] }")
                except Exception as e:
                    # One bad write must not end the thread: later changes still apply.
                    errorlog.log.report(type(e), e, e.__traceback__,
                                        label="EQ: couldn't set the gains, carrying on:")

    def _set_all(self, gains):
        gains = [max(-LIMIT, min(LIMIT, int(round(g)))) for g in gains]
        if gains != self._gains:
            self._gains = gains
            self._save()
            self._push()
            self.changed.emit()

    # ---- what QML sees ------------------------------------------------------
    @pyqtProperty(bool, notify=changed)
    def available(self):
        """True when the PipeWire filter is running and taking changes."""
        return self._node is not None

    @pyqtProperty(bool, constant=True)
    def supported(self):
        """False on machines without PipeWire (the controls only remember)."""
        return self._pw

    @pyqtProperty(int, constant=True)
    def limit(self):
        return LIMIT

    @pyqtProperty("QVariantList", constant=True)
    def bands(self):
        return [{"label": label, "freq": freq,
                 "freqText": f"{freq // 1000}k" if freq >= 1000 else str(freq)}
                for _, label, freq in BANDS]

    @pyqtProperty("QVariantList", notify=changed)
    def gains(self):
        return list(self._gains)

    @pyqtProperty("QStringList", notify=changed)
    def presetNames(self):
        return list(PRESETS) + [MINE]

    @pyqtProperty(str, notify=changed)
    def preset(self):
        """The preset the gains match, 'Mine' for the saved curve, or 'Custom'."""
        for name, gains in PRESETS.items():
            if gains == self._gains:
                return name
        return MINE if self._gains == self._mine else "Custom"

    @pyqtSlot(int, int)
    def setGain(self, index, db):
        if 0 <= index < len(BANDS):
            gains = list(self._gains)
            gains[index] = db
            self._set_all(gains)
            # Hand tuning is remembered; a curve that is just a built-in
            # preset is not, so picking a preset never overwrites 'Mine'.
            if self._gains not in PRESETS.values() and self._gains != self._mine:
                self._save_mine(self._gains)
                self.changed.emit()

    @pyqtSlot(str)
    def applyPreset(self, name):
        if name == MINE:
            self._set_all(self._mine)
        elif name in PRESETS:
            self._set_all(PRESETS[name])
