"""Network status for the Settings page: IP address, Wi-Fi name, online.

Checks run on a background thread every few seconds, because looking up the
Wi-Fi name and testing the internet connection can each take a moment.
"""

import getpass
import shutil
import socket
import subprocess
import threading

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
        out = subprocess.run(["nmcli", "-t", "-f", "active,ssid", "dev", "wifi"],
                             capture_output=True, text=True, timeout=3).stdout
    except (OSError, subprocess.SubprocessError):
        return ""
    for line in out.splitlines():
        if line.startswith("yes:"):
            return line[4:]
    return ""


def is_online():
    try:
        with socket.create_connection(PROBE_HOST, timeout=2):
            return True
    except OSError:
        return False


class Network(QObject):
    changed = pyqtSignal()
    _result = pyqtSignal(str, str, bool)

    def __init__(self, parent=None):
        super().__init__(parent)
        self._ip = ""
        self._ssid = ""
        self._online = False
        self._checked = False
        self._busy = False
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
        safe_emit(self, "_result", local_ip(), wifi_name(), is_online())

    def _apply(self, ip, ssid, online):
        self._busy = False
        if (ip, ssid, online, True) != (self._ip, self._ssid, self._online, self._checked):
            self._ip, self._ssid, self._online, self._checked = ip, ssid, online, True
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
    def checked(self):
        """False until the first check finishes."""
        return self._checked

    @pyqtProperty(str, constant=True)
    def user(self):
        """Login name, for showing the exact ssh command."""
        return getpass.getuser()
