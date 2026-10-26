"""Off-Pi tests for the engine warnings (backend/vehicle.py): the
thresholds, and that only the car's own readings warn.

    python3 -m unittest tests.test_vehicle
"""

import unittest

from PyQt6.QtCore import QCoreApplication

from backend.vehicle import LIMITS, VehicleData, warnings

# apply_obd restarts a QTimer, which wants an application object (no event loop).
app = QCoreApplication.instance() or QCoreApplication([])

FINE = {"coolant": 195.0, "voltage": 14.2, "boost": 8.0}


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


if __name__ == "__main__":
    unittest.main()
