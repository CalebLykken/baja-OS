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

Which source was on, and where local music was up to, are saved in
settings (every few seconds while it plays, and whenever that changes), so
a restart picks up the same album and song, near the same place. Shuffle
and repeat for the Pi's own music are saved with it (Spotify keeps its own,
and the phone has no way to set them from here). Local
music plays again only if it was what was playing; after Spotify or the
phone it waits, paused, for them to come back.

Spotify comes back by itself: while it plays, what it's playing is saved, and
once Spotify is signed in after a restart or a lost connection it carries on,
unless something else is already playing. Pausing it, playing something else
or moving it to another device forgets that, and Settings can turn it off.
"""

import contextlib
import json
import os
import shutil
import subprocess
import threading
import time
import urllib.request

from PyQt6.QtCore import QObject, QTimer, QUrl, Qt, pyqtProperty, pyqtSignal, pyqtSlot
from PyQt6.QtGui import QImage, QPainter, QPainterPath

from backend import artcache, retry, safe_emit
from backend.prefs import as_bool

PHONE_RECONNECT_GRACE_S = 10
# Soft pause and play, like a car stereo: music cut off mid-wave clicks.
# Pause fades the output out first; play starts silent and fades in once
# the source says it's playing (its sound lags a little behind that).
FADE_OUT_MS = 180
FADE_IN_MS = 400
FADE_STEP_MS = 30
START_WAIT_MS = 120
SETTLE_MS = 250            # after pausing, before the volume goes back up
MUTE_MS = 150              # the knob's mute ramps like this, so it doesn't click
FADE_GIVE_UP_MS = 3000     # a source that never answers doesn't leave it silent
# Local music leaves the Pi's output low and the phone and Spotify want it at
# 100%, so a switch goes through silence: whatever the old source still has
# in the pipe, or the new one starts with, must not come out at the new level.
SWITCH_SETTLE_MS = 600
SAVE_EVERY_MS = 5000       # while local music plays, its place is saved this often
RESUME_SETTING = "spotifyResume"
RESUME_URI_SETTING = "spotifyResumeUri"


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
    if not card.save(str(out)):
        raise OSError(f"couldn't save the card to {out}")     # not a blank file cached for ever


def art_card(url):
    """A file URL of the cover as a rounded square, or '' if it can't load."""
    path = QUrl(url).toLocalFile() if url else ""
    img = QImage(path) if path else QImage()
    in_cache = bool(path) and os.path.dirname(path) == str(artcache.cache_dir())
    if img.isNull():
        if in_cache:        # a corrupt download: drop it so the next play fetches it again
            with contextlib.suppress(OSError):
                os.unlink(path)
        return ""
    if in_cache:
        key = os.path.basename(path)       # already a content/URL hash; its mtime changes on every use
    else:
        try:
            st = os.stat(path)
            key = f"{path}|{st.st_mtime_ns}|{st.st_size}"      # a cover.jpg that changed gets a new card
        except OSError:
            key = path
    out, hit = artcache.lookup(artcache.digest(key) + "-card.png")
    if not hit:
        with artcache.writing(out) as tmp:
            _rounded_card(img, tmp)
    return QUrl.fromLocalFile(str(out)).toString()


def cached_art(url):
    """A local file URL for `url`: file URLs as-is, http(s) downloaded once."""
    if not url or not url.startswith("http"):
        return url
    out, hit = artcache.lookup(artcache.digest(url) + ".img")
    if not hit:
        def get():
            with urllib.request.urlopen(url, timeout=10) as r:
                return r.read()
        data = retry.call(get)        # back-off on timeouts, 429 and 5xx; callers are worker threads
        with artcache.writing(out) as tmp:
            tmp.write_bytes(data)
    return QUrl.fromLocalFile(str(out)).toString()


def read_state(text):
    """What the last run saved ({source, playing, local}), or None."""
    try:
        state = json.loads(text) if text else None
    except ValueError:
        return None
    return state if isinstance(state, dict) else None


def plays_on_start(state):
    """Local music starts playing only if it was the source and was playing."""
    return bool(state) and state.get("source") == "local" and state.get("playing") is True


class MediaHub(QObject):
    trackChanged = pyqtSignal()
    positionChanged = pyqtSignal()
    playingChanged = pyqtSignal()
    volumeChanged = pyqtSignal()
    sourceChanged = pyqtSignal()
    otherSourcesChanged = pyqtSignal()   # a phone player came or went, or the active source moved
    queueChanged = pyqtSignal()
    upNextChanged = pyqtSignal()      # what plays after this song (local order, Spotify queue)
    _artReady = pyqtSignal(str, str, str, str)   # source, its art url, local copy, rounded card

    maxVolumeChanged = pyqtSignal()
    modesChanged = pyqtSignal()
    mutedChanged = pyqtSignal()
    recentsChanged = pyqtSignal()
    resumeChanged = pyqtSignal()
    albumsChanged = pyqtSignal()        # the Pi's music was rescanned
    scanningChanged = pyqtSignal()

    def __init__(self, local, phone, spotify, volume=40, max_volume=100, settings=None, parent=None):
        super().__init__(parent)
        self._sources = {"local": local, "phone": phone, "spotify": spotify}
        self.sourceChanged.connect(self.otherSourcesChanged)
        self._source = "local"
        self._settings = settings
        saved = read_state(str(settings.get("music", ""))) if settings else None
        self._was_playing = plays_on_start(saved)      # kept while local music has no songs
        if saved is not None:
            modes = saved.get("modes")
            if isinstance(modes, dict):
                local.set_modes(modes.get("shuffle") is True, modes.get("repeat"))
            local.restore(saved.get("local"), play=self._was_playing)
        self._save_timer = QTimer(self, interval=SAVE_EVERY_MS, timeout=self._save)
        self._resume_on = as_bool(settings.get(RESUME_SETTING), True) if settings else False
        self._resume_uri = str(settings.get(RESUME_URI_SETTING, "")) if settings else ""
        self._resume_tried = False
        self._spotify_was_playing = False
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
        self._muted = False              # the knob's long press: silent, but still playing
        self._mute_gain = 1.0            # 0-1 on top of the volume, ramping to 0 or 1
        self._mute_timer = QTimer(self, interval=FADE_STEP_MS, timeout=self._mute_tick)
        self._fade_timer = QTimer(self, interval=FADE_STEP_MS, timeout=self._fade_tick)
        self._give_up = QTimer(self, singleShot=True, interval=FADE_GIVE_UP_MS,
                               timeout=self._give_up_waiting)
        self._switching = QTimer(self, singleShot=True, interval=SWITCH_SETTLE_MS,
                                 timeout=self._fade_in_after_switch)
        self._volume = max(0, min(100, int(volume)))
        self._max = max(30, min(100, int(max_volume)))
        self._art = {}                  # source -> (art url, rounded card url)
        self._phone_connected_at = 0.0
        self._phone_name = phone.deviceName
        self._phones_connected = self._connected_phones()

        for name, src in self._sources.items():
            for sig in ("trackChanged", "positionChanged", "playingChanged"):
                getattr(src, sig).connect(lambda n=name, s=sig: self._forward(n, s))
            src.playingChanged.connect(lambda n=name: self._source_playing_changed(n))
            src.trackChanged.connect(lambda n=name: self._update_art(n))
        phone.trackChanged.connect(self._phone_player_changed)
        phone.changed.connect(self._phone_connection_changed)
        for sig in (phone.changed, phone.trackChanged, local.queueChanged):
            sig.connect(self.otherSourcesChanged)      # the list of other sources may have changed
        phone.volumeChanged.connect(lambda: self._remote_volume_changed("phone"))
        spotify.volumeChanged.connect(lambda: self._remote_volume_changed("spotify"))
        spotify.changed.connect(self._spotify_changed)
        spotify.playingChanged.connect(self._note_spotify)
        spotify.trackChanged.connect(self._note_spotify)
        spotify.modesChanged.connect(self.modesChanged)
        spotify.queueChanged.connect(self.queueChanged)
        spotify.queueChanged.connect(self.upNextChanged)
        if hasattr(local, "upNextChanged"):
            local.upNextChanged.connect(self.upNextChanged)
        local.queueChanged.connect(self.queueChanged)       # an album started
        local.modesChanged.connect(self.modesChanged)
        if hasattr(local, "libraryChanged"):         # not the demo player
            local.libraryChanged.connect(self.albumsChanged)
            local.scanningChanged.connect(self.scanningChanged)
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
        if self._settings:
            # Only from here: before it starts, local music doesn't know its place.
            for sig in (self.sourceChanged, self.playingChanged, self.trackChanged,
                        self.modesChanged):
                sig.connect(self._save)
            self._save_timer.start()

    def _save(self):
        """Save which source is on, whether it's playing, and where local
        music is up to; unchanged, nothing is written. With no songs to
        play, "playing" stays as it was saved, so when they're back the next
        run picks up as it was."""
        playing = bool(self.playing)
        if self._no_songs():
            playing = self._was_playing
        self._settings.set("music", json.dumps({
            "source": self._source, "playing": playing,
            "local": self._sources["local"].state(),
            "modes": {"shuffle": self._sources["local"].shuffle,
                      "repeat": self._sources["local"].repeat}}))

    def _no_songs(self):
        """True when local music is the source and has nothing to play."""
        return self._source == "local" and self._sources["local"].index < 0

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
            if source != "local" and hasattr(self._sources["local"], "cancel_autoplay"):
                self._sources["local"].cancel_autoplay()    # songs found later mustn't take over
            self._apply_volume()
            for sig in ("sourceChanged", "volumeChanged", "trackChanged",
                        "positionChanged", "playingChanged", "queueChanged", "modesChanged", "upNextChanged"):
                getattr(self, sig).emit()

    def _pause_others(self, keep):
        if keep != "spotify":
            self._remember_spotify("")
            if hasattr(self._sources["spotify"], "cancel_resume"):
                self._sources["spotify"].cancel_resume()
        if keep != self._source:
            self._hush_for_switch()
        for name, src in self._sources.items():
            if name != keep and src.playing:
                if hasattr(src, "pause"):
                    src.pause()
                else:
                    src.togglePlay()

    def _source_playing_changed(self, name):
        if not self._sources[name].playing:
            return
        if name != "spotify" and hasattr(self._sources["spotify"], "cancel_resume"):
            self._sources["spotify"].cancel_resume()    # even when it's already the active source
        if name == self._source:
            return
        if (name == "phone" and self._source == "spotify"
                and time.monotonic() - self._phone_connected_at < PHONE_RECONNECT_GRACE_S):
            self._sources["phone"].pause()    # stays quiet: Spotify keeps the speakers
            return       # an iPhone auto-resuming after reconnecting
        self._pause_others(keep=name)
        self._set_source(name)

    def _phone_connection_changed(self):
        name = self._sources["phone"].deviceName
        connected = self._connected_phones()
        # Grace starts for the first phone and for a second one joining the first.
        if (name and not self._phone_name) or (connected - self._phones_connected):
            self._phone_connected_at = time.monotonic()
        changed = name != self._phone_name
        self._phone_name = name
        self._phones_connected = connected
        if changed and self._source == "phone":
            self.sourceChanged.emit()    # another phone took over: the badge shows its name

    def _connected_phones(self):
        paired = getattr(self._sources["phone"], "paired", None) or []
        return {d.get("address") or d.get("path") for d in paired if d.get("connected")}

    def _phone_player_changed(self):
        if not self._sources["phone"].hasPlayer and self._source == "phone":
            self._set_source("local")

    def _spotify_changed(self):
        sp = self._sources["spotify"]
        signed_in = sp.available and sp.linked
        if self._source == "spotify" and not (sp.available and sp.active):
            if signed_in:
                self._remember_spotify("")    # moved to another device
            self._set_source("local")    # moved to another device, or Soloist stopped
        if signed_in:
            self._resume_spotify()
        else:
            self._resume_tried = False   # try again when it's back

    # ---- Spotify carrying on by itself --------------------------------------
    def _remember_spotify(self, uri):
        if uri != self._resume_uri and self._settings:
            self._settings.set(RESUME_URI_SETTING, uri)
        self._resume_uri = uri

    def _note_spotify(self):
        sp = self._sources["spotify"]
        if sp.playing:
            self._remember_spotify(sp.resumeUri or self._resume_uri)
        elif self._spotify_was_playing and sp.available and sp.linked and sp.active:
            self._remember_spotify("")        # paused here, not lost
        self._spotify_was_playing = sp.playing

    def _resume_spotify(self):
        if self._resume_tried or not self._resume_on or not self._resume_uri:
            return
        self._resume_tried = True
        if not any(src.playing for src in self._sources.values()):
            self._sources["spotify"].resume(self._resume_uri)

    def _remote_volume_changed(self, name):
        if name == self._source:
            # The Pi's output goes to 100% once the volume is known, and back
            # to the local level when the phone stops sharing it.
            self._apply_volume()
            self.volumeChanged.emit()

    def _forward(self, origin, signal):
        if origin == self._source:
            getattr(self, signal).emit()

    # ---- album art --------------------------------------------------------
    def _update_art(self, name):
        """Fetch (Spotify) and round off the cover on a worker thread: decoding
        a big cover on the main thread stalls the screen just as a song starts."""
        url = self._sources[name].art
        if not url:
            self._apply_art(name, "", "", "")
            return

        def work():
            try:
                local = cached_art(url)
                card = art_card(local)
            except Exception:          # offline, bad URL: no cover for now
                local, card = url, ""
            safe_emit(self, "_artReady", name, url, local, card)
        threading.Thread(target=work, daemon=True).start()

    def _apply_art(self, name, source_url, url, card):
        if source_url != self._sources[name].art:
            return                     # the song moved on while this was made
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
                self._pending_level = level * self._fade * self._mute_gain
            self._level_wake.set()
        else:
            self._sources["local"].setVolume(round(self._volume * ceiling * self._mute_gain))

    def _set_muted(self, on):
        if on == self._muted:
            return
        self._muted = on
        self._mute_timer.start()
        self.mutedChanged.emit()

    def _mute_tick(self):
        step = FADE_STEP_MS / MUTE_MS
        if self._muted:
            self._mute_gain = max(0.0, self._mute_gain - step)
        else:
            self._mute_gain = min(1.0, self._mute_gain + step)
        self._apply_volume()
        if self._mute_gain == (0.0 if self._muted else 1.0):
            self._mute_timer.stop()

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
        if self.playing and not self._pausing and not self._switching.isActive():
            self._fade_to(1.0, FADE_IN_MS)

    def _hush_for_switch(self):
        self._fade_timer.stop()
        self._after_fade = None
        self._fade = self._fade_target = 0.0
        self._apply_volume()
        self._switching.start()

    def _fade_in_after_switch(self):
        self._fade_to(1.0, FADE_IN_MS)

    def _volume_back_if_paused(self):
        if not (self._resuming or self._pausing or self._fade_timer.isActive()
                or self._switching.isActive()):
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

    @pyqtProperty("QVariantList", notify=otherSourcesChanged)
    def otherSources(self):
        """The sources the driver could move to from here, not counting the
        one that's on: [{name, label}] for the phone (when it has a player)
        and the Pi's own songs (when it has some)."""
        phone, local = self._sources["phone"], self._sources["local"]
        out = []
        if self._source != "phone" and phone.hasPlayer:
            out.append({"name": "phone", "label": phone.deviceName or "Phone"})
        if self._source != "local" and local.index >= 0:
            out.append({"name": "local", "label": "On this Pi"})
        return out

    @pyqtSlot(str)
    def useSource(self, name):
        """Move to the phone or back to the Pi's songs, and play there."""
        if name == self._source or name not in [o["name"] for o in self.otherSources]:
            return
        self._pause_others(keep=name)
        self._set_source(name)
        src = self._sources[name]
        if name == "phone":
            src.play()
        elif not src.playing:
            src.togglePlay()

    @pyqtProperty(str, notify=trackChanged)
    def title(self):
        return self._active.title

    @pyqtProperty(str, notify=trackChanged)
    def artist(self):
        return self._active.artist

    @pyqtProperty(str, notify=trackChanged)
    def albumTitle(self):
        """The album of the Pi's song playing; '' for the phone and Spotify,
        which don't send it here."""
        return self._sources["local"].albumTitle if self._source == "local" else ""

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

    @pyqtProperty("QVariantList", notify=albumsChanged)
    def albums(self):
        """Albums of the Pi's own songs: [{title, artist, art, count, duration}]."""
        return self._sources["local"].albums

    @pyqtProperty("QVariantList", notify=albumsChanged)
    def songs(self):
        """Every song of the Pi's own music by title: [{title, artist, index}]."""
        return getattr(self._sources["local"], "songs", [])

    @pyqtProperty(bool, notify=scanningChanged)
    def scanning(self):
        """The Pi's music folder is still being read for the first time."""
        return getattr(self._sources["local"], "scanning", False)

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

    @pyqtProperty("QVariantList", notify=upNextChanged)
    def upNext(self):
        """The songs that play next: the Pi's own in their true order (shuffle
        included, each with its queue `index` to tap), Spotify's queue
        (display only), nothing for a phone (it picks)."""
        if self._source == "local":
            return getattr(self._sources["local"], "upNext", [])
        return self._sources["spotify"].upNext if self._source == "spotify" else []

    @pyqtProperty(bool, notify=sourceChanged)
    def canSeek(self):
        """The bar can be dragged: not on a phone, which has no seek."""
        return self._active.canSeek

    @pyqtSlot(int)
    def seek(self, seconds):
        if self._active.canSeek:
            self._active.seek(seconds)

    @property
    def _modes(self):
        """Whose shuffle and repeat the keys show: Spotify's or the Pi's."""
        return self._sources["spotify" if self._source == "spotify" else "local"]

    @pyqtProperty(bool, notify=modesChanged)
    def hasModes(self):
        """Shuffle and repeat can be set: the Pi's own music or Spotify is the source."""
        return self._source != "phone" and self._modes.hasModes

    @pyqtProperty(bool, notify=modesChanged)
    def shuffle(self):
        return self._modes.shuffle

    @pyqtProperty(str, notify=modesChanged)
    def repeat(self):
        """'all', 'one' or 'off'."""
        return self._modes.repeat

    @pyqtSlot()
    def toggleShuffle(self):
        if self.hasModes:
            self._modes.toggleShuffle()

    @pyqtSlot()
    def cycleRepeat(self):
        if self.hasModes:
            self._modes.cycleRepeat()

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

    @pyqtProperty(bool, notify=mutedChanged)
    def muted(self):
        """The knob's long press: silent, but still playing. Any volume change ends it."""
        return self._muted

    @pyqtSlot()
    def toggleMute(self):
        self._set_muted(not self._muted)

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
        if self._no_songs():
            return                        # nothing to fade: the knob must not mute the output
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

    @pyqtSlot(int)
    def playSong(self, index):
        self._pause_others(keep="local")
        self._set_source("local")
        self._sources["local"].playSong(index)

    @pyqtSlot()
    def playAll(self):
        self._pause_others(keep="local")
        self._set_source("local")
        self._sources["local"].playAll()

    @pyqtSlot()
    def shuffleAll(self):
        self._pause_others(keep="local")
        self._set_source("local")
        local = self._sources["local"]
        if hasattr(local, "shuffleAll"):
            local.shuffleAll()
        else:
            local.playAll()             # the demo player has no modes

    @pyqtSlot(str)
    def playSpotify(self, uri):
        """Play a song, album or playlist through Spotify; the hub switches
        to it once it starts."""
        self._sources["spotify"].playUri(uri)

    @pyqtSlot("QVariantList")
    def playSpotifyTracks(self, uris):
        """Play Spotify songs in order: the first now, the rest queued."""
        self._sources["spotify"].playTracks(uris)

    @pyqtSlot(str)
    def queueSpotify(self, uri):
        """Play a Spotify song after this one."""
        self._sources["spotify"].addToQueue(uri)

    @pyqtProperty(bool, notify=resumeChanged)
    def spotifyResume(self):
        """Spotify carries on by itself after a restart or a lost connection."""
        return self._resume_on

    @pyqtSlot(bool)
    def setSpotifyResume(self, on):
        if on != self._resume_on:
            self._resume_on = on
            if self._settings:
                self._settings.set(RESUME_SETTING, "true" if on else "false")
            self.resumeChanged.emit()

    @pyqtSlot(int)
    def setVolume(self, value):
        value = max(0, min(100, int(value)))
        self._set_muted(False)
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
