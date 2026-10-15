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
e.g. on a Mac). `maxVolume` is a ceiling on the Pi's output for every source
(for headphones): the sliders still run 0-100, and 100 means the ceiling.

It also prepares the current cover as a rounded square for the album-art
frame; Spotify covers are downloaded and cached first.
"""

import hashlib
import shutil
import subprocess
import tempfile
import threading
import time
import urllib.request
from pathlib import Path

from PyQt6.QtCore import QObject, QTimer, QUrl, Qt, pyqtProperty, pyqtSignal, pyqtSlot
from PyQt6.QtGui import QImage, QPainter, QPainterPath

from backend import safe_emit

ART_CACHE = Path(tempfile.gettempdir()) / "baja-art"
PHONE_RECONNECT_GRACE_S = 10
# Soft pause and play, like a car stereo: music cut off mid-wave clicks.
# Pause fades the output out first; play starts silent and fades in once
# the source says it's playing (its sound lags a little behind that).
FADE_OUT_MS = 180
FADE_IN_MS = 400
FADE_STEP_MS = 30
START_WAIT_MS = 120
SETTLE_MS = 250            # after pausing, before the volume goes back up
FADE_GIVE_UP_MS = 3000     # a source that never answers doesn't leave it silent


def _rounded_card(img, out, size=600, radius_frac=0.014):
    """The cover centre-cropped to a square with slightly rounded corners,
    ready to show as a framed print (AlbumArt.qml draws the border). Baked
    here because QML can't round an image's corners without the effects
    module."""
    sq = img.scaled(size, size, Qt.AspectRatioMode.KeepAspectRatioByExpanding,
                    Qt.TransformationMode.SmoothTransformation)
    sq = sq.copy((sq.width() - size) // 2, (sq.height() - size) // 2, size, size)
    card = QImage(size, size, QImage.Format.Format_ARGB32_Premultiplied)
    card.fill(Qt.GlobalColor.transparent)
    p = QPainter(card)
    p.setRenderHint(QPainter.RenderHint.Antialiasing)
    clip = QPainterPath()
    r = size * radius_frac
    clip.addRoundedRect(0, 0, size, size, r, r)
    p.setClipPath(clip)
    p.drawImage(0, 0, sq)
    p.end()
    card.save(str(out))


def art_card(url):
    """A file URL of the cover as a rounded square, or '' if it can't load."""
    path = QUrl(url).toLocalFile() if url else ""
    img = QImage(path) if path else QImage()
    if img.isNull():
        return ""
    ART_CACHE.mkdir(exist_ok=True)
    out = ART_CACHE / (hashlib.sha1(path.encode()).hexdigest() + "-card.png")
    if not out.exists():
        _rounded_card(img, out)
    return QUrl.fromLocalFile(str(out)).toString()


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
    _artReady = pyqtSignal(str, str, str)   # source, art url, rounded card url

    maxVolumeChanged = pyqtSignal()
    recentsChanged = pyqtSignal()

    def __init__(self, local, phone, spotify, volume=40, max_volume=100, parent=None):
        super().__init__(parent)
        self._sources = {"local": local, "phone": phone, "spotify": spotify}
        self._source = "local"
        self._system_volume = bool(shutil.which("wpctl"))
        # The output level goes out through one thread, in order, latest
        # wins (a fade sends a quick run of them).
        self._level_lock = threading.Lock()
        self._pending_level = None
        self._level_wake = threading.Event()
        if self._system_volume:
            threading.Thread(target=self._level_writer, name="volume", daemon=True).start()
        self._fade = 1.0                 # 0-1 on top of the volume
        self._fade_target = 1.0
        self._fade_step = 0.0
        self._after_fade = None
        self._pausing = self._resuming = False
        self._fade_timer = QTimer(self, interval=FADE_STEP_MS, timeout=self._fade_tick)
        self._give_up = QTimer(self, singleShot=True, interval=FADE_GIVE_UP_MS,
                               timeout=self._give_up_waiting)
        self._volume = max(0, min(100, int(volume)))
        self._max = max(30, min(100, int(max_volume)))
        self._art = {}                  # source -> (art url, rounded card url)
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
        local.queueChanged.connect(self.queueChanged)       # an album started
        self._recent_art = {}             # Spotify cover URL -> saved copy
        spotify.recentsChanged.connect(self._save_recent_art)
        spotify.recentsChanged.connect(self.recentsChanged)
        self.playingChanged.connect(self._fade_on_playing_changed)
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
            self._apply_art(name, url, art_card(url))
            return
        if not url:
            self._apply_art(name, "", "")
            return

        def work():
            try:
                local = cached_art(url)
                card = art_card(local)
            except Exception:          # offline, bad URL: no cover for now
                local, card = url, ""
            try:
                self._artReady.emit(name, local, card)
            except RuntimeError:       # app shutting down; nothing to update
                pass
        threading.Thread(target=work, daemon=True).start()

    def _apply_art(self, name, url, card):
        self._art[name] = (url, card)
        if name == self._source:
            self.trackChanged.emit()

    def _art_field(self, i):
        return self._art.get(self._source, ("", ""))[i]

    # ---- volume -----------------------------------------------------------
    def _apply_volume(self):
        ceiling = self._max / 100
        if self._system_volume:
            level = ceiling if self._remote_volume else self._volume / 100 * ceiling
            with self._level_lock:
                self._pending_level = level * self._fade
            self._level_wake.set()
        else:
            self._sources["local"].setVolume(round(self._volume * ceiling))

    def _level_writer(self):
        while True:
            self._level_wake.wait()
            self._level_wake.clear()
            with self._level_lock:
                level, self._pending_level = self._pending_level, None
            if level is not None:
                try:
                    subprocess.run(["wpctl", "set-volume", "@DEFAULT_AUDIO_SINK@", f"{level:.3f}"],
                                   capture_output=True, timeout=3)
                except Exception:        # keep the thread alive: it's the only one
                    pass

    # ---- soft pause and play ----------------------------------------------
    def _fade_to(self, target, ms, then=None):
        self._fade_target = target
        self._fade_step = (target - self._fade) / max(1, ms / FADE_STEP_MS)
        self._after_fade = then
        if self._fade == target:
            self._fade_timer.stop()
            self._fade_done()
        else:
            self._fade_timer.start()

    def _fade_tick(self):
        f = self._fade + self._fade_step
        done = f >= self._fade_target if self._fade_step > 0 else f <= self._fade_target
        self._fade = self._fade_target if done else f
        self._apply_volume()
        if done:
            self._fade_timer.stop()
            self._fade_done()

    def _fade_done(self):
        then, self._after_fade = self._after_fade, None
        if then:
            then()

    def _pause_now(self):
        self._pausing = True
        self._give_up.start()
        self._active.togglePlay()

    def _fade_on_playing_changed(self):
        if self._resuming and self.playing:
            self._resuming = False
            self._give_up.stop()
            QTimer.singleShot(START_WAIT_MS, self._fade_in_if_playing)
        elif self._pausing and not self.playing:
            self._pausing = False
            self._give_up.stop()
            QTimer.singleShot(SETTLE_MS, self._volume_back_if_paused)

    def _fade_in_if_playing(self):
        if self.playing and not self._pausing:
            self._fade_to(1.0, FADE_IN_MS)

    def _volume_back_if_paused(self):
        if not (self._resuming or self._pausing or self._fade_timer.isActive()):
            self._fade, self._fade_target = 1.0, 1.0
            self._apply_volume()

    def _give_up_waiting(self):
        if self._resuming:
            self._resuming = False
            self._fade_to(1.0, FADE_IN_MS)
        else:
            self._pausing = False
            self._fade, self._fade_target = 1.0, 1.0
            self._apply_volume()

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
    def artCard(self):
        """The cover as a rounded square, ready for the album-art frame, or ''."""
        return self._art_field(1)

    @pyqtProperty(int, notify=trackChanged)
    def duration(self):
        return self._active.duration

    @pyqtProperty(int, notify=trackChanged)
    def index(self):
        return self._sources["local"].index if self._source == "local" else -1

    @pyqtProperty("QVariantList", notify=queueChanged)
    def queue(self):
        """The Pi's own songs playing through: an album, or all of them (tap to play)."""
        return self._sources["local"].queue

    @pyqtProperty("QVariantList", constant=True)
    def albums(self):
        """Albums of the Pi's own songs: [{title, artist, art, count, duration}]."""
        return self._sources["local"].albums

    @pyqtProperty(int, notify=queueChanged)
    def album(self):
        """The Pi album playing (an index into `albums`), or -1."""
        return self._sources["local"].album if self._source == "local" else -1

    @pyqtSlot(int, result="QVariantList")
    def albumTracks(self, album):
        return self._sources["local"].albumTracks(album)

    @pyqtProperty("QVariantList", notify=recentsChanged)
    def spotifyRecents(self):
        """Albums and playlists recently played on the Pi through Spotify,
        newest first, with covers saved locally once downloaded."""
        out = []
        for r in self._sources["spotify"].recents:
            r["art"] = self._recent_art.get(r["art"]) or r["art"]
            out.append(r)
        return out

    def _save_recent_art(self):
        todo = [r["art"] for r in self._sources["spotify"].recents
                if r["art"].startswith("http") and r["art"] not in self._recent_art]
        if not todo:
            return
        for url in todo:
            self._recent_art[url] = ""            # being fetched

        def work():
            for url in todo:
                try:
                    self._recent_art[url] = cached_art(url)
                except Exception:                 # offline: try again next time
                    self._recent_art.pop(url, None)
            safe_emit(self, "recentsChanged")
        threading.Thread(target=work, daemon=True).start()

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

    @pyqtProperty(int, notify=maxVolumeChanged)
    def maxVolume(self):
        """Ceiling on the Pi's output, 30-100 (% of full)."""
        return self._max

    @pyqtSlot(int)
    def setMaxVolume(self, value):
        value = max(30, min(100, int(value)))
        if value != self._max:
            self._max = value
            self._apply_volume()
            self.maxVolumeChanged.emit()

    @property
    def local_volume(self):
        """The Pi's own volume (what's saved between runs); phone and Spotify keep their own."""
        return self._volume

    # ---- controls ---------------------------------------------------------
    @pyqtSlot()
    def togglePlay(self):
        if not self._system_volume:       # no output volume to fade (a Mac)
            self._active.togglePlay()
        elif self._active.playing:
            self._resuming = False
            self._fade_to(0.0, FADE_OUT_MS, then=self._pause_now)
        else:
            # Silent until it's really playing, then fade in.
            self._pausing = False
            self._fade_timer.stop()
            self._fade = self._fade_target = 0.0
            self._apply_volume()
            self._resuming = True
            self._give_up.start()
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

    @pyqtSlot(int, int)
    def playAlbum(self, album, start=0):
        self._pause_others(keep="local")
        self._set_source("local")
        self._sources["local"].playAlbum(album, start)

    @pyqtSlot()
    def playAll(self):
        self._pause_others(keep="local")
        self._set_source("local")
        self._sources["local"].playAll()

    @pyqtSlot(str)
    def playSpotify(self, uri):
        """Play an album or playlist from `spotifyRecents` through Spotify;
        the hub switches to it once it starts."""
        self._sources["spotify"].playUri(uri)

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
