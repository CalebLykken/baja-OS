"""Tell systemd the app is up and still alive (sd_notify), with no extra deps.

baja-os.service is Type=notify with a watchdog: the app reports READY once
its window is showing, then pings on a timer running on the UI thread. If
the UI thread hangs, the pings stop and systemd restarts the dashboard.
Off systemd (a Mac, or run by hand) NOTIFY_SOCKET isn't set and these are
no-ops.
"""

import os
import socket

from PyQt6.QtCore import QObject, QTimer


def notify(message):
    addr = os.environ.get("NOTIFY_SOCKET")
    if not addr:
        return
    if addr.startswith("@"):            # abstract socket namespace
        addr = "\0" + addr[1:]
    try:
        with socket.socket(socket.AF_UNIX, socket.SOCK_DGRAM) as s:
            s.setblocking(False)        # a full queue drops this ping, never stalls the UI
            s.connect(addr)
            s.sendall(message.encode())
    except OSError:                     # includes BlockingIOError
        pass


def _watchdog_usec():
    """WATCHDOG_USEC as a positive int, or 0 (no watchdog) if unset, malformed or <= 0."""
    try:
        usec = int(os.environ.get("WATCHDOG_USEC", "0") or 0)
    except (ValueError, TypeError):
        return 0
    return usec if usec > 0 else 0


class Watchdog(QObject):
    """Pings systemd's watchdog at half its timeout, from the UI thread."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self._timer = QTimer(self)
        self._timer.timeout.connect(lambda: notify("WATCHDOG=1"))
        self._usec = _watchdog_usec()
        if self._usec:
            # QTimer takes a C int; clamp so a huge value can't overflow it
            self._timer.setInterval(min(max(1000, self._usec // 2000), 2**31 - 1))

    def start(self):
        notify("READY=1")
        if self._usec:
            self._timer.start()
