"""Settings that survive a restart (style, volume, units).

Stored with QSettings in ~/.config/baja-os/baja-os.conf. Values come back
as strings from that file, so callers convert what they read.
"""

from PyQt6.QtCore import QObject, QSettings, pyqtSlot


class Settings(QObject):
    def __init__(self, parent=None):
        super().__init__(parent)
        self._store = QSettings("baja-os", "baja-os")

    @pyqtSlot(str, "QVariant", result="QVariant")
    def get(self, key, default=None):
        return self._store.value(key, default)

    @pyqtSlot(str, "QVariant")
    def set(self, key, value):
        if self._store.value(key) != value:
            self._store.setValue(key, value)
            self._store.sync()  # power can vanish any moment in a car

    def get_int(self, key, default):
        try:
            return int(self._store.value(key, default))
        except (TypeError, ValueError):
            return default
