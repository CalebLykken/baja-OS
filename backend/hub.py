"""The one `media` object the UI talks to.

Wraps the local player (library or demo) and the phone over Bluetooth and
forwards whichever is active, with the same properties and slots the QML
already uses. The phone takes over when it starts playing (local music
pauses); tapping a song in the queue switches back.

Volume follows the active source, like a car stereo: while the phone plays,
the bar is the phone's own volume (Bluetooth absolute volume, in sync with
the phone's buttons) and the Pi's output sits at 100%; for local music it's
the Pi's output volume via PipeWire's `wpctl` (or the player's own volume
where wpctl doesn't exist, e.g. on a Mac).

It also derives two things from the current album art for the Music page:
an accent colour and a pre-blurred backdrop image.
"""

import hashlib
import shutil
import subprocess
import tempfile
import threading
from pathlib import Path

from PyQt6.QtCore import QObject, QUrl, Qt, pyqtProperty, pyqtSignal, pyqtSlot
from PyQt6.QtGui import QColor, QImage

ART_CACHE = Path(tempfile.gettempdir()) / "baja-art"


def art_derivatives(url):
    """(accent colour, blurred backdrop URL) for an art file URL, or ('', '')."""
    path = QUrl(url).toLocalFile() if url else ""
    img = QImage(path) if path else QImage()
    if img.isNull():
        return "", ""
    # Averaging down to one pixel gives the dominant tone; nudge it so it
    # reads as a colour on the dark UI rather than mud.
    c = img.scaled(1, 1, Qt.AspectRatioMode.IgnoreAspectRatio,
                   Qt.TransformationMode.SmoothTransformation).pixelColor(0, 0)
    h, s, v, _ = c.getHsvF()
    accent = QColor.fromHsvF(max(h, 0.0), min(1.0, s * 1.4 + 0.15), max(0.55, v)).name()
    # A tiny image scaled up smoothly by the GPU looks like a heavy blur, at
    # no runtime cost.
    ART_CACHE.mkdir(exist_ok=True)
    out = ART_CACHE / (hashlib.sha1(path.encode()).hexdigest() + "-blur.png")
    if not out.exists():
        img.scaled(24, 24, Qt.AspectRatioMode.KeepAspectRatioByExpanding,
                   Qt.TransformationMode.SmoothTransformation).save(str(out))
    return accent, QUrl.fromLocalFile(str(out)).toString()


class MediaHub(QObject):
    trackChanged = pyqtSignal()
    positionChanged = pyqtSignal()
    playingChanged = pyqtSignal()
    volumeChanged = pyqtSignal()
    sourceChanged = pyqtSignal()

    def __init__(self, local, phone, volume=40, parent=None):
        super().__init__(parent)
        self._local = local
        self._phone = phone
        self._source = "local"
        self._system_volume = bool(shutil.which("wpctl"))
        self._volume = max(0, min(100, int(volume)))
        self._art_accent, self._art_blur = "", ""

        for sig in ("trackChanged", "positionChanged", "playingChanged"):
            getattr(local, sig).connect(lambda s=sig: self._forward("local", s))
            getattr(phone, sig).connect(lambda s=sig: self._forward("phone", s))
        local.trackChanged.connect(self._update_art)
        phone.playingChanged.connect(self._phone_playing_changed)
        phone.trackChanged.connect(self._phone_player_changed)
        phone.volumeChanged.connect(self._phone_volume_changed)

        if self._system_volume:
            local.setVolume(100)          # master volume lives in PipeWire
        self._apply_volume()
        self._update_art()

    def start(self):
        self._local.start()
        self._phone.start()

    # ---- source switching -------------------------------------------------
    @property
    def _active(self):
        return self._phone if self._source == "phone" else self._local

    @property
    def _phone_volume(self):
        return self._source == "phone" and self._phone.hasVolume

    def _set_source(self, source):
        if source != self._source:
            self._source = source
            self._apply_volume()
            self.sourceChanged.emit()
            self.volumeChanged.emit()
            self.trackChanged.emit()
            self.positionChanged.emit()
            self.playingChanged.emit()

    def _phone_playing_changed(self):
        if self._phone.playing:
            if self._local.playing:
                self._local.togglePlay()
            self._set_source("phone")

    def _phone_player_changed(self):
        if not self._phone.hasPlayer and self._source == "phone":
            self._set_source("local")

    def _phone_volume_changed(self):
        if self._phone_volume:
            self._apply_volume()      # the Pi's output goes to 100% once known
            self.volumeChanged.emit()

    def _forward(self, origin, signal):
        if origin == self._source:
            getattr(self, signal).emit()

    def _update_art(self):
        self._art_accent, self._art_blur = art_derivatives(self._local.art)
        if self._source == "local":
            self.trackChanged.emit()

    # ---- volume -----------------------------------------------------------
    def _apply_volume(self):
        if self._system_volume:
            # Phone audio: the phone sets the level, so the Pi stays at full.
            level = "1.00" if self._phone_volume else f"{self._volume / 100:.2f}"
            threading.Thread(target=lambda: subprocess.run(
                ["wpctl", "set-volume", "@DEFAULT_AUDIO_SINK@", level],
                capture_output=True, timeout=3), daemon=True).start()
        else:
            self._local.setVolume(self._volume)

    # ---- properties (same names as the players, plus source info) ---------
    @pyqtProperty(str, notify=sourceChanged)
    def source(self):
        """'local' or 'phone'."""
        return self._source

    @pyqtProperty(str, notify=sourceChanged)
    def sourceName(self):
        return self._phone.deviceName if self._source == "phone" else ""

    @pyqtProperty(str, notify=trackChanged)
    def title(self):
        return self._active.title

    @pyqtProperty(str, notify=trackChanged)
    def artist(self):
        return self._active.artist

    @pyqtProperty(str, notify=trackChanged)
    def art(self):
        return self._local.art if self._source == "local" else ""

    @pyqtProperty(str, notify=trackChanged)
    def artColor(self):
        """Accent colour taken from the album art, or '' when there's none."""
        return self._art_accent if self._source == "local" else ""

    @pyqtProperty(str, notify=trackChanged)
    def artBlur(self):
        """Blurred album art for page backdrops, or ''."""
        return self._art_blur if self._source == "local" else ""

    @pyqtProperty(int, notify=trackChanged)
    def duration(self):
        return self._active.duration

    @pyqtProperty(int, notify=trackChanged)
    def index(self):
        return self._local.index if self._source == "local" else -1

    @pyqtProperty("QVariantList", constant=True)
    def queue(self):
        return self._local.queue

    @pyqtProperty(int, notify=positionChanged)
    def position(self):
        return self._active.position

    @pyqtProperty(bool, notify=playingChanged)
    def playing(self):
        return self._active.playing

    @pyqtProperty(int, notify=volumeChanged)
    def volume(self):
        return self._phone.volume if self._phone_volume else self._volume

    @property
    def local_volume(self):
        """The Pi's own volume (what's saved between runs); the phone keeps its own."""
        return self._volume

    # ---- controls ---------------------------------------------------------
    @pyqtSlot()
    def togglePlay(self):
        self._active.togglePlay()

    @pyqtSlot()
    def next(self):
        self._active.next()

    @pyqtSlot()
    def previous(self):
        self._active.previous()

    @pyqtSlot(int)
    def playIndex(self, index):
        if self._source == "phone" and self._phone.playing:
            self._phone.pause()
        self._set_source("local")
        self._local.playIndex(index)

    @pyqtSlot(int)
    def setVolume(self, value):
        value = max(0, min(100, int(value)))
        if self._phone_volume:
            self._phone.setVolume(value)
            return
        if value != self._volume:
            self._volume = value
            self._apply_volume()
            self.volumeChanged.emit()

    @pyqtSlot()
    def volumeUp(self):
        self.setVolume(self.volume + 4)

    @pyqtSlot()
    def volumeDown(self):
        self.setVolume(self.volume - 4)
