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

from backend import safe_emit

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
CHECK_EVERY_MS = 5000


def _pw_cli(*args, timeout=3):
    try:
        return subprocess.run(["pw-cli", *args], capture_output=True, text=True,
                              timeout=timeout).stdout
    except (OSError, subprocess.SubprocessError):
        return ""


def node_id():
    """The filter's PipeWire object id, or None if it isn't running."""
    m = re.search(r"^\s*id: (\d+)", _pw_cli("i", NODE), re.M)
    return int(m[1]) if m else None


class Equalizer(QObject):
    changed = pyqtSignal()
    _found = pyqtSignal(object)        # node id or None, from the watcher thread

    def __init__(self, settings, parent=None):
        super().__init__(parent)
        self._settings = settings
        self._gains = self._load()
        self._pw = bool(shutil.which("pw-cli"))
        self._node = None
        self._pending = None
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
        self._check()
        self._timer.start()

    # ---- saved state --------------------------------------------------------
    def _load(self):
        raw = str(self._settings.get("eq", "") or "")
        try:
            gains = [max(-LIMIT, min(LIMIT, int(v))) for v in raw.split(",")]
        except ValueError:
            gains = []
        return gains if len(gains) == len(BANDS) else [0] * len(BANDS)

    def _save(self):
        self._settings.set("eq", ",".join(str(g) for g in self._gains))

    # ---- talking to PipeWire ------------------------------------------------
    def _check(self):
        threading.Thread(target=lambda: safe_emit(self, "_found", node_id()), daemon=True).start()

    def _on_found(self, nid):
        was = self._node
        self._node = nid
        if nid is not None and nid != was:
            self._push()              # (re)started: give it our gains
        if (nid is None) != (was is None):
            self.changed.emit()

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
                _pw_cli("s", NODE, "Props", "{ params = [ " + body + " ] }")

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

    @pyqtProperty("QStringList", constant=True)
    def presetNames(self):
        return list(PRESETS)

    @pyqtProperty(str, notify=changed)
    def preset(self):
        """The preset the gains match, or 'Custom'."""
        for name, gains in PRESETS.items():
            if gains == self._gains:
                return name
        return "Custom"

    @pyqtSlot(int, int)
    def setGain(self, index, db):
        if 0 <= index < len(BANDS):
            gains = list(self._gains)
            gains[index] = db
            self._set_all(gains)

    @pyqtSlot(str)
    def applyPreset(self, name):
        if name in PRESETS:
            self._set_all(PRESETS[name])
