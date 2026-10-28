"""Off-Pi tests for the engine data (backend/vehicle.py): the warning
thresholds (only the car's own readings warn), and when the gauges may show
the simulated drive, dashes, or the real battery.

    python3 -m unittest tests.test_vehicle
"""

import unittest

from PyQt6.QtCore import QCoreApplication, QObject, pyqtSignal

from backend.gps import Gps
from backend.vehicle import LIMITS, VOLTS_MS, VehicleData, estimate_gear, warnings

# apply_obd restarts a QTimer, which wants an application object (no event loop).
app = QCoreApplication.instance() or QCoreApplication([])

FINE = {"coolant": 195.0, "voltage": 14.2, "boost": 8.0}
DRIVING = {"rpm": 2500, "speed": 40.0, "boost": 4.0, "coolant": 190.0, "intake": 90.0}


class FakeSettings:
    """Just the get and set of backend/settings.py, kept in a dict."""

    def __init__(self, **values):
        self.values = dict(values)
        self.saved = []

    def get(self, key, default=None):
        return self.values.get(key, default)

    def set(self, key, value):
        self.values[key] = value
        self.saved.append((key, value))


def truck():
    """A truck whose car has answered before, and isn't answering now."""
    return VehicleData(FakeSettings(carAnswered="true"))


class FakeGps(QObject):
    """The bits of backend/gps.py that VehicleData reads: a fresh real fix
    (`realFix`, `speed` in m/s) and `changed`."""
    changed = pyqtSignal()

    def __init__(self):
        super().__init__()
        self.realFix = False
        self.speed = 0.0

    def fix(self, ms):
        self.realFix, self.speed = True, ms
        self.changed.emit()

    def lose(self):
        """The receiver went quiet: stale, so no real fix and a speed of 0."""
        self.realFix, self.speed = False, 0.0
        self.changed.emit()


def count(signal):
    """A list that gets an item each time `signal` fires."""
    fired = []
    signal.connect(lambda: fired.append(1))
    return fired


class ThresholdTest(unittest.TestCase):
    def test_fine(self):
        self.assertEqual(warnings(**FINE), [])

    def test_overheating(self):
        self.assertEqual(warnings(**{**FINE, "coolant": 231}), ["coolant"])
        self.assertEqual(warnings(**{**FINE, "coolant": LIMITS["coolantHigh"]}), [])

    def test_battery_voltage_both_ways(self):
        self.assertEqual(warnings(**{**FINE, "voltage": 11.9}), ["voltage"])
        self.assertEqual(warnings(**{**FINE, "voltage": 15.1}), ["voltage"])
        self.assertEqual(warnings(**{**FINE, "voltage": 12.0}), [])
        self.assertEqual(warnings(**{**FINE, "voltage": 15.0}), [])

    def test_a_battery_not_read_cant_warn(self):
        self.assertEqual(warnings(**{**FINE, "voltage": None}), [])

    def test_overboost(self):
        self.assertEqual(warnings(**{**FINE, "boost": 15.5}), ["boost"])

    def test_most_urgent_first(self):
        self.assertEqual(warnings(coolant=240, voltage=11, boost=17), ["coolant", "voltage", "boost"])


class LiveOnlyTest(unittest.TestCase):
    def test_simulated_data_never_warns(self):
        v = VehicleData()
        v._coolant, v._voltage, v._boost = 250.0, 10.0, 20.0
        self.assertFalse(v.live)
        self.assertEqual(v.warnings, [])

    def test_the_cars_readings_warn_until_it_goes_quiet(self):
        v = VehicleData()
        v.apply_obd({"coolant": 241, "voltage": 14.1, "boost": 2})
        self.assertEqual(v.warnings, ["coolant"])
        v.apply_obd({"coolant": 220})
        self.assertEqual(v.warnings, [])
        v.apply_obd({"voltage": 11.4})
        self.assertEqual(v.warnings, ["voltage"])
        v.lost_obd()
        self.assertEqual(v.warnings, [])

    def test_a_battery_not_read_lately_doesnt_warn(self):
        v = truck()
        v._voltage = 10.0                       # an old reading, or the simulation's
        v.apply_obd({"coolant": 190})
        self.assertEqual(v.warnings, [])


class SimulationTest(unittest.TestCase):
    """When the made-up drive may show, and what the gauges read otherwise."""

    def test_a_fresh_install_simulates(self):
        v = VehicleData(FakeSettings())
        self.assertTrue(v.simulated)
        self.assertTrue(v.engineKnown and v.voltageKnown)
        self.assertFalse(v.live)
        for _ in range(5):
            v._tick()
        self.assertGreater(v.rpm, 0)
        self.assertGreater(v.voltage, 13)
        self.assertEqual(v.warnings, [])

    def test_without_settings_it_counts_as_never_answered(self):
        self.assertTrue(VehicleData().simulated)

    def test_after_the_car_has_answered_the_engine_is_unknown(self):
        v = truck()
        self.assertFalse(v.simulated)
        self.assertFalse(v.engineKnown)
        self.assertFalse(v.voltageKnown)
        for _ in range(5):
            v._tick()
        for value in (v.rpm, v.speed, v.boost, v.coolant, v.intake, v.gear, v.voltage):
            self.assertEqual(value, 0)

    def test_the_simulation_stands_still_when_it_isnt_wanted(self):
        v = truck()
        fired = count(v.changed)
        v._tick()
        self.assertEqual((v._t, fired), (0.0, []))

    def test_demo_forces_the_simulation_after_the_car_has_answered(self):
        v = VehicleData(FakeSettings(carAnswered="true"), demo=True)
        self.assertTrue(v.simulated and v.engineKnown and v.voltageKnown)
        v._tick()
        self.assertGreater(v.rpm, 0)

    def test_no_demo_stops_the_simulation_on_a_fresh_install(self):
        v = VehicleData(FakeSettings(), demo=False)
        self.assertFalse(v.simulated)
        self.assertFalse(v.engineKnown)
        self.assertEqual(v.rpm, 0)

    def test_the_car_going_quiet_ends_the_simulation_for_good(self):
        v = VehicleData(FakeSettings())          # a fresh install, no flags
        v.apply_obd(DRIVING)
        v.lost_obd()
        self.assertFalse(v.simulated)
        self.assertFalse(v.engineKnown)
        self.assertEqual(v.rpm, 0)

    def test_even_with_no_settings_to_save_to(self):
        v = VehicleData()
        v.apply_obd(DRIVING)
        v.lost_obd()
        self.assertFalse(v.simulated)

    def test_demo_brings_the_simulation_back_when_the_car_goes_quiet(self):
        v = VehicleData(FakeSettings(), demo=True)
        v.apply_obd(DRIVING)
        self.assertFalse(v.simulated)
        v.lost_obd()
        self.assertTrue(v.simulated)
        self.assertTrue(v.engineKnown)


class LiveTest(unittest.TestCase):
    def test_the_first_reading_saves_that_the_car_answered_once(self):
        settings = FakeSettings()
        v = VehicleData(settings)
        v.apply_obd(DRIVING)
        v.apply_obd({"rpm": 2600})
        v.lost_obd()
        v.apply_obd(DRIVING)
        self.assertEqual(settings.saved, [("carAnswered", "true")])

    def test_it_isnt_saved_again_when_it_was_already_known(self):
        settings = FakeSettings(carAnswered="true")
        VehicleData(settings).apply_obd(DRIVING)
        self.assertEqual(settings.saved, [])

    def test_the_cars_numbers_show_while_it_answers(self):
        v = truck()
        v.apply_obd(DRIVING)
        self.assertTrue(v.live and v.engineKnown)
        self.assertFalse(v.simulated)
        self.assertEqual((v.rpm, v.speed, v.boost, v.coolant, v.intake), (2500, 40.0, 4.0, 190.0, 90.0))
        self.assertGreater(v.gear, 0)

    def test_the_flags_signal_only_when_they_change(self):
        v = VehicleData(FakeSettings())
        live, sim, eng, volts, values = (count(s) for s in (
            v.liveChanged, v.simulatedChanged, v.engineKnownChanged, v.voltageKnownChanged, v.changed))
        v.apply_obd(DRIVING)                    # live; no longer simulated; no battery read yet
        v.apply_obd(DRIVING)
        self.assertEqual((len(live), len(sim), len(eng), len(volts), len(values)), (1, 1, 0, 1, 2))
        v.lost_obd()                            # not live; engine now unknown
        v.lost_obd()
        self.assertEqual((len(live), len(sim), len(eng), len(volts), len(values)), (2, 1, 1, 1, 3))

    def test_the_gauges_refresh_when_the_car_goes_quiet(self):
        v = truck()
        v.apply_obd(DRIVING)
        fired = count(v.changed)
        v.lost_obd()
        self.assertEqual(len(fired), 1)


MPH = 0.44704   # metres per second in one mph


class SpeedTest(unittest.TestCase):
    """The one speed every page reads: the car's, else the GPS's, else the
    simulation's, else unknown."""

    def vehicle(self, answered=True, demo=None, fix=None):
        """A truck (a fresh install if not `answered`), with a GPS handed
        over late, as main.py does, holding a fresh fix of `fix` m/s."""
        v = VehicleData(FakeSettings(carAnswered="true") if answered else FakeSettings(), demo=demo)
        gps = FakeGps()
        v.set_gps(gps)
        if fix is not None:
            gps.fix(fix)
        return v, gps

    def test_the_car_and_no_gps(self):
        v, gps = self.vehicle()
        v.apply_obd(DRIVING)
        self.assertEqual((v.speed, v.speedKnown), (40.0, True))

    def test_the_car_wins_over_the_gps(self):
        v, gps = self.vehicle(fix=30 * MPH)
        self.assertEqual(round(v.speed), 30)
        v.apply_obd(DRIVING)
        self.assertEqual((v.speed, v.speedKnown), (40.0, True))
        gps.fix(31 * MPH)                       # a new GPS speed changes nothing while the car answers
        self.assertEqual(v.speed, 40.0)

    def test_the_gps_alone_shows_in_mph(self):
        v, gps = self.vehicle(fix=10.0)         # m/s
        self.assertTrue(v.speedKnown)
        self.assertAlmostEqual(v.speed, 22.369, places=3)
        self.assertFalse(v.engineKnown)         # the engine stays unknown ...
        self.assertEqual((v.rpm, v.gear), (0, 0))   # ... and so does the gear

    def test_neither_car_nor_gps_is_unknown(self):
        v, gps = self.vehicle()
        self.assertEqual((v.speed, v.speedKnown), (0.0, False))
        v, gps = self.vehicle(fix=20 * MPH)
        gps.lose()                              # the fix went stale
        self.assertEqual((v.speed, v.speedKnown), (0.0, False))
        v, gps = self.vehicle()
        v.apply_obd(DRIVING)
        v.lost_obd()                            # the car went quiet, no GPS
        self.assertEqual((v.speed, v.speedKnown), (0.0, False))

    def test_the_gps_takes_over_when_the_car_goes_quiet(self):
        v, gps = self.vehicle(fix=35 * MPH)
        v.apply_obd(DRIVING)
        v.lost_obd()
        self.assertEqual((round(v.speed), v.speedKnown), (35, True))
        gps.lose()
        self.assertEqual((v.speed, v.speedKnown), (0.0, False))

    def test_the_simulation_is_the_last_resort(self):
        v, gps = self.vehicle(answered=False)   # a fresh install simulates
        v._speed = 25.0
        self.assertTrue(v.simulated)
        self.assertEqual((v.speed, v.speedKnown), (25.0, True))
        gps.fix(50 * MPH)                       # a real fix beats it
        self.assertEqual(round(v.speed), 50)
        gps.lose()
        self.assertEqual(v.speed, 25.0)

    def test_no_simulation_when_the_car_has_answered(self):
        v, gps = self.vehicle(answered=True)
        v._speed = 25.0                         # left over from before
        for _ in range(5):
            v._tick()
        self.assertEqual((v.speed, v.speedKnown), (0.0, False))

    def test_demo_simulates_with_no_gps_fix_and_yields_to_one(self):
        v, gps = self.vehicle(answered=True, demo=True)
        v._speed = 25.0
        self.assertEqual((v.speed, v.speedKnown), (25.0, True))
        gps.fix(40 * MPH)
        self.assertEqual(round(v.speed), 40)

    def test_no_gps_handed_over(self):
        v = VehicleData(FakeSettings(carAnswered="true"))
        self.assertEqual((v.speed, v.speedKnown), (0.0, False))
        v.apply_obd(DRIVING)
        self.assertEqual(v.speed, 40.0)

    def test_gps_handed_over_with_a_fix_already(self):
        v = VehicleData(FakeSettings(carAnswered="true"))
        gps = FakeGps()
        gps.fix(20 * MPH)
        fired = count(v.speedKnownChanged)
        v.set_gps(gps)
        self.assertEqual((round(v.speed), v.speedKnown, len(fired)), (20, True, 1))

    def test_the_gear_comes_from_the_cars_speed_only(self):
        v, gps = self.vehicle(fix=80 * MPH)     # the GPS would make it another gear
        self.assertEqual(v.gear, 0)             # no gear from the GPS alone
        v.apply_obd(DRIVING)
        self.assertEqual(v.gear, estimate_gear(40.0, 2500))
        self.assertGreater(v.gear, 0)
        gps.fix(5 * MPH)
        self.assertEqual(v.gear, estimate_gear(40.0, 2500))
        v.lost_obd()
        self.assertEqual(v.gear, 0)

    def test_the_gps_speed_signals_only_while_it_matters(self):
        v, gps = self.vehicle()
        known, values = count(v.speedKnownChanged), count(v.changed)
        gps.fix(10 * MPH)                       # becomes known
        self.assertEqual((len(known), len(values)), (1, 1))
        gps.fix(11 * MPH)                       # a new speed
        self.assertEqual((len(known), len(values)), (1, 2))
        gps.fix(11 * MPH)                       # the same again
        self.assertEqual((len(known), len(values)), (1, 2))
        gps.lose()                              # unknown again
        self.assertEqual((len(known), len(values)), (2, 3))
        v.apply_obd(DRIVING)
        values.clear()
        gps.fix(12 * MPH)                       # the car answers: the GPS isn't shown
        self.assertEqual(values, [])

    def test_with_the_real_gps(self):
        v = VehicleData(FakeSettings(carAnswered="true"))
        gps = Gps(v)
        v.set_gps(gps)
        self.assertFalse(v.speedKnown)
        gps._apply({"lat": 47.6, "lon": -122.3, "speed": 10.0, "heading": 90.0, "source": "gps"})
        self.assertEqual((v.speedKnown, round(v.speed, 1)), (True, 22.4))
        gps._pos.real_at -= 60                  # not heard from for a minute
        gps.changed.emit()
        self.assertEqual((v.speedKnown, v.speed), (False, 0.0))


class BatteryTest(unittest.TestCase):
    def test_a_real_battery_is_known_with_the_simulation_off(self):
        v = truck()
        v.apply_voltage(12.4)
        self.assertTrue(v.voltageKnown)
        self.assertEqual(v.voltage, 12.4)
        self.assertFalse(v.live)
        self.assertFalse(v.engineKnown)         # only the battery; the engine stays unknown
        self.assertEqual(v.rpm, 0)

    def test_it_alone_doesnt_make_the_car_live_or_count_as_an_answer(self):
        settings = FakeSettings()
        v = VehicleData(settings, demo=False)
        v.apply_voltage(12.4)
        v.apply_obd({"voltage": 12.5})          # a round where only the battery answered
        self.assertFalse(v.live)
        self.assertFalse(v.engineKnown)
        self.assertEqual((v.voltage, settings.saved), (12.5, []))
        self.assertFalse(v._stale.isActive())

    def test_it_survives_the_car_going_quiet(self):
        v = truck()
        v.apply_obd({**DRIVING, "voltage": 13.9})
        self.assertEqual(v.voltage, 13.9)
        v.lost_obd()
        self.assertTrue(v.voltageKnown)
        self.assertEqual(v.voltage, 13.9)
        self.assertEqual(v.rpm, 0)

    def test_a_reading_with_the_engine_values_counts_too(self):
        v = truck()
        v.apply_obd({**DRIVING, "voltage": 14.1})
        self.assertEqual(v.voltage, 14.1)
        self.assertTrue(v._volts_stale.isActive())

    def test_it_ages_out(self):
        v = truck()
        v.apply_voltage(12.4)
        self.assertTrue(v._volts_stale.isActive())
        self.assertEqual(v._volts_stale.interval(), VOLTS_MS)
        self.assertEqual(VOLTS_MS, 3 * 60 * 1000)
        fired = count(v.voltageKnownChanged)
        v._volts_aged()                         # the timer's handler
        self.assertFalse(v.voltageKnown)
        self.assertEqual(v.voltage, 0)
        self.assertEqual(len(fired), 1)

    def test_a_new_reading_makes_it_current_again(self):
        v = truck()
        v.apply_voltage(12.4)
        v._volts_aged()
        v.apply_voltage(12.3)
        self.assertTrue(v.voltageKnown)
        self.assertEqual(v.voltage, 12.3)

    def test_the_same_reading_again_changes_nothing(self):
        v = truck()
        v.apply_voltage(12.4)
        fired = count(v.changed)
        v.apply_voltage(12.4)
        self.assertEqual(fired, [])
        v.apply_voltage(12.5)
        self.assertEqual(len(fired), 1)

    def test_a_real_battery_beats_the_simulated_one(self):
        v = VehicleData(FakeSettings())
        v.apply_voltage(12.3)
        for _ in range(20):
            v._tick()
        self.assertTrue(v.simulated)
        self.assertEqual(v.voltage, 12.3)       # the simulation says 14.2
        v._volts_aged()
        v._tick()
        self.assertTrue(v.voltageKnown)         # still simulated
        self.assertGreater(v.voltage, 13)

    def test_it_warns_only_while_the_car_is_live(self):
        v = truck()
        v.apply_voltage(11.0)
        self.assertEqual(v.warnings, [])        # engine off: not an engine warning
        v.apply_obd(DRIVING)
        self.assertEqual(v.warnings, ["voltage"])
        v._volts_aged()
        self.assertEqual(v.warnings, [])


if __name__ == "__main__":
    unittest.main()
