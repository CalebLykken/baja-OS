"""Shuts the Pi down cleanly after the truck is turned off.

In the truck the Pi is powered through a 12 V off-delay relay: it switches
on with the key and holds the power for a couple of minutes after the key
goes off. That time is for this.

The key is sensed through the OBD-II adapter, which is plugged in anyway:
the engine computer answers it while the key is on and goes quiet when the
key is turned off. Once the car has been quiet for QUIET_S (the adapter
keeps asking every few seconds, so a hiccup comes straight back), the
dashboard says it's shutting down and counts down WARN_S, with a button to
keep it on, then runs a normal `systemctl poweroff`. If that fails (no
polkit rule from setup-pi.sh), the prompt says so instead, and the next
key-off tries again.

It never acts:
  - unless "Shut down when the truck is off" is on in Settings > System
    (it's off until the relay is wired: on any other power, the Pi would
    stay off until it's unplugged and plugged back in);
  - before the car has answered once since the Pi started (a Pi on the
    bench, or the adapter unplugged);
  - when the adapter itself goes away, only when the car goes quiet;
  - while the truck is moving: the last speed the car reported was over
    MOVING_MPH, or the GPS (with a real position) says it's moving;
  - while the battery is over RUNNING_V: the alternator is charging, so the
    engine is running and only the K-line dropped (at a red light, say).
    The adapter reads the battery with the car quiet too. Without a
    reading in the last VOLTS_FRESH_S, the car going quiet is all it has.

Known limit: the engine computer is off at ACC too, so parking with the
key at ACC to keep listening looks like the truck being off. "Keep on"
stops that shutdown; the next one comes once the car has answered and gone
quiet again. If the key goes fully off meanwhile, the relay cuts the power
after its hold time, without a shutdown.
"""

import math
import time

from PyQt6.QtCore import QObject, QTimer, pyqtProperty, pyqtSignal, pyqtSlot

from backend.obd import RUNNING_V, VOLTS_FOR_S

QUIET_S = 15.0          # the car quiet this long before the countdown starts
WARN_S = 10.0           # the countdown on screen, with "Keep on"
MOVING_MPH = 3.0        # faster than this, it's a hiccup, not the key
# RUNNING_V (backend/obd.py, which needs it too) is the battery over which the
# engine is running: about 13.6-14.5 V charging, 12.4-12.8 V soon after it stops.
# Not measured on this truck yet: the journal's "Key off? Battery" lines give it
# once a second for the first two minutes after the car goes quiet.
VOLTS_FRESH_S = 30.0    # an older reading doesn't count (the reader stopped)
MPH_TO_MS = 0.44704
SETTING = "shutdownWhenOff"


class KeyOffLogic:
    """The decision, without Qt: told when the car answers and when it goes
    quiet, and asked what to do. Tests drive it with a fake clock."""

    def __init__(self, quiet_s=QUIET_S, warn_s=WARN_S):
        self.quiet_s, self.warn_s = quiet_s, warn_s
        self.seen_on = False        # the car has answered since the Pi started
        self.quiet_at = None        # when the wait started, while the car's quiet
        self.quiet_since = None     # when the car went quiet, while it's quiet
        self.last_mph = 0.0         # the car's last reported speed
        self.volts = None           # the battery's latest reading
        self.charging_until = -math.inf  # the battery says the engine's running until then
        self.kept_on = False        # "Keep on" was tapped for this quiet spell
        self.done = False           # the shutdown was asked for this quiet spell

    def answered(self, mph=None):
        self.seen_on = True
        self.quiet_at = self.quiet_since = None
        self.kept_on = False
        self.done = False
        if mph is not None:
            self.last_mph = mph

    def quiet(self, now):
        if self.seen_on and self.quiet_at is None:
            self.quiet_at = self.quiet_since = now

    def voltage(self, now, volts):
        """A battery reading. Over RUNNING_V, it counts for VOLTS_FRESH_S
        (the reader may stop) or until a lower one."""
        self.volts = volts
        if volts > RUNNING_V:
            self.charging_until = now + VOLTS_FRESH_S
        elif self.charging(now):
            self.charging_until = now

    def charging(self, now):
        """The battery says the engine's running."""
        return now < self.charging_until

    def keep_on(self):
        if self.quiet_at is not None:
            self.kept_on = True

    def failed(self):
        """The shutdown didn't happen: drop this countdown, as if kept on,
        so the dashboard is usable. The next key-off tries again."""
        self.done = False
        self.keep_on()

    def power_off_now(self, left):
        """True once, when the countdown (`left`) reaches 0."""
        if left == 0 and not self.done:
            self.done = True
            return True
        return False

    def seconds_left(self, now, moving=False):
        """Whole seconds until power off (0: now), or None while there's
        nothing to show. `moving` is what the GPS says."""
        if self.quiet_at is None or self.kept_on or self.last_mph > MOVING_MPH:
            return None
        if moving:
            self.quiet_at = now             # start the wait again once it stops
            return None
        if self.charging(now):
            return None
        # The prompt comes after the quiet wait, or as soon as the battery
        # falls if that's later: proof enough that the engine stopped.
        left = max(self.quiet_at + self.quiet_s, self.charging_until) + self.warn_s - now
        if left > self.warn_s:
            return None
        return max(0, math.ceil(left))


class KeyOff(QObject):
    """The dashboard's side: follows the OBD reader (the car and the
    battery) and the GPS, shows the countdown (`countdown`, -1 when there's
    none), and powers off. Told through power_failed() when that didn't
    work (`error`)."""
    changed = pyqtSignal()

    def __init__(self, obd, gps, settings, power_off, parent=None):
        super().__init__(parent)
        self._obd, self._gps, self._settings, self._power_off = obd, gps, settings, power_off
        self._held = False                  # the OBD reader is told to keep quiet
        self._logic = KeyOffLogic()
        self._enabled = str(settings.get(SETTING, "false")) == "true"
        self._countdown = -1
        self._error = ""
        obd.reading.connect(self._answered)
        obd.quiet.connect(self._quiet)
        obd.voltage.connect(self._voltage)
        self._timer = QTimer(self, interval=1000, timeout=self._second)

    def start(self):
        self._timer.start()

    def _answered(self, values):
        self._logic.answered(values.get("speed"))
        if self._error:
            self._error = ""                # a new drive: the old failure is done with
            self.changed.emit()
        self._tick()

    def _quiet(self):
        self._logic.quiet(time.monotonic())
        if self._enabled and self._logic.seen_on:
            print(f"Key off? The car stopped answering: shutting down in "
                  f"{QUIET_S + WARN_S:g} s unless it answers again or the "
                  f"battery is over {RUNNING_V:g} V", flush=True)

    def _voltage(self, volts):
        self._logic.voltage(time.monotonic(), volts)

    def _second(self):
        # The battery's fall after the key goes off, to set RUNNING_V by;
        # logged whether or not "Shut down with key" is on.
        since, volts = self._logic.quiet_since, self._logic.volts
        if since is not None and time.monotonic() - since < VOLTS_FOR_S:
            battery = "not read" if volts is None else f"{volts:.1f} V"
            print(f"Key off? Battery {battery}, {time.monotonic() - since:.0f} s "
                  f"after the car went quiet", flush=True)
        self._tick()

    def _moving(self):
        return self._gps.realFix and self._gps.speed > MOVING_MPH * MPH_TO_MS

    def _tick(self):
        left = self._logic.seconds_left(time.monotonic(), self._moving()) if self._enabled else None
        countdown = -1 if left is None else left
        if countdown != self._countdown:
            self._countdown = countdown
            self.changed.emit()
        if self._logic.power_off_now(left):
            print("Key off: the car has been quiet; shutting down", flush=True)
            self._hold(True)                # the adapter stays quiet while the Pi powers off
            self._power_off()

    def _hold(self, on):
        """Tell the OBD reader to stop sending, or carry on. Only once each way."""
        if on != self._held:
            self._held = on
            (self._obd.hold if on else self._obd.release)()

    def power_failed(self, why):
        """systemctl poweroff didn't work: show why instead of the countdown."""
        if not self._held and self._countdown < 0 and not self._logic.done:
            return                          # not from here (Settings > Shut down)
        print(f"Key off: couldn't shut down: {why}", flush=True)
        self._logic.failed()
        self._hold(False)
        self._error = why
        self._tick()
        self.changed.emit()

    @pyqtProperty(int, notify=changed)
    def countdown(self):
        """Seconds until the Pi shuts down, or -1."""
        return self._countdown

    @pyqtProperty(bool, notify=changed)
    def enabled(self):
        return self._enabled

    @pyqtProperty(str, notify=changed)
    def error(self):
        """Why the key-off shutdown failed, while that's on screen; else ''."""
        return self._error

    @pyqtSlot()
    def dismiss(self):
        if self._error:
            self._error = ""
            self.changed.emit()

    @pyqtSlot(bool)
    def setEnabled(self, on):
        if on != self._enabled:
            self._enabled = on
            self._settings.set(SETTING, "true" if on else "false")
            self._tick()
            self.changed.emit()

    @pyqtSlot()
    def keepOn(self):
        self._logic.keep_on()
        self._hold(False)
        print("Key off: kept on", flush=True)
        self._tick()
