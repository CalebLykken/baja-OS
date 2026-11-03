"""Settings that survive a restart (style, volume, units).

Stored with QSettings in ~/.config/baja-os/baja-os.conf. Values come back
as strings from that file, so callers convert what they read.

Qt rewrites the whole file, with an fsync, on every sync (and setValue posts
a write of its own for the next event-loop pass). On the Pi's SD card that
can freeze the UI for a good while, and the file holds big blobs (the Spotify
library) while the music position, the volume knob and the sliders save many
times a minute. So changes wait in memory and go to QSettings together, a
moment after the last one. Keys in IMMEDIATE (a power cut a second later
would hurt) are written at once. flush() writes whatever is waiting: the app
calls it on the way out and before it powers the Pi off or reboots it.
"""

from PyQt6.QtCore import QObject, QSettings, QTimer, pyqtSlot

FLUSH_AFTER_MS = 1500
# The route is what the truck picks up again after a power cut mid-drive.
IMMEDIATE = frozenset({"route"})


class Settings(QObject):
    def __init__(self, parent=None, store=None, flush_after_ms=FLUSH_AFTER_MS):
        super().__init__(parent)
        self._store = store if store is not None else QSettings("baja-os", "baja-os")
        self._pending = {}                  # changed, not yet in the store
        self._flush_timer = QTimer(self, singleShot=True, interval=flush_after_ms,
                                   timeout=self.flush)

    @pyqtSlot(str, "QVariant", result="QVariant")
    def get(self, key, default=None):
        if key in self._pending:
            return self._pending[key]
        return self._store.value(key, default)

    @pyqtSlot(str, "QVariant")
    def set(self, key, value):
        if self.get(key) == value:
            return
        self._pending[key] = value
        if key in IMMEDIATE:
            self.flush()
        else:
            self._flush_timer.start()       # restarts: one write after a burst

    @pyqtSlot()
    def flush(self):
        """Write what's waiting to the file, now."""
        self._flush_timer.stop()
        if not self._pending:
            return
        pending, self._pending = self._pending, {}
        for key, value in pending.items():
            self._store.setValue(key, value)
        self._store.sync()

    def get_int(self, key, default):
        try:
            return int(self.get(key, default))
        except (TypeError, ValueError):
            return default
