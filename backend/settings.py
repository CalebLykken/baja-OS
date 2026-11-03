"""Settings that survive a restart (style, volume, units).

Stored with QSettings in ~/.config/baja-os/baja-os.conf. Values come back
as strings from that file, so callers convert what they read.
"""

from PyQt6.QtCore import QCoreApplication, QObject, QSettings, QTimer, pyqtSlot

from backend.syncthrottle import SyncThrottle


class Settings(QObject):
    def __init__(self, parent=None):
        super().__init__(parent)
        self._store = QSettings("baja-os", "baja-os")
        self._throttle = SyncThrottle()
        self._timer = QTimer(self)
        self._timer.setSingleShot(True)
        self._timer.timeout.connect(self._sync)
        app = QCoreApplication.instance()
        if app is not None:
            app.aboutToQuit.connect(self.flush)

    @pyqtSlot(str, "QVariant", result="QVariant")
    def get(self, key, default=None):
        return self._store.value(key, default)

    @pyqtSlot(str, "QVariant")
    def set(self, key, value):
        if self._store.value(key) != value:
            self._store.setValue(key, value)
            # Power can vanish any moment in a car, so an isolated change
            # syncs at once; a burst (knob spin) folds into one sync per 250 ms.
            if self._throttle.changed() == "now":
                self._sync()
            elif not self._timer.isActive():
                self._timer.start(int(self._throttle.due_in() * 1000))

    def _sync(self):
        self._timer.stop()
        self._store.sync()
        self._throttle.synced()

    @pyqtSlot()
    def flush(self):
        if self._throttle.pending:
            self._sync()

    def get_int(self, key, default):
        try:
            return int(self._store.value(key, default))
        except (TypeError, ValueError):
            return default
