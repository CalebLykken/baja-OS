"""Off-Pi tests for which position the map shows (backend/gps.py): the
receiver's, its last one held when it loses the sky, or the demo drive,
with a clock that's just a number.

    python3 -m unittest tests.test_gps
"""

import unittest
from types import SimpleNamespace

from PyQt6.QtCore import QCoreApplication

from backend.gps import DemoRoute, Gps, Position

app = QCoreApplication.instance() or QCoreApplication([])

STALE_S = 10.0


def real(lat=47.0, lon=-122.0, speed=20.0, heading=90.0):
    return {"lat": lat, "lon": lon, "speed": speed, "heading": heading, "source": "gps"}


def demo():
    return {"lat": 47.6, "lon": -122.3, "speed": 13.0, "heading": 0.0, "source": "demo"}


class PositionTest(unittest.TestCase):
    def test_demo_drive_with_no_receiver_and_simulated_data(self):
        p = Position(demo=True, stale_s=STALE_S)    # a Mac, or a Pi on the bench
        self.assertTrue(p.demo_allowed(live=False))

    def test_no_demo_unless_asked(self):
        p = Position(demo=False, stale_s=STALE_S)
        self.assertFalse(p.demo_allowed(live=False))

    def test_no_demo_while_the_car_answers(self):
        p = Position(demo=True, stale_s=STALE_S)
        self.assertFalse(p.demo_allowed(live=True))

    def test_the_car_answering_drops_the_demo_position(self):
        p = Position(demo=True, stale_s=STALE_S)
        p.simulated(demo())
        self.assertTrue(p.check(0, live=True))
        self.assertIsNone(p.fix)
        self.assertFalse(p.check(1, live=True))     # said once

    def test_a_receiver_drops_the_demo_for_good(self):
        p = Position(demo=True, stale_s=STALE_S)
        p.simulated(demo())
        p.receiver()                                # talking, no position yet
        self.assertIsNone(p.fix)
        self.assertFalse(p.demo_allowed(live=False))

    def test_a_real_fix_ends_the_demo(self):
        p = Position(demo=True, stale_s=STALE_S)
        p.simulated(demo())
        p.real(real(), 0)
        self.assertEqual(p.fix["source"], "gps")
        self.assertFalse(p.demo_allowed(live=False))

    def test_losing_the_signal_holds_the_last_position(self):
        p = Position(demo=True, stale_s=STALE_S)
        p.real(real(lat=47.1, lon=-122.2), 0)
        self.assertTrue(p.fresh(9.9))
        self.assertFalse(p.stale(9.9))
        self.assertFalse(p.check(9.9, live=True))
        # Into a tunnel: the fix goes stale, but stays where it was.
        self.assertTrue(p.check(10, live=True))
        self.assertTrue(p.stale(10))
        self.assertFalse(p.fresh(10))
        self.assertEqual((p.fix["lat"], p.fix["lon"], p.fix["source"]), (47.1, -122.2, "gps"))
        self.assertFalse(p.check(11, live=True))   # said once
        # Not the demo drive, even with simulated data (the key off in a garage).
        self.assertFalse(p.demo_allowed(live=False))
        self.assertFalse(p.check(600, live=False))
        self.assertEqual(p.fix["source"], "gps")

    def test_the_signal_coming_back(self):
        p = Position(demo=True, stale_s=STALE_S)
        p.real(real(), 0)
        p.check(20, live=True)
        p.real(real(lat=47.2), 21)
        self.assertTrue(p.fresh(21))
        self.assertFalse(p.stale(21))
        self.assertFalse(p.check(22, live=True))   # the fix itself was the news

    def test_no_position_is_neither_fresh_nor_stale(self):
        p = Position(demo=True, stale_s=STALE_S)
        self.assertIsNone(p.fix)
        self.assertFalse(p.fresh(0))
        self.assertFalse(p.stale(100))

    def test_heading_kept_below_walking_pace(self):
        p = Position(stale_s=STALE_S)
        p.real(real(heading=270.0), 0)
        p.real(real(speed=0.4, heading=12.0), 1)  # parked: the track is noise
        self.assertEqual(p.fix["heading"], 270.0)
        p.real(real(heading=None), 2)
        self.assertEqual(p.fix["heading"], 270.0)
        p.real(real(heading=180.0), 3)
        self.assertEqual(p.fix["heading"], 180.0)


if __name__ == "__main__":
    unittest.main()


class DemoDriveFollowsTheEngineDataTest(unittest.TestCase):
    """The demo drive goes with the simulated engine data, not just a quiet
    car: in a truck whose car has answered, the key off isn't a reason to
    show a made-up position."""

    def tick(self, simulated):
        car = SimpleNamespace(simulated=simulated, live=False, speed=30.0)
        gps = Gps(car, demo=True)
        gps._route = DemoRoute()
        gps._tick()
        return gps._pos.fix

    def test_simulated_data_drives_the_demo(self):     # a Mac, or a bench Pi
        self.assertEqual(self.tick(simulated=True)["source"], "demo")

    def test_a_quiet_truck_shows_no_position(self):    # key off, no receiver
        self.assertIsNone(self.tick(simulated=False))
