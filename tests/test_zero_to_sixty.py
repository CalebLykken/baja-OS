"""Off-Pi tests for the 0-60 timer in backend/vehicle.py, run with a fake clock.

    python3 -m unittest tests.test_zero_to_sixty
"""

import unittest

from PyQt6.QtCore import QCoreApplication, QObject, pyqtSignal

from backend.gps import MPH_TO_MS
from backend.vehicle import VehicleData

app = QCoreApplication.instance() or QCoreApplication([])


class Run(unittest.TestCase):
    def setUp(self):
        self.now = 0.0
        self.v = VehicleData(settings=None, demo=False)
        self.v._clock = lambda: self.now
        self.fired = []
        self.v.launchChanged.connect(lambda: self.fired.append(1))

    def at(self, t, mph):
        self.now = t
        self.v.apply_obd({"rpm": 3000, "speed": mph})

    def launch(self, start, took, top=61):
        self.at(start, 0)
        self.at(start + 0.2, 5)
        self.at(start + took / 2, 30)
        self.at(start + took, top)

    def test_normal_launch(self):
        self.launch(10, 8.4)
        self.assertEqual(self.v.zeroToSixty, 8.4)
        self.assertEqual(self.v.zeroToHundred, 0.0)
        self.assertEqual(len(self.fired), 1)

    def test_start_is_when_it_rolls(self):
        self.at(0, 0)
        self.at(50, 0)       # sat at the light
        self.at(51, 10)
        self.at(58.5, 60)
        self.assertEqual(self.v.zeroToSixty, 8.5)    # from the last sample at rest

    def test_rolling_start_records_nothing(self):
        for t, mph in ((0, 20), (3, 40), (6, 61)):
            self.at(t, mph)
        self.assertEqual(self.v.zeroToSixty, 0.0)
        self.assertEqual(self.fired, [])

    def test_stopping_halfway_abandons(self):
        self.at(0, 0)
        self.at(1, 30)
        self.at(3, 0)        # stopped again: the run is off, timing restarts
        self.at(10, 30)
        self.at(12, 61)
        self.assertEqual(self.v.zeroToSixty, 9.0)    # from the stop at 3 to 12, not from 0

    def test_stop_without_finishing_records_nothing(self):
        self.at(0, 0)
        self.at(1, 30)
        self.at(3, 0)
        self.assertEqual(self.v.zeroToSixty, 0.0)
        self.assertEqual(self.fired, [])

    def test_slow_run_abandons(self):
        self.launch(0, 31)
        self.assertEqual(self.v.zeroToSixty, 0.0)
        self.assertEqual(self.fired, [])

    def test_second_launch_replaces_first(self):
        self.launch(0, 9.0)
        self.at(30, 0)
        self.launch(30, 7.2)
        self.assertEqual(self.v.zeroToSixty, 7.2)
        self.assertEqual(len(self.fired), 2)

    def test_hundred_kmh(self):
        self.launch(0, 10.0, top=63)
        self.assertEqual(self.v.zeroToSixty, 10.0)
        self.assertEqual(self.v.zeroToHundred, 10.0)

    def test_nothing_while_simulated(self):
        v = VehicleData(settings=None, demo=True)
        v._clock = lambda: self.now
        v.launchChanged.connect(lambda: self.fired.append(1))
        self.assertTrue(v.simulated)
        for t, mph in ((0, 0), (1, 30), (2, 65)):
            self.now = t
            v._speed = mph
            v._settle(v._flags())
        self.assertEqual(v.zeroToSixty, 0.0)
        self.assertEqual(self.fired, [])


class FakeGps(QObject):
    """The bits of backend/gps.py that VehicleData reads."""
    changed = pyqtSignal()

    def __init__(self):
        super().__init__()
        self.realFix, self.speed, self.source = False, 0.0, ""

    def fix(self, mph):
        self.realFix, self.speed, self.source = True, mph * MPH_TO_MS, "gps"
        self.changed.emit()


class GpsOnly(unittest.TestCase):
    """With the car silent the speed is the GPS's; a stopped receiver reports
    the same 0.0 on every fix."""

    def setUp(self):
        self.now = 0.0
        self.v = VehicleData(settings=None, demo=False)
        self.v._clock = lambda: self.now
        self.gps = FakeGps()
        self.v.set_gps(self.gps)

    def at(self, t, mph):
        self.now = t
        self.gps.fix(mph)

    def test_a_wait_at_exactly_zero_does_not_age_the_start(self):
        for t in range(1, 21):
            self.at(t, 0)           # sat at the light, 0.0 on every fix
        self.at(20.2, 5)
        self.at(24, 30)
        self.at(27.8, 61)
        self.assertEqual(self.v.zeroToSixty, 7.8)    # from the last fix at rest

    def test_a_very_long_wait_does_not_drop_the_run(self):
        for t in range(0, 41):
            self.at(t, 0)
        self.at(40.2, 5)
        self.at(44, 61)
        self.assertEqual(self.v.zeroToSixty, 4.0)


if __name__ == "__main__":
    unittest.main()
