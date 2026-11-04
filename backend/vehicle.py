"""Vehicle data exposed to the UI.

Real engine data comes from the OBD-II adapter (backend/obd.py) whenever
the car answers; `live` is then True. Without it a simulated drive keeps
the gauges moving, but only where that's wanted (`simulated`): a Mac, a
bench Pi, or --demo. Once the car has answered on this install the truck
never makes numbers up again: the engine values are unknown (0 here, a
dash in the UI) until it answers. The battery is the exception, because
the adapter reads it with the engine computer asleep: a real reading counts
for VOLTS_MS and beats the simulation's. Gear isn't reported over OBD, so
it's worked out from speed and RPM.

`speed` is the one speed every page reads (mph): the car's while it answers,
else a fresh GPS fix's, else the simulation (where that's wanted, and only
until the receiver has given a real position), else unknown (`speedKnown`
False, a dash in the UI). The gear only ever comes from the car's own speed.

LIMITS are the one place for the warning thresholds: the gauges draw their
red zones from them, and `warnings` (from the car only, never the
simulation) drives the warning on every page and the red readouts.
"""

import math
import random
import time

from PyQt6.QtCore import QObject, QTimer, pyqtProperty, pyqtSignal, pyqtSlot

from backend.demo import allowed
from backend.gps import MPH_TO_MS
from backend.obd import describe
from backend.prefs import as_bool

UPDATE_MS = 200  # 5 updates per second is plenty for gauges and cheap on a Pi 2
LAUNCH_MAX_S = 30  # a run from a standstill to 60 mph taking longer than this isn't a launch
STALE_MS = 4000  # no engine data for this long: the car has gone quiet
VOLTS_MS = 180000  # a battery reading is current this long after the latest one
ENGINE = ("rpm", "speed", "boost", "coolant", "intake")  # what only the car can answer

# Rough 5-speed gearing for the 2005 Baja Turbo: mph per 1000 rpm in each gear.
GEARS = [6.5, 11.5, 17.0, 22.5, 28.0]

# Where a reading needs attention, in the truck's units (rpm, psi, °F, volts).
LIMITS = {
    "rpmHigh": 6000.0,
    "boostHigh": 15.0,          # overboost
    "coolantHigh": 230.0,       # overheating
    "intakeHigh": 150.0,
    "voltageLow": 12.0,         # not charging
    "voltageHigh": 15.0,        # overcharging
}


def warnings(coolant, voltage, boost, mil=False):
    """The engine readings out of range, most urgent first: 'coolant',
    'voltage' and 'boost', then 'mil' (the check-engine lamp is on). A
    voltage of None (not read lately) can't warn."""
    found = []
    if coolant > LIMITS["coolantHigh"]:
        found.append("coolant")
    if voltage is not None and not LIMITS["voltageLow"] <= voltage <= LIMITS["voltageHigh"]:
        found.append("voltage")
    if boost > LIMITS["boostHigh"]:
        found.append("boost")
    if mil:
        found.append("mil")
    return found


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
    simulatedChanged = pyqtSignal()
    engineKnownChanged = pyqtSignal()
    speedKnownChanged = pyqtSignal()
    voltageKnownChanged = pyqtSignal()
    codesChanged = pyqtSignal()
    launchChanged = pyqtSignal()

    def __init__(self, settings=None, demo=None, parent=None):
        """`demo` is main.py's --demo (True), --no-demo (False) or neither
        (None). Left alone, the simulation runs only until the car has
        answered on this install (the "carAnswered" setting)."""
        super().__init__(parent)
        self._settings = settings
        self._demo = demo
        self._answered = settings is not None and as_bool(settings.get("carAnswered"))
        self._t = 0.0
        self._rpm = 800.0
        self._speed = 0.0
        self._boost = -18.0  # psi; negative = vacuum
        self._coolant = 120.0  # degrees F, warms up over the first minute
        self._intake = 72.0
        self._voltage = 14.2
        self._gear = 1
        self._live = False
        self._volts_real = False  # `_voltage` is the adapter's reading, current
        self._mil, self._codes, self._codes_count = False, [], 0   # the check-engine lamp, from the car
        self._gps = None
        self._gps_mph = None      # the GPS's speed while its fix is real and fresh
        self._gps_real = False    # the receiver has given a real position (fresh or held)
        self._clock = time.monotonic   # injectable for tests
        self._launch_at = None    # when the truck last stood still (or None: not armed)
        self._launch_six = False  # ... and has already passed 60 mph
        self._zero_sixty = 0.0    # seconds, the last 0-60 mph (0 = none yet); memory only
        self._zero_hundred = 0.0  # likewise 0-100 km/h
        self._stale = QTimer(self, singleShot=True, interval=STALE_MS, timeout=self.lost_obd)
        self._volts_stale = QTimer(self, singleShot=True, interval=VOLTS_MS, timeout=self._volts_aged)
        self._timer = QTimer(self)
        self._timer.setInterval(UPDATE_MS)
        self._timer.timeout.connect(self._tick)

    def start(self):
        self._timer.start()

    def set_gps(self, gps):
        """Take the speed from `gps` (backend/gps.py) while the car isn't
        answering. main.py makes the GPS after this, so it's handed over
        later."""
        self._gps = gps
        gps.changed.connect(self._gps_changed)
        self._gps_changed()

    def _gps_changed(self):
        """The GPS has news: its speed may be the one shown now."""
        before, was = self._flags(), self.speed
        gps = self._gps
        self._gps_mph = gps.speed / MPH_TO_MS if gps.realFix else None
        self._gps_real = gps.source == "gps"
        if self.speed != was or self._flags() != before:
            self._settle(before)

    def _flags(self):
        return self._live, self.simulated, self.engineKnown, self.speedKnown, self.voltageKnown

    def _settle(self, before):
        """Say which of the flags flipped since `before` (a _flags()), then
        that the values did, so the UI refreshes."""
        signals = (self.liveChanged, self.simulatedChanged, self.engineKnownChanged,
                   self.speedKnownChanged, self.voltageKnownChanged)
        for was, now, signal in zip(before, self._flags(), signals):
            if was != now:
                signal.emit()
        self._watch_launch()
        self.changed.emit()

    def _watch_launch(self):
        """Time a 0-60 mph (and 0-100 km/h) run from the speeds already
        arriving. Only real speeds count, and only runs that start from under
        1 mph; a stop, a long crawl or a lost speed abandons the run."""
        mph = None if self.simulated else self._speed_now()
        if mph is None or mph < 1:
            # armed: the start is refreshed until the moment it rolls
            self._launch_at = None if mph is None else self._clock()
            self._launch_six = False
            return
        if self._launch_at is None:
            return                                  # a rolling start, or this run is done
        took = self._clock() - self._launch_at
        if took > LAUNCH_MAX_S:
            self._launch_at = None
            return
        found = False
        if mph >= 60 and not self._launch_six:
            self._launch_six, self._zero_sixty, found = True, round(took, 1), True
        if mph >= 100 / 1.609344:
            self._zero_hundred, found = round(took, 1), True
            self._launch_at = None
        if found:
            self.launchChanged.emit()

    # ---- the real thing ---------------------------------------------------
    def apply_obd(self, values):
        """Fresh readings from the car (rpm, speed mph, boost psi, coolant
        and intake °F, voltage), any subset. The voltage alone doesn't make
        the car live: the adapter reads it whether the car answers or not."""
        before = self._flags()
        answering = False
        for key in ENGINE:
            if key in values:
                setattr(self, "_" + key, float(values[key]))
                answering = True
        if "voltage" in values:
            self._take_voltage(float(values["voltage"]))
        if answering:
            self._gear = estimate_gear(self._speed, self._rpm)
            self._stale.start()
            self._live = True
            if not self._answered:
                self._answered = True      # from now on the truck never simulates by itself
                if self._settings is not None:
                    self._settings.set("carAnswered", "true")
        self._settle(before)

    def lost_obd(self):
        """The readings stopped: the car went quiet, or the adapter went.
        The battery reading stays; it ages out by itself."""
        self._clear_codes()                # unknown while the car isn't answering
        if self._live:
            before = self._flags()
            self._live = False
            self._settle(before)           # no more warnings

    @pyqtSlot(dict)
    def apply_codes(self, found):
        """The check-engine lamp and trouble codes from the car (ObdReader's
        `codes`): {"mil": bool, "count": int, "stored": [...], "pending": [...]}."""
        self._mil = bool(found.get("mil"))
        stored = list(found.get("stored", []))
        self._codes = [{"code": c, "text": describe(c), "pending": False} for c in stored]
        self._codes += [{"code": c, "text": describe(c), "pending": True}
                        for c in found.get("pending", []) if c not in stored]
        self._codes_count = max(int(found.get("count", 0)), len(stored))
        self.codesChanged.emit()
        self.changed.emit()

    def _clear_codes(self):
        if self._mil or self._codes or self._codes_count:
            self._mil, self._codes, self._codes_count = False, [], 0
            self.codesChanged.emit()
            self.changed.emit()

    def apply_voltage(self, volts):
        """The battery, from every ATRV reading of the adapter (the car
        answering or not). It's real in a parked truck, so it wins over the
        simulation's."""
        volts = float(volts)
        if self._volts_real and volts == self._voltage:
            self._volts_stale.start()      # same as before: still current
            return
        before = self._flags()
        self._take_voltage(volts)
        self._settle(before)

    def _take_voltage(self, volts):
        self._voltage = volts
        self._volts_real = True
        self._volts_stale.start()

    def _volts_aged(self):
        """No battery reading for VOLTS_MS: don't keep showing the old one."""
        before = self._flags()
        self._volts_real = False
        self._settle(before)

    @pyqtProperty(bool, notify=liveChanged)
    def live(self):
        """True while the numbers come from the car, not the simulation."""
        return self._live

    @pyqtProperty(bool, notify=simulatedChanged)
    def simulated(self):
        """True while the engine numbers are made up: the car isn't
        answering and a simulation is wanted here (a fresh install, --demo)."""
        return not self._live and allowed(self._demo, not self._answered)

    @pyqtProperty(bool, notify=engineKnownChanged)
    def engineKnown(self):
        """Whether the engine values are worth showing, real or simulated;
        the UI shows a dash when not."""
        return self._live or self.simulated

    @pyqtProperty(bool, notify=speedKnownChanged)
    def speedKnown(self):
        """Whether `speed` is worth showing: the car's, a fresh GPS fix's or
        the simulation's. Known from the GPS alone while the engine isn't."""
        return self._speed_now() is not None

    @pyqtProperty(bool, notify=voltageKnownChanged)
    def voltageKnown(self):
        """Whether the battery voltage is worth showing: the adapter read it
        lately, or it's simulated."""
        return self._volts_real or self.simulated

    @pyqtProperty("QVariantMap", constant=True)
    def limits(self):
        """The warning thresholds (LIMITS), for the gauges' red zones."""
        return LIMITS

    @pyqtProperty("QStringList", notify=changed)
    def warnings(self):
        """The readings out of range ('coolant', 'voltage', 'boost') and
        'mil' (the check-engine lamp is on), from the car only: the
        simulation never warns."""
        if not self._live:
            return []
        return warnings(self._coolant, self._voltage if self._volts_real else None, self._boost,
                        mil=self._mil)

    @pyqtProperty(bool, notify=codesChanged)
    def milOn(self):
        """The check-engine lamp, as the car last said (off when unknown)."""
        return self._mil

    @pyqtProperty(int, notify=codesChanged)
    def codeCount(self):
        """How many trouble codes the car has stored."""
        return self._codes_count

    @pyqtProperty("QVariantList", notify=codesChanged)
    def codes(self):
        """The stored then pending trouble codes: {code, text, pending}."""
        return self._codes

    # ---- the simulated drive ----------------------------------------------
    def _tick(self):
        if not self.simulated:
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
        if not self._volts_real:
            self._voltage = 14.2 + random.uniform(-0.08, 0.08)

        self.changed.emit()

    def _engine(self, value):
        """What the UI reads: 0 for an engine value that isn't known."""
        return value if self.engineKnown else 0.0

    @pyqtProperty(float, notify=launchChanged)
    def zeroToSixty(self):
        """Seconds the last 0-60 mph run took (0 = none yet)."""
        return self._zero_sixty

    @pyqtProperty(float, notify=launchChanged)
    def zeroToHundred(self):
        """Seconds the last 0-100 km/h run took (0 = none yet)."""
        return self._zero_hundred

    @pyqtProperty(float, notify=changed)
    def rpm(self):
        return self._engine(self._rpm)

    def _speed_now(self):
        """The speed to show in mph, or None: the car's, else a real fresh
        GPS fix's, else the simulation's (only where that's wanted). Not the
        simulation's once the receiver has had a real position: a real truck
        on a fresh install would jump from 30 to a made-up 47 in a tunnel."""
        if self._live:
            return self._speed
        if self._gps_mph is not None:
            return self._gps_mph
        return self._speed if self.simulated and not self._gps_real else None

    @pyqtProperty(float, notify=changed)
    def speed(self):
        """mph, the one speed every page shows (0 while not `speedKnown`)."""
        mph = self._speed_now()
        return 0.0 if mph is None else mph

    @pyqtProperty(float, notify=changed)
    def boost(self):
        return self._engine(self._boost)

    @pyqtProperty(float, notify=changed)
    def coolant(self):
        return self._engine(self._coolant)

    @pyqtProperty(float, notify=changed)
    def intake(self):
        return self._engine(self._intake)

    @pyqtProperty(float, notify=changed)
    def voltage(self):
        return self._voltage if self.voltageKnown else 0.0

    @pyqtProperty(int, notify=changed)
    def gear(self):
        return self._gear if self.engineKnown else 0
