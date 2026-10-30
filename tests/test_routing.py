"""Off-Pi tests for following a route (backend/routing.py) with a fake GPS:
no reroute and nothing said while the position is stale; the route saved
in settings and picked up again after a restart.

    python3 -m unittest tests.test_routing
"""

import io
import json
import time
import unittest
import urllib.error
from types import SimpleNamespace
from unittest import mock

from PyQt6.QtCore import QCoreApplication

from backend.gps import STALE_S, Gps
from backend.routing import (OFF_ROUTE_FIXES, OFF_ROUTE_S, RESUME_S, Route, Router, route_record,
                             saved_route)

app = QCoreApplication.instance() or QCoreApplication([])   # arrival starts a timer

# North 2.2 km, then right (east) for 760 m.
START, CORNER, END = (-122.0, 47.0), (-122.0, 47.02), (-121.99, 47.02)


def answer(router, data, error, name, reroute, gen=None):
    """The router's reply to the latest request (or to request number `gen`)."""
    router._on_route(data, error, name, reroute, router._gen if gen is None else gen)


def polyline6(points):
    """[(lon, lat)] -> Valhalla's encoded shape (the reverse of decode_polyline6)."""
    out, prev = [], (0, 0)
    for lon, lat in points:
        now = (round(lat * 1e6), round(lon * 1e6))
        for v, p in zip(now, prev):
            d = v - p
            d = ~(d << 1) if d < 0 else d << 1
            while d >= 0x20:
                out.append(chr((0x20 | (d & 0x1F)) + 63))
                d >>= 5
            out.append(chr(d + 63))
        prev = now
    return "".join(out)


ROUTE = {"trip": {"summary": {"time": 200.0}, "legs": [{
    "shape": polyline6([START, CORNER, END]),
    "maneuvers": [
        {"type": 1, "begin_shape_index": 0, "instruction": "Drive north.",
         "verbal_pre_transition_instruction": "Drive north."},
        {"type": 10, "begin_shape_index": 1, "instruction": "Turn right.",
         "verbal_pre_transition_instruction": "Turn right.",
         "verbal_transition_alert_instruction": "Turn right."},
        {"type": 4, "begin_shape_index": 2, "instruction": "You have arrived."},
    ],
}]}}


class TimeLeftTest(unittest.TestCase):
    """Time left comes from the maneuvers' own times, not an even share."""

    def route(self, times=(100.0, 100.0, 0.0), ends=(1, 2, 2)):
        data = json.loads(json.dumps(ROUTE))
        data["trip"]["summary"]["time"] = sum(times)
        for m, t, e in zip(data["trip"]["legs"][0]["maneuvers"], times, ends):
            m["time"], m["end_shape_index"] = t, e
        return Route(data, "Shop")

    def test_the_whole_route_at_the_start(self):
        self.assertAlmostEqual(self.route().time_left(), 200.0)

    def test_uneven_legs_are_not_averaged(self):
        # 2.2 km in 20 s (a highway), then 760 m in 180 s: at the corner
        # a quarter of the distance is left but nine tenths of the time.
        r = self.route(times=(20.0, 180.0, 0.0))
        r.along = r.cum[1]
        self.assertAlmostEqual(r.time_left(), 180.0)
        self.assertGreater(abs(r.time_left() - 200.0 * r.remaining / r.length), 50)

    def test_part_way_along_a_leg(self):
        r = self.route(times=(100.0, 100.0, 0.0))
        r.along = r.cum[1] / 2
        self.assertAlmostEqual(r.time_left(), 150.0)

    def test_the_end(self):
        r = self.route()
        r.along = r.length
        self.assertEqual(r.time_left(), 0.0)

    def test_without_maneuver_times_it_falls_back_to_the_even_share(self):
        r = Route(ROUTE, "Shop")
        r.along = r.length / 2
        self.assertAlmostEqual(r.time_left(), 100.0)


class Changed:
    def connect(self, slot):
        pass


class FakeGps:
    """What the router reads from backend.gps.Gps."""
    changed = Changed()
    fixChanged = Changed()

    def __init__(self):
        self.hasFix, self.stale, self.source = True, False, "gps"
        self.lon, self.lat = START
        self.speed, self.heading = 10.0, 0.0

    def at(self, lon, lat, stale=False):
        self.lon, self.lat, self.stale = lon, lat, stale
        self.speed = 0.0 if stale else 10.0          # as Gps reports it

    def followPath(self, points):
        pass

    def clearPath(self):
        pass


class FollowingTest(unittest.TestCase):
    def setUp(self):
        # A clock that moves only with each fix. By default they're slow
        # (OFF_ROUTE_S apart), so the count of fixes is what these tests see.
        self.now, self.fix_every = 1000.0, OFF_ROUTE_S
        clock = mock.patch("backend.routing.time.monotonic", lambda: self.now)
        clock.start()
        self.addCleanup(clock.stop)
        self.gps = FakeGps()
        self.router = Router(self.gps)
        self.router._clock = lambda: self.now
        on_fix = self.router._on_fix

        def fix():
            self.now += self.fix_every
            on_fix()
        self.router._on_fix = fix
        self.said, self.asked = [], []
        self.router.speak.connect(self.said.append)
        self.router._request = lambda *a, **k: self.asked.append(k.get("reroute", False))
        self.router._last_reroute = float("-inf")   # the clock may have just started
        self.router.routeTo("Shop", *END)
        answer(self.router, ROUTE, "", "Shop", False)
        self.router.go()
        self.assertEqual(self.said, ["Drive north."])
        self.said.clear()
        self.asked.clear()

    def test_no_reroute_while_stale(self):
        self.gps.at(-122.003, 47.005, stale=True)    # 230 m off the line
        for _ in range(OFF_ROUTE_FIXES * 3):
            self.router._on_fix()
        self.assertEqual(self.asked, [])
        self.assertFalse(self.router.offRoute)
        # Back on a fresh fix, still off the line: a new route.
        self.gps.at(-122.003, 47.005)
        for _ in range(OFF_ROUTE_FIXES):
            self.router._on_fix()
        self.assertEqual(self.asked, [True])

    def test_stale_restarts_the_off_route_count(self):
        self.gps.at(-122.003, 47.005)
        for _ in range(OFF_ROUTE_FIXES - 1):
            self.router._on_fix()
        self.gps.at(-122.003, 47.005, stale=True)
        self.router._on_gps_changed()                # going stale brings no new fix
        self.gps.at(-122.003, 47.005)
        for _ in range(OFF_ROUTE_FIXES - 1):
            self.router._on_fix()
        self.assertEqual(self.asked, [])
        self.router._on_fix()
        self.assertEqual(self.asked, [True])

    def test_quick_fixes_off_the_line_are_not_a_new_route(self):
        self.fix_every = 0.1                         # a receiver reporting 10 times a second
        self.gps.at(-122.003, 47.005)                # 230 m off the line
        for _ in range(int(OFF_ROUTE_S * 10)):       # OFF_ROUTE_S of fixes (just under it, first to last)
            self.router._on_fix()
        self.assertEqual(self.asked, [])
        self.assertTrue(self.router.offRoute)

    def test_a_receiver_at_one_hertz_reroutes_on_the_third_fix(self):
        self.fix_every = 1.0                         # 3 fixes span 2 s: the time is no extra wait
        self.gps.at(-122.003, 47.005)                # 230 m off the line
        for _ in range(OFF_ROUTE_FIXES - 1):
            self.router._on_fix()
        self.assertEqual(self.asked, [])
        self.router._on_fix()
        self.assertEqual(self.asked, [True])

    def test_off_the_line_for_the_time_and_the_fixes_is_a_new_route(self):
        self.fix_every = 0.5
        self.gps.at(-122.003, 47.005)
        for _ in range(int(OFF_ROUTE_S / self.fix_every)):   # the last one 0.5 s short of it
            self.router._on_fix()
        self.assertEqual(self.asked, [])
        self.router._on_fix()                        # OFF_ROUTE_S after the first
        self.assertEqual(self.asked, [True])

    def test_back_on_the_line_starts_the_time_again(self):
        self.fix_every = 0.25
        self.gps.at(-122.003, 47.005)                # off the line, not quite long enough ...
        for _ in range(int(OFF_ROUTE_S / self.fix_every)):
            self.router._on_fix()
        self.gps.at(-122.0, 47.005)                  # ... back on it ...
        self.router._on_fix()
        self.gps.at(-122.003, 47.005)                # ... and off again: OFF_ROUTE_S from here
        for _ in range(int(OFF_ROUTE_S / self.fix_every)):
            self.router._on_fix()
        self.assertEqual(self.asked, [])
        self.router._on_fix()
        self.assertEqual(self.asked, [True])

    def test_nothing_said_while_stale(self):
        self.gps.at(-122.0, 47.0195, stale=True)     # 55 m before the turn
        self.router._on_fix()
        self.assertEqual(self.said, [])
        self.gps.at(-122.0, 47.0195)
        self.router._on_fix()
        self.assertEqual(self.said, ["Turn right."])

    def test_a_new_route_arriving_while_stale_is_not_said(self):
        self.gps.at(-122.0, 47.005, stale=True)
        answer(self.router, ROUTE, "", "Shop", True)
        self.assertEqual(self.said, [])
        self.assertTrue(self.router.active)


class GpsWiringTest(unittest.TestCase):
    """The router on a real Gps (the fakes' signals do nothing): a new
    position is a fix and nothing else is, so satellite counts and the
    receiver coming and going don't count toward a new route."""

    def setUp(self):
        self.now = 1000.0
        clock = mock.patch("backend.routing.time.monotonic", lambda: self.now)
        clock.start()
        self.addCleanup(clock.stop)
        self.gps = Gps()
        self.router = Router(self.gps)
        self.router._clock = lambda: self.now
        self.asked = []
        self.router._request = lambda *a, **k: self.asked.append(k.get("reroute", False))
        self.router._last_reroute = float("-inf")
        self.report(0.0003, 0.0)                     # 33 m up the route, on it
        self.router.routeTo("Shop", *END)
        answer(self.router, ROUTE, "", "Shop", False)
        self.router.go()
        self.asked.clear()

    def report(self, north, east, after=1.0):
        """A position report `after` seconds on, `east` degrees of longitude
        off the line (0.003 is 230 m) and `north` of the start."""
        self.now += after
        self.gps._apply({"lat": START[1] + north, "lon": START[0] + east, "speed": 10.0,
                         "heading": 0.0, "source": "gps"})

    def test_each_position_is_one_fix(self):
        for n in range(1, 4):
            self.report(0.0003 + n * 1e-5, 0.003)    # off the line, a metre further each time
            self.assertEqual(self.router._off_count, n)
        self.assertEqual(self.asked, [True])         # the third, 2 s after the first

    def test_nothing_else_the_receiver_says_is_a_fix(self):
        self.report(0.0004, 0.003)
        self.assertEqual(self.router._off_count, 1)
        for status in ({"sats": 7, "view": 11}, {"gpsd": True}, {"receiver": True},
                       {"sats": 8, "view": 11}, {"gpsd": False}, {"sats": 0, "view": 0}):
            self.now += 0.2
            self.gps._apply(status)
        self.assertEqual(self.router._off_count, 1)
        self.assertEqual(self.asked, [])
        self.report(0.0005, 0.003)
        self.assertEqual(self.router._off_count, 2)

    def test_going_stale_starts_the_count_again(self):
        self.report(0.0004, 0.003)
        self.report(0.0005, 0.003)
        self.assertEqual(self.router._off_count, 2)
        self.now += STALE_S + 1                      # a tunnel: no new fix, the position held
        self.gps._tick()
        self.assertTrue(self.gps.stale)
        self.assertEqual(self.router._off_count, 0)
        self.report(0.0006, 0.003)                   # back in the open, still off the line
        self.assertEqual(self.router._off_count, 1)
        self.assertEqual(self.asked, [])


class FakeSettings:
    def __init__(self, **values):
        self.values = dict(values)

    def get(self, key, default=None):
        return self.values.get(key, default)

    def set(self, key, value):
        self.values[key] = value


class SavedRouteTest(unittest.TestCase):
    """What's saved, read back with a clock that's just a number."""

    def test_read_back(self):
        text = route_record("Shop", -121.99, 47.02, True, 1000.0)
        self.assertEqual(saved_route(text, 1000.0 + 600),
                         {"name": "Shop", "lon": -121.99, "lat": 47.02, "started": True})

    def test_too_old(self):
        text = route_record("Shop", -121.99, 47.02, True, 1000.0)
        self.assertIsNotNone(saved_route(text, 1000.0 + RESUME_S - 1))
        self.assertIsNone(saved_route(text, 1000.0 + RESUME_S + 1))

    def test_a_clock_behind_after_a_restart_still_counts(self):
        text = route_record("Shop", -121.99, 47.02, False, 1000.0)
        self.assertIsNotNone(saved_route(text, 1000.0 - 600))

    def test_nothing_or_junk(self):
        for text in ("", "None", "[]", "{", '{"name": "Shop"}', '{"name": 3, "lon": 0, "lat": 0, "at": 0}',
                     '{"name": "Shop", "lon": "x", "lat": 0, "at": 0}'):
            self.assertIsNone(saved_route(text, 0.0), text)


class ResumeTest(unittest.TestCase):
    """A restart with a route saved: the router asks for it again once the
    service answers and there's a position, and carries on."""

    def make(self, started=True, at=None, gps=None):
        self.gps = gps or FakeGps()
        record = route_record("Shop", *END, started, time.time() if at is None else at)
        self.settings = FakeSettings(route=record)
        router = Router(self.gps, self.settings)
        self.said, self.asked, self.resumed = [], [], []
        router.speak.connect(self.said.append)
        router.resumed.connect(lambda *a: self.resumed.append(a))
        router._request = lambda *a, **k: self.asked.append(a)
        return router

    def saved(self):
        return saved_route(self.settings.values["route"], time.time())

    def test_guidance_carries_on(self):
        router = self.make(started=True)
        self.assertEqual(self.asked, [])             # no service yet
        router._on_status(True)
        self.assertEqual(self.asked, [("Shop", *END)])
        answer(router, ROUTE, "", "Shop", False)
        self.assertTrue(router.active)
        self.assertEqual(self.said, ["Continuing to Shop. Drive north."])
        self.assertEqual(self.resumed, [])
        self.assertTrue(self.saved()["started"])

    def test_waits_for_a_position(self):
        gps = FakeGps()
        gps.hasFix = False
        router = self.make(gps=gps)
        router._on_status(True)
        self.assertEqual(self.asked, [])
        gps.hasFix = True
        router._on_fix()
        self.assertEqual(self.asked, [("Shop", *END)])
        router._on_fix()                             # asked once only
        self.assertEqual(len(self.asked), 1)

    def test_a_preview_comes_back_as_a_preview(self):
        router = self.make(started=False, at=time.time() - 600)
        router._on_status(True)
        answer(router, ROUTE, "", "Shop", False)
        self.assertTrue(router.previewing)
        self.assertEqual(self.said, [])
        self.assertEqual(self.resumed, [("Shop", *END)])
        # Still saved from when it was picked: a preview doesn't stay fresh.
        self.assertLess(json.loads(self.settings.values["route"])["at"], time.time() - 500)

    def test_too_old_stays_gone(self):
        router = self.make(at=time.time() - RESUME_S - 60)
        router._on_status(True)
        router._on_fix()
        self.assertEqual(self.asked, [])
        self.assertFalse(router.active)

    def test_already_there(self):
        gps = FakeGps()
        gps.at(END[0] - 0.001, END[1])               # 76 m away: parked at it
        router = self.make(gps=gps)
        router._on_status(True)
        self.assertEqual(self.asked, [])
        self.assertEqual(self.settings.values["route"], "")

    def test_a_place_picked_first_wins(self):
        router = self.make()
        router.routeTo("Cafe", -122.01, 47.01)
        router._on_status(True)
        self.assertEqual(self.asked, [("Cafe", -122.01, 47.01)])
        self.assertEqual(self.saved()["name"], "Cafe")

    def test_no_route_now_forgets_it(self):
        router = self.make()
        router._on_status(True)
        answer(router, None, "No path could be found", "Shop", False)
        self.assertFalse(router.active)
        self.assertEqual(router.destinationName, "")
        self.assertEqual(self.settings.values["route"], "")


class SavingTest(unittest.TestCase):
    """What gets saved as the route changes."""

    def setUp(self):
        self.gps = FakeGps()
        self.settings = FakeSettings()
        self.router = Router(self.gps, self.settings)
        self.router._request = lambda *a, **k: None

    def saved(self):
        return saved_route(self.settings.values.get("route", ""), time.time())

    def test_preview_then_go_then_end(self):
        self.router.routeTo("Shop", *END)
        self.assertEqual(self.saved(), {"name": "Shop", "lon": END[0], "lat": END[1], "started": False})
        answer(self.router, ROUTE, "", "Shop", False)
        self.router.go()
        self.assertTrue(self.saved()["started"])
        self.router.stop()
        self.assertEqual(self.settings.values["route"], "")

    def test_arriving_forgets_it(self):
        self.router.routeTo("Shop", *END)
        answer(self.router, ROUTE, "", "Shop", False)
        self.router.go()
        self.gps.at(END[0] - 0.0001, END[1])
        self.router._on_fix()
        self.assertTrue(self.router.arrived)
        self.assertEqual(self.settings.values["route"], "")

    def test_kept_fresh_while_driving(self):
        self.router.routeTo("Shop", *END)
        answer(self.router, ROUTE, "", "Shop", False)
        self.router.go()
        self.settings.values["route"] = route_record("Shop", *END, True, time.time() - 3000)
        self.router._saved_at -= 61                  # a minute since the last save
        self.gps.at(-122.0, 47.005)
        self.router._on_fix()
        self.assertGreater(json.loads(self.settings.values["route"])["at"], time.time() - 5)


class RepeatTest(unittest.TestCase):
    def setUp(self):
        self.gps = FakeGps()
        self.router = Router(self.gps)
        self.said = []
        self.router.speak.connect(self.said.append)
        self.router._request = lambda *a, **k: None
        self.router.routeTo("Shop", *END)
        answer(self.router, ROUTE, "", "Shop", False)

    def test_nothing_without_guidance(self):
        self.router.repeatLast()                       # only a preview
        self.assertEqual(self.said, [])
        self.router.stop()
        self.router.repeatLast()
        self.assertEqual(self.said, [])

    def test_says_the_last_direction_again(self):
        self.router.go()
        self.router.repeatLast()
        self.assertEqual(self.said, ["Drive north.", "Drive north."])
        self.gps.at(CORNER[0], 47.0195)                 # just before the right turn
        self.router._on_fix()
        self.router.repeatLast()
        self.assertEqual(self.said[-1], self.said[-2])
        self.assertNotEqual(self.said[-1], "Drive north.")

    def test_a_new_route_forgets_it(self):
        self.router.go()
        self.router.routeTo("Cafe", *START)
        answer(self.router, ROUTE, "", "Cafe", False)
        self.said.clear()
        self.router.repeatLast()
        self.assertEqual(self.said, [])


class InlineThread:
    """Stands in for threading.Thread: start() runs the work on the spot."""

    def __init__(self, target=None, name=None, daemon=None):
        self.target = target

    def start(self):
        self.target()


class Reply(io.BytesIO):
    """What urlopen hands back, as a context manager."""


def http_error(body):
    return urllib.error.HTTPError("http://router/route", 400, "Bad Request", {}, io.BytesIO(body))


class RequestTest(unittest.TestCase):
    """Whatever the router answers, the request comes back and `computing`
    clears, or the Maps page would say "Finding a route" for good."""

    def setUp(self):
        inline = mock.patch("backend.routing.threading", SimpleNamespace(Thread=InlineThread))
        inline.start()
        self.addCleanup(inline.stop)
        self.router = Router(FakeGps())

    def ask(self, answer):
        def urlopen(req, timeout):
            if isinstance(answer, Exception):
                raise answer
            return Reply(answer)
        with mock.patch("backend.routing.urllib.request.urlopen", urlopen), \
                mock.patch("builtins.print"):
            self.router.routeTo("Shop", *END)
        self.assertFalse(self.router.computing)
        return self.router.error

    def test_a_route(self):
        self.assertEqual(self.ask(json.dumps(ROUTE).encode()), "")
        self.assertTrue(self.router.previewing)

    def test_the_routers_own_words_for_why_not(self):
        body = json.dumps({"error_code": 442, "error": "No path could be found for input"})
        self.assertEqual(self.ask(http_error(body.encode())), "No road route to there")

    def test_an_error_body_that_isnt_an_object(self):
        for body in (b'["no"]', b'"no"', b"null", b'{"error": 7}', b"<html>", b""):
            with self.subTest(body=body):
                self.assertEqual(self.ask(http_error(body)), "No route found")

    def test_no_router(self):
        self.assertEqual(self.ask(urllib.error.URLError("refused")), "Routing isn't running")

    def test_an_answer_that_isnt_a_route(self):
        broken = {"trip": {"summary": {"time": 1}, "legs": [{"shape": polyline6([START, END]),
                                                             "maneuvers": []}]}}
        for body in (b"[1, 2]", b'"route"', b"null", b"{}", json.dumps(broken).encode()):
            with self.subTest(body=body):
                self.assertEqual(self.ask(body), "Couldn't read the route")
                self.assertFalse(self.router.previewing)

    def test_something_unexpected_still_comes_back(self):
        # A bug in the request code: logged by threading.excepthook, and
        # the request still ends.
        with self.assertRaises(ZeroDivisionError):
            self.ask(ZeroDivisionError("bug"))
        self.assertFalse(self.router.computing)
        self.assertEqual(self.router.error, "Couldn't get a route")


class AvoidTest(unittest.TestCase):
    """The avoid options reach Valhalla's costing, on reroutes too."""

    def setUp(self):
        inline = mock.patch("backend.routing.threading", SimpleNamespace(Thread=InlineThread))
        inline.start()
        self.addCleanup(inline.stop)
        self.settings = FakeSettings()
        self.router = Router(FakeGps(), self.settings)
        self.sent = []

    def urlopen(self, req, timeout):
        self.sent.append(json.loads(req.data))
        return Reply(json.dumps(ROUTE).encode())

    def run_with_router(self, fn):
        with mock.patch("backend.routing.urllib.request.urlopen", self.urlopen):
            fn()

    def test_nothing_avoided_sends_no_options(self):
        self.run_with_router(lambda: self.router.routeTo("Shop", *END))
        self.assertNotIn("costing_options", self.sent[0])

    def test_avoided_roads_are_zeroed(self):
        self.router.setAvoid("avoidFerries", True)
        self.router.setAvoid("avoidTolls", True)
        self.run_with_router(lambda: self.router.routeTo("Shop", *END))
        self.assertEqual(self.sent[0]["costing_options"], {"auto": {"use_ferry": 0, "use_tolls": 0}})
        self.assertEqual(self.sent[0]["costing"], "auto")

    def test_a_reroute_carries_them(self):
        self.router.setAvoid("avoidHighways", True)
        self.run_with_router(lambda: self.router.routeTo("Shop", *END))
        self.run_with_router(lambda: self.router._request(*self.router._dest, reroute=True))
        self.assertEqual(self.sent[1]["costing_options"], {"auto": {"use_highways": 0}})

    def test_changing_one_with_a_route_shown_asks_again(self):
        self.run_with_router(lambda: self.router.routeTo("Shop", *END))
        self.run_with_router(lambda: self.router.setAvoid("avoidFerries", True))
        self.assertEqual(len(self.sent), 2)
        self.assertEqual(self.sent[1]["costing_options"], {"auto": {"use_ferry": 0}})
        self.assertTrue(self.router.previewing)
        self.assertFalse(self.router.computing)
        self.assertTrue(self.router.avoidFerries)
        self.assertEqual(self.settings.values["avoidFerries"], "true")

    def test_no_route_means_no_request(self):
        self.run_with_router(lambda: self.router.setAvoid("avoidFerries", True))
        self.assertEqual(self.sent, [])

    def test_unchanged_or_unknown_does_nothing(self):
        self.run_with_router(lambda: self.router.routeTo("Shop", *END))
        self.run_with_router(lambda: self.router.setAvoid("avoidFerries", False))
        self.run_with_router(lambda: self.router.setAvoid("bogus", True))
        self.assertEqual(len(self.sent), 1)

    def test_still_computing_the_first_route_is_replaced(self):
        held = mock.patch("backend.routing.threading", SimpleNamespace(
            Thread=lambda **k: SimpleNamespace(start=lambda: None)))
        held.start()
        self.addCleanup(held.stop)
        self.router.routeTo("Shop", *END)
        old = self.router._gen
        self.router.setAvoid("avoidFerries", True)
        self.assertGreater(self.router._gen, old)
        self.assertTrue(self.router.computing)
        answer(self.router, ROUTE, "", "Shop", False, gen=old)       # the old answer is dropped
        self.assertTrue(self.router.computing)


class StaleAnswerTest(unittest.TestCase):
    """An answer that isn't for the latest request is dropped: a cancelled
    route stays cancelled and the last place picked wins."""

    def setUp(self):
        self.router = Router(FakeGps())
        self.threads = mock.patch("backend.routing.threading", SimpleNamespace(
            Thread=lambda **k: SimpleNamespace(start=lambda: None)))
        self.threads.start()
        self.addCleanup(self.threads.stop)

    def test_cancel_while_computing(self):
        self.router.routeTo("Shop", *END)
        old = self.router._gen
        self.assertTrue(self.router.computing)
        self.router.stop()
        self.assertFalse(self.router.computing)
        answer(self.router, ROUTE, "", "Shop", False, gen=old)
        self.assertFalse(self.router.previewing)
        self.assertFalse(self.router.computing)
        self.assertEqual(self.router.destinationName, "")

    def test_a_new_place_while_computing(self):
        self.router.routeTo("Shop", *END)
        old = self.router._gen
        self.router.routeTo("Cafe", *START)
        answer(self.router, ROUTE, "", "Cafe", False)
        self.assertEqual(self.router.destinationName, "Cafe")
        # The first answer lands last: it changes nothing.
        answer(self.router, ROUTE, "", "Shop", False, gen=old)
        self.assertEqual(self.router.destinationName, "Cafe")

    def test_a_stale_answer_leaves_a_newer_request_computing(self):
        self.router.routeTo("Shop", *END)
        old = self.router._gen
        self.router.routeTo("Cafe", *START)
        answer(self.router, None, "No route found", "Shop", False, gen=old)
        self.assertTrue(self.router.computing)
        self.assertEqual(self.router.error, "")

    def test_a_stale_reroute_answer(self):
        self.router.routeTo("Shop", *END)
        answer(self.router, ROUTE, "", "Shop", False)
        self.router.go()
        self.router._request("Shop", *END, reroute=True)
        old = self.router._gen
        self.router.stop()
        answer(self.router, ROUTE, "", "Shop", True, gen=old)
        self.assertFalse(self.router.active)
        self.assertFalse(self.router.previewing)


if __name__ == "__main__":
    unittest.main()
