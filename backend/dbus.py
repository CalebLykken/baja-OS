"""System bus signals, for backends that would otherwise poll a command.

A BusWatch subscribes to a service's signals and calls the backend's refresh
when one arrives, so parsing stays in one code path: a signal only says "look
again". Bursts are merged (a track change is several signals). Qt delivers
signals on the UI thread, so the refresh keeps its own worker thread.

There's no bus on a Mac, and a service can be down, so `live()` is the backend's
cue: while it's False it polls as before, and while it's True a slow safety poll
is enough. `live()` is answered from a flag kept by a QDBusServiceWatcher (the
bus tells us when the service comes and goes), so it never waits on the bus
daemon; if no watcher can be made it asks the bus each time instead. Nothing
here raises: a D-Bus problem only ever means polling.
"""

from PyQt6.QtCore import QObject, QTimer, pyqtSlot

try:
    from PyQt6.QtDBus import QDBusConnection, QDBusMessage, QDBusServiceWatcher
except ImportError:                  # a PyQt build without QtDBus: poll instead
    QDBusConnection, QDBusMessage, QDBusServiceWatcher = None, object, None

DEBOUNCE_MS = 150
PROPERTIES = "org.freedesktop.DBus.Properties"

# NetworkManager, for both backends that read it: the overall state and
# connectivity (root object), and any device or connection coming and going
# (empty path = every object). The saved list has its own signals. Not
# PropertiesChanged on every object: access points send it with each signal
# strength change.
NM_SERVICE = "org.freedesktop.NetworkManager"
NM_ROOT = "/org/freedesktop/NetworkManager"
NM_SIGNALS = [
    (NM_ROOT, NM_SERVICE, "StateChanged"),
    (NM_ROOT, PROPERTIES, "PropertiesChanged"),
    ("", NM_SERVICE + ".Device", "StateChanged"),
    ("", NM_SERVICE + ".Connection.Active", "StateChanged"),
    (NM_ROOT + "/Settings", NM_SERVICE + ".Settings", "NewConnection"),
    (NM_ROOT + "/Settings", NM_SERVICE + ".Settings", "ConnectionRemoved"),
]
NM_DEBOUNCE_MS = 500        # joining a network is a burst over a few seconds, and each refresh runs nmcli


def system_bus():
    """The connected system bus, or None."""
    if QDBusConnection is None:
        return None
    try:
        bus = QDBusConnection.systemBus()
        return bus if bus.isConnected() else None
    except Exception as e:
        print(f"D-Bus: no system bus: {type(e).__name__}: {e}", flush=True)
        return None


class BusWatch(QObject):
    """Calls on_change (on the UI thread, debounced) when `service` sends one
    of `signals`, a list of (path, interface, name); an empty path is any object.
    `live()` comes from a service watcher's cached answer, or from asking the
    bus when there's no watcher. `watcher` is a test seam:
    watcher(service, bus, parent) -> object with a serviceOwnerChanged signal."""

    def __init__(self, service, signals, on_change, parent=None, debounce_ms=DEBOUNCE_MS,
                 watcher=None):
        super().__init__(parent)
        self._service = service
        self._signals = signals
        self._on_change = on_change
        self._bus = None
        self._make_watcher = watcher
        self._watcher = None
        self._present = False
        # Not restarted by each signal: a steady stream mustn't hold off the refresh forever.
        self._timer = QTimer(self, singleShot=True, interval=debounce_ms, timeout=self._fire)

    def start(self):
        """Subscribe. False, and the backend keeps polling, without a bus or
        if any subscription fails. Works before the service is running."""
        try:
            bus = system_bus()
            if bus is None:
                return False
            ok = [bus.connect(self._service, path, iface, name, self._on_signal)
                  for path, iface, name in self._signals]
            if not all(ok):
                print(f"D-Bus: couldn't subscribe to {self._service}, polling instead", flush=True)
                return False
            self._bus = bus
            self._watch_service(bus)
            return True
        except Exception as e:
            print(f"D-Bus: couldn't subscribe to {self._service}: {type(e).__name__}: {e}", flush=True)
            return False

    def _watch_service(self, bus):
        """Follow the service coming and going without asking the bus each time.
        Any failure leaves live() asking the bus, as it always did."""
        try:
            if self._make_watcher is not None:
                watcher = self._make_watcher(self._service, bus, self)
            else:
                watcher = QDBusServiceWatcher(
                    self._service, bus, QDBusServiceWatcher.WatchModeFlag.WatchForOwnerChange, self)
            watcher.serviceOwnerChanged.connect(self._owner_changed)
        except Exception as e:
            print(f"D-Bus: no service watcher for {self._service}, asking the bus: {type(e).__name__}: {e}", flush=True)
            self._watcher = None
            return
        self._watcher = watcher
        # After connecting, so a registration in between isn't missed.
        self._present = self._ask_bus()

    def _ask_bus(self):
        try:
            reply = self._bus.interface().isServiceRegistered(self._service)
            return reply.isValid() and bool(reply.value())
        except Exception:
            return False

    def live(self):
        """True while signals can be trusted: subscribed, and the service is
        on the bus right now (a service that isn't there says nothing)."""
        if self._bus is None:
            return False
        if self._watcher is not None:
            return self._present
        return self._ask_bus()

    def poke(self):
        """Refresh soon, as if a signal had come. Signals merge with this."""
        if not self._timer.isActive():
            self._timer.start()

    # The QDBusMessage parameter matches any signature; its contents don't matter.
    @pyqtSlot(QDBusMessage)
    def _on_signal(self, message=None):
        try:
            self.poke()
        except Exception as e:
            print(f"D-Bus: signal from {self._service} dropped: {type(e).__name__}: {e}", flush=True)

    @pyqtSlot(str, str, str)
    def _owner_changed(self, name="", old_owner="", new_owner=""):
        try:
            appeared = bool(new_owner) and not self._present
            self._present = bool(new_owner)
            if appeared:
                self.poke()      # NetworkManager/bluetoothd (re)started: look again now
        except Exception as e:
            print(f"D-Bus: owner change of {self._service} dropped: {type(e).__name__}: {e}", flush=True)

    def _fire(self):
        try:
            self._on_change()
        except Exception as e:
            print(f"D-Bus: refresh after a {self._service} signal failed: {type(e).__name__}: {e}", flush=True)
