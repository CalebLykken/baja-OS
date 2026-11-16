"""Off-Pi tests for the top speed and peak rpm since key-on: the saved record,
and VehicleData keeping them across a restart.

    python3 -m unittest tests.test_trip_peaks
"""

import unittest

try:
    from PyQt6.QtCore import QCoreApplication
except ImportError:
    raise unittest.SkipTest("PyQt6 isn't installed")

from backend import vehicle
from backend.trip import PEAKS_SETTING, peaks_record, saved_peaks
from backend.vehicle import VehicleData
from tests.test_vehicle import FakeGps, FakeSettings

app = QCoreApplication.instance() or QCoreApplication([])


class PeaksRecordTest(unittest.TestCase):
    def test_round_trip(self):
        self.assertEqual(saved_peaks(peaks_record(92.5, 6400, "b", 100.0), "b", 130.0), (92.5, 6400))

    def test_another_boot_is_rejected(self):
        self.assertIsNone(saved_peaks(peaks_record(92.5, 6400, "b", 100.0), "c", 130.0))
        self.assertIsNone(saved_peaks(peaks_record(92.5, 6400, "b", 100.0), "", 130.0))

    def test_bad_numbers_are_rejected(self):
        for top, rpm in ((float("nan"), 1), (-1, 1), (1, -5), (1, float("inf"))):
            self.assertIsNone(saved_peaks(peaks_record(top, rpm, "b", 1.0), "b", 2.0))

    def test_junk_is_rejected(self):
        for text in (None, "", "nope", "[]", '{"boot": "b"}'):
            self.assertIsNone(saved_peaks(text, "b", 2.0))


class VehiclePeaksTest(unittest.TestCase):
    def setUp(self):
        self._boot, self._up = vehicle.boot_id, vehicle.uptime
        vehicle.boot_id, vehicle.uptime = lambda: "boot-a", lambda: 500.0

    def tearDown(self):
        vehicle.boot_id, vehicle.uptime = self._boot, self._up

    def make(self, **values):
        settings = FakeSettings(carAnswered="true", **values)
        v = VehicleData(settings)
        self.now = 0.0
        v._clock = lambda: self.now
        return v, settings

    def writes(self, settings):
        return [x for x in settings.saved if x[0] == PEAKS_SETTING]

    def test_restores_from_settings(self):
        v, _ = self.make(**{PEAKS_SETTING: peaks_record(88.0, 6100, "boot-a", 400.0)})
        self.assertEqual((v.topSpeed, v.peakRpm), (88.0, 6100))

    def test_ignores_another_boot(self):
        v, _ = self.make(**{PEAKS_SETTING: peaks_record(88.0, 6100, "boot-z", 400.0)})
        self.assertEqual((v.topSpeed, v.peakRpm), (0, 0))

    def test_simulated_speed_does_not_count(self):
        v = VehicleData(FakeSettings(), demo=True)
        for _ in range(50):
            v._tick()
        self.assertGreater(v.speed, 0)
        self.assertEqual((v.topSpeed, v.peakRpm), (0, 0))

    def test_signal_only_on_a_new_maximum(self):
        v, _ = self.make()
        seen = []
        v.topSpeedChanged.connect(lambda: seen.append(1))
        v.apply_obd({"speed": 40.0, "rpm": 2500})
        v.apply_obd({"speed": 30.0, "rpm": 2000})
        self.assertEqual(len(seen), 1)
        v.apply_obd({"speed": 55.0, "rpm": 2000})
        self.assertEqual((len(seen), v.topSpeed, v.peakRpm), (2, 55.0, 2500))

    def test_gps_speed_counts_when_the_car_is_quiet(self):
        v, _ = self.make()
        gps = FakeGps()
        v.set_gps(gps)
        gps.realFix, gps.speed = True, 20.0 * 0.44704
        gps.changed.emit()
        self.assertAlmostEqual(v.topSpeed, 20.0, places=3)

    def test_saves_at_most_once_per_30_seconds(self):
        v, settings = self.make()
        v.apply_obd({"speed": 40.0, "rpm": 2500})
        self.assertEqual(len(self.writes(settings)), 1)
        self.now = 10.0
        v.apply_obd({"speed": 50.0, "rpm": 3000})
        self.assertEqual(len(self.writes(settings)), 1)
        self.now = 31.0
        v.apply_obd({"speed": 45.0, "rpm": 2000})      # nothing new, but a save is owed
        self.assertEqual(len(self.writes(settings)), 2)
        self.assertEqual(saved_peaks(self.writes(settings)[-1][1], "boot-a", 500.0), (50.0, 3000))
        self.now = 90.0
        v.apply_obd({"speed": 10.0, "rpm": 900})       # nothing changed: no write
        self.assertEqual(len(self.writes(settings)), 2)


if __name__ == "__main__":
    unittest.main()
