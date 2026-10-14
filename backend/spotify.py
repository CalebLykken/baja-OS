"""Spotify playback on the Pi through Spotify Soloist (Spotify Connect).

Soloist is Spotify's official headless Connect player. It plays the audio
itself through PipeWire; this class talks to its local WebSocket API
(soloist --ws 127.0.0.1:PORT, see deploy/spotify/) to show what's playing
and send play/pause/skip/seek/volume. Reference:
https://developer.spotify.com/documentation/soloist/reference/websocket-api

If Soloist isn't installed or running, `available` stays False, the socket
keeps retrying quietly, and the rest of the dashboard carries on.
"""

import json
import time

from PyQt6.QtCore import QObject, QTimer, QUrl, pyqtProperty, pyqtSignal, pyqtSlot

try:
    from PyQt6.QtWebSockets import QWebSocket
except ImportError:          # python3-pyqt6.qtwebsockets not installed
    QWebSocket = None

DEFAULT_URL = "ws://127.0.0.1:47240"
RETRY_MS = 3000


def _name(entity):
    return ((entity or {}).get("decorations") or {}).get("identity", {}).get("name", "")


def _cover(entity, prefer=("large", "xlarge", "default", "small")):
    covers = ((entity or {}).get("decorations") or {}).get("visual_identity", {}).get("cover") or []
    by_size = {c.get("size"): c.get("url") for c in covers if c.get("url")}
    return next((by_size[s] for s in prefer if s in by_size), "")


def _artists(entity):
    creators = ((entity or {}).get("decorations") or {}).get("creators") or []
    return ", ".join(n for n in (_name(c) for c in creators) if n)


def _duration_ms(entity):
    return int(((entity or {}).get("decorations") or {}).get("playback", {}).get("duration_ms") or 0)


def _parent(entity):
    return ((entity or {}).get("decorations") or {}).get("parent", {}).get("entity") or {}


class SpotifyPlayer(QObject):
    changed = pyqtSignal()          # connection / login / active device
    trackChanged = pyqtSignal()
    positionChanged = pyqtSignal()
    playingChanged = pyqtSignal()
    volumeChanged = pyqtSignal()
    queueChanged = pyqtSignal()

    def __init__(self, url=DEFAULT_URL, parent=None):
        super().__init__(parent)
        self._url = url
        self._connected = False
        self._logged_in = False
        self._active = False
        self._device = ""
        self._item = {}
        self._status = "idle"
        self._pos = (0, 0.0, 0.0)       # position_ms, at (local monotonic s), speed
        self._volume = 0
        self._up_next = []

        self._ws = QWebSocket() if QWebSocket else None
        self._retry = QTimer(self)
        self._retry.setSingleShot(True)
        self._retry.timeout.connect(self._open)
        self._tick = QTimer(self)
        self._tick.setInterval(1000)
        self._tick.timeout.connect(lambda: self.playing and self.positionChanged.emit())
        if self._ws:
            self._ws.connected.connect(self._on_connected)
            self._ws.disconnected.connect(self._on_disconnected)
            self._ws.textMessageReceived.connect(self._on_message)

    def start(self):
        if self._ws:
            self._open()
            self._tick.start()

    # ---- socket -----------------------------------------------------------
    def _open(self):
        self._ws.open(QUrl(self._url))

    def _on_connected(self):
        self._connected = True
        self._send({"type": "command", "command": "get_auth_state"})
        self.changed.emit()

    def _on_disconnected(self):
        was = self._connected
        self._connected = self._logged_in = self._active = False
        self._status = "idle"
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
        kind = ev.get("type")
        if kind == "auth_state":
            self._logged_in = bool(ev.get("logged_in"))
            self._active = bool(ev.get("is_active"))
            self._device = ev.get("device_name") or self._device
            self.changed.emit()
            if self._logged_in:
                self._command("get_queue", limit=10)
        elif kind == "playback_state":
            self._set_item(ev.get("item"))
            self._set_status(ev.get("status"))
            self._set_position(ev.get("position"))
            self._set_volume(ev.get("volume"))
            self._set_active(ev.get("is_active"))
        elif kind == "track_changed":
            self._set_item(ev.get("item"))
        elif kind == "playback_changed":
            self._set_status(ev.get("status"))
        elif kind == "position_sync":
            self._set_position(ev.get("position"))
        elif kind == "volume_changed":
            self._set_volume(ev.get("volume"))
        elif kind == "device_changed":
            self._device = ev.get("device_name") or self._device
            self._set_active(ev.get("is_active"))
        elif kind == "queue_changed":
            self._up_next = [{"title": _name(e.get("item")), "artist": _artists(e.get("item"))}
                             for e in (ev.get("upcoming") or [])][:10]
            self.queueChanged.emit()
        elif kind == "error":
            print(f"Spotify: {ev.get('message')}")

    def _set_item(self, item):
        item = item or {}
        if item != self._item:
            self._item = item
            self.trackChanged.emit()
            self._command("get_queue", limit=10)

    def _set_status(self, status):
        if status and status != self._status:
            self._status = status
            self.playingChanged.emit()

    def _set_position(self, pos):
        if not pos:
            return
        # The server's timestamp is the same machine's clock, so convert it
        # to an age and anchor to our monotonic clock for interpolation.
        age = max(0.0, time.time() - (pos.get("timestamp_ms") or 0) / 1000)
        self._pos = (int(pos.get("position_ms") or 0), time.monotonic() - age,
                     float(pos.get("speed") or 0.0))
        self.positionChanged.emit()

    def _set_volume(self, volume):
        if volume is not None and int(volume) != self._volume:
            self._volume = int(volume)
            self.volumeChanged.emit()

    def _set_active(self, active):
        if active is not None and bool(active) != self._active:
            self._active = bool(active)
            self.changed.emit()

    # ---- properties -------------------------------------------------------
    @pyqtProperty(bool, notify=changed)
    def available(self):
        """Soloist is running and reachable."""
        return self._connected

    @pyqtProperty(bool, notify=changed)
    def linked(self):
        """A Spotify account is paired with the player."""
        return self._logged_in

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

    @pyqtProperty("QVariantList", notify=queueChanged)
    def upNext(self):
        return self._up_next

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
        self._command("seek", position_ms=max(0, int(seconds)) * 1000)

    @pyqtSlot(int)
    def setVolume(self, value):
        value = max(0, min(100, int(value)))
        self._volume = value
        self._command("set_volume", volume=value)
        self.volumeChanged.emit()

    @pyqtSlot(str)
    def playUri(self, uri):
        """Start a track, album, playlist or episode by its spotify: URI."""
        self._command("play", uri=uri)
