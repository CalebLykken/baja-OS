"""Off-Pi tests for which position the map shows (backend/gps.py): the
receiver's, its last one held when it loses the sky, or the demo drive,
with a clock that's just a number; and which updates count as a new fix.

    python3 -m unittest tests.test_gps
"""

import json
import unittest
from unittest import mock
from types import SimpleNamespace

from PyQt6.QtCore import QCoreApplication

from backend.gps import DemoRoute, Gps, Position, sky_report

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


class FakeVehicle:
    def __init__(self, live=False, speed=30.0):
        self.live, self.speed = live, speed

    @property
    def simulated(self):            # as VehicleData on a Mac: simulated while the car is quiet
        return not self.live


class FixSignalTest(unittest.TestCase):
    """`fixChanged` is a new position and nothing else; `changed` is anything."""

    def setUp(self):
        self.now = 100.0
        clock = mock.patch("backend.gps.time.monotonic", lambda: self.now)
        clock.start()
        self.addCleanup(clock.stop)
        self.events = []

    def gps(self, demo=False, vehicle=None):
        g = Gps(vehicle, demo=demo)
        g.changed.connect(lambda: self.events.append("changed"))
        g.fixChanged.connect(lambda: self.events.append("fix"))
        return g

    def test_each_real_report_is_one_fix(self):
        g = self.gps()
        g._apply(real())
        self.assertEqual(self.events, ["changed", "fix"])     # changed first
        self.events.clear()
        g._apply(real(lat=47.001))
        g._apply(real(lat=47.002))
        self.assertEqual(self.events.count("fix"), 2)
        self.assertEqual(self.events.count("changed"), 2)

    def test_the_same_position_again_is_still_a_new_fix(self):
        g = self.gps()
        g._apply(real())
        g._apply(real())                                      # stopped at a light
        self.assertEqual(self.events.count("fix"), 2)

    def test_satellite_updates_are_not_fixes(self):
        g = self.gps()
        g._apply(real())
        self.events.clear()
        g._apply({"sats": 7, "view": 11})
        self.assertEqual(self.events, ["changed"])
        g._apply({"sats": 7, "view": 11})                     # nothing new at all
        g._apply({"sats": 8, "view": 11})
        self.assertEqual(self.events, ["changed", "changed"])

    def test_the_receiver_coming_and_going_is_not_a_fix(self):
        g = self.gps()
        g._apply({"gpsd": True})
        g._apply({"receiver": True})                          # talking, no position yet
        g._apply({"gpsd": False})
        self.assertEqual(self.events, ["changed", "changed"])

    def test_going_stale_is_not_a_fix(self):
        g = self.gps()
        g._apply(real())
        self.events.clear()
        self.now += STALE_S + 1                               # into a tunnel
        g._tick()
        self.assertTrue(g.stale)
        self.assertEqual(self.events, ["changed"])

    def test_each_demo_step_is_one_fix(self):
        g = self.gps(demo=True)
        g._route = DemoRoute()
        g._demo_step()
        self.assertEqual(self.events, ["changed", "fix"])
        self.assertEqual(g.source, "demo")
        g._demo_step()
        self.assertEqual(self.events.count("fix"), 2)

    def test_the_demo_giving_way_is_not_a_fix(self):
        g = self.gps(demo=True)
        g._route = DemoRoute()
        g._demo_step()
        self.events.clear()
        g._apply({"receiver": True})                          # a receiver showed up
        self.assertFalse(g.hasFix)
        self.assertEqual(self.events, ["changed"])
        g._tick()                                             # and no more demo steps
        self.assertEqual(self.events, ["changed"])

    def test_the_car_answering_stops_the_demo_without_a_fix(self):
        g = self.gps(demo=True, vehicle=FakeVehicle(live=True))
        g._route = DemoRoute()
        g._pos.simulated({"lat": 47.6, "lon": -122.3, "speed": 13.0, "heading": 0.0, "source": "demo"})
        g._tick()
        self.assertFalse(g.hasFix)
        self.assertEqual(self.events, ["changed"])


class FakeGpsd:
    """A socket that plays canned gpsd JSON lines, then closes."""

    def __init__(self, messages):
        self.lines = "".join(json.dumps(m) + "\n" for m in messages)

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False

    def sendall(self, data):
        pass

    def settimeout(self, seconds):
        pass

    def makefile(self, *args, **kwargs):
        return iter(self.lines.splitlines(True))


class GpsdSatellitesTest(unittest.TestCase):
    """gpsd's SKY reports give the same satellite counts as the NMEA path."""

    SKY = {"class": "SKY", "device": "/dev/ttyACM0", "uSat": 7, "nSat": 11}
    LISTED = {"class": "SKY", "satellites": [
        {"PRN": 1, "used": True}, {"PRN": 2, "used": False},
        {"PRN": 3, "used": True}, {"PRN": 4}]}

    def test_the_counts_gpsd_gives(self):
        self.assertEqual(sky_report(self.SKY), {"sats": 7, "view": 11})

    def test_counting_the_satellite_list_when_there_are_no_counts(self):
        self.assertEqual(sky_report(self.LISTED), {"sats": 2, "view": 4})

    def test_the_counts_win_over_the_list(self):
        self.assertEqual(sky_report(dict(self.LISTED, uSat=3, nSat=9)), {"sats": 3, "view": 9})

    def test_no_satellites_in_view_is_zero_not_missing(self):
        self.assertEqual(sky_report({"class": "SKY", "uSat": 0, "nSat": 0}), {"sats": 0, "view": 0})
        self.assertEqual(sky_report({"class": "SKY", "satellites": []}), {"sats": 0, "view": 0})

    def test_a_sky_with_only_dops_says_nothing(self):
        self.assertIsNone(sky_report({"class": "SKY", "device": "/dev/ttyACM0", "hdop": 1.1}))

    def test_odd_values_are_ignored(self):
        self.assertIsNone(sky_report({"class": "SKY", "uSat": "7", "nSat": None, "satellites": "x"}))
        self.assertEqual(sky_report({"class": "SKY", "satellites": [None, 3, {"used": True}]}),
                         {"sats": 1, "view": 1})

    def read(self, messages):
        g = Gps(demo=False)
        reports = []
        g._report.connect(reports.append)
        with mock.patch("backend.gps.socket.create_connection", lambda *a, **k: FakeGpsd(messages)):
            self.assertTrue(g._read_gpsd())
        return g, reports

    def test_reading_gpsd_reports_the_satellites(self):
        tpv = {"class": "TPV", "mode": 3, "lat": 47.0, "lon": -122.0, "speed": 5.0, "track": 90.0}
        g, reports = self.read([{"class": "VERSION"}, self.SKY, tpv,
                                {"class": "SKY", "hdop": 1.0}, dict(self.SKY, uSat=8)])
        self.assertEqual([r for r in reports if "sats" in r],
                         [{"sats": 7, "view": 11}, {"sats": 8, "view": 11}])
        for r in reports:
            g._apply(r)
        self.assertEqual((g.satellites, g.satellitesInView), (8, 11))
        self.assertTrue(g.hasFix)

    def test_satellites_show_before_there_is_a_fix(self):
        g, reports = self.read([self.SKY, {"class": "TPV", "mode": 1}])
        for r in reports:
            g._apply(r)
        self.assertEqual((g.satellites, g.satellitesInView), (7, 11))
        self.assertFalse(g.hasFix)

    def test_gpsd_going_away_clears_the_counts(self):
        g, reports = self.read([self.SKY])
        for r in reports:
            g._apply(r)
        g._apply({"gpsd": False})
        self.assertEqual((g.satellites, g.satellitesInView), (0, 0))


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
