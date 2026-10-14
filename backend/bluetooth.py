"""Phone audio over Bluetooth: what's playing, and the play/pause/skip remote.

The audio itself flows phone -> BlueZ -> PipeWire -> speakers without
touching this code. This class watches BlueZ for a connected phone's
AVRCP media player (org.bluez.MediaPlayer1) to show its track and send
commands, and can make the Pi discoverable for pairing.

BlueZ is polled once a second with `busctl` (JSON output) on a worker
thread rather than through D-Bus signals: simple, robust across BlueZ
versions, and a negligible load on the Pi 5. Off a Pi (no busctl/BlueZ)
everything reports "unavailable" and the UI hides the Bluetooth bits.
"""

import json
import shutil
import subprocess
import threading
import time

from PyQt6.QtCore import QObject, QTimer, pyqtProperty, pyqtSignal, pyqtSlot

POLL_MS = 1000
PAIRING_SECONDS = 120


def _v(variant):
    """Unwrap a busctl JSON variant {"type": ..., "data": ...}."""
    return variant.get("data") if isinstance(variant, dict) and "type" in variant else variant


def parse_objects(objects):
    """Reduce BlueZ's GetManagedObjects data to what the UI needs."""
    state = {"adapter": None, "discoverable": False, "device": None, "player": None,
             "to_trust": [], "transport": None, "volume": None}
    devices = {}
    for path, ifaces in objects.items():
        if "org.bluez.Adapter1" in ifaces and state["adapter"] is None:
            a = ifaces["org.bluez.Adapter1"]
            state["adapter"] = path
            state["discoverable"] = bool(_v(a.get("Discoverable")))
        if "org.bluez.Device1" in ifaces:
            d = ifaces["org.bluez.Device1"]
            devices[path] = d
            if _v(d.get("Paired")) and not _v(d.get("Trusted")):
                state["to_trust"].append(path)
        if "org.bluez.MediaTransport1" in ifaces:
            # The audio link. Its Volume (0-127) is the phone's own volume
            # setting, kept in sync both ways (AVRCP absolute volume).
            t = ifaces["org.bluez.MediaTransport1"]
            vol = _v(t.get("Volume"))
            if vol is not None:
                state["transport"] = path
                state["volume"] = int(vol)
        if "org.bluez.MediaPlayer1" in ifaces:
            p = ifaces["org.bluez.MediaPlayer1"]
            track = _v(p.get("Track")) or {}
            state["player"] = {
                "path": path,
                "device": _v(p.get("Device")),
                "status": _v(p.get("Status")) or "stopped",
                "position_ms": int(_v(p.get("Position")) or 0),
                "title": _v(track.get("Title")) or "",
                "artist": _v(track.get("Artist")) or "",
                "album": _v(track.get("Album")) or "",
                "duration_ms": int(_v(track.get("Duration")) or 0),
            }
    connected = [(p, d) for p, d in devices.items() if _v(d.get("Connected"))]
    if state["player"] and state["player"]["device"] in devices:
        path = state["player"]["device"]
        state["device"] = _v(devices[path].get("Alias")) or _v(devices[path].get("Name")) or "Phone"
    elif connected:
        d = connected[0][1]
        state["device"] = _v(d.get("Alias")) or _v(d.get("Name")) or "Phone"
    return state


def _busctl(*args, timeout=3):
    return subprocess.run(["busctl", "--system", *args],
                          capture_output=True, text=True, timeout=timeout)


class BluetoothAudio(QObject):
    changed = pyqtSignal()          # connection / pairing state
    volumeChanged = pyqtSignal()    # the phone's volume (changed on either end)
    trackChanged = pyqtSignal()
    positionChanged = pyqtSignal()
    playingChanged = pyqtSignal()
    _polled = pyqtSignal(object)

    def __init__(self, parent=None):
        super().__init__(parent)
        self._available = bool(shutil.which("busctl"))
        self._state = parse_objects({})
        self._player = None
        self._pos_ms = 0
        self._pos_at = time.monotonic()
        self._pairing_until = 0.0
        self._volume_sent_at = 0.0
        self._busy = False
        self._polled.connect(self._apply)
        self._timer = QTimer(self)
        self._timer.setInterval(POLL_MS)
        self._timer.timeout.connect(self._tick)

    def start(self):
        if self._available:
            self._tick()
            self._timer.start()

    # ---- polling ----------------------------------------------------------
    def _tick(self):
        if self.playing:
            self.positionChanged.emit()   # interpolated between BlueZ updates
        if self._pairing_until and time.monotonic() >= self._pairing_until:
            self._pairing_until = 0.0
            self.changed.emit()
        if not self._busy:
            self._busy = True
            threading.Thread(target=self._poll, daemon=True).start()

    def _poll(self):
        try:
            out = _busctl("--json=short", "call", "org.bluez", "/",
                          "org.freedesktop.DBus.ObjectManager", "GetManagedObjects").stdout
            data = json.loads(out)["data"][0] if out else {}
            state = parse_objects(data)
        except (OSError, subprocess.SubprocessError, ValueError, KeyError, IndexError):
            state = parse_objects({})
        # Trust paired phones so they reconnect by themselves next time.
        for path in state["to_trust"]:
            try:
                _busctl("set-property", "org.bluez", path, "org.bluez.Device1", "Trusted", "b", "true")
            except (OSError, subprocess.SubprocessError):
                pass
        self._polled.emit(state)

    def _apply(self, state):
        self._busy = False
        old, old_player = self._state, self._player
        self._state, self._player = state, state["player"]
        p, o = self._player, old_player or {}
        if (old["adapter"], old["discoverable"], old["device"]) != \
                (state["adapter"], state["discoverable"], state["device"]):
            self.changed.emit()
        # Ignore polls that raced a change we just sent, so the bar doesn't
        # jump back while the phone catches up.
        if state["volume"] != old["volume"] and time.monotonic() - self._volume_sent_at > 1.5:
            self.volumeChanged.emit()
        elif time.monotonic() - self._volume_sent_at <= 1.5:
            state["volume"] = old["volume"]
        if not p:
            if old_player:
                self.trackChanged.emit()
                self.playingChanged.emit()
            return
        if (p["title"], p["artist"], p["duration_ms"]) != (o.get("title"), o.get("artist"), o.get("duration_ms")):
            self.trackChanged.emit()
        if p["status"] != o.get("status"):
            self.playingChanged.emit()
        # BlueZ only refreshes Position on status changes and seeks; keep our
        # own clock running in between and resync whenever it reports.
        if p["position_ms"] != o.get("position_ms") or p["status"] != o.get("status"):
            self._pos_ms, self._pos_at = p["position_ms"], time.monotonic()
            self.positionChanged.emit()

    def _command(self, method):
        if not self._player:
            return
        path = self._player["path"]
        threading.Thread(target=lambda: _busctl("call", "org.bluez", path,
                                                "org.bluez.MediaPlayer1", method),
                         daemon=True).start()

    # ---- properties -------------------------------------------------------
    @pyqtProperty(bool, constant=True)
    def available(self):
        return self._available

    @pyqtProperty(bool, notify=changed)
    def adapterPresent(self):
        return self._state["adapter"] is not None

    @pyqtProperty(bool, notify=changed)
    def pairing(self):
        return self._state["discoverable"] and self._pairing_until > 0

    @pyqtProperty(int, notify=changed)
    def pairingSecondsLeft(self):
        return max(0, int(self._pairing_until - time.monotonic())) if self._pairing_until else 0

    @pyqtProperty(str, notify=changed)
    def deviceName(self):
        return self._state["device"] or ""

    @pyqtProperty(bool, notify=trackChanged)
    def hasPlayer(self):
        return self._player is not None

    @pyqtProperty(str, notify=trackChanged)
    def title(self):
        return (self._player or {}).get("title") or "Bluetooth audio"

    @pyqtProperty(str, notify=trackChanged)
    def artist(self):
        p = self._player or {}
        return p.get("artist") or self.deviceName or ""

    @pyqtProperty(int, notify=trackChanged)
    def duration(self):
        return (self._player or {}).get("duration_ms", 0) // 1000

    @pyqtProperty(int, notify=positionChanged)
    def position(self):
        ms = self._pos_ms
        if self.playing:
            ms += int((time.monotonic() - self._pos_at) * 1000)
        dur = (self._player or {}).get("duration_ms", 0)
        return (min(ms, dur) if dur else ms) // 1000

    @pyqtProperty(bool, notify=playingChanged)
    def playing(self):
        return (self._player or {}).get("status") == "playing"

    @pyqtProperty(bool, notify=volumeChanged)
    def hasVolume(self):
        """True when the phone shares its volume (absolute volume)."""
        return self._state["volume"] is not None

    @pyqtProperty(int, notify=volumeChanged)
    def volume(self):
        """The phone's volume as 0-100."""
        v = self._state["volume"]
        return round(v * 100 / 127) if v is not None else 0

    # ---- controls ---------------------------------------------------------
    @pyqtSlot()
    def play(self):
        self._command("Play")

    @pyqtSlot()
    def pause(self):
        self._command("Pause")

    @pyqtSlot()
    def togglePlay(self):
        self._command("Pause" if self.playing else "Play")

    @pyqtSlot()
    def next(self):
        self._command("Next")

    @pyqtSlot()
    def previous(self):
        self._command("Previous")

    @pyqtSlot(int)
    def setVolume(self, value):
        """Set the phone's volume (0-100); the phone's own slider follows."""
        transport = self._state["transport"]
        if not transport:
            return
        raw = max(0, min(127, round(int(value) * 127 / 100)))
        self._state["volume"] = raw
        self._volume_sent_at = time.monotonic()
        threading.Thread(target=lambda: _busctl(
            "set-property", "org.bluez", transport, "org.bluez.MediaTransport1",
            "Volume", "q", str(raw)), daemon=True).start()
        self.volumeChanged.emit()

    @pyqtSlot(bool)
    def setPairing(self, on):
        """Make the Pi visible to phones for a couple of minutes, or stop."""
        adapter = self._state["adapter"]
        if not adapter:
            return
        self._pairing_until = time.monotonic() + PAIRING_SECONDS if on else 0.0
        val = "true" if on else "false"

        def run():
            _busctl("set-property", "org.bluez", adapter, "org.bluez.Adapter1",
                    "DiscoverableTimeout", "u", str(PAIRING_SECONDS))
            _busctl("set-property", "org.bluez", adapter, "org.bluez.Adapter1", "Pairable", "b", val)
            _busctl("set-property", "org.bluez", adapter, "org.bluez.Adapter1", "Discoverable", "b", val)
        threading.Thread(target=run, daemon=True).start()
        self.changed.emit()
