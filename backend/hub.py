"""The one `media` object the UI talks to.

Fronts three sources and forwards whichever is active, with the same
properties and slots the QML already uses:

- `local`:   files on the Pi (or the demo playlist)
- `phone`:   the phone over Bluetooth (A2DP + AVRCP)
- `spotify`: Spotify Connect on the Pi (Soloist)

Switching: whichever source most recently started playing takes over and the
others are paused. Tapping a song in the local queue switches back to local.
One exception: right after the phone (re)connects over Bluetooth, iPhones
often resume playback by themselves; for a few seconds that doesn't count as
"started playing" while Spotify is the active source.

Volume follows the active source, like a car stereo. Phone and Spotify keep
their own volume (synced with the phone's slider), and the Pi's output sits
at 100% while they play. Local music uses the Pi's output volume via
PipeWire's `wpctl` (or the player's own volume where wpctl doesn't exist,
e.g. on a Mac).

It also derives an accent colour and a pre-blurred backdrop from the
current album art for the Music page; Spotify covers are downloaded and
cached first.
"""

import hashlib
import shutil
import subprocess
import tempfile
import threading
import time
import urllib.request
from pathlib import Path

from PyQt6.QtCore import QObject, QUrl, Qt, pyqtProperty, pyqtSignal, pyqtSlot
from PyQt6.QtGui import QColor, QImage

ART_CACHE = Path(tempfile.gettempdir()) / "baja-art"
PHONE_RECONNECT_GRACE_S = 10


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


def cached_art(url):
    """A local file URL for `url`: file URLs as-is, http(s) downloaded once."""
    if not url or not url.startswith("http"):
        return url
    ART_CACHE.mkdir(exist_ok=True)
    out = ART_CACHE / (hashlib.sha1(url.encode()).hexdigest() + ".img")
    if not out.exists():
        with urllib.request.urlopen(url, timeout=10) as r:
            out.write_bytes(r.read())
    return QUrl.fromLocalFile(str(out)).toString()


class MediaHub(QObject):
    trackChanged = pyqtSignal()
    positionChanged = pyqtSignal()
    playingChanged = pyqtSignal()
    volumeChanged = pyqtSignal()
    sourceChanged = pyqtSignal()
    queueChanged = pyqtSignal()
    _artReady = pyqtSignal(str, str, str, str)   # source, art url, accent, blur

    def __init__(self, local, phone, spotify, volume=40, parent=None):
        super().__init__(parent)
        self._sources = {"local": local, "phone": phone, "spotify": spotify}
        self._source = "local"
        self._system_volume = bool(shutil.which("wpctl"))
        self._volume = max(0, min(100, int(volume)))
        self._art = {}                  # source -> (art url, accent, blur)
        self._phone_connected_at = 0.0
        self._phone_name = phone.deviceName

        for name, src in self._sources.items():
            for sig in ("trackChanged", "positionChanged", "playingChanged"):
                getattr(src, sig).connect(lambda n=name, s=sig: self._forward(n, s))
            src.playingChanged.connect(lambda n=name: self._source_playing_changed(n))
            src.trackChanged.connect(lambda n=name: self._update_art(n))
        phone.trackChanged.connect(self._phone_player_changed)
        phone.changed.connect(self._phone_connection_changed)
        phone.volumeChanged.connect(lambda: self._remote_volume_changed("phone"))
        spotify.volumeChanged.connect(lambda: self._remote_volume_changed("spotify"))
        spotify.changed.connect(self._spotify_changed)
        spotify.queueChanged.connect(self.queueChanged)
        self._artReady.connect(self._apply_art)

        if self._system_volume:
            local.setVolume(100)          # master volume lives in PipeWire
        self._apply_volume()
        self._update_art("local")

    def start(self):
        for src in self._sources.values():
            src.start()

    # ---- source switching -------------------------------------------------
    @property
    def _active(self):
        return self._sources[self._source]

    @property
    def _remote_volume(self):
        """True when the active source keeps its own volume (phone, Spotify)."""
        return self._source != "local" and self._active.hasVolume

    def _set_source(self, source):
        if source != self._source:
            self._source = source
            self._apply_volume()
            for sig in ("sourceChanged", "volumeChanged", "trackChanged",
                        "positionChanged", "playingChanged", "queueChanged"):
                getattr(self, sig).emit()

    def _pause_others(self, keep):
        for name, src in self._sources.items():
            if name != keep and src.playing:
                if hasattr(src, "pause"):
                    src.pause()
                else:
                    src.togglePlay()

    def _source_playing_changed(self, name):
        if not self._sources[name].playing or name == self._source:
            return
        if (name == "phone" and self._source == "spotify"
                and time.monotonic() - self._phone_connected_at < PHONE_RECONNECT_GRACE_S):
            return       # an iPhone auto-resuming after reconnecting
        self._pause_others(keep=name)
        self._set_source(name)

    def _phone_connection_changed(self):
        name = self._sources["phone"].deviceName
        if name and not self._phone_name:
            self._phone_connected_at = time.monotonic()
        self._phone_name = name

    def _phone_player_changed(self):
        if not self._sources["phone"].hasPlayer and self._source == "phone":
            self._set_source("local")

    def _spotify_changed(self):
        sp = self._sources["spotify"]
        if self._source == "spotify" and not (sp.available and sp.active):
            self._set_source("local")    # moved to another device, or Soloist stopped

    def _remote_volume_changed(self, name):
        if name == self._source and self._remote_volume:
            self._apply_volume()      # the Pi's output goes to 100% once known
            self.volumeChanged.emit()

    def _forward(self, origin, signal):
        if origin == self._source:
            getattr(self, signal).emit()

    # ---- album art --------------------------------------------------------
    def _update_art(self, name):
        url = self._sources[name].art
        if name == "local":
            accent, blur = art_derivatives(url)
            self._apply_art(name, url, accent, blur)
            return
        if not url:
            self._apply_art(name, "", "", "")
            return

        def work():
            try:
                local = cached_art(url)
                accent, blur = art_derivatives(local)
            except Exception:          # offline, bad URL: keep the remote URL
                local, accent, blur = url, "", ""
            self._artReady.emit(name, local, accent, blur)
        threading.Thread(target=work, daemon=True).start()

    def _apply_art(self, name, url, accent, blur):
        self._art[name] = (url, accent, blur)
        if name == self._source:
            self.trackChanged.emit()

    def _art_field(self, i):
        return self._art.get(self._source, ("", "", ""))[i]

    # ---- volume -----------------------------------------------------------
    def _apply_volume(self):
        if self._system_volume:
            level = "1.00" if self._remote_volume else f"{self._volume / 100:.2f}"
            threading.Thread(target=lambda: subprocess.run(
                ["wpctl", "set-volume", "@DEFAULT_AUDIO_SINK@", level],
                capture_output=True, timeout=3), daemon=True).start()
        else:
            self._sources["local"].setVolume(self._volume)

    # ---- properties (same names as the players, plus source info) ---------
    @pyqtProperty(str, notify=sourceChanged)
    def source(self):
        """'local', 'phone' or 'spotify'."""
        return self._source

    @pyqtProperty(str, notify=sourceChanged)
    def sourceName(self):
        """Who's playing, for the badge: the phone's name, or 'Spotify'."""
        if self._source == "phone":
            return self._sources["phone"].deviceName
        return "Spotify" if self._source == "spotify" else ""

    @pyqtProperty(str, notify=trackChanged)
    def title(self):
        return self._active.title

    @pyqtProperty(str, notify=trackChanged)
    def artist(self):
        return self._active.artist

    @pyqtProperty(str, notify=trackChanged)
    def art(self):
        return self._art_field(0)

    @pyqtProperty(str, notify=trackChanged)
    def artColor(self):
        """Accent colour taken from the album art, or '' when there's none."""
        return self._art_field(1)

    @pyqtProperty(str, notify=trackChanged)
    def artBlur(self):
        """Blurred album art for page backdrops, or ''."""
        return self._art_field(2)

    @pyqtProperty(int, notify=trackChanged)
    def duration(self):
        return self._active.duration

    @pyqtProperty(int, notify=trackChanged)
    def index(self):
        return self._sources["local"].index if self._source == "local" else -1

    @pyqtProperty("QVariantList", constant=True)
    def queue(self):
        """The local music library (tap to play)."""
        return self._sources["local"].queue

    @pyqtProperty("QVariantList", notify=queueChanged)
    def upNext(self):
        """What Spotify plays next (display only)."""
        return self._sources["spotify"].upNext if self._source == "spotify" else []

    @pyqtProperty(int, notify=positionChanged)
    def position(self):
        return self._active.position

    @pyqtProperty(bool, notify=playingChanged)
    def playing(self):
        return self._active.playing

    @pyqtProperty(int, notify=volumeChanged)
    def volume(self):
        return self._active.volume if self._remote_volume else self._volume

    @property
    def local_volume(self):
        """The Pi's own volume (what's saved between runs); phone and Spotify keep their own."""
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
        self._pause_others(keep="local")
        self._set_source("local")
        self._sources["local"].playIndex(index)

    @pyqtSlot(int)
    def setVolume(self, value):
        value = max(0, min(100, int(value)))
        if self._remote_volume:
            self._active.setVolume(value)
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
