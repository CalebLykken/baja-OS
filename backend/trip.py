"""The trip counter's numbers across a dashboard restart.

The counting is in qml/components/Trip.qml; this keeps what it has counted in
settings so a restart mid-drive (the watchdog, the updater at a stop) picks
the trip up again instead of starting over, which would fire the milestones
a second time. A save only counts in the boot it was made in: a real key-on
is a new boot and a new trip.
"""

import json
import math
import time

from PyQt6.QtCore import QObject, pyqtSlot

from backend.routing import boot_id

SETTING = "trip"


def uptime():
    """Seconds since this boot started. It carries on across a restart of the
    dashboard, which the wall clock can't promise early in a boot."""
    clock = getattr(time, "CLOCK_BOOTTIME", None)
    return time.clock_gettime(clock) if clock is not None else time.monotonic()


def trip_record(metres, moving_seconds, running_seconds, peak_boost, boot, up):
    """What's saved: JSON, with the boot and how long the boot had run. The
    peak boost is None until the engine has answered."""
    peak = float(peak_boost)
    return json.dumps({"metres": float(metres), "moving": float(moving_seconds),
                       "running": float(running_seconds),
                       "peak": peak if math.isfinite(peak) else None,
                       "boot": boot, "up": float(up)})


def saved_trip(text, boot, up):
    """The trip to carry on from what was saved, or None when there's none, it
    can't be read, or it is from another boot (or this one can't be told).
    The seconds the dashboard was down count as running time."""
    try:
        r = json.loads(text) if text else None
        if not isinstance(r, dict) or not boot or r.get("boot") != boot:
            return None
        metres, moving, running = float(r["metres"]), float(r["moving"]), float(r["running"])
        gap = max(0.0, up - float(r["up"]))
        if not all(math.isfinite(v) and v >= 0 for v in (metres, moving, running, gap)):
            return None
        peak = None if r.get("peak") is None else float(r["peak"])
        if peak is not None and not math.isfinite(peak):
            peak = None
        return {"metres": metres, "movingSeconds": moving,
                "runningSeconds": running + gap, "peakBoost": peak}
    except (ValueError, TypeError, KeyError, OverflowError, RecursionError):
        return None


class TripStore(QObject):
    """Saves and restores the trip for Trip.qml. save() is cheap: one small
    string handed to settings, which writes it later on its own thread."""

    def __init__(self, settings, parent=None):
        super().__init__(parent)
        self._settings = settings

    @pyqtSlot(result="QVariant")
    def restore(self):
        """The saved numbers as a map, or an empty one for a fresh trip."""
        return saved_trip(str(self._settings.get(SETTING, "")), boot_id(), uptime()) or {}

    @pyqtSlot(float, float, float, float)
    def save(self, metres, moving_seconds, running_seconds, peak_boost):
        self._settings.set(SETTING, trip_record(metres, moving_seconds, running_seconds,
                                                peak_boost, boot_id(), uptime()))
