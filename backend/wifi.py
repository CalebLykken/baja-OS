"""Wi-Fi and the phone as a backup connection, through NetworkManager.

The Settings page lists nearby networks and joins one (the phone's hotspot,
home Wi-Fi). Networks joined here retry forever and stay saved, so the Pi
picks the hotspot up by itself whenever the phone is in the truck.

Backup: when there's been no Wi-Fi for a while, it brings up Bluetooth
tethering to the paired phone (NetworkManager's "bluetooth" connection for
it), and drops it again once Wi-Fi is back, to spare the phone's battery.

The radio only scans while the Wi-Fi settings are open (and right after a
join or forget there): a scan takes the one radio off the hotspot's channel,
which hurts a stream running over the phone. The backup's watchdog just reads
NetworkManager's connection list, which never scans.

Changing networks from a service needs a polkit rule, which setup-pi.sh
installs; until then `canControl` is False and the page says so. Passwords
go to nmcli on stdin, never on its command line.
"""

import re
import shutil
import subprocess
import threading
import time
import traceback

from PyQt6.QtCore import QObject, QTimer, pyqtProperty, pyqtSignal, pyqtSlot

from backend import safe_emit

SCAN_EVERY_MS = 15000
WATCH_EVERY_MS = 10000
TETHER_AFTER_S = 45          # this long with no Wi-Fi before trying the phone
TETHER_RETRY_S = 120
UNTETHER_AFTER_S = 60        # Wi-Fi back this long before letting the phone go
IPHONE_GATEWAY = "172.20.10.1"
HOTSPOT_ADDRESS = "172.20.10.14/28"   # a fixed extra address, for the "Send to Baja" Shortcut


def nmcli(*args, input=None, timeout=10):
    """(returncode, stdout, stderr) from nmcli; never raises."""
    try:
        r = subprocess.run(["nmcli", *args], capture_output=True, text=True,
                           input=input, timeout=timeout)
        return r.returncode, r.stdout, r.stderr
    except (OSError, subprocess.SubprocessError) as e:
        return 1, "", str(e)


def split_terse(line):
    """Split one line of `nmcli -t` output on unescaped colons."""
    parts = re.split(r"(?<!\\):", line)
    return [p.replace("\\:", ":").replace("\\\\", "\\") for p in parts]


def can_control():
    _, out, _ = nmcli("-t", "-f", "PERMISSION,VALUE", "general", "permissions", timeout=4)
    perms = dict(split_terse(l)[:2] for l in out.splitlines() if ":" in l)
    return perms.get("org.freedesktop.NetworkManager.network-control") == "yes"


def connections():
    """[{uuid, name, type, device, ssid}] for Wi-Fi and Bluetooth connections
    in one cheap call (no scan), or None if nmcli failed. `device` is empty
    unless the connection is up; `ssid` is left empty here."""
    rc, out, _ = nmcli("-t", "-f", "UUID,NAME,TYPE,DEVICE", "connection", "show", timeout=5)
    if rc != 0:
        return None
    conns = []
    for line in out.splitlines():
        f = split_terse(line)
        if len(f) < 4 or f[2] not in ("802-11-wireless", "bluetooth"):
            continue
        conns.append({"uuid": f[0], "name": f[1], "type": f[2], "device": f[3], "ssid": ""})
    return conns


def saved_connections():
    """connections(), with each Wi-Fi one's network name filled in (one more
    nmcli call apiece, so only for the Settings scan). [] if nmcli failed."""
    conns = connections() or []
    for c in conns:
        if c["type"] == "802-11-wireless":
            _, ssid, _ = nmcli("-g", "802-11-wireless.ssid", "connection", "show", "uuid", c["uuid"], timeout=4)
            c["ssid"] = ssid.strip()
    return conns


def scan(rescan):
    """Nearby networks, strongest first, one entry per name."""
    _, out, _ = nmcli("-t", "-f", "IN-USE,SSID,SIGNAL,SECURITY", "device", "wifi", "list",
                      "--rescan", "yes" if rescan else "no", timeout=15)
    best = {}
    for line in out.splitlines():
        f = split_terse(line)
        if len(f) < 4 or not f[1]:
            continue                                   # hidden networks
        try:
            signal = int(f[2] or 0)
        except ValueError:
            signal = 0       # a garbled number shouldn't lose the scan, or hide the active network
        net = {"ssid": f[1], "signal": signal, "secure": f[3] not in ("", "--"),
               "active": f[0] == "*"}
        old = best.get(net["ssid"])
        if not old or net["active"] or (not old["active"] and net["signal"] > old["signal"]):
            best[net["ssid"]] = net
    return sorted(best.values(), key=lambda n: (not n["active"], -n["signal"]))


class Wifi(QObject):
    changed = pyqtSignal()
    _scanned = pyqtSignal(object, object, bool)      # networks, saved, canControl
    _polled = pyqtSignal(object)                      # (saved, canControl), or None if nmcli failed
    _finished = pyqtSignal(str, bool)                 # message, ok

    def __init__(self, settings, parent=None):
        super().__init__(parent)
        self._settings = settings
        self._available = bool(shutil.which("nmcli"))
        self._networks = []
        self._saved = []
        self._control = False
        self._busy = ""            # SSID being joined
        self._message = ""
        self._scanning = False
        self._polling = False
        self._tether = str(settings.get("tethering", "true")) == "true"
        self._no_wifi_since = None
        self._wifi_since = None
        self._last_tether_try = 0
        self._hotspot_done = set()   # connections already looked at (a hotspot gets the fixed address)
        self._errors = {}            # what each worker last died of, while it keeps happening
        self._scanned.connect(self._on_scanned)
        self._polled.connect(self._on_polled)
        self._finished.connect(self._on_finished)
        self._scan_timer = QTimer(self, interval=SCAN_EVERY_MS, timeout=self.refresh)
        self._watch_timer = QTimer(self, interval=WATCH_EVERY_MS, timeout=self._watch)

    def start(self):
        if not self._available:
            return
        self._watch()                # no scan: the list waits for Settings to open
        self._watch_timer.start()

    # ---- scanning -----------------------------------------------------------
    @pyqtSlot()
    def refresh(self):
        """Scan for networks (this takes the radio off its channel), then
        read the saved connections. Only while the Wi-Fi settings are open."""
        if not self._available or self._scanning:
            return
        self._scanning = True

        def work():
            result = (None, None, False)     # stays this if the scan crashes: _on_scanned keeps its list
            try:
                control = can_control()
                nets = scan(rescan=control)
                result = (nets, saved_connections(), control)
                self._logged("scan")
            except Exception as e:
                self._logged("scan", e)
            finally:
                safe_emit(self, "_scanned", *result)    # always, or _scanning would never clear
        threading.Thread(target=work, daemon=True).start()

    def _logged(self, what, error=None):
        """Log a worker that crashed (once, while the same error repeats), or
        that it's working again."""
        err = "" if error is None else f"{type(error).__name__}: {error}"
        if err and err != self._errors.get(what):
            trace = "".join(traceback.format_exception(error)).rstrip()
            print(f"Wi-Fi: {what} failed: {err}\n{trace}", flush=True)
        elif not err and self._errors.get(what):
            print(f"Wi-Fi: {what} working again", flush=True)
        self._errors[what] = err

    def _ensure_hotspot_address(self):
        """On an iPhone hotspot, give the connection a fixed second address
        (172.20.10.14) so the phone's Shortcut always knows where the Pi is.
        DHCP still runs alongside it for the route and DNS."""
        try:
            _, out, _ = nmcli("-t", "-f", "IP4.GATEWAY,GENERAL.CONNECTION", "device", "show", "wlan0", timeout=4)
            fields = dict(split_terse(l)[:2] for l in out.splitlines() if ":" in l)
            conn = fields.get("GENERAL.CONNECTION", "")
            gateway = fields.get("IP4.GATEWAY")
            if not conn or not gateway or conn in self._hotspot_done:
                return                      # nothing up yet, or already looked at
            self._hotspot_done.add(conn)
            if gateway != IPHONE_GATEWAY:
                return
            _, addrs, _ = nmcli("-g", "ipv4.addresses", "connection", "show", "id", conn, timeout=4)
            if HOTSPOT_ADDRESS not in addrs:
                nmcli("connection", "modify", "id", conn, "+ipv4.addresses", HOTSPOT_ADDRESS)
                nmcli("device", "reapply", "wlan0", timeout=15)
            self._logged("hotspot address")
        except Exception as e:
            self._logged("hotspot address", e)

    def _on_scanned(self, nets, saved, control):
        self._scanning = False
        if nets is None:
            return                   # the scan crashed: keep the last list
        if control and any(n["active"] for n in nets):
            threading.Thread(target=self._ensure_hotspot_address, daemon=True).start()
        saved_ssids = {c["ssid"] for c in saved if c["ssid"]}
        for n in nets:
            n["saved"] = n["ssid"] in saved_ssids
        self._networks, self._saved, self._control = nets, saved, control
        self.changed.emit()

    @pyqtSlot(bool)
    def setScanning(self, on):
        """Scan every few seconds while the Wi-Fi settings are on screen."""
        if on and self._available:
            self.refresh()
            self._scan_timer.start()
        else:
            self._scan_timer.stop()

    # ---- joining and forgetting ----------------------------------------------
    def _run(self, ssid, fn, failed):
        if self._busy:
            return
        self._busy, self._message = ssid, ""
        self.changed.emit()

        def work():
            msg, ok = failed, False          # what the page says if fn() crashes
            try:
                msg, ok = fn()
                self._logged("join or forget")
            except Exception as e:
                self._logged("join or forget", e)
            finally:
                safe_emit(self, "_finished", msg, ok)    # always, or busy would never clear
        threading.Thread(target=work, daemon=True).start()

    def _on_finished(self, message, ok):
        self._busy, self._message = "", message
        self.changed.emit()
        if self._scan_timer.isActive():
            self.refresh()           # the Wi-Fi settings are still open: show the new state
        else:
            self._watch()            # they were closed meanwhile: no need to scan

    @pyqtSlot(str, str)
    def join(self, ssid, password):
        """Join a network: a saved one by name, or a new one with a password."""
        saved = next((c for c in self._saved if c["ssid"] == ssid), None)

        def work():
            if saved and not password:
                rc, _, err = nmcli("connection", "up", "uuid", saved["uuid"], timeout=40)
                return (f"Connected to {ssid}", True) if rc == 0 else (self._why(err, ssid), False)
            if saved:                       # new password for a saved network
                nmcli("connection", "delete", "uuid", saved["uuid"])
            # --ask reads the password from stdin rather than the command line.
            rc, out, err = nmcli("--ask", "device", "wifi", "connect", ssid,
                                 input=password + "\n", timeout=45)
            if rc != 0:
                return self._why(err or out, ssid), False
            # Keep trying forever (the hotspot comes and goes), no power saving.
            nmcli("connection", "modify", "id", ssid,
                  "connection.autoconnect-retries", "0", "802-11-wireless.powersave", "2")
            return f"Connected to {ssid}", True
        self._run(ssid, work, f"Couldn't join {ssid}")

    @pyqtSlot(str)
    def forget(self, ssid):
        conns = [c for c in self._saved if c["ssid"] == ssid]

        def work():
            for c in conns:
                nmcli("connection", "delete", "uuid", c["uuid"])
            return f"Forgot {ssid}", True
        self._run(ssid, work, f"Couldn't forget {ssid}")

    @staticmethod
    def _why(err, ssid):
        e = err.lower()
        if "secrets were required" in e or "password" in e or "802-1x" in e:
            return f"Wrong password for {ssid}"
        if "no network with ssid" in e or "not found" in e:
            return f"Can't see {ssid}; is the hotspot on?"
        if "not authorized" in e or "insufficient privileges" in e:
            return "Not allowed yet: run deploy/setup-pi.sh once on the Pi"
        return f"Couldn't join {ssid}"

    # ---- the phone as a backup ------------------------------------------------
    def _tether_conn(self):
        return next((c for c in self._saved if c["type"] == "bluetooth"), None)

    def _watch(self):
        """Every few seconds: one cheap read of the connection list (never a
        scan), then decide about the backup in _on_polled."""
        if not self._available or self._polling:
            return
        self._polling = True

        def work():
            result = None            # stays this if nmcli fails or crashes: _on_polled changes nothing
            try:
                control = self._control or can_control()
                conns = connections()
                if conns is not None:
                    result = (conns, control)
                self._logged("watchdog")
            except Exception as e:
                self._logged("watchdog", e)
            finally:
                safe_emit(self, "_polled", result)    # always, or _polling would never clear
        threading.Thread(target=work, daemon=True).start()

    def _on_polled(self, result):
        self._polling = False
        if result is None:
            return
        conns, control = result
        ssids = {c["uuid"]: c["ssid"] for c in self._saved}     # the poll doesn't look these up
        for c in conns:
            c["ssid"] = ssids.get(c["uuid"], "")
        if (conns, control) != (self._saved, self._control):
            self._saved, self._control = conns, control
            self.changed.emit()
        wifi = next((c for c in conns if c["type"] == "802-11-wireless" and c["device"]), None)
        if control and wifi and wifi["name"] not in self._hotspot_done:
            threading.Thread(target=self._ensure_hotspot_address, daemon=True).start()
        self._tether_step(wifi is not None)

    def _tether_step(self, on_wifi):
        now = time.monotonic()
        if on_wifi:
            self._no_wifi_since = None
            self._wifi_since = self._wifi_since or now
        else:
            self._wifi_since = None
            self._no_wifi_since = self._no_wifi_since or now
        conn = self._tether_conn()
        if not (self._control and conn):
            return
        tethered = bool(conn["device"])
        if (self._tether and not on_wifi and not tethered
                and now - self._no_wifi_since > TETHER_AFTER_S
                and now - self._last_tether_try > TETHER_RETRY_S):
            self._last_tether_try = now
            threading.Thread(target=lambda: nmcli("connection", "up", "uuid", conn["uuid"], timeout=40),
                             daemon=True).start()
        elif tethered and (not self._tether or (on_wifi and now - self._wifi_since > UNTETHER_AFTER_S)):
            threading.Thread(target=lambda: nmcli("connection", "down", "uuid", conn["uuid"]),
                             daemon=True).start()

    @pyqtSlot(bool)
    def setTethering(self, on):
        if on != self._tether:
            self._tether = on
            self._settings.set("tethering", "true" if on else "false")
            self.changed.emit()

    # ---- what QML sees ------------------------------------------------------
    @pyqtProperty(bool, constant=True)
    def available(self):
        return self._available

    @pyqtProperty(bool, notify=changed)
    def canControl(self):
        return self._control

    @pyqtProperty("QVariantList", notify=changed)
    def networks(self):
        return self._networks

    @pyqtProperty(str, notify=changed)
    def busy(self):
        """The network being joined right now, or ''."""
        return self._busy

    @pyqtProperty(str, notify=changed)
    def message(self):
        return self._message

    @pyqtProperty(bool, notify=changed)
    def tethering(self):
        return self._tether

    @pyqtProperty(str, notify=changed)
    def tetherPhone(self):
        """The phone NetworkManager can tether to over Bluetooth, or ''."""
        c = self._tether_conn()
        return c["name"].removesuffix(" Network") if c else ""

    @pyqtProperty(bool, notify=changed)
    def tetherActive(self):
        c = self._tether_conn()
        return bool(c and c["device"])
