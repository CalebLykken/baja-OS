"""Off-Pi tests for which position the map shows (backend/gps.py): the
receiver's, its last one held when it loses the sky, or the demo drive,
with a clock that's just a number; and which updates count as a new fix.

    python3 -m unittest tests.test_gps
"""

import io
import json
import os
import select
import tempfile
import threading
import tty
import unittest
from contextlib import redirect_stdout
from unittest import mock
from types import SimpleNamespace

from PyQt6.QtCore import QCoreApplication

from backend import gps as gpsmod
from backend.gps import (DemoRoute, Gps, Position, configure_receiver, nmea_coord, nmea_fields,
                         sky_report, tpv_report, ubx_frame, ubx_nav5_frame, ubx_rate_frame, ubx_replies,
                         ubx_valset_frame)

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

    def test_a_speed_that_is_not_a_number_counts_as_parked(self):
        p = Position(stale_s=STALE_S)
        p.real(real(heading=270.0), 0)
        p.real(dict(real(heading=45.0), speed="fast"), 1)      # no TypeError on the comparison
        self.assertEqual(p.fix["speed"], 0.0)
        self.assertEqual(p.fix["heading"], 270.0)


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
        self.sent = getattr(self, "sent", []) + [data]

    def settimeout(self, seconds):
        pass

    def makefile(self, *args, **kwargs):
        return iter(self.lines.splitlines(True))


class GpsdOddMessagesTest(unittest.TestCase):
    """Odd JSON from gpsd is skipped, not fatal to the reader thread."""

    def test_junk_lines_are_skipped_and_one_fix_reported(self):
        sock = FakeGpsd([])
        sock.lines = "".join(l + "\n" for l in (
            "null", "[1,2]", "7", '{"class":"TPV","mode":null}',
            '{"class":"TPV","mode":"3","lat":1}', '{"class":"TPV","mode":3,"lat":true,"lon":2}',
            '{"class":"TPV","mode":3,"lat":47.6,"lon":-122.3,"speed":1.5}'))
        got = []
        g = Gps(None)
        g._report.disconnect()
        g._report.connect(got.append)
        with mock.patch("backend.gps.socket.create_connection", lambda *a, **k: sock):
            self.assertTrue(g._read_gpsd())
        fixes = [r for r in got if "lat" in r]
        self.assertEqual(len(fixes), 1)
        self.assertEqual(fixes[0]["lat"], 47.6)

    def test_odd_speed_and_track_still_give_one_safe_fix(self):
        sock = FakeGpsd([])
        sock.lines = "".join(l + "\n" for l in (
            '{"class":"TPV","mode":3,"lat":47.6,"lon":-122.3,"speed":null,"track":"x"}',
            '{"class":"TPV","mode":3,"lat":47.6,"lon":-122.3,"speed":NaN,"track":NaN}',
            '{"class":"TPV","mode":3,"lat":91,"lon":-122.3,"speed":5}'))
        got = []
        g = Gps(None)
        g._report.disconnect()
        g._report.connect(got.append)
        with mock.patch("backend.gps.socket.create_connection", lambda *a, **k: sock):
            self.assertTrue(g._read_gpsd())
        fixes = [r for r in got if "lat" in r]
        self.assertEqual(len(fixes), 2)                    # the lat 91 one is dropped
        for fix in fixes:
            self.assertEqual(fix["speed"], 0.0)
            self.assertIsNone(fix["heading"])
            g._apply(fix)                                  # the UI thread side: no TypeError
        self.assertEqual(g._pos.fix["speed"], 0.0)
        self.assertEqual(g.heading, 0.0)


class TpvReportTest(unittest.TestCase):
    """gpsd's TPV fixes: only real numbers reach the map and the routing."""

    GOOD = {"class": "TPV", "mode": 3, "lat": 47.6, "lon": -122.3, "speed": 5.0, "track": 90.0}

    def report(self, **changes):
        return tpv_report(dict(self.GOOD, **changes))

    def test_a_good_tpv(self):
        self.assertEqual(tpv_report(self.GOOD),
                         {"lat": 47.6, "lon": -122.3, "speed": 5.0, "heading": 90.0, "source": "gps"})

    def test_a_missing_speed_is_zero(self):
        self.assertEqual(tpv_report({"mode": 2, "lat": 1, "lon": 2})["speed"], 0.0)

    def test_speed_that_is_not_a_number_is_zero(self):
        for speed in (None, "5", float("nan"), True, -3.0, float("inf")):
            self.assertEqual(self.report(speed=speed)["speed"], 0.0, speed)

    def test_track_that_is_not_a_number_is_no_heading(self):
        for track in ("x", float("nan"), None, True):
            self.assertIsNone(self.report(track=track)["heading"], track)

    def test_track_is_wrapped_to_a_bearing(self):
        self.assertEqual(self.report(track=370)["heading"], 10)

    def test_a_position_that_is_not_on_the_earth_is_no_fix(self):
        for changes in ({"lat": float("nan")}, {"lat": 91}, {"lon": -181},
                        {"lat": True}, {"lon": float("inf")}, {"lat": -90.5}):
            self.assertIsNone(self.report(**changes), changes)

    def test_a_mode_that_is_not_a_2d_fix_is_no_fix(self):
        for mode in ("3", True, 1, None, float("nan")):
            self.assertIsNone(self.report(mode=mode), mode)


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


def sentence(body):
    """'$body*hh' with the right checksum."""
    total = 0
    for ch in body:
        total ^= ord(ch)
    return f"${body}*{total:02X}"


class NmeaTest(unittest.TestCase):
    RMC = "GPRMC,123519,A,4807.038,N,01131.000,E,022.4,084.4,230394,003.1,W"

    def test_a_checked_sentence_splits_into_fields(self):
        f = nmea_fields("$GPRMC,123519,A,4807.038,N,01131.000,E,022.4,084.4,230394,003.1,W*6A\r\n")
        self.assertEqual(f, self.RMC.split(","))

    def test_a_bad_checksum_is_dropped(self):
        self.assertIsNone(nmea_fields("$GPRMC,123519,A,4807.038,N,01131.000,E,022.4,084.4,230394,003.1,W*6B"))
        self.assertIsNone(nmea_fields(sentence(self.RMC)[:-2] + "00"))

    def test_no_dollar_no_star_or_a_garbled_checksum_is_dropped(self):
        good = sentence(self.RMC)
        for line in (good[1:], good.split("*")[0], good.split("*")[0] + "*ZZ", good.split("*")[0] + "*", ""):
            self.assertIsNone(nmea_fields(line), line)

    def test_the_checksum_may_be_lower_case(self):
        line = sentence("GNGGA,1,2")
        self.assertEqual(nmea_fields(line[:-2] + line[-2:].lower()), ["GNGGA", "1", "2"])

    def test_coordinates_are_degrees_and_minutes(self):
        self.assertAlmostEqual(nmea_coord("4736.37200", "N"), 47.6062, places=4)
        self.assertAlmostEqual(nmea_coord("12219.92600", "W"), -122.33210, places=4)
        self.assertAlmostEqual(nmea_coord("3351.000", "S"), -(33 + 51 / 60), places=6)
        self.assertAlmostEqual(nmea_coord("01131.000", "E"), 11 + 31 / 60, places=6)

    def test_less_than_a_degree(self):
        self.assertAlmostEqual(nmea_coord("0030.000", "N"), 0.5)
        self.assertAlmostEqual(nmea_coord("30.000", "N"), 0.5)

    def test_nothing_to_convert(self):
        self.assertIsNone(nmea_coord("", "N"))
        self.assertIsNone(nmea_coord(None, "N"))
        self.assertIsNone(nmea_coord("4736", "N"))

    def rmc_reports(self, body):
        g = Gps(None)
        got = []
        g._report.disconnect()
        g._report.connect(got.append)
        g._sentence(nmea_fields(sentence(body)), False, 0, {})
        return got

    def test_a_nan_speed_or_heading_in_rmc_is_zero_or_no_heading(self):
        got = self.rmc_reports("GPRMC,123519,A,4807.038,N,01131.000,E,nan,nan,230394,003.1,W")
        self.assertEqual(len(got), 1)
        self.assertEqual(got[0]["speed"], 0.0)
        self.assertIsNone(got[0]["heading"])
        self.assertAlmostEqual(got[0]["lat"], 48 + 7.038 / 60, places=6)

    def test_an_inf_speed_in_rmc_is_zero(self):
        got = self.rmc_reports("GPRMC,123519,A,4807.038,N,01131.000,E,inf,084.4,230394,003.1,W")
        self.assertEqual(got[0]["speed"], 0.0)
        self.assertEqual(got[0]["heading"], 84.4)

    def test_an_rmc_position_off_the_earth_is_dropped(self):
        self.assertEqual(self.rmc_reports("GPRMC,123519,A,9999.000,N,01131.000,E,022.4,084.4,230394,003.1,W"), [])


class DemoRouteAtTest(unittest.TestCase):
    NORTH = [(-122.0, 47.0), (-122.0, 47.01)]                    # about 1.1 km
    SQUARE = [(-122.0, 47.0), (-122.0, 47.01), (-121.99, 47.01), (-121.99, 47.0)]

    def test_the_start_and_heading_of_a_one_way_route(self):
        r = DemoRoute(points=self.NORTH, loop=False)
        lon, lat, heading = r.at(0)
        self.assertEqual((lon, lat), (-122.0, 47.0))
        self.assertAlmostEqual(heading, 0.0, places=3)

    def test_part_way_along(self):
        r = DemoRoute(points=self.NORTH, loop=False)
        lon, lat, _ = r.at(r.length / 2)
        self.assertAlmostEqual(lat, 47.005, places=6)
        self.assertAlmostEqual(lon, -122.0, places=9)

    def test_a_one_way_route_ends_at_its_last_point(self):
        r = DemoRoute(points=self.NORTH, loop=False)
        for d in (r.length, r.length + 5000):
            lon, lat, heading = r.at(d)
            self.assertAlmostEqual(lat, 47.01, places=5)
            self.assertAlmostEqual(heading, 0.0, places=1)

    def test_a_loop_closes_and_wraps(self):
        r = DemoRoute(points=self.SQUARE)
        self.assertEqual(r.points[0], r.points[-1])
        for d in (10.0, 700.0, 1500.0):
            a, b = r.at(d), r.at(d + 3 * r.length)
            self.assertAlmostEqual(a[0], b[0], places=6)
            self.assertAlmostEqual(a[1], b[1], places=6)
        self.assertEqual(r.at(r.length)[:2], r.at(0)[:2])

    def test_it_heads_along_the_leg_it_is_on(self):
        r = DemoRoute(points=self.SQUARE)
        self.assertAlmostEqual(r.at(r.cum[1] / 2)[2], 0.0, places=1)                  # north
        self.assertAlmostEqual(r.at((r.cum[1] + r.cum[2]) / 2)[2], 90.0, delta=1)     # east
        self.assertAlmostEqual(r.at(r.cum[3] - 100)[2], 180.0, delta=1)               # south

    def test_it_turns_a_little_before_a_corner(self):
        r = DemoRoute(points=self.SQUARE)
        before = r.at(r.cum[1] - 10)[2]       # the point 25 m ahead is round the corner
        self.assertTrue(0 < before < 90, before)


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


def fletcher(data):
    """The UBX checksum, worked out on its own for the tests."""
    a = b = 0
    for x in data:
        a = (a + x) % 256
        b = (b + a) % 256
    return bytes([a, b])


def frames(data):
    """Split concatenated UBX frames into (class, id, payload), checking each."""
    out = []
    while data:
        assert data[:2] == b"\xb5\x62", data[:2]
        n = int.from_bytes(data[4:6], "little")
        assert fletcher(data[2:6 + n]) == data[6 + n:8 + n]
        out.append((data[2], data[3], data[6:6 + n]))
        data = data[8 + n:]
    return out


class UbxFramesTest(unittest.TestCase):
    def test_frame_layout_and_checksum(self):
        f = ubx_frame(0x06, 0x08, b"\x01\x02\x03")
        self.assertEqual(f[:6], b"\xb5\x62\x06\x08\x03\x00")
        self.assertEqual(f[6:9], b"\x01\x02\x03")
        self.assertEqual(f[9:], fletcher(f[2:9]))

    def test_the_documented_5_hz_command(self):
        # CFG-RATE 200 ms, 1, GPS time: the vector u-blox tutorials print.
        self.assertEqual(ubx_rate_frame().hex(" "), "b5 62 06 08 06 00 c8 00 01 00 01 00 de 6a")

    def test_valset_is_ram_only_with_the_three_items(self):
        (cls, mid, payload), = frames(ubx_valset_frame())
        self.assertEqual((cls, mid), (0x06, 0x8A))
        self.assertEqual(len(payload), 4 + 5 + 6 + 6)
        self.assertEqual(payload[:4], b"\x00\x01\x00\x00")           # version 0, RAM only
        self.assertEqual(payload[4:], bytes.fromhex("21001120" "04" "01002130" "c800" "02002130" "0100"))

    def test_nav5_sets_only_the_dynamic_model(self):
        (cls, mid, payload), = frames(ubx_nav5_frame())
        self.assertEqual((cls, mid, len(payload)), (0x06, 0x24, 36))
        self.assertEqual(payload[:3], b"\x01\x00\x04")
        self.assertEqual(payload[3:], bytes(33))

    def test_nothing_is_ever_saved_to_the_receiver(self):
        sent = ubx_valset_frame() + ubx_nav5_frame() + ubx_rate_frame()
        self.assertNotIn((0x06, 0x09), [(c, i) for c, i, _ in frames(sent)])
        self.assertEqual(gpsmod.RATE_HZ, 5)
        self.assertEqual(gpsmod.DYNMODEL, 4)

    def test_replies_are_found_among_nmea(self):
        ack = ubx_frame(5, 1, b"\x06\x8a")
        nak = ubx_frame(5, 0, b"\x06\x24")
        data = b"$GNGGA,1*00\r\n" + ack + b"\r\n$GNRMC,2*00\r\n" + nak
        self.assertEqual(ubx_replies(data), [(True, 6, 0x8A), (False, 6, 0x24)])
        self.assertEqual(ubx_replies(ack[:-1]), [])
        self.assertEqual(ubx_replies(ack[:-1] + b"\x00"), [])         # bad checksum


class ConfigureReceiverTest(unittest.TestCase):
    def test_other_receivers_are_never_written_to(self):
        with mock.patch("backend.gps.os.open") as op, mock.patch("backend.gps.os.write") as wr:
            for name in ("usb-Generic_GNSS_Receiver-if00", "usb-GPS_thing-if00", "usb-FTDI_OBD-if00", ""):
                configure_receiver("/dev/serial/by-id/" + name, 5)
            configure_receiver(None, 5)
        op.assert_not_called()
        wr.assert_not_called()

    def test_it_never_opens_the_port_itself(self):
        path = "/dev/serial/by-id/usb-u-blox_AG_u-blox_GNSS_receiver-if00"
        with mock.patch("backend.gps.os.open") as op:
            self.assertFalse(configure_receiver(path, None))
        op.assert_not_called()

    def test_errors_are_swallowed(self):
        path = "/dev/serial/by-id/usb-u-blox_AG_-_www.u-blox.com_u-blox_GNSS_receiver-if00"
        with mock.patch("backend.gps.os.write", side_effect=OSError("gone")), redirect_stdout(io.StringIO()) as out:
            self.assertFalse(configure_receiver(path, 99, sleep=lambda s: None))
        self.assertIn("couldn't set the receiver up (gone)", out.getvalue())

    def test_a_pty_gets_the_exact_bytes_and_the_replies_are_read(self):
        master, slave = os.openpty()
        tty.setraw(slave)                  # the reader has set the port raw by now
        got = []

        def receiver():
            if select.select([master], [], [], 3)[0]:
                got.append(os.read(master, 4096))
                os.write(master, b"$GNGGA,1*00\r\n" + ubx_frame(5, 1, b"\x06\x8a")
                         + ubx_frame(5, 0, b"\x06\x24") + ubx_frame(5, 1, b"\x06\x08"))

        t = threading.Thread(target=receiver)
        t.start()
        path = "/dev/serial/by-id/usb-u-blox_AG_u-blox_GNSS_receiver-if00"
        with mock.patch.object(gpsmod, "SETUP_WAIT_S", 0.6), redirect_stdout(io.StringIO()) as out:
            self.assertTrue(configure_receiver(path, slave))
        t.join()
        os.close(master)
        os.close(slave)
        self.assertEqual(got, [ubx_valset_frame() + ubx_nav5_frame() + ubx_rate_frame()])
        self.assertIn("GPS: set automotive mode and 5 Hz (acked: VALSET ack, NAV5 nak, RATE ack)", out.getvalue())


class SetupRetryTest(unittest.TestCase):
    PATH = "/dev/serial/by-id/usb-u-blox_AG_u-blox_GNSS_receiver-if00"

    def run_setup(self, answers):
        sleeps = []
        with mock.patch("backend.gps.configure_fd", side_effect=answers) as cf, redirect_stdout(io.StringIO()):
            ok = configure_receiver(self.PATH, fd=7, sleep=sleeps.append)
        return ok, cf.call_count, sleeps

    def test_it_asks_up_to_three_times_when_nothing_is_acked(self):
        self.assertEqual(self.run_setup([False, False, False]), (False, 3, [gpsmod.SETUP_RETRY_S] * 2))

    def test_it_stops_at_the_first_ack(self):
        self.assertEqual(self.run_setup([False, True, True]), (True, 2, [gpsmod.SETUP_RETRY_S]))

    def test_the_log_says_set_only_when_something_was_acked(self):
        nak = ubx_frame(5, 0, b"\x06\x8a")
        ok, text = gpsmod.setup_summary(nak)
        self.assertFalse(ok)
        self.assertNotIn("set automotive", text)
        self.assertIn("VALSET nak", text)
        self.assertIn("heard nothing", gpsmod.setup_summary(b"$GNGGA*00")[1])
        ok, text = gpsmod.setup_summary(nak + ubx_frame(5, 1, b"\x06\x24"))
        self.assertTrue(ok)
        self.assertIn("set automotive mode and 5 Hz (acked: VALSET nak, NAV5 ack)", text)


class DirectReaderSetupTest(unittest.TestCase):
    def test_setup_runs_first_on_the_readers_own_port_then_fixes_are_read(self):
        rmc = "GNRMC,120000.00,A,4736.37200,N,12219.92000,W,10.0,90.0,010125,,,A"
        c = 0
        for ch in rmc:
            c ^= ord(ch)
        master, slave = os.openpty()
        got = []

        def receiver():
            if select.select([master], [], [], 3)[0]:
                got.append(os.read(master, 4096))
                os.write(master, ubx_frame(5, 1, b"\x06\x8a"))
                select.select([], [], [], 0.9)      # past the setup's listening time
                os.write(master, f"${rmc}*{c:02X}\r\n".encode())
                select.select([], [], [], 0.3)
                os.close(master)

        t = threading.Thread(target=receiver)
        t.start()
        g = Gps(None)
        seen = []
        g._report.disconnect()
        g._report.connect(seen.append)
        with tempfile.TemporaryDirectory() as d:
            link = os.path.join(d, "usb-u-blox_AG_u-blox_GNSS_receiver-if00")
            os.symlink(os.ttyname(slave), link)
            with mock.patch.object(gpsmod, "SETUP_WAIT_S", 0.6), mock.patch.object(gpsmod, "SETUP_RETRY_S", 0), \
                    redirect_stdout(io.StringIO()) as out:
                try:
                    g._read_receiver(link)
                except OSError:
                    pass                      # the pty's far end closed: "unplugged"
        t.join()
        os.close(slave)
        self.assertEqual(got, [gpsmod.setup_frames()])
        self.assertIn("set automotive mode and 5 Hz (acked: VALSET ack)", out.getvalue())
        self.assertEqual(len([x for x in seen if "lat" in x]), 1)

    def test_a_non_ublox_receiver_is_only_read(self):
        opened = []
        with mock.patch("backend.gps.os.open", side_effect=lambda p, flags: opened.append(flags) or 5), \
                mock.patch("backend.gps.termios.tcgetattr", return_value=[0] * 7), \
                mock.patch("backend.gps.termios.tcsetattr"), mock.patch("backend.gps.os.read", return_value=b""), \
                mock.patch("backend.gps.select.select", return_value=([5], [], [])), \
                mock.patch("backend.gps.os.write") as wr, mock.patch("backend.gps.os.close"), \
                redirect_stdout(io.StringIO()):
            Gps(None)._read_receiver("/dev/serial/by-id/usb-Generic_GNSS_Receiver-if00")
        wr.assert_not_called()
        self.assertFalse(opened[0] & os.O_RDWR)
        self.assertFalse(opened[0] & os.O_WRONLY)


class GpsdSetupTest(unittest.TestCase):
    def run_gpsd(self, lines, found=None):
        sock = mock.MagicMock()
        sock.__enter__.return_value = sock
        sock.makefile.return_value = [json.dumps(x) + "\n" for x in lines]
        g = Gps(None)
        g._report.disconnect()
        g._report.connect(lambda r: None)
        with mock.patch("backend.gps.socket.create_connection", return_value=sock), \
                mock.patch("backend.gps.find_receiver", return_value=found), redirect_stdout(io.StringIO()) as out:
            g._read_gpsd()
        sent = [c.args[0] for c in sock.sendall.call_args_list if c.args[0].startswith(b"?DEVICE")]
        return sent, out.getvalue()

    def test_a_ublox_behind_gpsd_gets_the_frames_through_gpsd_once(self):
        dev = {"class": "DEVICE", "path": "/dev/ttyACM0", "driver": "u-blox"}
        sent, out = self.run_gpsd([{"class": "DEVICES", "devices": [dev]}, dev, dev])
        self.assertEqual(len(sent), 1)
        self.assertTrue(sent[0].startswith(b"?DEVICE=") and sent[0].endswith(b";\n"))
        cmd = json.loads(sent[0][len(b"?DEVICE="):-2])
        self.assertEqual(cmd["path"], "/dev/ttyACM0")
        self.assertEqual(bytes.fromhex(cmd["hexdata"]), gpsmod.setup_frames())
        self.assertEqual([(c, i) for c, i, _ in frames(bytes.fromhex(cmd["hexdata"]))],
                         [(6, 0x8A), (6, 0x24), (6, 8)])
        self.assertIn("through gpsd (unverified", out)

    def test_a_replugged_receiver_is_sent_the_frames_again(self):
        up = {"class": "DEVICE", "path": "/dev/ttyACM0", "driver": "u-blox", "activated": "2025-01-01T00:00:00Z"}
        down = {"class": "DEVICE", "path": "/dev/ttyACM0", "activated": 0}
        sent, _ = self.run_gpsd([up, up, down, up])
        self.assertEqual(len(sent), 2)
        sent, _ = self.run_gpsd([down])
        self.assertEqual(sent, [])

    def test_other_receivers_behind_gpsd_are_left_alone(self):
        dev = {"class": "DEVICE", "path": "/dev/ttyUSB0", "driver": "NMEA0183"}
        sent, _ = self.run_gpsd([{"class": "DEVICES", "devices": [dev]}], found="/dev/serial/by-id/usb-FTDI-if00")
        self.assertEqual(sent, [])

    def test_a_send_error_is_swallowed(self):
        sock = mock.MagicMock()
        sock.__enter__.return_value = sock
        sock.sendall.side_effect = [None, OSError("closed")]
        sock.makefile.return_value = [json.dumps({"class": "DEVICE", "path": "/dev/x", "driver": "u-blox"}) + "\n"]
        g = Gps(None)
        with mock.patch("backend.gps.socket.create_connection", return_value=sock), redirect_stdout(io.StringIO()) as out:
            g._read_gpsd()
        self.assertIn("couldn't set the receiver up through gpsd", out.getvalue())


class BinaryJunkTest(unittest.TestCase):
    """The receiver's UBX replies share the NMEA stream."""

    def test_binary_lines_are_not_sentences(self):
        junk = ubx_frame(5, 1, b"\x06\x8a") + bytes(range(256))
        for line in junk.split(b"\n"):
            self.assertIsNone(nmea_fields(line.decode("ascii", "replace")))

    def test_the_direct_reader_survives_junk(self):
        rmc = "GNRMC,120000.00,A,4736.37200,N,12219.92000,W,10.0,90.0,010125,,,A"
        c = 0
        for ch in rmc:
            c ^= ord(ch)
        text = f"${rmc}*{c:02X}\r\n".encode()
        stream = ubx_frame(5, 1, b"\x06\x8a") + b"\r\n" + ubx_frame(5, 0, b"\x06\x24") + b"\xff\xfe\n" + text
        r, w = os.pipe()
        os.write(w, stream)
        os.close(w)
        g = Gps(None)
        seen = []
        g._report.disconnect()
        g._report.connect(seen.append)
        with mock.patch("backend.gps.termios.tcgetattr", return_value=[0] * 7), \
                mock.patch("backend.gps.termios.tcsetattr"), mock.patch("backend.gps.os.open", return_value=r), \
                mock.patch("backend.gps.configure_receiver"), redirect_stdout(io.StringIO()):
            g._read_receiver("/dev/serial/by-id/usb-u-blox-if00")
        fixes = [x for x in seen if "lat" in x]
        self.assertEqual(len(fixes), 1)
        self.assertAlmostEqual(fixes[0]["lat"], 47.606, places=2)


class ReaderSurvivesTest(unittest.TestCase):
    RMC = "GNRMC,120000.00,A,4736.37200,N,12219.92000,W,{},90.0,010125,,,A"

    def test_a_bad_sentence_is_skipped_not_fatal(self):
        stream = (sentence(self.RMC.format("1O.0")) + "\r\n" + sentence(self.RMC.format("10.0")) + "\r\n").encode()
        r, w = os.pipe()
        os.write(w, stream)
        os.close(w)
        g = Gps(None)
        seen = []
        g._report.disconnect()
        g._report.connect(seen.append)
        with mock.patch("backend.gps.termios.tcgetattr", return_value=[0] * 7), \
                mock.patch("backend.gps.termios.tcsetattr"), mock.patch("backend.gps.os.open", return_value=r), \
                mock.patch("backend.gps.configure_receiver"), redirect_stdout(io.StringIO()):
            g._read_receiver("/dev/serial/by-id/usb-u-blox-if00")
        self.assertEqual(len([x for x in seen if "lat" in x]), 1)

    def test_a_termios_error_means_retry_not_a_dead_thread(self):
        import termios
        g = Gps(None)
        calls = []

        def read(path):
            calls.append(path)
            raise termios.error(5, "Input/output error")

        class Stop(Exception):
            pass

        out = io.StringIO()
        with mock.patch.object(g, "_read_gpsd", return_value=False), \
                mock.patch("backend.gps.find_receiver", return_value="/dev/ttyACM0"), \
                mock.patch.object(g, "_read_receiver", read), \
                mock.patch("backend.gps.time.sleep", side_effect=Stop), redirect_stdout(out):
            with self.assertRaises(Stop):     # reached the 5 s wait, i.e. the error was caught
                g._receiver_loop()
        self.assertEqual(calls, ["/dev/ttyACM0"])
        self.assertIn("lost the receiver", out.getvalue())


class GpsdSetupTimingTest(unittest.TestCase):
    def run_messages(self, messages):
        g = Gps(demo=False)
        sock = FakeGpsd(messages)
        out = io.StringIO()
        with mock.patch("backend.gps.socket.create_connection", lambda *a, **k: sock), redirect_stdout(out):
            g._read_gpsd()
        return getattr(sock, "sent", []), out.getvalue()

    def test_nothing_is_sent_before_gpsd_names_a_driver(self):
        dev = {"class": "DEVICE", "path": "/dev/ttyACM0"}
        with mock.patch("backend.gps.find_receiver", return_value="/dev/ttyACM0"), \
                mock.patch("backend.gps.is_ublox", return_value=True):
            sent, out = self.run_messages([dev])
            self.assertEqual([x for x in sent if b"?DEVICE" in x], [])
            self.assertNotIn("sent automotive", out)
            sent, out = self.run_messages([dev, dict(dev, driver="u-blox")])
        self.assertEqual(len([x for x in sent if b"?DEVICE" in x]), 1)

    def test_an_error_reply_is_not_called_success_and_allows_a_retry(self):
        dev = {"class": "DEVICE", "path": "/dev/ttyACM0", "driver": "u-blox"}
        err = {"class": "ERROR", "message": "Type of /dev/ttyACM0 is unknown."}
        sent, out = self.run_messages([dev, err, dev])
        self.assertIn("refused", out)
        self.assertEqual(len([x for x in sent if b"?DEVICE" in x]), 2)
