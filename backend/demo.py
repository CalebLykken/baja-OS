"""Whether this run may make things up: the simulated drive, the demo
playlist, the Seattle demo loop.

On the Mac everything is simulated so the UI can be worked on. In the truck
the dashboard must only show what's real. Each backend decides for itself
when it's allowed to fall back to its demo (see their docstrings); --demo
and --no-demo on the command line force the choice for all of them.

DemoDrive (below) is the scripted drive for the simulated engine: stops, real
launches, a cold engine that warms up. It is only for the simulated drive and
must never run where the car's data is real; the gate stays allowed() here and
VehicleData.simulated. It is plain Python (math and random only, no Qt) and
nothing runs at import time.
"""

import math
import random
from pathlib import Path

MODEL = Path("/proc/device-tree/model")


def on_pi():
    """True on a Raspberry Pi (the truck or a bench Pi)."""
    try:
        return "Raspberry Pi" in MODEL.read_text(errors="ignore")
    except OSError:
        return False


def allowed(flag, default):
    """flag is True for --demo, False for --no-demo, None for neither;
    default is what the backend picks when it isn't forced."""
    return default if flag is None else flag


# mph per 1000 rpm in each gear; mirrors GEARS in backend/vehicle.py (not
# imported: vehicle.py imports this module).
GEARS = [6.5, 11.5, 17.0, 22.5, 28.0]

_FULL_ACCEL = 10.8   # mph/s at a standstill with the throttle floored
_TOP_SPEED = 110.0   # accel tapers to zero here: gives a ~8 s 0-60
_JERK = 12.0         # mph/s^2: how fast acceleration may change
_WARM_TAU = 220.0    # s: coolant time constant from cold
_COOLANT_COLD = 120.0
_COOLANT_HOT = 196.0


class DemoDrive:
    """A scripted drive: idle at a light, launch, cruise, a corner, stop and
    go, a highway pull, a long coast to a stop, then round again. Seeded
    randomness varies phase lengths and target speeds.

    Only for the simulated drive. step() is O(1) and allocates only the dict
    it returns (the phase list is rebuilt once per cycle, not per step)."""

    def __init__(self, seed=None):
        self._rng = random.Random(seed)
        self._t = 0.0
        self._speed = 0.0
        self._accel = 0.0
        self._gear = 1
        self._throttle = 0.0
        self._boost = -18.0
        self._intake = 72.0
        self._wobble = 0.0
        self._phases = []
        self._idx = 0
        self._phase_t = 0.0
        self._first = True
        self._next_cycle()

    # ---- the script -------------------------------------------------------
    def _next_cycle(self):
        r = self._rng.uniform
        idle0 = r(8, 12) if self._first else r(6, 12)
        self._first = False
        # (kind, target mph, seconds, comfortable decel mph/s)
        # idle: stand still; full: floor it up to target; ease: hold target;
        # stop: brake to a standstill.
        ph = [("idle", 0.0, idle0, 0.0),
              ("full", r(64, 72), 30.0, 0.0),
              ("ease", r(48, 58), r(18, 28), 4.0),
              ("ease", r(18, 26), r(5, 9), 4.0)]
        for _ in range(2):
            ph += [("ease", r(28, 38), r(7, 11), 4.0),
                   ("stop", 0.0, 40.0, 4.0),
                   ("idle", 0.0, r(4, 7), 0.0)]
        ph += [("ease", r(40, 50), r(8, 12), 4.0),
               ("full", r(74, 80), 30.0, 0.0),
               ("ease", r(74, 80), r(15, 25), 4.0),
               ("stop", 0.0, 60.0, 1.8)]
        self._phases = ph
        self._idx = 0
        self._phase_t = 0.0

    def _advance_phase(self, speed_target):
        kind, target, dur, _dec = self._phases[self._idx]
        v = self._speed
        if kind == "idle":
            done = self._phase_t >= dur
        elif kind == "full":
            done = v >= speed_target or self._phase_t >= dur
        elif kind == "stop":
            done = v <= 0.0 or self._phase_t >= dur
        else:
            done = self._phase_t >= dur
        if done:
            self._idx += 1
            self._phase_t = 0.0
            if self._idx >= len(self._phases):
                self._next_cycle()

    # ---- one tick ---------------------------------------------------------
    def step(self, dt, limit_mph=None):
        """Advance dt seconds. limit_mph, when given, caps the target speed:
        the drive eases off and brakes smoothly toward it."""
        if dt <= 0:
            return self._state()
        self._t += dt
        self._phase_t += dt
        kind, target, _dur, dec = self._phases[self._idx]
        v = self._speed
        capped = limit_mph is not None and limit_mph < target
        tv = float(limit_mph) if capped else target
        if limit_mph is not None and kind == "stop":
            tv = 0.0
        avail = max(1.0, _FULL_ACCEL * (1.0 - v / _TOP_SPEED))

        if kind == "idle":
            want = -min(6.0, v) / dt if v > 0 else 0.0
        elif kind == "full" and not capped:
            want = avail
        elif tv <= 0.0:
            # braking to a stop: gentle, but always arriving
            d = 8.0 if limit_mph is not None else dec
            want = -min(d, max(1.2, v * 0.8)) if v > 0 else 0.0
        else:
            d = 8.0 if capped else (dec or 4.0)
            gain = 1.0 if capped else 0.5
            want = max(-d, min(0.6 * avail, (tv - v) * gain))

        step = _JERK * dt
        self._accel += max(-step, min(step, want - self._accel))
        v += self._accel * dt
        if v < 0.5 and (tv <= 0.0 or kind == "idle") and self._accel <= 0:
            v = 0.0
            self._accel = 0.0
        v = max(0.0, v)
        self._speed = v

        # Throttle follows the acceleration being asked for.
        if kind == "full" and not capped:
            throttle = 1.0
        elif self._accel >= 0:
            throttle = 0.12 + 0.88 * self._accel / avail if v > 0 else 0.0
        else:
            throttle = 0.12 + 0.24 * self._accel
        if tv <= 0.0:
            throttle = 0.0
        self._throttle = max(0.0, min(1.0, throttle))

        self._shift()
        self._advance_phase(tv)

        # Turbo: vacuum at light load, positive boost once spooled.
        rpm = self._rpm()
        spool = max(0.0, min(1.0, (rpm - 2400) / 1600))
        target_boost = -18 + self._throttle * 18 + spool * self._throttle * 14
        k = 1.0 - math.exp(-dt / 0.2 * 0.288)
        self._boost += (target_boost - self._boost) * k
        k = 1.0 - math.exp(-dt * 0.25)
        self._intake += (70 + max(0.0, self._boost) * 3 - self._intake) * k

        # Coolant warms on a clock, then a thermostat wobble around 195.
        warm = 1.0 - math.exp(-self._t / _WARM_TAU)
        base = _COOLANT_COLD + (_COOLANT_HOT - _COOLANT_COLD) * warm
        self._wobble += -self._wobble * min(1.0, dt / 20.0) \
            + self._rng.uniform(-0.06, 0.06) * math.sqrt(dt / 0.2)
        self._coolant = base + warm * 1.5 * math.sin(self._t / 40.0) + self._wobble
        return self._state()

    def _shift(self):
        """One gear at most per tick: up near redline (sooner when cruising),
        down when the engine would labour."""
        base = self._speed / GEARS[self._gear - 1] * 1000
        if self._gear < len(GEARS) and base >= 2800 + self._throttle * 3000:
            self._gear += 1
        elif self._gear > 1 and base < 1300:
            self._gear -= 1

    def _rpm(self):
        v = self._speed
        rpm = v / GEARS[self._gear - 1] * 1000 + self._throttle * 600
        if v < 6:  # clutch slip on a launch
            rpm = max(rpm, 800 + self._throttle * 2500 * (1 - v / 6))
        return max(800.0, min(6800.0, rpm))

    def _state(self):
        return {"speed": self._speed, "rpm": self._rpm(), "gear": self._gear,
                "throttle": self._throttle, "boost": self._boost,
                "coolant": self._coolant, "intake": self._intake}
