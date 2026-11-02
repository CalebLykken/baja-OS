"""The dashboard as BlueZ's pairing agent, so pairing takes a tap on the screen.

BlueZ asks its default agent before a phone can pair. We register as that agent
(capability DisplayYesNo) and show a prompt with the code the phone shows; only
what's accepted there pairs. `_Agent1` is the bit on the bus and only passes
calls on: every decision is in PairingAgent, in plain Python.

Nothing here raises. If registering fails, `problem` says why, Settings shows
it, and tick() tries again every so often, so a bluetoothd restart heals itself.
"""

import time

from PyQt6.QtCore import QObject, QTimer, pyqtClassInfo, pyqtSignal, pyqtSlot

from backend import dbus

try:
    from PyQt6.QtDBus import QDBusError, QDBusObjectPath
except ImportError:                  # a PyQt build without QtDBus: `problem` says so
    QDBusError, QDBusObjectPath = object, object

BLUEZ = "org.bluez"
AGENT_PATH = "/org/baja/agent"
AGENT_INTERFACE = "org.bluez.Agent1"
AGENT_MANAGER = "org.bluez.AgentManager1"
CAPABILITY = "DisplayYesNo"
REJECTED = "org.bluez.Error.Rejected"
ALREADY_EXISTS = "org.bluez.Error.AlreadyExists"

PROMPT_SECONDS = 30
RETRY_SECONDS = 10          # between tries at registering, driven by tick()
CALL_TIMEOUT_MS = 5000


def _path(device):
    """The path of a device argument, which PyQt may hand over as a plain string."""
    return device.path() if hasattr(device, "path") else str(device)


class _Reply:
    """The answer BlueZ is waiting for. Qt doesn't send one of its own once
    this has marked the call as delayed."""

    def __init__(self, bus, message):
        self._bus = bus
        self._message = message
        message.setDelayedReply(True)

    def accept(self):
        return self._send(self._message.createReply())

    def reject(self, why):
        return self._send(self._message.createErrorReply(REJECTED, why))

    def _send(self, reply):
        try:
            return bool(self._bus.send(reply))
        except Exception as e:
            print(f"Pairing agent: couldn't answer BlueZ: {type(e).__name__}: {e}", flush=True)
            return False


# Qt only delivers a call on org.bluez.Agent1 to an object that says it has that
# interface. An exception escaping a slot would end the app, hence _guarded.
@pyqtClassInfo("D-Bus Interface", AGENT_INTERFACE)
class _Agent1(QObject):
    """org.bluez.Agent1 on the bus. The trailing QDBusMessage isn't part of the
    D-Bus signature: Qt adds it, and it's how a slot answers later."""

    def __init__(self, agent, bus):
        super().__init__(agent)
        self._agent = agent
        self._bus = bus

    def _guarded(self, method, message, *args):
        reply = _Reply(self._bus, message)
        try:
            method(*args, reply)
        except Exception as e:
            print(f"Pairing agent: {method.__name__} failed: {type(e).__name__}: {e}", flush=True)
            reply.reject("Internal error")

    @pyqtSlot()
    def Release(self):
        try:
            self._agent.lost("BlueZ dropped the pairing agent (bluetoothd stopped or restarted)")
        except Exception as e:
            print(f"Pairing agent: Release failed: {type(e).__name__}: {e}", flush=True)

    @pyqtSlot()
    def Cancel(self):
        try:
            self._agent.bluez_cancelled()
        except Exception as e:
            print(f"Pairing agent: Cancel failed: {type(e).__name__}: {e}", flush=True)

    @pyqtSlot(QDBusObjectPath, "uint", dbus.QDBusMessage)
    def RequestConfirmation(self, device, passkey, message):
        self._guarded(self._agent.confirm, message, _path(device), passkey)

    @pyqtSlot(QDBusObjectPath, dbus.QDBusMessage)
    def RequestAuthorization(self, device, message):
        self._guarded(self._agent.authorize, message, _path(device))

    @pyqtSlot(QDBusObjectPath, str, dbus.QDBusMessage)
    def AuthorizeService(self, device, uuid, message):
        self._guarded(self._agent.authorize_service, message, _path(device), uuid)

    @pyqtSlot(QDBusObjectPath, "uint", "ushort", dbus.QDBusMessage)
    def DisplayPasskey(self, device, passkey, entered, message):
        self._guarded(self._agent.refuse, message, "a passkey to display")

    @pyqtSlot(QDBusObjectPath, str, dbus.QDBusMessage)
    def DisplayPinCode(self, device, pincode, message):
        self._guarded(self._agent.refuse, message, "a PIN to display")

    @pyqtSlot(QDBusObjectPath, dbus.QDBusMessage, result=str)
    def RequestPinCode(self, device, message):
        self._guarded(self._agent.refuse, message, "a PIN")
        return ""                    # not sent: the reply is delayed

    @pyqtSlot(QDBusObjectPath, dbus.QDBusMessage, result="uint")
    def RequestPasskey(self, device, message):
        self._guarded(self._agent.refuse, message, "a passkey")
        return 0                     # not sent: the reply is delayed


class PairingAgent(QObject):
    """One prompt at a time, and only while `allowed()` (the Pair phone window
    is open). `is_trusted(path)` answers for a phone's services; `on_accepted(path)`
    is told when a device is accepted on screen."""

    changed = pyqtSignal()

    def __init__(self, allowed, is_trusted, on_accepted, parent=None, clock=time.monotonic):
        super().__init__(parent)
        self._allowed = allowed
        self._is_trusted = is_trusted
        self._on_accepted = on_accepted
        self._clock = clock
        self._started = False
        self._registered = False
        self._problem = ""
        self._exported = None
        self._bus = None
        self._calling = False
        self._last_try = 0.0
        self._pending = None         # {"device", "code", "reply"}
        self._timeout = QTimer(self, singleShot=True, interval=PROMPT_SECONDS * 1000,
                               timeout=self._timed_out)

    # ---- state ------------------------------------------------------------
    @property
    def registered(self):
        return self._registered

    @property
    def problem(self):
        """Why we aren't the agent, "" when we are."""
        return self._problem

    @property
    def pending(self):
        return self._pending is not None

    @property
    def device(self):
        """The object path of the device being asked about, "" when none."""
        return self._pending["device"] if self._pending else ""

    @property
    def code(self):
        """The six digits to compare, "" when none (or the phone has no display)."""
        return self._pending["code"] if self._pending else ""

    def _set(self, registered, problem):
        if (registered, problem) == (self._registered, self._problem):
            return
        self._registered, self._problem = registered, problem
        print("Pairing agent: registered" if registered else f"Pairing agent: {problem}", flush=True)
        self.changed.emit()

    # ---- what BlueZ asks --------------------------------------------------
    def _prompt(self, device, code, reply):
        if self._pending is not None:
            reply.reject("Another pairing is waiting")
        elif not self._allowed():
            print(f"Pairing agent: rejected {device}: Pair phone isn't on", flush=True)
            reply.reject("Pairing isn't open")
        else:
            self._pending = {"device": device, "code": code, "reply": reply}
            self._timeout.start()
            self.changed.emit()

    def confirm(self, device, passkey, reply):
        """RequestConfirmation: both sides show this code."""
        self._prompt(device, f"{int(passkey):06d}", reply)

    def authorize(self, device, reply):
        """RequestAuthorization: a phone with no screen or buttons, so no code exists."""
        self._prompt(device, "", reply)

    def authorize_service(self, device, uuid, reply):
        if self._is_trusted(device):
            reply.accept()
        else:
            print(f"Pairing agent: rejected {uuid} from {device}: not trusted", flush=True)
            reply.reject("Not trusted")

    def refuse(self, what, reply):
        """We do no legacy PINs and show no passkeys to type in."""
        print(f"Pairing agent: refused to handle {what}", flush=True)
        reply.reject("Not supported")

    def bluez_cancelled(self):
        """BlueZ gave up on the request, and wants no answer now."""
        self._take()

    def lost(self, why):
        """We aren't the agent any more. tick() registers again, after a wait."""
        self._take()
        self._last_try = self._clock()
        self._set(False, why)

    def _take(self):
        pending, self._pending = self._pending, None
        self._timeout.stop()
        if pending is not None:
            self.changed.emit()
        return pending

    # ---- what the screen answers ------------------------------------------
    def accept(self):
        """The Pair button. Only an answer that reached BlueZ counts."""
        pending = self._take()
        if pending and pending["reply"].accept():
            self._on_accepted(pending["device"])

    def cancel(self, why="Cancelled on the dashboard"):
        pending = self._take()
        if pending:
            pending["reply"].reject(why)

    def _timed_out(self):
        try:
            self.cancel("Nobody answered in time")
        except Exception as e:
            print(f"Pairing agent: timeout failed: {type(e).__name__}: {e}", flush=True)

    # ---- registering ------------------------------------------------------
    def start(self):
        self._started = True
        self._register()

    def tick(self):
        """Call about once a second: heals a lost or failed registration."""
        if self._started and not self._registered and not self._calling \
                and self._clock() - self._last_try >= RETRY_SECONDS:
            self._register()

    def _register(self):
        self._last_try = self._clock()
        try:
            bus = dbus.system_bus()
            if bus is None:
                self._set(False, "This PyQt has no QtDBus" if dbus.QDBusConnection is None
                          else "Can't reach the system bus")
                return
            if self._exported is None and not self._export(bus):
                return
            self._bus = bus
            self._call("RegisterAgent", [QDBusObjectPath(AGENT_PATH), CAPABILITY], self._agent_registered)
        except Exception as e:
            self._calling = False
            self._set(False, f"Couldn't register the pairing agent: {type(e).__name__}: {e}")

    def _export(self, bus):
        exported = _Agent1(self, bus)
        if not bus.registerObject(AGENT_PATH, exported, dbus.QDBusConnection.RegisterOption.ExportAllSlots):
            exported.deleteLater()
            self._set(False, "Couldn't put the pairing agent on the bus")
            return False
        self._exported = exported
        # bluetoothd crashing sends no Release, and it forgets us all the same.
        bus.connect("org.freedesktop.DBus", "/org/freedesktop/DBus", "org.freedesktop.DBus",
                    "NameOwnerChanged", self._name_owner_changed)
        return True

    def _call(self, method, arguments, done):
        message = dbus.QDBusMessage.createMethodCall(BLUEZ, "/org/bluez", AGENT_MANAGER, method)
        message.setArguments(arguments)
        self._calling = True
        if not self._bus.callWithCallback(message, done, self._call_failed, CALL_TIMEOUT_MS):
            self._calling = False
            self._set(False, f"Couldn't ask BlueZ to {method}")

    @pyqtSlot(dbus.QDBusMessage)
    def _agent_registered(self, reply=None):
        self._calling = False
        try:
            self._call("RequestDefaultAgent", [QDBusObjectPath(AGENT_PATH)], self._agent_default)
        except Exception as e:
            self._calling = False
            self._set(False, f"Couldn't register the pairing agent: {type(e).__name__}: {e}")

    @pyqtSlot(dbus.QDBusMessage)
    def _agent_default(self, reply=None):
        self._calling = False
        self._set(True, "")

    @pyqtSlot(QDBusError)
    def _call_failed(self, error):
        self._calling = False
        try:
            if error.name() == ALREADY_EXISTS:      # an earlier try got this far
                self._agent_registered()
            else:
                self._set(False, f"BlueZ wouldn't take the pairing agent: {error.message() or error.name()}")
        except Exception as e:
            self._set(False, f"Couldn't register the pairing agent: {type(e).__name__}: {e}")

    @pyqtSlot(dbus.QDBusMessage)
    def _name_owner_changed(self, message):
        try:
            arguments = message.arguments()
            if arguments and arguments[0] == BLUEZ and self._registered:
                self.lost("bluetoothd restarted, so the pairing agent has to register again")
        except Exception as e:
            print(f"Pairing agent: name change failed: {type(e).__name__}: {e}", flush=True)
