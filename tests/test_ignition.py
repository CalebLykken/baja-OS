"""Off-Pi tests for the key-off decision (backend/ignition.py), with a
clock that's just a number.

    python3 -m unittest tests.test_ignition
"""

import unittest
from unittest import mock

from PyQt6.QtCore import QCoreApplication

from backend.ignition import RUNNING_V, VOLTS_FRESH_S, KeyOff, KeyOffLogic
from backend.obd import VOLTS_FOR_S

QUIET_S, WARN_S = 15.0, 10.0
app = QCoreApplication.instance() or QCoreApplication([])   # QTimer needs one to run


def logic():
    return KeyOffLogic(quiet_s=QUIET_S, warn_s=WARN_S)


class KeyOffTest(unittest.TestCase):
    def test_nothing_before_the_car_has_answered(self):
        k = logic()
        k.quiet(0)                                 # a bench Pi, or the key never on
        for t in range(0, 120):
            self.assertIsNone(k.seconds_left(t))

    def test_counts_down_after_the_quiet_wait(self):
        k = logic()
        k.answered(0)
        k.quiet(100)
        self.assertIsNone(k.seconds_left(100))
        self.assertIsNone(k.seconds_left(114.9))   # still waiting: no prompt yet
        self.assertEqual(k.seconds_left(115), 10)  # the prompt appears
        self.assertEqual(k.seconds_left(120.5), 5)
        self.assertEqual(k.seconds_left(125), 0)   # power off
        self.assertEqual(k.seconds_left(130), 0)

    def test_the_car_answering_again_cancels(self):
        k = logic()
        k.answered(0)
        k.quiet(0)
        self.assertEqual(k.seconds_left(18), 7)
        k.answered(0)                              # a hiccup, or cranking
        self.assertIsNone(k.seconds_left(30))
        k.quiet(40)                                # the real key-off: a fresh wait
        self.assertIsNone(k.seconds_left(50))
        self.assertEqual(k.seconds_left(65), 0)

    def test_repeated_quiet_doesnt_restart_the_wait(self):
        k = logic()
        k.answered(0)
        k.quiet(0)
        k.quiet(10)                                # the reader reports it again
        self.assertEqual(k.seconds_left(25), 0)

    def test_keep_on_lasts_until_the_car_answers_again(self):
        k = logic()
        k.answered(0)
        k.quiet(0)
        self.assertEqual(k.seconds_left(16), 9)
        k.keep_on()
        self.assertIsNone(k.seconds_left(30))
        self.assertIsNone(k.seconds_left(600))
        k.answered(0)
        k.quiet(700)
        self.assertEqual(k.seconds_left(725), 0)

    def test_keep_on_with_nothing_pending_does_nothing(self):
        k = logic()
        k.answered(0)
        k.keep_on()
        k.quiet(0)
        self.assertEqual(k.seconds_left(25), 0)

    def test_not_while_the_car_last_said_it_was_moving(self):
        k = logic()
        k.answered(40.0)                           # quiet at 40 mph: a glitch
        k.quiet(0)
        self.assertIsNone(k.seconds_left(60))
        k.answered(0.0)                            # parked, then the key goes off
        k.quiet(100)
        self.assertEqual(k.seconds_left(125), 0)

    def test_answers_without_speed_keep_the_last_one(self):
        k = logic()
        k.answered(0.0)
        k.answered(None)                           # a round without the speed
        k.quiet(0)
        self.assertEqual(k.seconds_left(25), 0)

    def test_gps_movement_starts_the_wait_again(self):
        k = logic()
        k.answered(0)
        k.quiet(0)
        self.assertEqual(k.seconds_left(16), 9)
        self.assertIsNone(k.seconds_left(17, moving=True))
        self.assertIsNone(k.seconds_left(30))      # 13 s since it stopped moving
        self.assertEqual(k.seconds_left(32), 10)
        self.assertEqual(k.seconds_left(42), 0)

    def test_powers_off_once(self):
        k = logic()
        k.answered(0)
        k.quiet(0)
        self.assertFalse(k.power_off_now(k.seconds_left(24)))
        self.assertTrue(k.power_off_now(k.seconds_left(25)))
        self.assertFalse(k.power_off_now(k.seconds_left(26)))

    def test_a_failed_shutdown_drops_the_countdown(self):
        k = logic()
        k.answered(0)
        k.quiet(0)
        self.assertTrue(k.power_off_now(k.seconds_left(25)))
        k.failed()                                 # no polkit rule
        self.assertFalse(k.done)
        self.assertIsNone(k.seconds_left(26))
        self.assertIsNone(k.seconds_left(600))     # not again for this key-off
        k.answered(0)                              # the next drive
        k.quiet(700)
        self.assertTrue(k.power_off_now(k.seconds_left(725)))

    def test_the_car_answering_resets_done(self):
        k = logic()
        k.answered(0)
        k.quiet(0)
        self.assertTrue(k.power_off_now(k.seconds_left(25)))
        k.answered(0)                              # still running after all
        self.assertFalse(k.done)
        k.quiet(100)
        self.assertTrue(k.power_off_now(k.seconds_left(125)))

    def test_no_countdown_while_the_battery_is_charging(self):
        k = logic()
        k.answered(0)
        k.voltage(0, 14.2)                         # idling at a red light
        k.quiet(0)                                 # and the K-line drops
        for t in range(0, 600):
            k.voltage(t, 14.1)                     # the reader, once a second
            self.assertIsNone(k.seconds_left(t))

    def test_counts_down_once_the_battery_falls(self):
        k = logic()
        k.answered(0)
        k.voltage(0, 14.2)
        k.quiet(0)
        for t in range(0, 40):                     # a slow fall: the veto holds
            k.voltage(t, 13.5)
            self.assertIsNone(k.seconds_left(t))
        k.voltage(40, 13.1)                        # the engine's off
        self.assertEqual(k.seconds_left(40.5), 10) # the prompt, straight away
        self.assertEqual(k.seconds_left(45), 5)
        self.assertEqual(k.seconds_left(50), 0)

    def test_a_quick_fall_doesnt_delay_it(self):
        k = logic()
        k.answered(0)
        k.voltage(0, 14.2)                         # read while the engine ran
        k.quiet(0)                                 # the key goes off
        for t, volts in ((1, 13.2), (2, 12.9), (5, 12.8), (10, 12.7)):
            k.voltage(t, volts)
            self.assertIsNone(k.seconds_left(t))
        self.assertEqual(k.seconds_left(15), 10)
        self.assertEqual(k.seconds_left(25), 0)    # as without a battery reading

    def test_at_the_threshold_isnt_charging(self):
        k = logic()
        k.answered(0)
        k.quiet(0)
        k.voltage(1, RUNNING_V)
        self.assertEqual(k.seconds_left(25), 0)

    def test_without_a_battery_reading_it_counts_down_as_before(self):
        k = logic()
        k.answered(0)
        k.quiet(0)
        self.assertIsNone(k.volts)
        self.assertIsNone(k.seconds_left(14))
        self.assertEqual(k.seconds_left(15), 10)
        self.assertEqual(k.seconds_left(25), 0)

    def test_an_old_battery_reading_stops_counting(self):
        k = logic()
        k.answered(0)
        k.voltage(0, 14.2)                         # then the reader stops
        k.quiet(0)
        for t in range(0, int(VOLTS_FRESH_S)):
            self.assertIsNone(k.seconds_left(t))
        self.assertEqual(k.seconds_left(VOLTS_FRESH_S), 10)  # the prompt, not straight to 0
        self.assertEqual(k.seconds_left(VOLTS_FRESH_S + WARN_S), 0)

    def test_a_charging_battery_hides_a_countdown_already_showing(self):
        k = logic()
        k.answered(0)
        k.quiet(0)
        k.voltage(0, 12.6)
        self.assertEqual(k.seconds_left(18), 7)
        for t in range(19, 300):                   # running, but the car still quiet
            k.voltage(t, 14.0)
            self.assertIsNone(k.seconds_left(t))
        k.voltage(300, 12.6)
        self.assertEqual(k.seconds_left(300), 10)


class Signal:
    def connect(self, slot):
        pass


class FakeObd:
    reading, quiet, voltage = Signal(), Signal(), Signal()

    def __init__(self):
        self.calls = []

    def hold(self):
        self.calls.append("hold")

    def release(self):
        self.calls.append("release")


class FakeGps:
    realFix, speed = False, 0.0


class FakeSettings:
    def __init__(self, on=True):
        self.value = "true" if on else "false"     # "Shut down with key"

    def get(self, key, default=None):
        return self.value

    def set(self, key, value):
        self.value = value


class DashboardTest(unittest.TestCase):
    """The dashboard's side, with fakes and a clock that's just a number."""

    def setUp(self):
        self.now = 1000.0
        self.powered = []
        patches = (mock.patch("backend.ignition.time.monotonic", lambda: self.now),
                   mock.patch("builtins.print"))
        _, self.print = [p.start() for p in patches]
        for p in patches:
            self.addCleanup(p.stop)
        self.obd = FakeObd()
        self.cancelled = []
        self.k = KeyOff(self.obd, FakeGps(), FakeSettings(), power_off=lambda: self.powered.append(self.now),
                        cancel_power=lambda: self.cancelled.append(self.now))

    def key_off(self):
        """A drive, then the key off and the countdown to 0."""
        self.k._answered({"speed": 0})
        self.k._quiet()
        self.now += QUIET_S + WARN_S
        self.k._tick()

    def test_a_failed_shutdown_says_so_and_frees_the_dashboard(self):
        self.key_off()
        self.assertEqual(len(self.powered), 1)
        self.assertEqual(self.k.countdown, 0)
        self.k.power_failed("Access denied")
        self.assertEqual(self.k.countdown, -1)    # the prompt's countdown is gone
        self.assertEqual(self.k.error, "Access denied")
        self.now += 60
        self.k._tick()
        self.assertEqual(self.k.countdown, -1)
        self.assertEqual(len(self.powered), 1)    # no retry loop
        self.k.dismiss()
        self.assertEqual(self.k.error, "")

    def test_the_reader_is_held_at_power_off_and_released_on_failure(self):
        self.k._answered({"speed": 0})
        self.k._quiet()
        self.now += QUIET_S + WARN_S - 1
        self.k._tick()
        self.assertEqual(self.obd.calls, [])       # still counting down
        self.now += 1
        self.k._tick()
        self.assertEqual(self.obd.calls, ["hold"])
        self.k._tick()
        self.assertEqual(self.obd.calls, ["hold"])
        self.k.power_failed("Access denied")
        self.assertEqual(self.obd.calls, ["hold", "release"])

    def test_a_reading_after_the_hold_doesnt_strand_the_reader(self):
        self.key_off()
        self.k._answered({"speed": 0})             # the car answers once more
        self.assertEqual(self.k.countdown, -1)
        self.k.power_failed("Access denied")
        self.assertEqual(self.obd.calls, ["hold", "release"])

    def test_a_failure_from_settings_doesnt_release(self):
        self.k.power_failed("Access denied")
        self.assertEqual(self.obd.calls, [])

    def test_no_hold_when_the_shutdown_is_off(self):
        self.k.setEnabled(False)
        self.key_off()
        self.assertEqual(self.obd.calls, [])
        self.assertEqual(self.powered, [])

    def test_no_hold_when_the_countdown_is_cancelled(self):
        self.k._answered({"speed": 0})
        self.k._quiet()
        self.now += QUIET_S + 5
        self.k._tick()
        self.k.keepOn()
        self.now += 60
        self.k._tick()
        self.assertEqual(self.obd.calls, [])
        self.k._answered({"speed": 0})            # the car came back
        self.assertEqual(self.obd.calls, [])

    def test_keep_on_releases_a_held_reader(self):
        self.key_off()
        self.k.keepOn()
        self.assertEqual(self.obd.calls, ["hold", "release"])

    def test_keep_on_cancels_a_shutdown_waiting_for_an_update(self):
        self.key_off()
        self.k.keepOn()
        self.assertEqual(len(self.cancelled), 1)

    def test_the_key_coming_back_cancels_a_waiting_shutdown(self):
        self.key_off()
        self.k._answered({"speed": 0})
        self.assertEqual(len(self.cancelled), 1)
        self.assertEqual(self.obd.calls, ["hold", "release"])
        self.k._answered({"speed": 0})
        self.assertEqual(len(self.cancelled), 1)   # once

    def test_moving_cancels_a_waiting_shutdown(self):
        self.key_off()
        self.k._gps = type("G", (), {"realFix": True, "speed": 10.0})()
        self.k._tick()
        self.assertEqual(len(self.cancelled), 1)

    def test_nothing_to_cancel_before_the_shutdown_is_asked_for(self):
        self.k._answered({"speed": 0})
        self.k._quiet()
        self.now += QUIET_S + 5
        self.k._tick()
        self.k.keepOn()
        self.assertEqual(self.cancelled, [])

    def test_a_failed_shutdown_isnt_cancelled_later(self):
        self.key_off()
        self.k.power_failed("Access denied")
        self.k.keepOn()
        self.assertEqual(self.cancelled, [])

    def test_the_next_key_off_still_shuts_down(self):
        self.key_off()
        self.k.power_failed("Access denied")
        self.now += 3600
        self.key_off()                             # the rule is in place now
        self.assertEqual(len(self.powered), 2)
        self.assertEqual(self.k.error, "")         # cleared when the car answered

    def test_the_timer_is_idle_while_the_car_answers(self):
        self.assertFalse(self.k._timer.isActive())  # nothing ticks until the car's quiet
        self.k._answered({"speed": 0})
        self.assertFalse(self.k._timer.isActive())
        self.k._quiet()
        self.assertTrue(self.k._timer.isActive())  # the battery log and the countdown
        self.k._answered({"speed": 0})
        self.assertFalse(self.k._timer.isActive())  # the car's back: stop ticking

    def test_quiet_before_the_car_has_answered_doesnt_start_the_timer(self):
        self.k._quiet()                            # a bench Pi, the key never on
        self.assertFalse(self.k._timer.isActive())

    def test_the_timer_runs_through_a_countdown_and_stops_when_it_is_kept_on(self):
        self.k._answered({"speed": 0})
        self.k._quiet()
        self.now += QUIET_S + 1
        self.k._tick()
        self.assertEqual(self.k.countdown, 9)
        self.assertTrue(self.k._timer.isActive())  # still counting down
        self.k.keepOn()
        self.assertTrue(self.k._timer.isActive())  # the car's still quiet
        self.k._answered({"speed": 0})
        self.assertFalse(self.k._timer.isActive())

    def test_the_timer_stops_when_the_key_comes_back_during_a_shutdown_wait(self):
        self.key_off()
        self.assertTrue(self.k._timer.isActive())  # power off asked, waiting on the car
        self.k._answered({"speed": 0})
        self.assertEqual(len(self.cancelled), 1)
        self.assertFalse(self.k._timer.isActive())

    def test_a_failure_from_settings_isnt_shown_here(self):
        self.k.power_failed("Access denied")      # Settings > Shut down, no countdown
        self.assertEqual(self.k.error, "")

    def battery_lines(self):
        return [c.args[0] for c in self.print.call_args_list if "Key off? Battery" in c.args[0]]

    def test_a_charging_battery_keeps_it_on(self):
        self.k._answered({"speed": 0})
        self.k._voltage(14.1)
        self.k._quiet()
        for _ in range(300):
            self.now += 1
            self.k._voltage(14.1)
            self.k._second()
        self.assertEqual(self.k.countdown, -1)
        self.assertEqual(self.powered, [])

    def off_and_quiet_for(self, seconds):
        """The setting off, the key at ACC for `seconds`; returns the KeyOff."""
        k = KeyOff(self.obd, FakeGps(), FakeSettings(on=False),
                   power_off=lambda: self.powered.append(self.now))
        k._answered({"speed": 0})
        k._quiet()
        for _ in range(int(seconds)):
            self.now += 1
            k._second()
        return k

    def test_turning_it_on_while_already_quiet_waits_and_counts_down(self):
        k = self.off_and_quiet_for(600)
        k.setEnabled(True)
        self.assertEqual(self.powered, [])         # not at once
        self.assertEqual(k.countdown, -1)          # the quiet wait starts over
        for _ in range(int(QUIET_S) - 1):
            self.now += 1
            k._second()
        self.assertEqual(k.countdown, -1)
        self.now += 1
        k._second()
        self.assertEqual(k.countdown, 10)          # the prompt, with Keep on
        self.assertEqual(self.powered, [])
        for _ in range(int(WARN_S)):
            self.now += 1
            k._second()
        self.assertEqual(self.powered, [self.now])

    def test_keep_on_works_after_turning_it_on_while_quiet(self):
        k = self.off_and_quiet_for(600)
        k.setEnabled(True)
        self.now += QUIET_S
        k._second()
        self.assertEqual(k.countdown, 10)
        k.keepOn()
        self.assertEqual(k.countdown, -1)
        self.now += 60
        k._second()
        self.assertEqual(self.powered, [])

    def test_turning_it_on_with_the_car_answering_changes_nothing(self):
        k = KeyOff(self.obd, FakeGps(), FakeSettings(on=False),
                   power_off=lambda: self.powered.append(self.now))
        k._answered({"speed": 0})
        k.setEnabled(True)
        self.assertEqual(k.countdown, -1)
        k._quiet()                                 # the key goes off after
        self.now += QUIET_S + WARN_S
        k._tick()
        self.assertEqual(self.powered, [self.now])

    def test_logs_the_battery_each_second_for_two_minutes(self):
        self.k._answered({"speed": 0})
        self.k._second()                           # the car's answering: nothing
        self.assertEqual(self.battery_lines(), [])
        self.k._quiet()
        self.k._second()
        self.assertEqual(self.battery_lines(), ["Key off? Battery not read, 0 s after the car went quiet"])
        self.k._voltage(13.04)
        self.now += 1
        self.k._second()
        self.assertEqual(self.battery_lines()[-1], "Key off? Battery 13.0 V, 1 s after the car went quiet")
        for _ in range(int(VOLTS_FOR_S) + 30):
            self.now += 1
            self.k._second()
        self.assertEqual(len(self.battery_lines()), int(VOLTS_FOR_S))


    def with_notes(self):
        self.notes = []
        self.k = KeyOff(self.obd, FakeGps(), FakeSettings(), power_off=lambda: self.powered.append(self.now),
                        cancel_power=lambda: self.cancelled.append(self.now), note=self.notes.append)

    def test_notes_for_a_quiet_spell_that_the_car_ends(self):
        self.with_notes()
        self.k._answered({"speed": 0})
        self.k._quiet()
        self.k._quiet()                             # repeats aren't new
        self.now += QUIET_S + 1
        self.k._tick()
        self.k._answered({"speed": 0})
        self.assertEqual(self.notes, ["car quiet", "countdown", "cancelled: car answered"])

    def test_notes_for_keep_on_and_for_power_off(self):
        self.with_notes()
        self.k._answered({"speed": 0})
        self.k._quiet()
        self.now += QUIET_S + 1
        self.k._tick()
        self.k.keepOn()
        self.assertEqual(self.notes, ["car quiet", "countdown", "cancelled: kept on"])
        self.notes.clear()
        self.k._answered({"speed": 0})
        self.k._quiet()
        self.now += QUIET_S + WARN_S
        self.k._tick()
        self.k.power_failed("no polkit rule")
        self.assertEqual(self.notes[:3], ["car quiet", "countdown", "power off requested"])
        self.assertIn("power off failed: no polkit rule", self.notes)


if __name__ == "__main__":
    unittest.main()
