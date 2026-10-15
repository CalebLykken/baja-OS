"""Vehicle data exposed to the UI.

Real engine data comes from the OBD-II adapter (backend/obd.py) whenever
the car answers; `live` is then True. Without it (no adapter, key off, at
a desk) a simulated drive keeps the gauges moving. Gear isn't reported over
OBD, so it's worked out from speed and RPM.
"""

import math
import random

from PyQt6.QtCore import QObject, QTimer, pyqtProperty, pyqtSignal

UPDATE_MS = 200  # 5 updates per second is plenty for gauges and cheap on a Pi 2
STALE_MS = 4000  # no engine data for this long: back to the simulation

# Rough 5-speed gearing for the 2005 Baja Turbo: mph per 1000 rpm in each gear.
GEARS = [6.5, 11.5, 17.0, 22.5, 28.0]


def estimate_gear(mph, rpm):
    """The gear whose ratio fits speed and RPM best, or 0 (stopped, clutch
    in, or between gears)."""
    if mph < 3 or rpm < 500:
        return 0
    per_k = mph / (rpm / 1000)
    best = min(range(len(GEARS)), key=lambda i: abs(per_k - GEARS[i]))
    return best + 1 if abs(per_k - GEARS[best]) / GEARS[best] < 0.12 else 0


class VehicleData(QObject):
    changed = pyqtSignal()
    liveChanged = pyqtSignal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self._t = 0.0
        self._rpm = 800.0
        self._speed = 0.0
        self._boost = -18.0  # psi; negative = vacuum
        self._coolant = 120.0  # degrees F, warms up over the first minute
        self._intake = 72.0
        self._voltage = 14.2
        self._gear = 1
        self._live = False
        self._stale = QTimer(self, singleShot=True, interval=STALE_MS, timeout=self.lost_obd)
        self._timer = QTimer(self)
        self._timer.setInterval(UPDATE_MS)
        self._timer.timeout.connect(self._tick)

    def start(self):
        self._timer.start()

    # ---- the real thing ---------------------------------------------------
    def apply_obd(self, values):
        """Fresh readings from the car (rpm, speed mph, boost psi, coolant
        and intake °F, voltage), any subset."""
        for key in ("rpm", "speed", "boost", "coolant", "intake", "voltage"):
            if key in values:
                setattr(self, "_" + key, float(values[key]))
        self._gear = estimate_gear(self._speed, self._rpm)
        self._stale.start()
        if not self._live:
            self._live = True
            self.liveChanged.emit()
        self.changed.emit()

    def lost_obd(self):
        if self._live:
            self._live = False
            self.liveChanged.emit()

    @pyqtProperty(bool, notify=liveChanged)
    def live(self):
        """True while the numbers come from the car, not the simulation."""
        return self._live

    # ---- the simulated drive ----------------------------------------------
    def _tick(self):
        if self._live:
            return
        dt = UPDATE_MS / 1000.0
        self._t += dt
        t = self._t

        # Throttle wanders between cruising and the occasional pull.
        throttle = 0.35 + 0.3 * math.sin(t * 0.25) + 0.25 * max(0.0, math.sin(t * 0.9))
        throttle = max(0.0, min(1.0, throttle))

        target_speed = 15 + 55 * (0.5 + 0.5 * math.sin(t * 0.05))
        self._speed += (target_speed - self._speed) * 0.04 + (throttle - 0.5) * 0.3
        self._speed = max(0.0, self._speed)

        # Pick the gear that keeps rpm in a normal driving range.
        gear = 1
        for i, mph_per_k in enumerate(GEARS, start=1):
            if self._speed / mph_per_k * 1000 >= 1800 or i == 1:
                gear = i
        self._gear = gear
        rpm = max(800.0, self._speed / GEARS[gear - 1] * 1000 + throttle * 600)
        self._rpm = min(rpm, 6800.0)

        # Turbo: vacuum at light load, positive boost once spooled.
        spool = max(0.0, min(1.0, (self._rpm - 2400) / 1600))
        target_boost = -18 + throttle * 18 + spool * throttle * 14
        self._boost += (target_boost - self._boost) * 0.25

        self._coolant += (196 - self._coolant) * 0.01 + random.uniform(-0.2, 0.2)
        self._intake += (70 + max(0.0, self._boost) * 3 - self._intake) * 0.05
        self._voltage = 14.2 + random.uniform(-0.08, 0.08)

        self.changed.emit()

    @pyqtProperty(float, notify=changed)
    def rpm(self):
        return self._rpm

    @pyqtProperty(float, notify=changed)
    def speed(self):
        return self._speed

    @pyqtProperty(float, notify=changed)
    def boost(self):
        return self._boost

    @pyqtProperty(float, notify=changed)
    def coolant(self):
        return self._coolant

    @pyqtProperty(float, notify=changed)
    def intake(self):
        return self._intake

    @pyqtProperty(float, notify=changed)
    def voltage(self):
        return self._voltage

    @pyqtProperty(int, notify=changed)
    def gear(self):
        return self._gear
