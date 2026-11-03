"""Spotify playback on the Pi through Spotify Soloist (Spotify Connect).

Soloist is Spotify's official headless Connect player. It plays the audio
itself through PipeWire; this class talks to its local WebSocket API
(soloist --ws 127.0.0.1:PORT, see deploy/spotify/) to show what's playing
and send play/pause/skip/seek/volume. Reference:
https://developer.spotify.com/documentation/soloist/reference/websocket-api

If Soloist isn't installed or running, `available` stays False, the socket
keeps retrying quietly, and the rest of the dashboard carries on.

Soloist can't list your Spotify history or library, so `recents` is kept
here: the albums and playlists that have played on the Pi (from the
playback context it reports), newest first, for one-tap replay. Searching
is the Spotify Web API's job: backend/spotifysearch.py.

Soloist restores its saved sign-in once, at startup, and doesn't try again,
so if the connection drops or moves (a dead zone, home Wi-Fi to the hotspot)
it can sit signed out while the phone hangs on "Connecting to Baja". `main.py`
passes the network's state to `set_network`, and a slow check restarts Soloist
when it's stuck like that, never over playing music, and only on a Pi that
has paired before: a restart mid-pairing would lose it.
"""

import json
import subprocess
import threading
import time
from pathlib import Path

from PyQt6.QtCore import QObject, QTimer, QUrl, pyqtProperty, pyqtSignal, pyqtSlot

try:
    from PyQt6.QtWebSockets import QWebSocket
except ImportError:          # python3-pyqt6.qtwebsockets not installed
    QWebSocket = None

DEFAULT_URL = "ws://127.0.0.1:47240"
RETRY_MS = 3000
RECENTS_MAX = 12
ACTIVATE_WAIT_MS = 2000      # play anyway if Soloist hasn't said it's the active device by then
RESUME_WAIT_MS = 4000        # Spotify had nothing to carry on with: play the saved album instead
CHECK_EVERY_MS = 5000
SETTLE_S = 20                # a just-started Soloist gets this long to sign in
REVIVE_MIN_S = 60            # between restarts, doubling up to the max while they don't help
REVIVE_MAX_S = 600
SERVICE = "baja-soloist.service"
SOLOIST_BIN = Path("~/.local/opt/soloist/soloist").expanduser()    # deploy/spotify/
SOLOIST_ENV = Path("~/.config/baja-os/soloist.env").expanduser()
PAIRED_SETTING = "spotifyPaired"
REPEAT_WORDS = {"off": "off", "context": "all", "track": "one"}    # Soloist's, the dashboard's
KIND_WORDS = {"playlist": "Playlist", "artist": "Artist", "show": "Podcast",
              "collection": "Liked Songs", "station": "Radio"}
NUMBER = (int, float)


def _get(obj, *keys, want=dict):
    """obj[key1][key2]... if it's a `want` (a type, or a tuple of them),
    else an empty one. A key that's missing or null, or a step that isn't
    an object, reads as empty: Soloist sends null for parts it doesn't
    have (a cover, an album), and its API can change under us."""
    for key in keys:
        obj = obj.get(key) if isinstance(obj, dict) else None
    if isinstance(obj, want):
        return obj
    return want[0]() if isinstance(want, tuple) else want()


def _name(entity):
    return _get(entity, "decorations", "identity", "name", want=str)


def _cover(entity, prefer=("large", "xlarge", "default", "small")):
    covers = _get(entity, "decorations", "visual_identity", "cover", want=list)
    urls = ((_get(c, "size", want=str), _get(c, "url", want=str)) for c in covers)
    by_size = {size: url for size, url in urls if url}
    return next((by_size[s] for s in prefer if s in by_size), "")


def _artists(entity):
    # Each creator is wrapped: {"entity": {..., "decorations": {"identity": ...}}}
    creators = _get(entity, "decorations", "creators", want=list)
    return ", ".join(n for n in (_name(_get(c, "entity") or c) for c in creators) if n)


def _duration_ms(entity):
    return int(_get(entity, "decorations", "playback", "duration_ms", want=NUMBER))


def _parent(entity):
    return _get(entity, "decorations", "parent", "entity")


class SpotifyPlayer(QObject):
    changed = pyqtSignal()          # connection / login / active device
    trackChanged = pyqtSignal()
    positionChanged = pyqtSignal()
    playingChanged = pyqtSignal()
    volumeChanged = pyqtSignal()
    queueChanged = pyqtSignal()
    recentsChanged = pyqtSignal()
    modesChanged = pyqtSignal()

    def __init__(self, url=DEFAULT_URL, settings=None, parent=None):
        super().__init__(parent)
        self._url = url
        self._settings = settings
        self._connected = False
        self._logged_in = False
        self._active = False
        self._device = ""
        self._item = {}
        self._status = "idle"
        self._error = ""      # short message after a Soloist error, until playback moves on
        self._pos = (0, 0.0, 0.0)       # position_ms, at (local monotonic s), speed
        self._volume = 0
        self._up_next = []
        self._recents = []          # [{uri, kind, title, subtitle, art}], newest first
        self._context_uri = ""      # the album or playlist playing
        self._shuffle = False
        self._repeat = "off"        # Soloist's word for it: off, context or track
        self._pending = None        # what to play once this Pi is the active device
        self._fallback = ""         # what to play if resuming finds nothing to carry on with
        self._then = []             # songs to queue once the next play has gone
        self._online = None         # None until the network's first check
        self._address = ""
        self._moved_at = 0.0        # when the connection last came back or changed
        self._connected_at = 0.0    # when the socket to Soloist last opened
        self._paired = str(settings.get(PAIRED_SETTING, "false")) == "true" if settings else False
        self._next_revive = 0.0
        self._revive_gap = REVIVE_MIN_S

        self._ws = QWebSocket() if QWebSocket else None
        self._retry = QTimer(self)
        self._retry.setSingleShot(True)
        self._retry.timeout.connect(self._open)
        self._tick = QTimer(self)
        self._tick.setInterval(1000)
        self._tick.timeout.connect(lambda: self.playing and self.positionChanged.emit())
        self._pending_timer = QTimer(self, singleShot=True, interval=ACTIVATE_WAIT_MS,
                                     timeout=self._send_pending)
        self._fallback_timer = QTimer(self, singleShot=True, interval=RESUME_WAIT_MS,
                                      timeout=self._play_fallback)
        self._check_timer = QTimer(self, interval=CHECK_EVERY_MS, timeout=self._check_session)
        if self._ws:
            self._ws.connected.connect(self._on_connected)
            self._ws.disconnected.connect(self._on_disconnected)
            self._ws.textMessageReceived.connect(self._on_message)

    def start(self):
        if self._ws:
            self._open()
            self._tick.start()
            self._check_timer.start()

    # ---- socket -----------------------------------------------------------
    def _open(self):
        self._ws.open(QUrl(self._url))

    def _on_connected(self):
        self._connected = True
        self._connected_at = time.monotonic()
        self._send({"type": "command", "command": "get_auth_state"})
        self.changed.emit()

    def _on_disconnected(self):
        was = self._connected
        self._connected = self._logged_in = self._active = False
        self._status = "idle"
        self._error = ""
        self._pending = None
        self._pending_timer.stop()
        if was:
            self.changed.emit()
            self.playingChanged.emit()
        self._retry.start(RETRY_MS)

    def _send(self, msg):
        if self._ws and self._connected:
            self._ws.sendTextMessage(json.dumps(msg))

    def _command(self, name, **fields):
        self._send({"type": "command", "command": name, **fields})

    # ---- events -----------------------------------------------------------
    def _on_message(self, text):
        try:
            ev = json.loads(text)
        except ValueError:
            return
        kind = _get(ev, "type", want=str)
        try:
            self._handle(ev, kind)
        except Exception as e:      # drop the one odd event; it mustn't stop the dashboard
            print(f"Spotify: ignored a {kind} event that didn't parse ({e!r})")

    def _handle(self, ev, kind):
        if kind == "auth_state":
            self._logged_in = bool(ev.get("logged_in"))
            self._device = _get(ev, "device_name", want=str) or self._device
            if self._logged_in:
                self._signed_in()
            self.changed.emit()
            self._set_active(bool(ev.get("is_active")))
            if self._logged_in:
                self._command("get_state")       # Soloist only volunteers auth_state on connect
                self._command("get_queue", limit=10)
        elif kind == "playback_state":
            self._note_context(ev.get("context"))
            self._set_item(ev.get("item"))
            self._set_status(_get(ev, "status", want=str))
            self._set_position(_get(ev, "position"))
            self._set_volume(ev.get("volume"))
            self._set_active(ev.get("is_active"))
            self._set_options(ev.get("options"))
        elif kind == "track_changed":
            self._set_item(ev.get("item"))
        elif kind == "context_changed":
            self._note_context(ev.get("context"))
        elif kind == "playback_changed":
            self._set_status(_get(ev, "status", want=str))
        elif kind == "position_sync":
            self._set_position(_get(ev, "position"))
        elif kind == "volume_changed":
            self._set_volume(ev.get("volume"))
        elif kind == "options_changed":
            self._set_options(ev.get("options"))
        elif kind == "device_changed":
            self._device = _get(ev, "device_name", want=str) or self._device
            self._set_active(ev.get("is_active"))
        elif kind == "queue_changed":
            self._up_next = [{"title": _name(_get(e, "item")), "artist": _artists(_get(e, "item"))}
                             for e in _get(ev, "upcoming", want=list)][:10]
            self.queueChanged.emit()
        elif kind == "error":
            print(f"Spotify: {ev.get('message')}")
            signing_in = "authentication" in _get(ev, "message", want=str).lower()
            self._error = "Spotify is still connecting" if signing_in else "Spotify isn't answering right now"
            self.changed.emit()

    def _set_item(self, item):
        item = item if isinstance(item, dict) else {}
        if item != self._item:
            self._item = item
            self.trackChanged.emit()
            self._clear_error()
            self._command("get_queue", limit=10)
            if self._fill_subtitle():
                self.recentsChanged.emit()

    # ---- recently played here ---------------------------------------------
    def _note_context(self, ctx):
        """Put what's playing (an album or playlist) first in `recents`."""
        uri, name = _get(ctx, "uri", want=str), _name(ctx)
        self._context_uri = uri or self._context_uri
        if not uri or not name:
            return
        kind = _get(ctx, "entity_type", want=str) or (uri.split(":") + [""])[1]
        old = next((r for r in self._recents if r["uri"] == uri), None)
        entry = {"uri": uri, "kind": kind, "title": name,
                 "subtitle": old["subtitle"] if old else "",
                 "art": _cover(ctx) or (old["art"] if old else "")}
        if self._recents and self._recents[0] == entry:
            return
        self._recents = [entry] + [r for r in self._recents if r["uri"] != uri][:RECENTS_MAX - 1]
        self._fill_subtitle()
        self.recentsChanged.emit()

    def _fill_subtitle(self):
        """The newest entry's second line: the artist of an album (once one
        of its songs is playing), else what kind of thing it is."""
        if not self._recents or self._recents[0]["subtitle"]:
            return False
        first = self._recents[0]
        if first["kind"] != "album":
            first["subtitle"] = KIND_WORDS.get(first["kind"], first["kind"].title())
        elif _parent(self._item).get("uri") == first["uri"]:
            first["subtitle"] = _artists(self._item)
        return bool(first["subtitle"])

    def load_recents(self, recents):
        """Recently played, as saved last time (a list of dicts)."""
        keep = ("uri", "kind", "title", "subtitle", "art")
        self._recents = [{k: str(r.get(k, "")) for k in keep} for r in recents
                         if isinstance(r, dict) and r.get("uri")][:RECENTS_MAX]
        self.recentsChanged.emit()

    @pyqtProperty(str, notify=changed)
    def error(self):
        """A short message when Soloist reported an error (offline, rate limited), else ''."""
        return self._error

    def _clear_error(self):
        if self._error:
            self._error = ""
            self.changed.emit()

    def _set_status(self, status):
        if status and status != self._status:
            self._status = status
            self._clear_error()
            self.playingChanged.emit()

    def _set_position(self, pos):
        if not pos:
            return
        # The server's timestamp is the same machine's clock, so convert it
        # to an age and anchor to our monotonic clock for interpolation.
        age = max(0.0, time.time() - _get(pos, "timestamp_ms", want=NUMBER) / 1000)
        self._pos = (int(_get(pos, "position_ms", want=NUMBER)), time.monotonic() - age,
                     float(_get(pos, "speed", want=NUMBER)))
        self.positionChanged.emit()

    def _set_volume(self, volume):
        if isinstance(volume, NUMBER) and int(volume) != self._volume:
            self._volume = int(volume)
            self.volumeChanged.emit()

    def _set_active(self, active):
        if active is not None and bool(active) != self._active:
            self._active = bool(active)
            self.changed.emit()
            self.playingChanged.emit()     # `playing` needs this too, and "playing" can come first
            self.modesChanged.emit()
            if self._active:
                self._send_pending()

    def _set_options(self, options):
        if not isinstance(options, dict):
            return
        shuffle, repeat = _get(options, "shuffle", want=bool), _get(options, "repeat", want=str)
        new = (shuffle if "shuffle" in options else self._shuffle,
               repeat if repeat in REPEAT_WORDS else self._repeat)
        if new != (self._shuffle, self._repeat):
            self._shuffle, self._repeat = new
            self.modesChanged.emit()

    def _signed_in(self):
        self._clear_error()
        self._revive_gap = REVIVE_MIN_S
        if not self._paired:
            self._paired = True
            if self._settings:
                self._settings.set(PAIRED_SETTING, "true")

    # ---- staying signed in ------------------------------------------------
    def set_network(self, online, address):
        """Tell it about the connection (from backend/network.py)."""
        came_back = online and self._online is False
        moved = bool(self._address and address and address != self._address)
        if came_back or moved:
            self._moved_at = time.monotonic()
        self._address = address or self._address
        if online != self._online:
            self._online = online
            self.changed.emit()

    def _check_session(self):
        """Restart Soloist if it's signed out while online, or if the
        connection has moved under it since it started."""
        now = time.monotonic()
        up = now - self._connected_at
        moved = self._moved_at - self._connected_at > SETTLE_S
        stuck = not self._logged_in and up > SETTLE_S
        if (not (self._connected and self._online and self._paired) or not (moved or stuck)
                or (self._status == "playing" and self._active) or now < self._next_revive):
            return
        self._moved_at = 0.0
        self._next_revive = now + self._revive_gap
        self._revive_gap = min(REVIVE_MAX_S, self._revive_gap * 2)
        print("Spotify: restarting Soloist so it signs in on this connection", flush=True)
        threading.Thread(target=self._restart_soloist, daemon=True).start()

    @staticmethod
    def _restart_soloist():
        try:
            subprocess.run(["systemctl", "--user", "--no-block", "restart", SERVICE],
                           capture_output=True, timeout=10)
        except (OSError, subprocess.SubprocessError) as e:
            print(f"Spotify: couldn't restart Soloist ({e})", flush=True)

    # ---- properties -------------------------------------------------------
    @pyqtProperty(bool, notify=changed)
    def available(self):
        """Soloist is running and reachable."""
        return self._connected

    @pyqtProperty(bool, notify=changed)
    def linked(self):
        """A Spotify account is paired with the player."""
        return self._logged_in

    @pyqtProperty(str, notify=changed)
    def statusText(self):
        """Where Spotify is up to, in a few plain words."""
        name = self._device or "Baja"
        if not SOLOIST_BIN.exists():
            return "Not set up on this Pi"
        if not SOLOIST_ENV.exists():
            return "Needs its key: run deploy/spotify/set-spotify-key.sh on the Pi"
        if not self._connected:
            return ("Waiting for internet: it starts once the phone's hotspot connects"
                    if self._online is False else "Starting Spotify")
        if not self._logged_in:
            return ("Reconnecting to Spotify" if self._paired
                    else f"Pick {name} in the Spotify app, with the phone on the same Wi-Fi as the Pi")
        return f"Connected as {name}"

    @pyqtProperty(bool, notify=changed)
    def active(self):
        """This Pi is the active Spotify Connect device."""
        return self._active

    @pyqtProperty(str, notify=changed)
    def deviceName(self):
        return self._device

    @pyqtProperty(str, notify=trackChanged)
    def title(self):
        return _name(self._item)

    @pyqtProperty(str, notify=trackChanged)
    def artist(self):
        return _artists(self._item) or _name(_parent(self._item))

    @pyqtProperty(str, notify=trackChanged)
    def album(self):
        return _name(_parent(self._item))

    @pyqtProperty(str, notify=trackChanged)
    def art(self):
        """Cover art URL (https), from the track or its album."""
        return _cover(self._item) or _cover(_parent(self._item))

    @pyqtProperty(int, notify=trackChanged)
    def duration(self):
        return _duration_ms(self._item) // 1000

    @pyqtProperty(int, notify=positionChanged)
    def position(self):
        ms, at, speed = self._pos
        ms += int((time.monotonic() - at) * 1000 * speed)
        dur = _duration_ms(self._item)
        return (min(ms, dur) if dur else ms) // 1000

    @pyqtProperty(bool, notify=playingChanged)
    def playing(self):
        return self._status in ("playing", "buffering") and self._active

    @pyqtProperty(bool, notify=volumeChanged)
    def hasVolume(self):
        return self._connected and self._active

    @pyqtProperty(int, notify=volumeChanged)
    def volume(self):
        return self._volume

    @property
    def resumeUri(self):
        """The album or playlist playing, or the song if it's in neither."""
        return self._context_uri or _get(self._item, "uri", want=str)

    @pyqtProperty(bool, notify=modesChanged)
    def hasModes(self):
        """Shuffle and repeat can be set: this Pi is the active device."""
        return self._connected and self._active

    @pyqtProperty(bool, notify=modesChanged)
    def shuffle(self):
        return self._shuffle

    @pyqtProperty(str, notify=modesChanged)
    def repeat(self):
        """'off', 'all' or 'one', as for the Pi's own music."""
        return REPEAT_WORDS[self._repeat]

    @pyqtProperty("QVariantList", notify=queueChanged)
    def upNext(self):
        return self._up_next

    @pyqtProperty("QVariantList", notify=recentsChanged)
    def recents(self):
        return [dict(r) for r in self._recents]

    # ---- controls ---------------------------------------------------------
    @pyqtSlot()
    def play(self):
        self._command("play")

    @pyqtSlot()
    def pause(self):
        self._command("pause")

    @pyqtSlot()
    def togglePlay(self):
        self._command("pause" if self.playing else "play")

    @pyqtSlot()
    def next(self):
        self._command("skip_next")

    @pyqtSlot()
    def previous(self):
        self._command("skip_prev")

    @pyqtSlot(int)
    def seek(self, seconds):
        ms = max(0, int(seconds)) * 1000
        self._command("seek", position_ms=ms)
        # Show it now rather than when the server's next event arrives.
        self._pos = (ms, time.monotonic(), self._pos[2])
        self.positionChanged.emit()

    @pyqtProperty(bool, constant=True)
    def canSeek(self):
        return True

    @pyqtSlot(int)
    def setVolume(self, value):
        value = max(0, min(100, int(value)))
        self._volume = value
        self._command("set_volume", volume=value)
        self.volumeChanged.emit()

    @pyqtSlot()
    def toggleShuffle(self):
        self._shuffle = not self._shuffle
        self._command("set_shuffle", enabled=self._shuffle)
        self.modesChanged.emit()

    @pyqtSlot()
    def cycleRepeat(self):
        self._repeat = {"off": "context", "context": "track", "track": "off"}[self._repeat]
        # Soloist's order: the one being turned off first.
        if self._repeat == "track":
            self._command("set_repeat_context", enabled=False)
            self._command("set_repeat_track", enabled=True)
        else:
            self._command("set_repeat_track", enabled=False)
            self._command("set_repeat_context", enabled=self._repeat == "context")
        self.modesChanged.emit()

    @pyqtSlot("QVariantList")
    def playTracks(self, uris):
        """Play the first song and queue the rest: Liked Songs have no URI
        that Soloist's `play` is documented to take."""
        if uris:
            self.playUri(uris[0], uris[1:])

    @pyqtSlot(str)
    def playUri(self, uri, then=()):
        """Start a track, album, playlist or episode by its spotify: URI
        (making the Pi the playing device first if it isn't), then queue the
        songs in `then`."""
        if not self._logged_in:
            self._error = "Spotify is still connecting"
            self.changed.emit()
            return
        self._fallback = ""
        self._then = list(then)
        self._start_here({"uri": uri})

    def resume(self, uri=""):
        """Bring Spotify's session to this Pi and carry on from it, or play
        `uri` if that finds nothing to carry on with."""
        self._fallback = uri
        self._fallback_timer.start()
        self._start_here({})

    def _start_here(self, fields):
        if self._active:
            self._play(fields)
        else:
            # Soloist's reply only means it took the command, so wait for the
            # device to change: a play sent before that can go nowhere.
            self._pending = fields
            self._pending_timer.start()
            self._command("activate")

    def _send_pending(self):
        fields, self._pending = self._pending, None
        self._pending_timer.stop()
        if fields is not None:
            self._play(fields)

    def _play(self, fields):
        self._command("play", **fields)
        then, self._then = self._then, []
        for uri in then:
            self._command("add_to_queue", uri=uri)

    def _play_fallback(self):
        uri, self._fallback = self._fallback, ""
        if uri and self._logged_in and not self.playing:
            self._start_here({"uri": uri})

    @pyqtSlot(str)
    def addToQueue(self, uri):
        """Play a track after this one (Soloist only queues tracks)."""
        self._command("add_to_queue", uri=uri)
