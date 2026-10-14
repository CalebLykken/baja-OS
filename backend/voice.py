"""Spoken directions: turns a line of text into speech with Piper and plays
it over the music, which dips while it speaks.

Piper runs in its own process (voice_worker.py, under the Piper install's
Python from deploy/audio/install-voice.sh), started on first use and kept
loaded. Playback is `pw-play`; the other audio streams are turned down
with `wpctl` for the length of the line and put back afterwards, so
Spotify's own volume (and the phone's slider) never moves.
"""

import json
import os
import queue
import re
import shutil
import subprocess
import tempfile
import threading
import time
from pathlib import Path

from PyQt6.QtCore import QObject, pyqtProperty, pyqtSignal, pyqtSlot

ROOT = Path(__file__).resolve().parent.parent
VOICE_DIR = Path(os.environ.get("BAJA_VOICE_DIR", "~/.local/share/baja-os/voice")).expanduser()
MODEL = VOICE_DIR / "en_US-kristin-medium.onnx"
PYTHON = VOICE_DIR / "venv" / "bin" / "python"
NODE_NAME = "baja-voice"
# The equalizer's own output carries everything, the voice included; leave it.
NOT_DUCKED = {NODE_NAME, "baja_eq.output"}
DUCK_TO = 0.3           # other audio drops to this share of its volume while speaking
STALE_S = 8             # a line not spoken within this long is dropped


def _output_streams():
    """{node id: volume} of the other audio streams playing right now."""
    try:
        out = subprocess.run(["pw-dump"], capture_output=True, text=True, timeout=3).stdout
        objects = json.loads(out)
    except (OSError, subprocess.SubprocessError, ValueError):
        return {}
    streams = {}
    for o in objects:
        props = ((o.get("info") or {}).get("props") or {})
        if props.get("media.class") != "Stream/Output/Audio" or props.get("node.name") in NOT_DUCKED:
            continue
        try:
            vol = subprocess.run(["wpctl", "get-volume", str(o["id"])], capture_output=True,
                                 text=True, timeout=2).stdout
            m = re.search(r"Volume: ([\d.]+)", vol)
            if m:
                streams[o["id"]] = float(m[1])
        except (OSError, subprocess.SubprocessError):
            pass
    return streams


def _set_volumes(volumes):
    for node, vol in volumes.items():
        subprocess.run(["wpctl", "set-volume", str(node), f"{vol:.3f}"],
                       capture_output=True, timeout=2)


class Voice(QObject):
    changed = pyqtSignal()

    def __init__(self, settings, parent=None):
        super().__init__(parent)
        self._settings = settings
        self._enabled = str(settings.get("voice", "true")) == "true"
        self._available = MODEL.is_file() and PYTHON.is_file() and bool(shutil.which("pw-play"))
        self._jobs = queue.Queue()
        self._proc = None
        self._tmp = Path(os.environ.get("XDG_RUNTIME_DIR") or tempfile.gettempdir())
        if self._available:
            threading.Thread(target=self._run, name="voice", daemon=True).start()

    # ---- the worker ------------------------------------------------------------------
    def _worker(self):
        if self._proc is None or self._proc.poll() is not None:
            self._proc = subprocess.Popen(
                # -I: nothing in backend/ can shadow what Piper imports.
                [str(PYTHON), "-I", str(ROOT / "backend" / "voice_worker.py"), str(MODEL)],
                stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL,
                text=True, bufsize=1)
            self._proc.stdout.readline()            # {"ready": true} once the voice is loaded
        return self._proc

    def _run(self):
        n = 0
        while True:
            text, queued_at = self._jobs.get()
            if time.monotonic() - queued_at > STALE_S:
                continue                            # the moment has passed
            try:
                proc = self._worker()
                n += 1
                out = str(self._tmp / f"baja-voice-{n % 4}.wav")
                proc.stdin.write(json.dumps({"text": text, "out": out}) + "\n")
                reply = json.loads(proc.stdout.readline() or "{}")
                if "out" not in reply:
                    continue
                others = _output_streams()
                _set_volumes({k: v * DUCK_TO for k, v in others.items()})
                try:
                    subprocess.run(["pw-play", "--media-role", "Navigation",
                                    "--properties", '{ node.name = "%s" }' % NODE_NAME, out],
                                   capture_output=True, timeout=30)
                finally:
                    _set_volumes(others)
            except (OSError, subprocess.SubprocessError, ValueError, BrokenPipeError):
                self._proc = None                    # start it again next time

    # ---- what QML and the router use -----------------------------------------------
    @pyqtSlot(str)
    def say(self, text):
        if self._available and self._enabled and text:
            self._jobs.put((text, time.monotonic()))

    @pyqtSlot()
    def test(self):
        """Say a sample line, even if spoken directions are off."""
        if self._available:
            self._jobs.put(("In a quarter mile, turn right onto Broad Street.", time.monotonic()))

    @pyqtProperty(bool, constant=True)
    def available(self):
        return self._available

    @pyqtProperty(bool, notify=changed)
    def enabled(self):
        return self._enabled

    @pyqtSlot(bool)
    def setEnabled(self, on):
        if on != self._enabled:
            self._enabled = on
            self._settings.set("voice", "true" if on else "false")
            self.changed.emit()
