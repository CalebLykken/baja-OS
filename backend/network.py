"""Network status for the Settings page: IP address, Wi-Fi name, online.

Checks run on a background thread every few seconds, because looking up the
Wi-Fi name and testing the internet connection can each take a moment.
"""

import getpass
import shutil
import socket
import subprocess
import threading
import traceback

from PyQt6.QtCore import QObject, QTimer, pyqtProperty, pyqtSignal

from backend import safe_emit

CHECK_EVERY_MS = 5000
PROBE_HOST = ("1.1.1.1", 53)  # Cloudflare DNS: answers quickly when online


def local_ip():
    """The address this machine uses to reach the internet, or ''."""
    # A UDP "connect" picks the outgoing interface without sending anything.
    try:
        with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as s:
            s.connect(PROBE_HOST)
            return s.getsockname()[0]
    except OSError:
        return ""


def wifi_name():
    """Name of the connected Wi-Fi network via NetworkManager, or ''."""
    if not shutil.which("nmcli"):
        return ""
    try:
        # --rescan no: a bare `dev wifi` scans whenever its list is over 30 s old,
        # which pulls the radio off the hotspot's channel every few seconds.
        out = subprocess.run(["nmcli", "-t", "-f", "active,ssid", "dev", "wifi", "list", "--rescan", "no"],
                             capture_output=True, text=True, timeout=3).stdout
    except (OSError, subprocess.SubprocessError):
        return ""
    for line in out.splitlines():
        if line.startswith("yes:"):
            return line[4:]
    return ""


def nm_connectivity():
    """NetworkManager's own connectivity check: full/limited/portal/none, or
    None when nmcli is missing, NM isn't running or it can't say."""
    if not shutil.which("nmcli"):
        return None
    try:
        r = subprocess.run(["nmcli", "-t", "networking", "connectivity"],
                           capture_output=True, text=True, timeout=3)
    except (OSError, subprocess.SubprocessError):
        return None
    state = r.stdout.strip()
    if r.returncode != 0 or state not in ("full", "limited", "portal", "none"):
        return None                       # error, or "unknown": ask the probe instead
    return state


def tcp_online():
    try:
        with socket.create_connection(PROBE_HOST, timeout=2):
            return True
    except OSError:
        return False


def internet_state():
    """(online, portal). NetworkManager's check sees captive portals, which a
    TCP probe can't; the probe is the fallback where NM isn't there (the Mac)."""
    state = nm_connectivity()
    if state is None:
        return tcp_online(), False
    return state == "full", state == "portal"


class Network(QObject):
    changed = pyqtSignal()
    _result = pyqtSignal(object)    # (ip, ssid, online, portal), or None if the check crashed

    def __init__(self, parent=None):
        super().__init__(parent)
        self._ip = ""
        self._ssid = ""
        self._online = False
        self._portal = False
        self._checked = False
        self._busy = False
        self._check_error = ""     # the error the last check died of, while it keeps happening
        self._result.connect(self._apply)  # queued back onto the UI thread
        self._timer = QTimer(self)
        self._timer.setInterval(CHECK_EVERY_MS)
        self._timer.timeout.connect(self._check)

    def start(self):
        self._check()
        self._timer.start()

    def _check(self):
        if self._busy:
            return
        self._busy = True
        threading.Thread(target=self._work, daemon=True).start()

    def _work(self):
        result = None
        try:
            result = (local_ip(), wifi_name(), *internet_state())
            self._logged()
        except Exception as e:
            self._logged(e)
        finally:
            safe_emit(self, "_result", result)    # always, or _busy would never clear

    def _logged(self, error=None):
        """Log a check that crashed (once, while the same error repeats), or
        that it's working again."""
        err = "" if error is None else f"{type(error).__name__}: {error}"
        if err and err != self._check_error:
            trace = "".join(traceback.format_exception(error)).rstrip()
            print(f"Network: check failed: {err}\n{trace}", flush=True)
        elif not err and self._check_error:
            print("Network: working again", flush=True)
        self._check_error = err

    def _apply(self, result):
        self._busy = False
        if result is None:
            return                        # the check crashed: keep what we had
        ip, ssid, online, portal = result
        if (ip, ssid, online, portal, True) != (self._ip, self._ssid, self._online, self._portal, self._checked):
            self._ip, self._ssid, self._online, self._portal, self._checked = ip, ssid, online, portal, True
            self.changed.emit()

    @pyqtProperty(str, notify=changed)
    def ip(self):
        return self._ip

    @pyqtProperty(str, notify=changed)
    def ssid(self):
        return self._ssid

    @pyqtProperty(bool, notify=changed)
    def online(self):
        return self._online

    @pyqtProperty(bool, notify=changed)
    def portal(self):
        """Connected, but a captive portal wants a sign-in first."""
        return self._portal

    @pyqtProperty(bool, notify=changed)
    def checked(self):
        """False until the first check finishes."""
        return self._checked

    @pyqtProperty(str, constant=True)
    def user(self):
        """Login name, for showing the exact ssh command."""
        return getpass.getuser()
