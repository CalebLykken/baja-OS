"""Phone audio over Bluetooth: what's playing, and the play/pause/skip remote.

The audio itself flows phone -> BlueZ -> PipeWire -> speakers without
touching this code. This class watches BlueZ for a connected phone's
AVRCP media player (org.bluez.MediaPlayer1) to show its track and send
commands, and can make the Pi discoverable for pairing. New phones are
confirmed on the screen (backend/btagent.py), and only those get trusted.

BlueZ's state is read with `busctl` (JSON output) on a worker thread. Its
D-Bus signals say when to read it, so a track change shows at once; a slow
safety poll catches anything missed, and without the bus or BlueZ's signals it
polls once a second. Off a Pi (no busctl/BlueZ) everything reports
"unavailable" and the UI hides the Bluetooth bits.
"""

import json
import shutil
import subprocess
import threading
import time
import traceback
from datetime import date

from PyQt6.QtCore import QObject, QTimer, pyqtProperty, pyqtSignal, pyqtSlot

from backend import safe_emit
from backend.btagent import PairingAgent
from backend.dbus import PROPERTIES, BusWatch
from backend.prefs import as_json

POLL_MS = 1000
SAFETY_TICKS = 60       # seconds between polls while BlueZ's signals are coming through
PAIRING_SECONDS = 120
ACCEPTED_SECONDS = 120      # for the phone's side to finish after Pair was tapped here
DATES_KEY = "btPairedDates"
VOLUME_SETTLE_MS = 1600     # just past the 1.5 s that _apply ignores after a change we sent
OBJECT_MANAGER = "org.freedesktop.DBus.ObjectManager"
BLUEZ_SIGNALS = [("/", OBJECT_MANAGER, "InterfacesAdded"),
                 ("/", OBJECT_MANAGER, "InterfacesRemoved"),
                 ("", PROPERTIES, "PropertiesChanged")]      # any object: players, transports, devices


def _v(variant):
    """Unwrap a busctl JSON variant {"type": ..., "data": ...}."""
    return variant.get("data") if isinstance(variant, dict) and "type" in variant else variant


def _name(device):
    return _v(device.get("Alias")) or _v(device.get("Name")) or _v(device.get("Address")) or "Device"


def _address(path, device):
    """The device's address; BlueZ's object paths end in it too."""
    return _v(device.get("Address")) or (path.rsplit("/dev_", 1)[1].replace("_", ":") if "/dev_" in path else "")


def _shown_date(iso):
    """"Oct 31, 2026" from "2026-10-31"; "" if it isn't a date."""
    try:
        d = date.fromisoformat(str(iso))
    except ValueError:
        return ""
    return f"{d:%b} {d.day}, {d.year}"


def _pick_player(players, prefer):
    """With two phones connected there are two players: the one that is
    playing wins; if both (or neither) are, keep the one used last."""
    playing = [p for p in players if p["status"] == "playing"]
    pool = playing or players
    return next((p for p in pool if p["path"] == prefer), pool[-1]) if pool else None


def parse_objects(objects, prefer=None):
    """Reduce BlueZ's GetManagedObjects data to what the UI needs. `prefer` is
    the path of the player used last, to stay on it when nothing says otherwise."""
    state = {"adapter": None, "discoverable": False, "device": None, "player": None,
             "known": {}, "confirmed": [], "transport": None, "volume": None, "paired": []}
    devices, players, transports = {}, [], {}
    for path, ifaces in objects.items():
        if "org.bluez.Adapter1" in ifaces and state["adapter"] is None:
            a = ifaces["org.bluez.Adapter1"]
            state["adapter"] = path
            state["discoverable"] = bool(_v(a.get("Discoverable")))
        if "org.bluez.Device1" in ifaces:
            d = ifaces["org.bluez.Device1"]
            devices[path] = d
            state["known"][path] = {"name": _name(d), "address": _address(path, d),
                                    "paired": bool(_v(d.get("Paired"))), "trusted": bool(_v(d.get("Trusted")))}
        if "org.bluez.MediaTransport1" in ifaces:
            # The audio link. Its Volume (0-127) is the phone's own volume
            # setting, kept in sync both ways (AVRCP absolute volume).
            t = ifaces["org.bluez.MediaTransport1"]
            vol = _v(t.get("Volume"))
            if vol is not None:
                transports[_v(t.get("Device"))] = (path, int(vol))
        if "org.bluez.MediaPlayer1" in ifaces:
            p = ifaces["org.bluez.MediaPlayer1"]
            track = _v(p.get("Track")) or {}
            players.append({
                "path": path,
                "device": _v(p.get("Device")),
                "status": _v(p.get("Status")) or "stopped",
                "position_ms": int(_v(p.get("Position")) or 0),
                "title": _v(track.get("Title")) or "",
                "artist": _v(track.get("Artist")) or "",
                "album": _v(track.get("Album")) or "",
                "duration_ms": int(_v(track.get("Duration")) or 0),
            })
    state["player"] = _pick_player(players, prefer)
    # The volume is the chosen phone's own, or none: another phone's would
    # move the passenger's volume. With no player at all, any transport.
    if state["player"]:
        chosen = transports.get(state["player"]["device"])
    else:
        chosen = list(transports.values())[-1] if transports else None
    if chosen:
        state["transport"], state["volume"] = chosen
    connected = [(p, d) for p, d in devices.items() if _v(d.get("Connected"))]
    state["paired"] = sorted(
        ({"path": p, "name": _name(d), "connected": bool(_v(d.get("Connected"))),
          "address": _address(p, d), "trusted": bool(_v(d.get("Trusted")))}
         for p, d in devices.items() if _v(d.get("Paired"))),
        key=lambda d: (not d["connected"], d["name"].lower()))
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

    def __init__(self, parent=None, settings=None):
        super().__init__(parent)
        self._available = bool(shutil.which("busctl"))
        self._settings = settings
        self._dates = self._load_dates()    # {address: ISO date}, when a device was accepted here
        self._accepted = {}                 # {device path: when to give up}, accepted but not yet trusted
        self._state = parse_objects({})
        self._player = None
        self._pos_ms = 0
        self._pos_at = time.monotonic()
        self._pairing_until = 0.0
        self._volume_sent_at = 0.0
        self._busy = False
        self._again = False        # a signal came during a poll, which may have read too early
        self._ticks_left = 0       # until the next poll
        self._poll_error = ""      # the error the last poll died of, while it keeps happening
        self._polled.connect(self._apply)
        self._timer = QTimer(self)
        self._timer.setInterval(POLL_MS)
        self._timer.timeout.connect(self._tick)
        self._bluez = BusWatch("org.bluez", BLUEZ_SIGNALS, self._signalled, self)
        # What the phone made of a volume we sent, which _apply ignores until then.
        self._volume_settle = QTimer(self, singleShot=True, interval=VOLUME_SETTLE_MS,
                                     timeout=self._bluez.poke)
        self._agent = PairingAgent(self._pairing_open, self._is_trusted, self._accepted_on_screen, self)
        self._agent.changed.connect(self._agent_changed)

    def start(self):
        if self._available:
            self._agent.start()      # first: its call on the bus mustn't wait behind the poll
            self._bluez.start()
            self._tick()
            self._timer.start()

    # ---- polling ----------------------------------------------------------
    def _tick(self):
        if self.playing:
            self.positionChanged.emit()   # interpolated between BlueZ updates
        if self._pairing_until and time.monotonic() >= self._pairing_until:
            self._pairing_until = 0.0
            self._agent.cancel("Pairing closed")
            self.changed.emit()
        self._agent.tick()
        now = time.monotonic()
        self._accepted = {p: until for p, until in self._accepted.items() if until > now}
        self._ticks_left -= 1
        if self._ticks_left <= 0:
            self._refresh()

    def _refresh(self):
        # Fast while a device accepted on screen waits for its trust.
        self._ticks_left = SAFETY_TICKS if self._bluez.live() and not self._accepted else 1
        if not self._busy:
            self._busy = True
            threading.Thread(target=self._poll, daemon=True).start()

    def _signalled(self):
        if self._busy:
            self._again = True
        else:
            self._refresh()

    def _poll(self):
        state = None     # stays None if the poll crashes, and _apply keeps the old state
        accepted = list(self._accepted)
        try:
            try:
                out = _busctl("--json=short", "call", "org.bluez", "/",
                              "org.freedesktop.DBus.ObjectManager", "GetManagedObjects").stdout
                data = json.loads(out)["data"][0] if out else {}
            except (OSError, subprocess.SubprocessError, ValueError, KeyError, IndexError):
                data = {}                    # no BlueZ, or nothing usable from it
            state = parse_objects(data, (self._player or {}).get("path"))
            self._trust(state, accepted)
            self._logged()
        except Exception as e:
            self._logged(e)
        finally:
            safe_emit(self, "_polled", state)     # always, or _busy would never clear

    def _trust(self, state, accepted):
        """Trust what was accepted on screen, now that it's paired, so it
        reconnects by itself. Nothing else ever gets trusted here. Runs on the
        poll's thread; a failure leaves the device for the next poll."""
        for path in accepted:
            device = state["known"].get(path)
            if not device or not device["paired"]:
                continue
            if not device["trusted"]:
                try:
                    done = _busctl("set-property", "org.bluez", path, "org.bluez.Device1",
                                   "Trusted", "b", "true")
                except (OSError, subprocess.SubprocessError):
                    continue
                if done.returncode != 0:
                    continue
                device["trusted"] = True
                for entry in state["paired"]:
                    if entry["path"] == path:
                        entry["trusted"] = True
            state["confirmed"].append((path, device["address"]))

    def _logged(self, error=None):
        """Log a poll that crashed (once, while the same error repeats), or
        that it's working again."""
        err = "" if error is None else f"{type(error).__name__}: {error}"
        if err and err != self._poll_error:
            trace = "".join(traceback.format_exception(error)).rstrip()
            print(f"Bluetooth: poll failed: {err}\n{trace}", flush=True)
        elif not err and self._poll_error:
            print("Bluetooth: working again", flush=True)
        self._poll_error = err

    def _apply(self, state):
        self._busy = False
        if self._again:
            self._again = False
            self._bluez.poke()
        if state is None:
            return
        old, old_player = self._state, self._player
        self._state, self._player = state, state["player"]
        p, o = self._player, old_player or {}
        dated = self._update_dates(state)
        # A prompt's device can turn up (or get its name) after the prompt does.
        if dated or self._agent.pending or (old["adapter"], old["discoverable"], old["device"], old["paired"]) != \
                (state["adapter"], state["discoverable"], state["device"], state["paired"]):
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

    # ---- pairing ----------------------------------------------------------
    def _pairing_open(self):
        return self._pairing_until > time.monotonic()

    def _is_trusted(self, path):
        """For a service BlueZ wants allowed. A phone connects its audio right
        after pairing, which can beat the poll that trusts it."""
        return path in self._accepted or self._state["known"].get(path, {}).get("trusted", False)

    def _accepted_on_screen(self, path):
        self._accepted[path] = time.monotonic() + ACCEPTED_SECONDS
        self._bluez.poke()

    def _agent_changed(self):
        if self._agent.pending:
            self._bluez.poke()       # the phone that's asking is usually new to us
        self.changed.emit()

    def _load_dates(self):
        if self._settings is None:
            return {}
        return as_json(self._settings.get(DATES_KEY), dict, {})

    def _update_dates(self, state):
        """Note the day each device was accepted, and forget the ones that are
        gone (not while BlueZ is down: that's no answer). True if any changed."""
        before = dict(self._dates)
        for path, address in state["confirmed"]:
            self._accepted.pop(path, None)
            self._dates[address] = date.today().isoformat()
        if state["adapter"]:
            paired = {d["address"] for d in state["paired"]}
            self._dates = {a: d for a, d in self._dates.items() if a in paired}
        if self._dates == before:
            return False
        if self._settings is not None:
            self._settings.set(DATES_KEY, json.dumps(self._dates))
        return True

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

    @pyqtProperty("QVariantList", notify=changed)
    def paired(self):
        """Paired devices, connected first: [{path, name, address, connected,
        trusted, pairedOn}]. trusted is False for one not accepted on this
        screen; pairedOn is "" for one paired before dates were kept."""
        return [dict(d, pairedOn=_shown_date(self._dates.get(d["address"], "")))
                for d in self._state["paired"]]

    @pyqtProperty(bool, notify=changed)
    def pairPending(self):
        """A device is asking to pair, and the screen has to answer."""
        return self._agent.pending

    @pyqtProperty(str, notify=changed)
    def pairName(self):
        return self._state["known"].get(self._agent.device, {}).get("name") or self.pairAddress

    @pyqtProperty(str, notify=changed)
    def pairAddress(self):
        return _address(self._agent.device, {})

    @pyqtProperty(str, notify=changed)
    def pairCode(self):
        """The six digits to compare with the phone; "" if it can't show any."""
        return self._agent.code

    @pyqtProperty(bool, notify=changed)
    def agentOk(self):
        return self._agent.registered

    @pyqtProperty(str, notify=changed)
    def agentProblem(self):
        """Why new phones can't be confirmed; nothing where there's no Bluetooth to pair with."""
        return self._agent.problem if self._available else ""

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

    @pyqtProperty(str, notify=trackChanged)
    def art(self):
        """Always '': AVRCP doesn't carry cover art in practice."""
        return ""

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

    @pyqtProperty(bool, constant=True)
    def canSeek(self):
        """AVRCP has no seek: the progress bar isn't draggable on a phone."""
        return False

    @pyqtSlot(int)
    def seek(self, seconds):
        pass

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
        self._volume_settle.start()
        threading.Thread(target=lambda: _busctl(
            "set-property", "org.bluez", transport, "org.bluez.MediaTransport1",
            "Volume", "q", str(raw)), daemon=True).start()
        self.volumeChanged.emit()

    @pyqtSlot()
    def acceptPairing(self):
        self._agent.accept()

    @pyqtSlot()
    def cancelPairing(self):
        self._agent.cancel()

    @pyqtSlot(str)
    def connectDevice(self, path):
        if path.startswith("/org/bluez/"):
            threading.Thread(target=lambda: _busctl("call", "org.bluez", path, "org.bluez.Device1",
                                                    "Connect", timeout=25), daemon=True).start()

    @pyqtSlot(str)
    def disconnectDevice(self, path):
        if path.startswith("/org/bluez/"):
            threading.Thread(target=lambda: _busctl("call", "org.bluez", path, "org.bluez.Device1",
                                                    "Disconnect", timeout=10), daemon=True).start()

    @pyqtSlot(str)
    def forgetDevice(self, path):
        """Unpair: the phone has to pair again to come back."""
        adapter = self._state["adapter"]
        if adapter and path.startswith(adapter + "/"):
            self._accepted.pop(path, None)
            threading.Thread(target=lambda: _busctl("call", "org.bluez", adapter, "org.bluez.Adapter1",
                                                    "RemoveDevice", "o", path), daemon=True).start()

    @pyqtSlot(bool)
    def setPairing(self, on):
        """Make the Pi visible to phones for a couple of minutes, or stop."""
        if not on:
            self._agent.cancel("Pairing closed")
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
