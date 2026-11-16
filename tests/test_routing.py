"""Off-Pi tests for following a route (backend/routing.py) with a fake GPS:
no reroute and nothing said while the position is stale; the route saved
in settings and picked up again after a restart.

    python3 -m unittest tests.test_routing
"""

import io
import json
import math
import time
import unittest
import urllib.error
from pathlib import Path
from types import SimpleNamespace
from unittest import mock

from PyQt6.QtCore import QCoreApplication

from backend.gps import STALE_S, Gps
from backend.routing import (OFF_ROUTE_FIXES, OFF_ROUTE_S, RESUME_S, Route, Router, decode_polyline6,
                             exit_sign, has_toll, route_record, saved_route, short_instruction, tidy, via_name)

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


class ClockAfterRebootTest(unittest.TestCase):
    """fake-hwclock: after a reboot the clock starts where it stopped, so a
    route left days ago looks seconds old until the clock is set."""

    BOOT, EARLIER = "boot-now", "boot-before"

    def setUp(self):
        for name, value in (("boot_id", lambda: self.BOOT), ("CLOCK_POLL_S", 0)):
            p = mock.patch(f"backend.routing.{name}", value)
            p.start()
            self.addCleanup(p.stop)
        self.gps = FakeGps()

    def make(self, boot, started=True, age=60):
        with mock.patch("backend.routing.boot_id", lambda: boot):
            record = route_record("Shop", *END, started, time.time() - age)
        self.settings = FakeSettings(route=record)
        router = Router(self.gps, self.settings)
        self.said, self.asked, self.resumed = [], [], []
        router.speak.connect(self.said.append)
        router.resumed.connect(lambda *a: self.resumed.append(a))
        router._request = lambda *a, **k: self.asked.append(a)
        router._on_status(True)
        return router

    def test_saved_route_from_an_earlier_boot_is_not_aged_yet(self):
        text = route_record("Shop", *END, True, 1000.0)
        r = saved_route(text, 1000.0 + 60, "another boot")
        self.assertTrue(r["unverified"])
        self.assertEqual(r["at"], 1000.0)
        self.assertNotIn("unverified", saved_route(text, 1000.0 + 60, json.loads(text)["boot"]))
        self.assertIsNone(saved_route(text, 1000.0 + RESUME_S + 1, json.loads(text)["boot"]))

    def test_an_earlier_boot_waits_for_the_clock(self):
        router = self.make(self.EARLIER)
        router._on_fix()
        self.assertEqual(self.asked, [])             # looks 60 s old, but nobody knows
        self.assertEqual(self.said, [])

    def test_the_clock_set_and_it_is_recent_carries_on(self):
        router = self.make(self.EARLIER, age=1800)
        router._on_clock(True)
        self.assertEqual(self.asked, [("Shop", *END)])
        answer(router, ROUTE, "", "Shop", False)
        self.assertEqual(self.said, ["Continuing to Shop. Drive north."])

    def test_the_clock_set_and_it_is_days_old_stays_gone(self):
        router = self.make(self.EARLIER)
        # The clock jumps ahead days when it's set.
        with mock.patch("backend.routing.time") as t:
            t.time.return_value = time.time() + 4 * 86400
            router._on_clock(True)
        self.assertEqual(self.asked, [])
        self.assertFalse(router.active)
        self.assertEqual(self.settings.values["route"], "")

    def test_the_clock_never_set_gives_a_preview_not_guidance(self):
        router = self.make(self.EARLIER)
        router._on_clock(False)
        self.assertEqual(self.asked, [("Shop", *END)])
        answer(router, ROUTE, "", "Shop", False)
        self.assertFalse(router.active)
        self.assertEqual(self.said, [])
        self.assertEqual(self.resumed, [("Shop", *END)])

    def test_the_same_boot_carries_on_without_the_clock(self):
        router = self.make(self.BOOT)
        router._on_fix()
        self.assertEqual(self.asked, [("Shop", *END)])
        answer(router, ROUTE, "", "Shop", False)
        self.assertEqual(self.said, ["Continuing to Shop. Drive north."])

    def test_a_place_picked_while_waiting_is_not_lost(self):
        router = self.make(self.EARLIER)
        router.routeTo("Cafe", -122.01, 47.01)
        router._on_clock(False)
        self.assertEqual(self.asked, [("Cafe", -122.01, 47.01)])

    def test_the_wait_is_over_when_the_clock_is_set(self):
        router = self.make(self.EARLIER)
        answers = iter([False, False, True])
        got = []
        router._synced.connect(got.append)
        with mock.patch("backend.routing.clock_synced", lambda: next(answers)):
            router._wait_for_clock()
        self.assertEqual(got, [True])

    def test_the_wait_is_bounded(self):
        router = self.make(self.EARLIER)
        got = []
        router._synced.connect(got.append)
        with mock.patch("backend.routing.clock_synced", lambda: False), \
                mock.patch("backend.routing.CLOCK_WAIT_S", 0):
            router._wait_for_clock()
        self.assertEqual(got, [False])

    def test_start_waits_in_a_thread_only_for_an_earlier_boot(self):
        for boot, waits in ((self.EARLIER, True), (self.BOOT, False)):
            router = self.make(boot)
            router._check = lambda: None
            with mock.patch("backend.routing.threading.Thread") as thread:
                router.start()
            self.assertEqual(thread.called, waits, boot)
            router._check_timer.stop()


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

    def test_a_new_place_picked_after_arriving_is_not_stopped_by_the_auto_stop(self):
        self.router.routeTo("Shop", *END)
        answer(self.router, ROUTE, "", "Shop", False)
        self.router.go()
        self.gps.at(END[0] - 0.0001, END[1])
        self.router._on_fix()
        self.assertTrue(self.router.arrived)
        self.assertTrue(self.router._arrive_timer.isActive())
        self.router.routeTo("Cafe", *START)         # within the 20 s
        self.assertFalse(self.router._arrive_timer.isActive())
        self.assertFalse(self.router.arrived)
        self.assertEqual(self.router._dest[0], "Cafe")

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

    def test_a_route_that_failed_is_tried_again_with_the_new_option(self):
        def no_route(req, timeout):
            raise urllib.error.URLError("refused")
        with mock.patch("backend.routing.urllib.request.urlopen", no_route):
            self.router.routeTo("Shop", *END)
        self.assertFalse(self.router.previewing)
        self.run_with_router(lambda: self.router.setAvoid("avoidTolls", True))
        self.assertTrue(self.router.previewing)

    def test_after_arriving_an_option_asks_for_nothing(self):
        self.run_with_router(lambda: self.router.routeTo("Shop", *END))
        self.router._arrived = True
        self.sent.clear()
        self.run_with_router(lambda: self.router.setAvoid("avoidTolls", True))
        self.assertEqual(self.sent, [])
        self.assertTrue(self.router._arrived)       # the auto-stop still comes

    def test_directions_are_in_miles_unless_metric(self):
        self.run_with_router(lambda: self.router.routeTo("Shop", *END))
        self.assertEqual(self.sent[0]["directions_options"]["units"], "miles")
        self.settings.set("metric", "true")
        self.run_with_router(lambda: self.router._request(*self.router._dest, reroute=True))
        self.assertEqual(self.sent[1]["directions_options"]["units"], "kilometers")

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

    def test_a_toll_change_keeps_the_old_route_until_the_answer_lands(self):
        self.run_with_router(lambda: self.router.routeTo("Shop", *END))
        shown = self.router.remainingDistance
        held = mock.patch("backend.routing.threading", SimpleNamespace(
            Thread=lambda **k: SimpleNamespace(start=lambda: None)))
        held.start()
        self.addCleanup(held.stop)
        self.router.setAvoid("avoidTolls", True)
        self.assertTrue(self.router.computing)
        self.assertTrue(self.router.previewing)
        self.assertEqual(self.router.remainingDistance, shown)
        answer(self.router, ROUTE, "", "Shop", True)
        self.assertFalse(self.router.computing)
        self.assertTrue(self.router.previewing)

    def test_the_toll_request_zeroes_use_tolls(self):
        self.run_with_router(lambda: self.router.routeTo("Shop", *END))
        self.run_with_router(lambda: self.router.setAvoid("avoidTolls", True))
        self.assertEqual(self.sent[-1]["costing_options"]["auto"]["use_tolls"], 0)

    def test_maps_page_has_a_chip_for_each_avoid_option(self):
        qml = (Path(__file__).resolve().parent.parent / "qml/pages/MapsPage.qml").read_text()
        for key in ("avoidHighways", "avoidTolls", "avoidFerries"):
            self.assertIn('routing.setAvoid("%s", !routing.%s)' % (key, key), qml)

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


class DecodePolylineTest(unittest.TestCase):
    def test_a_known_shape(self):
        # Google's documented example, whose 1e-5 values are (38.5, -120.2),
        # (40.7, -120.95), (43.252, -126.453): at Valhalla's 1e-6 they come out a tenth the size.
        points = decode_polyline6("_p~iF~ps|U_ulLnnqC_mqNvxq`@")
        want = [(-12.02, 3.85), (-12.095, 4.07), (-12.6453, 4.3252)]
        self.assertEqual(len(points), 3)
        for got, exp in zip(points, want):
            self.assertAlmostEqual(got[0], exp[0], places=6)
            self.assertAlmostEqual(got[1], exp[1], places=6)

    def test_lon_lat_order_and_the_canned_route(self):
        self.assertEqual(decode_polyline6(ROUTE["trip"]["legs"][0]["shape"]), [START, CORNER, END])

    def test_nothing(self):
        self.assertEqual(decode_polyline6(""), [])

    def test_south_and_west_are_negative_deltas(self):
        pts = [(-122.0, 47.0), (-122.5, 46.5), (-122.5001, 46.4999)]
        for got, exp in zip(decode_polyline6(polyline6(pts)), pts):
            self.assertAlmostEqual(got[0], exp[0], places=6)
            self.assertAlmostEqual(got[1], exp[1], places=6)


class TidyTest(unittest.TestCase):
    def test_a_chained_step_loses_its_capital(self):
        self.assertEqual(tidy("Turn left onto Pine Street. Then Keep right at the fork."),
                         "Turn left onto Pine Street. Then keep right at the fork.")

    def test_after_a_sentence_it_stays_a_sentence(self):
        self.assertEqual(tidy("Drive north. Then Turn right."), "Drive north. Then turn right.")

    def test_in_the_middle_of_a_sentence(self):
        self.assertEqual(tidy("Turn left, Then Merge onto I-5"), "Turn left, then merge onto I-5")

    def test_nothing_to_change(self):
        for text in ("Turn right.", "", "Then", "Then we go on.", "Bethen Keep left"):
            self.assertEqual(tidy(text), text)


class RouteShapeTest(unittest.TestCase):
    """A Route over the canned Valhalla reply: north 2.2 km, then east 760 m."""

    def setUp(self):
        self.r = Route(ROUTE, "Shop")

    def test_the_length_is_the_legs_in_metres(self):
        self.assertAlmostEqual(self.r.length, 0.02 * 110540 + 0.01 * 111320 * math.cos(math.radians(47.0)), delta=1)
        self.assertEqual(self.r.cum[0], 0.0)
        self.assertAlmostEqual(self.r.cum[1], 2210.8, delta=1)

    def test_it_starts_at_the_start(self):
        self.r.locate(*START)
        self.assertAlmostEqual(self.r.along, 0.0, places=3)
        self.assertAlmostEqual(self.r.off, 0.0, places=3)
        self.assertAlmostEqual(self.r.remaining, self.r.length, places=3)
        self.assertEqual(self.r.seg, 0)

    def test_half_way_up_the_first_leg(self):
        self.r.locate(-122.0, 47.01)
        self.assertAlmostEqual(self.r.along, self.r.cum[1] / 2, delta=0.5)
        self.assertLess(self.r.off, 0.5)

    def test_beside_the_road_it_is_the_distance_off(self):
        self.r.locate(-121.999, 47.01)        # 0.001 degrees of longitude east
        self.assertAlmostEqual(self.r.off, 0.001 * 111320 * math.cos(math.radians(47.0)), delta=1)
        self.assertAlmostEqual(self.r.along, self.r.cum[1] / 2, delta=1)

    def test_on_the_second_leg(self):
        self.r.locate(-121.995, 47.02)
        self.assertEqual(self.r.seg, 1)
        self.assertAlmostEqual(self.r.along, self.r.cum[1] + 0.005 * 111320 * math.cos(math.radians(47.0)), delta=1)
        self.assertAlmostEqual(self.r.to_end, 0.005 * 111320 * math.cos(math.radians(47.0)), delta=1)

    def test_past_the_end_stops_at_the_end(self):
        self.r.locate(-121.9, 47.02)
        self.assertAlmostEqual(self.r.along, self.r.length, places=3)
        self.assertEqual(self.r.remaining, 0.0)

    def test_the_same_fix_again_is_ignored(self):
        self.r.locate(-122.0, 47.01, 0.0, 10.0, 0.0)
        before = (self.r.along, self.r._at)
        self.r.locate(-122.0, 47.01, 0.0, 10.0, 5.0)
        self.assertEqual((self.r.along, self.r._at), before)


class ManeuverTest(unittest.TestCase):
    def route(self, end=END):
        data = json.loads(json.dumps(ROUTE))
        data["trip"]["legs"][0]["shape"] = polyline6([START, CORNER, end])
        return Route(data, "Shop")

    def test_the_first_turn_ahead_at_the_start(self):
        r = Route(ROUTE, "Shop")
        r.locate(*START)
        self.assertEqual(r.next_maneuver()["instruction"], "Turn right.")

    def test_the_turn_just_reached_is_behind(self):
        r = Route(ROUTE, "Shop")
        r.along = r.cum[1] - 6
        self.assertEqual(r.next_maneuver()["instruction"], "Turn right.")
        r.along = r.cum[1] - 4              # within 5 m: already counted as done
        self.assertEqual(r.next_maneuver()["instruction"], "You have arrived.")

    def test_after_the_last_turn_it_is_the_arrival(self):
        r = Route(ROUTE, "Shop")
        r.locate(-121.995, 47.02)
        self.assertEqual(r.next_maneuver()["instruction"], "You have arrived.")
        r.locate(-121.9, 47.02)
        self.assertEqual(r.next_maneuver()["instruction"], "You have arrived.")

    def test_a_turn_far_after_the_next_is_not_shown_with_it(self):
        r = Route(ROUTE, "Shop")
        r.locate(*START)
        self.assertIsNone(r.then_maneuver())          # the arrival is 760 m after the turn

    def test_a_turn_right_after_the_next_is_shown_with_it(self):
        r = self.route(end=(-121.9975, 47.02))        # 190 m after the turn
        r.locate(*START)
        self.assertEqual(r.next_maneuver()["instruction"], "Turn right.")
        self.assertEqual(r.then_maneuver()["instruction"], "You have arrived.")

    def test_the_gap_has_a_limit(self):
        r = self.route(end=(-121.9965, 47.02))        # 266 m: still near
        self.assertIsNotNone(r.then_maneuver())
        r = self.route(end=(-121.995, 47.02))         # 380 m: too far
        self.assertIsNone(r.then_maneuver())

    def test_nothing_after_the_arrival(self):
        r = self.route(end=(-121.9975, 47.02))
        r.locate(-121.9, 47.02)
        self.assertEqual(r.next_maneuver()["instruction"], "You have arrived.")
        self.assertIsNone(r.then_maneuver())


class FerryTest(unittest.TestCase):
    def route(self, *extra):
        data = json.loads(json.dumps(ROUTE))
        data["trip"]["legs"][0]["maneuvers"][1:1] = list(extra)
        return Route(data, "Shop")

    def test_no_ferry(self):
        self.assertEqual(Route(ROUTE, "Shop").ferries, [])

    def test_detected_from_type_and_named(self):
        r = self.route({"type": 28, "instruction": "Take the Fauntleroy - Vashon ferry.",
                        "time": 600, "length": 8.0})
        self.assertEqual(r.ferries, [{"name": "Fauntleroy - Vashon", "time": 600.0, "length": 8000.0}])

    def test_lengths_follow_the_units_the_router_used(self):
        data = json.loads(json.dumps(ROUTE))
        data["trip"]["units"] = "miles"
        data["trip"]["legs"][0]["maneuvers"].insert(1, {"type": 28, "ferry": True, "time": 600, "length": 5.0,
                                                       "instruction": "Take the A - B ferry."})
        r = Route(data, "Shop")
        self.assertAlmostEqual(r.ferries[0]["length"], 5.0 * 1609.344)

    def test_detected_from_travel_mode_and_merged(self):
        r = self.route({"type": 28, "travel_mode": "drive", "ferry": True, "instruction": "Take the A - B ferry.",
                        "time": 300, "length": 4.0},
                       {"type": 29, "travel_mode": "drive", "ferry": True, "instruction": "Exit the ferry.",
                        "time": 300, "length": 4.0})
        self.assertEqual(len(r.ferries), 1)
        self.assertEqual(r.ferries[0]["name"], "A - B")
        self.assertEqual(r.ferries[0]["time"], 600.0)
        self.assertEqual(r.ferries[0]["length"], 8000.0)

    def test_unnamed_ferry(self):
        r = self.route({"ferry": True, "instruction": "Board."})
        self.assertEqual(r.ferries[0]["name"], "Ferry")

    def test_missing_keys_do_not_raise(self):
        r = self.route({"type": 28}, {"ferry": True, "time": None, "length": "x"})
        self.assertEqual(r.ferries, [{"name": "Ferry", "time": 0.0, "length": 0.0}])

    def test_two_ferries_stay_separate(self):
        r = self.route({"type": 28, "instruction": "Take the A ferry.", "time": 60},
                       {"type": 10, "instruction": "Turn right."},
                       {"type": 28, "instruction": "Take the B ferry.", "time": 120})
        self.assertEqual([f["name"] for f in r.ferries], ["A", "B"])

    def test_unflagged_exit_is_not_a_ferry(self):
        r = self.route({"type": 28, "instruction": "Take the A ferry.", "time": 60},
                       {"type": 29, "travel_mode": "drive", "instruction": "Exit.", "time": 99})
        self.assertEqual(r.ferries[0]["time"], 60.0)

    def test_names(self):
        for text, names, want in (
                ("Take the ferry toward Kingston Ferry Terminal.", None, "Ferry"),
                ("Take the Fauntleroy Ferry Dock - Vashon Ferry.", None, "Fauntleroy Ferry Dock - Vashon"),
                ("Take the ferry.", ["Bainbridge FERRY"], "Bainbridge"),
                ("Take the ferry.", [" ferry "], "Ferry")):
            m = {"type": 28, "instruction": text}
            if names:
                m["street_names"] = names
            self.assertEqual(self.route(m).ferries[0]["name"], want, text)

    def test_nan_and_inf_do_not_raise(self):
        r = self.route({"type": 28, "time": float("nan"), "length": float("inf")},
                       {"ferry": True, "time": float("inf")})
        router = Router(FakeGps())
        router._route = r
        self.assertEqual(router.ferries, [{"name": "Ferry", "minutes": 0}])

    def test_router_properties(self):
        router = Router(FakeGps())
        self.assertEqual(router.ferries, [])
        router._route = self.route({"type": 28, "instruction": "Take the A ferry.", "time": 10})
        self.assertEqual(router.ferries, [{"name": "A", "minutes": 1}])


class ShortInstructionTest(unittest.TestCase):
    @staticmethod
    def el(*texts):
        return [{"text": t} for t in texts]

    def m(self, kind, text="Valhalla says this.", streets=(), **sign):
        out = {"type": kind, "instruction": text, "street_names": list(streets)}
        if sign:
            out["sign"] = {f"exit_{k}_elements": self.el(*v) for k, v in sign.items()}
        return out

    def test_exit_with_number_and_toward_or_branch(self):
        self.assertEqual(short_instruction(self.m(20, number=["165B"], toward=["I-5 S"])),
                         "Exit 165B toward I-5 S")
        self.assertEqual(short_instruction(self.m(21, number=["165B"], branch=["I-5 S"])),
                         "Exit 165B onto I-5 S")
        both = self.m(20, number=["165B"], toward=["Tacoma"], branch=["I-5 S"])
        self.assertEqual(short_instruction(both), "Exit 165B toward Tacoma")
        self.assertEqual(short_instruction(self.m(20, toward=["Tacoma", "Seattle"])),
                         "Exit toward Tacoma / Seattle")

    def test_ramp(self):
        self.assertEqual(short_instruction(self.m(18, toward=["Tacoma"])), "Ramp toward Tacoma")
        self.assertEqual(short_instruction(self.m(19, branch=["SR 16 W"])), "Ramp onto SR 16 W")
        self.assertEqual(short_instruction(self.m(18, "Take the ramp on the right.")),
                         "Take the ramp on the right")

    def test_turns(self):
        self.assertEqual(short_instruction(self.m(15, streets=["Pine St"])), "Turn left onto Pine St")
        self.assertEqual(short_instruction(self.m(10, streets=["Pine St"])), "Turn right onto Pine St")
        both = {"type": 10, "begin_street_names": ["Oak Ave"], "street_names": ["Pine St"],
                "instruction": "x."}
        self.assertEqual(short_instruction(both), "Turn right onto Oak Ave")
        for kind in (2, 3):                      # start right/left: "Head north on X"
            self.assertEqual(short_instruction(self.m(kind, "Head north on Pine St.", ["Pine St"])),
                             "Head north on Pine St")
        self.assertEqual(short_instruction(self.m(9, streets=["Pine St"])), "Bear right onto Pine St")
        self.assertEqual(short_instruction(self.m(16, streets=["Pine St"])), "Bear left onto Pine St")
        self.assertEqual(short_instruction(self.m(11, streets=["Pine St"])), "Sharp right onto Pine St")
        self.assertEqual(short_instruction(self.m(14, streets=["Pine St"])), "Sharp left onto Pine St")
        begin = {"type": 10, "begin_street_names": ["Oak Ave"], "instruction": "x."}
        self.assertEqual(short_instruction(begin), "Turn right onto Oak Ave")
        self.assertEqual(short_instruction(self.m(15, "Turn left.")), "Turn left")     # no street

    def test_keep(self):
        self.assertEqual(short_instruction(self.m(23, toward=["I-5 S"])), "Keep right toward I-5 S")
        self.assertEqual(short_instruction(self.m(24, streets=["Main St"])), "Keep left onto Main St")
        self.assertEqual(short_instruction(self.m(22, streets=["Main St"])), "Keep straight on Main St")
        self.assertEqual(short_instruction(self.m(23, "Keep right at the fork.")), "Keep right at the fork")

    def test_merge(self):
        for kind, text in ((25, "Merge onto"), (37, "Merge right onto"), (38, "Merge left onto")):
            self.assertEqual(short_instruction(self.m(kind, branch=["I-5 S"])), f"{text} I-5 S")
        self.assertEqual(short_instruction(self.m(25, streets=["I-90 E"])), "Merge onto I-90 E")

    def test_roundabout(self):
        m = self.m(26, streets=["Main St"])
        for n, word in ((1, "1st"), (2, "2nd"), (3, "3rd"), (4, "4th"), (11, "11th"), (22, "22nd")):
            m["roundabout_exit_count"] = n
            self.assertEqual(short_instruction(m), f"Roundabout, take the {word} exit")
        self.assertEqual(short_instruction(m), "Roundabout, take the 22nd exit")
        del m["roundabout_exit_count"]
        self.assertEqual(short_instruction(m), "Valhalla says this")

    def test_continue(self):
        self.assertEqual(short_instruction(self.m(8, streets=["Main St"])), "Continue on Main St")
        self.assertEqual(short_instruction(self.m(7, streets=["Main St"])), "Continue on Main St")
        self.assertEqual(short_instruction(self.m(8, "Continue.")), "Continue")

    def test_ferry_arrival_and_unknown_keep_valhalla_text(self):
        for kind in (28, 29, 4, 5, 6, 12, 13, 99, None):
            self.assertEqual(short_instruction(self.m(kind, "Take the Bremerton ferry.", ["X"],
                                                      toward=["Y"])), "Take the Bremerton ferry")
        self.assertEqual(short_instruction({"type": 5, "instruction": "Arrive at Cafe"}), "Arrive at Cafe")

    def test_junk_never_raises(self):
        for junk in (None, [], "text", 5, {}, {"type": "x"}, {"type": 20, "sign": "no"},
                     {"type": 20, "sign": {"exit_toward_elements": "I-5"}},
                     {"type": 20, "sign": {"exit_toward_elements": [None, 3, {"text": None}, {"x": 1}]},
                      "instruction": "Take the exit."},
                     {"type": 15, "street_names": "Pine", "instruction": "Turn left."},
                     {"type": 15, "street_names": [None, 4], "instruction": "Turn left."},
                     {"type": 26, "roundabout_exit_count": "2", "instruction": None},
                     {"type": 26, "roundabout_exit_count": True},
                     {"type": [1], "instruction": 7}):
            self.assertIsInstance(short_instruction(junk), str)
        self.assertEqual(short_instruction(
            {"type": 20, "sign": {"exit_toward_elements": [None, 3, {"text": None}]},
             "instruction": "Take the exit."}), "Take the exit")
        self.assertEqual(short_instruction({"type": 15, "street_names": "Pine", "instruction": "Turn left."}),
                         "Turn left")

    def test_length_cap(self):
        long_names = ["Interstate 5 Southbound Express Lanes", "Tacoma Narrows Bridge", "Gig Harbor"]
        out = short_instruction(self.m(20, number=["165B"], toward=long_names))
        self.assertEqual(out, "Exit 165B toward Interstate 5 Southbound Express Lanes")
        self.assertLessEqual(len(out), 60)
        out = short_instruction(self.m(15, streets=["Martin Luther King Junior Memorial Way South East"]))
        self.assertLessEqual(len(out), 60)
        self.assertEqual(out, "Turn left onto Martin Luther King Junior Memorial Way South")
        out = short_instruction(self.m(15, streets=["Supercalifragilisticexpialidocious" * 3]))
        self.assertLessEqual(len(out), 60)
        self.assertTrue(out.startswith("Turn left onto"))

    def test_screen_short_speech_full(self):
        route = {"trip": {"summary": {"time": 200.0}, "legs": [{
            "shape": polyline6([START, CORNER, END]),
            "maneuvers": [
                {"type": 1, "begin_shape_index": 0, "instruction": "Drive north.",
                 "verbal_pre_transition_instruction": "Drive north."},
                {"type": 10, "begin_shape_index": 1, "street_names": ["Pine St"],
                 "instruction": "Turn right onto Pine Street.",
                 "verbal_pre_transition_instruction": "Turn right onto Pine Street, then arrive.",
                 "verbal_transition_alert_instruction": "Turn right onto Pine Street."},
                {"type": 4, "begin_shape_index": 2, "instruction": "You have arrived."},
            ]}]}}
        gps = FakeGps()
        router = Router(gps)
        said = []
        router.speak.connect(said.append)
        router._request = lambda *a, **k: None
        router.routeTo("Shop", *END)
        answer(router, route, "", "Shop", False)
        router.go()
        self.assertEqual(said, ["Drive north."])
        gps.at(CORNER[0], 47.0195)
        router._on_fix()
        self.assertEqual(router.instruction, "Turn right onto Pine St")
        self.assertEqual(said[-1], "Turn right onto Pine Street, then arrive.")
        router.repeatLast()
        self.assertEqual(said[-1], "Turn right onto Pine Street, then arrive.")


class ExitSignTest(unittest.TestCase):
    EXIT = {"type": 20, "sign": {"exit_number_elements": [{"text": "165B"}],
                                 "exit_toward_elements": [{"text": "I-5 S"}, {"text": "Tacoma"}]}}

    def test_exit_gives_number_and_first_toward(self):
        self.assertEqual(exit_sign(self.EXIT), ("165B", "I-5 S"))
        self.assertEqual(exit_sign(dict(self.EXIT, type=21)), ("165B", "I-5 S"))

    def test_turn_has_none(self):
        self.assertEqual(exit_sign(dict(self.EXIT, type=10)), ("", ""))

    def test_junk_never_raises(self):
        for m in (None, "x", 5, {}, {"type": 20}, {"type": 20, "sign": None},
                  {"type": 20, "sign": {"exit_number_elements": [5, None, {"text": 3}],
                                        "exit_toward_elements": "I-5"}}):
            self.assertEqual(exit_sign(m), ("", ""))


class ViaTollTest(unittest.TestCase):
    def test_via_longest_total(self):
        ms = [{"street_names": ["Main St"], "length": 1.0}, {"street_names": ["5th Ave"], "length": 1.5},
              {"street_names": ["Main St", "SR 9"], "length": "0.8"}]
        self.assertEqual(via_name(ms), "Main St")       # 1.8 beats 1.5
        ms[2]["length"] = 0.4
        self.assertEqual(via_name(ms), "5th Ave")

    def test_via_skips_and_never_raises(self):
        ms = [{"street_names": ["Ferry Rd"], "length": 9, "ferry": True}, {"street_names": [], "length": 3},
              {"street_names": ["A"], "length": "x"}, {"street_names": ["B"]}, None, "z",
              {"street_names": [5], "length": 1}, {"street_names": "I-5", "length": 1}]
        self.assertEqual(via_name(ms), "")
        for odd in ([], None, 5, "x", {}):
            self.assertEqual(via_name(odd), "")

    def test_toll(self):
        data = json.loads(json.dumps(ROUTE))
        self.assertFalse(Route(data, "x").toll)
        self.assertFalse(has_toll(None))
        data["trip"]["legs"][0]["maneuvers"][1]["toll"] = True
        self.assertTrue(Route(data, "x").toll)
        data = json.loads(json.dumps(ROUTE))
        data["trip"]["summary"]["has_toll"] = True
        self.assertTrue(Route(data, "x").toll)

    def test_route_via(self):
        data = json.loads(json.dumps(ROUTE))
        data["trip"]["legs"][0]["maneuvers"][0]["street_names"] = ["I-5 N"]
        data["trip"]["legs"][0]["maneuvers"][0]["length"] = 2.2
        self.assertEqual(Route(data, "x").via, "I-5 N")


class MapsPageViaTest(unittest.TestCase):
    def test_card_uses_via(self):
        from pathlib import Path
        qml = (Path(__file__).resolve().parent.parent / "qml/pages/MapsPage.qml").read_text()
        self.assertIn("routing.via", qml)
        self.assertIn("routing.hasToll", qml)


class MapsPageExitChipTest(unittest.TestCase):
    def test_turn_card_uses_exit_number(self):
        from pathlib import Path
        qml = (Path(__file__).resolve().parent.parent / "qml/pages/MapsPage.qml").read_text()
        self.assertIn("routing.exitNumber", qml)


if __name__ == "__main__":
    unittest.main()
