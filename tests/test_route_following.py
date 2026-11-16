"""Off-Pi tests for where the truck is put on a route that comes back near
itself (backend/routing.py): a U-turn to a place across a divided road and
a cloverleaf loop ramp, where a little GPS error is nearer a later part of
the route than the road the truck is on (#77). Also ordinary driving, so
the truck still moves along, and arrival only near the destination.

    python3 -m unittest tests.test_route_following
"""

import json
import math
import time
import unittest
from unittest import mock

from PyQt6.QtCore import QCoreApplication

from backend.routing import ARRIVED_M, JUMP_FIXES, JUMP_S, Route, Router, route_record, saved_route
from tests.test_routing import FakeGps, FakeSettings, answer, polyline6

app = QCoreApplication.instance() or QCoreApplication([])   # arrival starts a timer

LON0, LAT0 = -122.0, 47.0


def ll(e, n):
    """Metres east and north of LON0, LAT0 -> (lon, lat)."""
    return LON0 + e / (111320.0 * math.cos(math.radians(LAT0))), LAT0 + n / 110540.0


def response(points, maneuvers):
    """A Valhalla-shaped answer for a route through `points` (metres east, north)."""
    return {"trip": {"summary": {"time": 100.0}, "legs": [{
        "shape": polyline6([ll(*p) for p in points]), "maneuvers": maneuvers}]}}


def step(type, index, words):
    return {"type": type, "begin_shape_index": index, "instruction": words,
            "verbal_pre_transition_instruction": words, "verbal_transition_alert_instruction": words}


def drive(points, every=10.0, sideways=(0.0,)):
    """(east, north, heading, metres along) every `every` metres along
    `points`, pushed sideways (to the right of the way it's going) by each
    of `sideways` in turn, like GPS error."""
    out, done = [], 0.0
    for (ax, ay), (bx, by) in zip(points, points[1:]):
        length = math.hypot(bx - ax, by - ay)
        ux, uy = (bx - ax) / length, (by - ay) / length
        heading = math.degrees(math.atan2(ux, uy)) % 360
        s = 0.0 if not out else every - (done - out[-1][3])
        while s < length:
            side = sideways[len(out) % len(sideways)]
            out.append((ax + ux * s + uy * side, ay + uy * s - ux * side, heading, done + s))
            s += every
        done += length
    end = points[-1]
    out.append((end[0], end[1], out[-1][2], done))
    return out


# 300 m north, a U-turn, then back south on the other carriageway 12 m to
# the east, to a place 20 m from the start (the shape in #77).
UTURN = [(0, 0), (0, 300), (12, 300), (12, 20)]
UTURN_ROUTE = response(UTURN, [step(1, 0, "Drive north."), step(13, 1, "Make a U-turn."),
                               step(4, 3, "You have arrived.")])

# North on B, under A at 155 m, then the cloverleaf loop on the right,
# 270 degrees round, and down beside B to join A heading west: the way
# down runs within GPS error of B, the other way, before the ramp.
LOOP = ([(0, 0), (0, 250), (6, 270)]
        + [(36 + 30 * math.cos(math.radians(a)), 270 + 30 * math.sin(math.radians(a)))
           for a in range(165, -91, -15)]
        + [(18, 222), (10, 200), (6, 180), (4, 165), (2, 155), (-300, 155)])
MERGE = LOOP.index((2, 155))
LOOP_ROUTE = response(LOOP, [step(1, 0, "Drive north on B."), step(18, 1, "Take the ramp on the right."),
                             step(25, MERGE, "Merge onto A."), step(4, len(LOOP) - 1, "You have arrived.")])


class LocateTest(unittest.TestCase):
    """Route.locate fix by fix, with a clock that's just a number."""

    def follow(self, data, fixes, speed=10.0, every=1.0):
        """Locate each (east, north, heading, ...) fix in turn; [(seg, along)]."""
        route, now, out = Route(data, "Shop"), 0.0, []
        route.locate(*ll(0, 0), now=now)
        for e, n, heading, *_ in fixes:
            now += every
            route.locate(*ll(e, n), heading, speed, now)
            out.append((route.seg, route.along))
        return route, out

    def test_u_turn_route_offsets_stay_on_the_way_out(self):
        # Every 5 m up to 10 m off the lane, including the fixes in #77.
        issue = {5: 0, 20: 4, 40: 7, 100: 5}
        fixes = [(issue.get(n, (0, 4, 7, 10)[n // 5 % 4]), n, 0) for n in range(5, 300, 5)]
        # With no heading to go by (under walking pace), the way back is
        # somewhere the truck could have got for the last few metres.
        for speed, last in ((10.0, 300), (0.0, 285)):
            route, out = self.follow(UTURN_ROUTE, [f for f in fixes if f[1] < last], speed)
            for (e, n, _), (seg, along) in zip(fixes, out):
                self.assertEqual(seg, 0, (speed, e, n))
                self.assertAlmostEqual(along, n, delta=1, msg=(speed, e, n))

    def test_parked_off_the_lane(self):
        # Stopped (no heading to go by) where the way back is nearer.
        route = Route(UTURN_ROUTE, "Shop")
        route.locate(*ll(0, 40), now=0.0)
        for s in range(30):
            route.locate(*ll(10, 40), 0.0, 0.0, s + 1.0)
        self.assertEqual(route.seg, 0)
        self.assertAlmostEqual(route.along, 40, delta=1)

    def test_u_turn_driven(self):
        fixes = drive(UTURN, sideways=(0, 3, -3, 5, -5))
        route, out = self.follow(UTURN_ROUTE, fixes)
        for (e, n, _, truth), (seg, along) in zip(fixes, out):
            self.assertAlmostEqual(along, truth, delta=6, msg=(e, n))

    def test_an_early_u_turn_is_followed(self):
        # Through a gap in the median at 150 m: once the truck has been
        # going back down the other side for a few fixes, that's where it is.
        fixes = [(0, n, 0) for n in range(10, 160, 10)] + [(6, 155, 90)]
        fixes += [(12, n, 180) for n in range(150, 80, -10)]
        route, out = self.follow(UTURN_ROUTE, fixes)
        back = [seg == 2 for seg, _ in out[-7:]]
        self.assertFalse(back[0])                   # not on one fix
        self.assertTrue(all(back[JUMP_FIXES - 1:]), back)
        self.assertAlmostEqual(out[-1][1], 312 + 300 - 90, delta=1)

    def test_a_hop_to_the_other_carriageway_needs_time_as_well_as_fixes(self):
        # The same wander onto the way back, 2 m a fix: 5 Hz (10 m/s) gets
        # JUMP_FIXES of them in well under JUMP_S, so it waits for the time.
        fixes = [(0, n, 0) for n in range(10, 160, 2)] + [(6, 155, 90)]
        back = [(12, n, 180) for n in range(150, 80, -2)]
        _, out = self.follow(UTURN_ROUTE, fixes + back[:JUMP_FIXES + 2], every=0.2)
        self.assertEqual([seg for seg, _ in out[len(fixes):]], [0] * (JUMP_FIXES + 2))
        _, out = self.follow(UTURN_ROUTE, fixes + back, every=0.2)
        segs = [seg == 2 for seg, _ in out[len(fixes):]]
        self.assertFalse(segs[JUMP_FIXES - 1])
        self.assertTrue(segs[-1])                   # but kept up for JUMP_S, it's there
        first = segs.index(True)
        self.assertGreaterEqual(first * 0.2, JUMP_S - 0.2)
        self.assertLessEqual(first * 0.2, JUMP_S + 0.4)

    def test_loop_ramp_beside_the_road(self):
        # Up B with the GPS a little to the right, where the end of the
        # loop runs past it, moving and stopped.
        fixes = [((5, 8, 9)[n // 10 % 3], n, 0) for n in range(10, 250, 10)]
        for speed in (12.0, 0.0):
            route, out = self.follow(LOOP_ROUTE, fixes, speed)
            for (e, n, _), (seg, along) in zip(fixes, out):
                self.assertEqual(seg, 0, (speed, e, n))
                self.assertAlmostEqual(along, n, delta=1, msg=(speed, e, n))

    def test_loop_driven(self):
        fixes = drive(LOOP, sideways=(0, 4, -4))
        route, out = self.follow(LOOP_ROUTE, fixes)
        for (e, n, _, truth), (seg, along) in zip(fixes, out):
            self.assertAlmostEqual(along, truth, delta=6, msg=(e, n))

    def test_out_of_a_tunnel(self):
        # No fixes for a minute at 25 m/s, then the truck 1.5 km on.
        straight = response([(0, 0), (0, 3000)], [step(1, 0, "Drive north."), step(4, 1, "You have arrived.")])
        route = Route(straight, "Shop")
        route.locate(*ll(0, 0), now=0.0)
        route.locate(*ll(0, 25), 0.0, 25.0, 1.0)
        route.locate(*ll(3, 1525), 0.0, 25.0, 61.0)
        self.assertAlmostEqual(route.along, 1525, delta=1)

    def test_the_same_fix_again(self):
        # The GPS also says when the satellites change, with the same
        # position: that's not the truck going nowhere, nor another fix.
        straight = response([(0, 0), (0, 3000)], [step(1, 0, "Drive north."), step(4, 1, "You have arrived.")])
        route = Route(straight, "Shop")
        route.locate(*ll(0, 0), now=0.0)
        for s in range(1, 20):
            for again in (0.0, 0.5, 0.9):            # at 40 m/s, a fix a second
                route.locate(*ll(0, 40 * s), 0.0, 40.0, s + again)
            self.assertAlmostEqual(route.along, 40 * s, delta=1)
        route = Route(UTURN_ROUTE, "Shop")
        route.locate(*ll(0, 150), now=0.0)
        for s in range(1, JUMP_FIXES):
            for again in (0.0, 0.5):
                route.locate(*ll(12, 150 - 10 * s), 180.0, 10.0, s + again)
        self.assertEqual(route.seg, 0)

    def test_a_wild_fix_far_off_the_route(self):
        # Nowhere near where the truck could have got, but on the route
        # further on (a lost fix, or the first after a long gap): it's there.
        route = Route(UTURN_ROUTE, "Shop")
        route.locate(*ll(0, 0), now=0.0)
        route.locate(*ll(12, 100), 180.0, 10.0, 1.0)
        self.assertEqual(route.seg, 2)

    def test_a_new_route_or_go_takes_the_nearest(self):
        route = Route(UTURN_ROUTE, "Shop")
        route.locate(*ll(10, 150))
        self.assertEqual(route.seg, 2)


class FollowingTest(unittest.TestCase):
    """The router on a fake GPS: what's said, and arrival."""

    def start(self, data, at=(0, 0)):
        self.gps = FakeGps()
        self.gps.lon, self.gps.lat = ll(*at)
        self.router = Router(self.gps)
        self.said = []
        self.router.speak.connect(self.said.append)
        self.router._request = lambda *a, **k: None
        self.router.routeTo("Shop", *ll(*at))
        answer(self.router, data, "", "Shop", False)
        self.router.go()

    def fix(self, e, n, heading, speed=10.0):
        self.gps.lon, self.gps.lat = ll(e, n)
        self.gps.heading, self.gps.speed = heading, speed
        self.router._on_fix()

    def test_u_turn_said_and_arrival_at_the_end(self):
        self.start(UTURN_ROUTE)
        for n in range(10, 300, 10):
            self.fix((0, 4, 7, 10)[n // 10 % 4], n, 0)     # up to 10 m off the lane
            self.assertFalse(self.router.arrived, n)
            self.assertGreater(self.router.remainingDistance, 280, n)
        self.assertIn("Make a U-turn.", self.said)
        self.assertEqual(self.router.instruction, "Make a U-turn")
        for e, n, heading, _ in drive(UTURN[1:], sideways=(0, 3, -3)):
            self.fix(e, n, heading)
        self.assertTrue(self.router.arrived)
        self.assertEqual(self.said[-1], "You have arrived at Shop.")
        self.assertEqual(self.said.count("You have arrived at Shop."), 1)

    def test_loop_ramp_said(self):
        self.start(LOOP_ROUTE)
        for e, n, heading, along in drive(LOOP, sideways=(0, 8, 9, 5)):
            self.fix(e, n, heading)
            if along < 245:
                self.assertEqual(self.router.instruction, "Take the ramp on the right", (e, n))
        self.assertEqual([s for s in self.said if "In a quarter mile" not in s],
                         ["Drive north on B.", "Take the ramp on the right.", "Merge onto A.",
                          "You have arrived at Shop."])

    def test_arrival_only_near_the_destination(self):
        # Pulled off into a lot beside the road 45 m short of the end: the
        # route is nearly done there, but the place isn't here.
        straight = response([(0, 0), (0, 500)], [step(1, 0, "Drive north."), step(4, 1, "You have arrived.")])
        self.start(straight)
        for n in range(10, 470, 10):
            self.fix(0, n, 0)
        self.fix(45, 480, 0, 0.0)
        self.assertLess(self.router.remainingDistance, 35)
        self.assertFalse(self.router.arrived)
        self.fix(3, 492, 0, 3.0)
        self.assertTrue(self.router.arrived)

    def test_off_route_then_a_failed_reroute_keeps_the_line_and_says_why(self):
        straight = response([(0, 0), (0, 500)], [step(1, 0, "Drive north."), step(4, 1, "You have arrived.")])
        self.start(straight)
        self.assertFalse(self.router.offRoute)
        for n in (100, 110, 120, 130):
            self.fix(80, n, 0)                       # 80 m east of the line
        self.assertTrue(self.router.offRoute)
        message = "Routing isn't running"
        answer(self.router, None, message, "Shop", True)
        self.assertTrue(self.router.active)
        self.assertEqual(self.router.error, message)
        self.assertTrue(self.router.offRoute)
        answer(self.router, straight, "", "Shop", True)
        self.assertEqual(self.router.error, "")
        self.assertFalse(self.router.offRoute)

    def test_stop_clears_a_failed_reroute(self):
        straight = response([(0, 0), (0, 500)], [step(1, 0, "Drive north."), step(4, 1, "You have arrived.")])
        self.start(straight)
        for n in (100, 110, 120, 130):
            self.fix(80, n, 0)
        answer(self.router, None, "No route found", "Shop", True)
        self.router.stop()
        self.assertEqual(self.router.error, "")
        self.assertFalse(self.router.offRoute)


# North past two stops to the shop, a leg each, with a turn to take after
# the first stop. Every maneuver is numbered from its own leg's start.
def timed(type, begin, end, words, seconds):
    return dict(step(type, begin, words), end_shape_index=end, time=seconds)


A, B, SHOP = (0, 1000), (0, 2000), (500, 2000)
STOP_A, STOP_B = ("Gas", *ll(*A)), ("Cafe", *ll(*B))
TWO_STOPS = {"trip": {"summary": {"time": 300.0}, "legs": [
    {"shape": polyline6([ll(0, 0), ll(0, 500), ll(*A)]),
     "maneuvers": [timed(1, 0, 2, "Drive north.", 100.0),
                   timed(5, 2, 2, "You have arrived at your destination.", 0.0)]},
    {"shape": polyline6([ll(*A), ll(0, 1500), ll(*B)]),
     "maneuvers": [timed(1, 0, 2, "Carry on north.", 100.0),
                   timed(4, 2, 2, "You have arrived at your stop.", 0.0)]},
    {"shape": polyline6([ll(*B), ll(*SHOP)]),
     "maneuvers": [timed(10, 0, 1, "Turn right.", 100.0), timed(4, 1, 1, "You have arrived.", 0.0)]},
]}}
ONE_STOP = {"trip": {"summary": {"time": 200.0}, "legs": TWO_STOPS["trip"]["legs"][1:]}}
NO_STOPS = {"trip": {"summary": {"time": 100.0}, "legs": TWO_STOPS["trip"]["legs"][2:]}}
TWO_STOPS_AND_ONE = {"trip": {"summary": {"time": 400.0},
                              "legs": TWO_STOPS["trip"]["legs"] + TWO_STOPS["trip"]["legs"][2:]}}


class MultiLegRouteTest(unittest.TestCase):
    def setUp(self):
        self.route = Route(TWO_STOPS, "Shop", [STOP_A, STOP_B])

    def test_the_legs_join_up(self):
        r = self.route
        self.assertEqual(len(r.shape), 6)           # 3 + 3 + 2, less the two shared points
        self.assertEqual(len(r.maneuvers), 6)
        self.assertEqual(r.leg_ends, [2, 4])
        self.assertAlmostEqual(r.length, 2500, delta=1)
        self.assertEqual(r.time, 300.0)
        self.assertEqual([m["begin_shape_index"] for m in r.maneuvers], [0, 2, 2, 4, 4, 5])
        self.assertEqual([m["end_shape_index"] for m in r.maneuvers], [2, 2, 4, 4, 5, 5])

    def test_the_answer_is_left_alone(self):
        self.assertEqual(TWO_STOPS["trip"]["legs"][1]["maneuvers"][0]["begin_shape_index"], 0)
        self.assertNotIn("Arrive", TWO_STOPS["trip"]["legs"][0]["maneuvers"][1]["instruction"])

    def test_a_stop_is_called_by_its_name(self):
        r = self.route
        self.assertEqual(r.maneuvers[1]["instruction"], "Arrive at Gas")
        self.assertEqual(r.maneuvers[3]["instruction"], "Arrive at Cafe")
        self.assertEqual(r.maneuvers[5]["instruction"], "You have arrived.")

    def test_time_left_covers_every_leg(self):
        self.assertAlmostEqual(self.route.time_left(), 300.0)

    def test_nothing_is_shown_after_a_stop_arrival(self):
        self.route.locate(*ll(0, 900))
        self.assertEqual(self.route.next_maneuver()["instruction"], "Arrive at Gas")
        self.assertIsNone(self.route.then_maneuver())

    def test_a_ferry_on_a_later_leg_is_seen(self):
        data = json.loads(json.dumps(ONE_STOP))
        data["trip"]["legs"][1]["maneuvers"][0].update(type=28, ferry=True, time=600)
        self.assertEqual([f["time"] for f in Route(data, "Shop", [STOP_B]).ferries], [600.0])

    def test_a_leg_missing_for_a_stop_is_not_a_route(self):
        with self.assertRaises(ValueError):
            Route(NO_STOPS, "Shop", [STOP_A])


class StopsTest(unittest.TestCase):
    """The router on a fake GPS with stops added along the way."""

    def setUp(self):
        self.gps = FakeGps()
        self.gps.lon, self.gps.lat = ll(0, 0)
        self.settings = FakeSettings()
        self.router = Router(self.gps, self.settings)
        self.said, self.asked = [], []
        self.router.speak.connect(self.said.append)
        self.router._request = lambda *a, **k: self.asked.append(
            (list(self.router._stops), k.get("reroute", False)))
        self.now = 0.0                # a second per fix from `at`, like a 1 Hz receiver
        self.router._clock = lambda: self.now

    def driving(self):
        """Guiding along TWO_STOPS, nothing yet asked or said."""
        self.router.routeTo("Shop", *ll(*SHOP))
        self.router._stops = [STOP_A, STOP_B]
        answer(self.router, TWO_STOPS, "", "Shop", False)
        self.router.go()
        self.said.clear()
        self.asked.clear()

    def at(self, e, n, every=1.0):
        self.now += every
        self.gps.lon, self.gps.lat = ll(e, n)
        self.router._on_fix()

    def test_added_before_the_destination_and_the_old_line_stays(self):
        self.router.routeTo("Shop", *ll(*SHOP))
        answer(self.router, NO_STOPS, "", "Shop", False)
        old = self.router._route
        self.router.addStop(*STOP_B)
        self.router.addStop(*STOP_A)
        self.assertEqual(self.asked[-1], ([STOP_B, STOP_A], True))
        self.assertIs(self.router._route, old)
        self.assertEqual(self.router.stopCount, 2)
        self.assertEqual([s["name"] for s in self.router.stops], ["Cafe", "Gas"])
        self.assertEqual(self.router.nextStopName, "Cafe")
        self.assertEqual(self.router.stops[0]["lon"], STOP_B[1])

    def test_a_stop_goes_in_the_order_the_route_reaches_it(self):
        self.driving()
        self.router.addStop("Diner", *ll(0, 1500))
        self.assertEqual(self.asked[-1][0], [STOP_A, ("Diner", *ll(0, 1500)), STOP_B])
        self.driving()
        self.router.addStop("Early", *ll(0, 500))
        self.assertEqual([s[0] for s in self.asked[-1][0]], ["Early", "Gas", "Cafe"])

    def test_a_stop_far_from_the_route_goes_last(self):
        self.driving()
        self.router.addStop("Island", *ll(9000, 9000))
        self.assertEqual(self.asked[-1][0][-1][0], "Island")

    def test_no_route_no_stop(self):
        self.router.addStop(*STOP_A)
        self.assertEqual(self.asked, [])
        self.assertEqual(self.router.stopCount, 0)

    def test_after_arriving_no_stop(self):
        self.router.routeTo("Shop", *ll(*SHOP))
        answer(self.router, NO_STOPS, "", "Shop", False)
        self.router._arrived = True
        self.asked.clear()
        self.router.addStop(*STOP_A)
        self.assertEqual(self.asked, [])

    def test_a_new_place_or_the_end_clears_them(self):
        self.driving()
        self.router.routeTo("Elsewhere", *ll(*SHOP))
        self.assertEqual(self.router.stopCount, 0)
        self.driving()
        self.router.stop()
        self.assertEqual(self.router.stopCount, 0)
        self.assertEqual(self.router.nextStopName, "")

    def test_removing_one(self):
        self.driving()
        self.router.removeStop(0)
        self.assertEqual(self.asked, [([STOP_B], True)])
        for index in (-1, 1):
            self.router.removeStop(index)
        self.assertEqual(len(self.asked), 1)

    def test_a_stop_with_no_road_to_it_goes_back_off(self):
        self.driving()
        self.router.addStop("Island", *ll(9000, 9000))
        answer(self.router, None, "No path could be found", "Shop", True)
        self.assertEqual(self.router.error, "No road route to there")
        self.assertEqual(self.router._stops, [STOP_A, STOP_B])
        self.assertTrue(self.router.active)
        saved = saved_route(self.settings.values["route"], time.time())
        self.assertEqual(saved["stops"], [STOP_A, STOP_B])

    def test_each_arrival_is_announced_once_and_guidance_carries_on(self):
        self.driving()
        self.assertEqual(self.router.instruction, "Arrive at Gas")
        self.assertEqual(self.router.maneuverIcon, "place")
        self.at(0, 980)
        self.at(0, 985)
        self.at(0, 990)
        self.assertEqual(self.said.count("You have arrived at Gas. Continuing to Cafe."), 1)
        self.assertTrue(self.router.active)
        self.assertFalse(self.router.arrived)
        self.assertEqual(self.router._stops, [STOP_B])
        self.assertEqual(self.router.nextStopName, "Cafe")
        self.assertEqual(self.router.instruction, "Carry on north")      # not back to the stop
        self.at(0, 1100)
        self.assertEqual(self.router.instruction, "Arrive at Cafe")
        self.assertAlmostEqual(self.router.distanceToTurn, 900, delta=2)
        self.at(0, 1990)
        self.assertEqual(self.said[-1], "You have arrived at Cafe. Continuing to Shop.")
        self.assertEqual(self.router.stopCount, 0)
        self.assertEqual(self.router.nextStopName, "")
        self.at(495, 2000)
        self.assertTrue(self.router.arrived)
        self.assertEqual(self.said[-1], "You have arrived at Shop.")

    def test_not_there_until_arrived_m_away(self):
        self.driving()
        self.at(0, 1000 - ARRIVED_M - 5)
        self.assertEqual(self.router.stopCount, 2)
        self.at(ARRIVED_M + 5, 1000)                # level with it, but across a field
        self.assertEqual(self.router.stopCount, 2)

    def test_a_stop_gone_by_unseen_goes_quietly_and_the_next_still_counts(self):
        self.driving()
        for n in (1200, 1210, 1220):
            self.at(0, n)
        self.assertEqual(self.router._stops, [STOP_B])
        self.assertEqual(self.router._route.leg, 1)
        self.assertEqual(self.said, [])
        self.assertEqual(saved_route(self.settings.values["route"], time.time())["stops"], [STOP_B])
        self.at(0, 1990)
        self.assertEqual(self.said[-1], "You have arrived at Cafe. Continuing to Shop.")
        self.assertEqual(self.router._route.leg, 2)
        self.router._request(*self.router._dest, reroute=True)
        self.assertEqual(self.asked[-1], ([], True))

    def test_a_stop_gone_by_at_5_hz_needs_the_time_too(self):
        self.driving()
        for k in range(JUMP_FIXES + 1):             # 2 m a fix, 0.2 s apart: 0.8 s of it
            self.at(0, 1200 + 2 * k, 0.2)
        self.assertEqual(self.router._stops, [STOP_A, STOP_B])
        for k in range(int(JUMP_S / 0.2) + 1):
            self.at(0, 1210 + 2 * k, 0.2)
        self.assertEqual(self.router._stops, [STOP_B])

    def test_several_stops_gone_by_at_once(self):
        self.driving()
        for e in (100, 110, 120):
            self.at(e, 2000)
            self.gps.heading = 90.0
        self.at(130, 2000)
        self.assertEqual(self.router._stops, [])

    def test_one_fix_past_a_stop_isnt_enough(self):
        self.driving()
        self.at(0, 1200)
        self.at(0, 1210)
        self.assertEqual(self.router.stopCount, 2)

    def test_past_a_stop_only_going_the_way_of_the_line(self):
        self.driving()
        self.gps.heading = 180.0
        for n in (1200, 1190, 1180, 1170):
            self.at(0, n)
        self.assertEqual(self.router.stopCount, 2)

    def test_past_a_stop_only_when_moving(self):
        self.driving()
        self.gps.speed = 0.0
        for n in (1200, 1200.5, 1201, 1201.5):
            self.at(0, n)
        self.assertEqual(self.router.stopCount, 2)

    def leave_line(self, e, n):
        """Three fixes well off the line, enough for a reroute."""
        self.gps.heading = 60.0
        with mock.patch("backend.routing.time.monotonic", lambda: 5000.0):
            for k in range(3):
                self.router._clock = lambda k=k: 5000.0 + 2 * k
                self.at(e + 40 * k, n + 15 * k)

    def test_a_stop_gone_by_on_a_road_beside_the_line_isnt_asked_for_again(self):
        self.driving()
        for n in range(0, 1500, 15):
            self.at(45, n)
        self.leave_line(70, 1515)
        self.assertEqual(self.asked, [([STOP_B], True)])

    def test_a_stop_not_reached_yet_stays_in_a_reroute(self):
        self.driving()
        for n in range(0, 900, 15):
            self.at(0, n)
        self.leave_line(70, 915)
        self.assertEqual(self.asked, [([STOP_A, STOP_B], True)])

    def test_past_a_stop_waits_for_a_new_route_on_its_way(self):
        self.driving()
        self.router._computing = True
        for n in (1200, 1210, 1220, 1230):
            self.at(0, n)
        self.assertEqual(self.router.stopCount, 2)

    def test_adding_says_if_it_was_taken(self):
        failed = []
        self.router.stopsFailed.connect(failed.append)
        self.assertFalse(self.router.addStop(*STOP_A))              # no route
        self.assertEqual(failed, ["Couldn't add Gas"])
        self.driving()
        self.gps.hasFix = False
        self.assertFalse(self.router.addStop("Diner", 1.0, 2.0))
        self.assertFalse(self.router.removeStop(0))
        self.assertEqual(failed[1:], ["Couldn't add Diner", "Couldn't skip Gas"])
        self.assertEqual(self.router.stopCount, 2)
        self.gps.hasFix = True
        self.assertFalse(self.router.removeStop(5))
        self.assertEqual(len(failed), 3)
        self.assertTrue(self.router.addStop("Diner", 1.0, 2.0))
        self.assertTrue(self.router.removeStop(0))

    def test_no_route_for_a_change_of_stops_is_told(self):
        failed = []
        self.router.stopsFailed.connect(failed.append)
        self.driving()
        self.router.addStop("Island", *ll(9000, 9000))
        answer(self.router, None, "No path could be found", "Shop", True)
        self.assertEqual(failed, ["Couldn't add Island"])
        self.router.removeStop(0)
        answer(self.router, None, "Routing isn't running", "Shop", True)
        self.assertEqual(failed[1:], ["Couldn't skip Gas"])
        self.assertEqual(self.router._stops, [STOP_A, STOP_B])

    def test_other_reroutes_failing_tell_nothing(self):
        failed = []
        self.router.stopsFailed.connect(failed.append)
        self.driving()
        self.router.addStop("Diner", 1.0, 2.0)
        answer(self.router, TWO_STOPS_AND_ONE, "", "Shop", True)
        self.router._request(*self.router._dest, reroute=True)
        answer(self.router, None, "Routing isn't running", "Shop", True)
        self.assertEqual(failed, [])

    def test_a_failed_change_after_arriving_saves_nothing(self):
        failed = []
        self.router.stopsFailed.connect(failed.append)
        self.driving()
        self.router.addStop("Island", *ll(9000, 9000))
        self.router._arrived = True
        self.settings.values["route"] = ""
        answer(self.router, None, "No path could be found", "Shop", True)
        self.assertEqual(self.settings.values["route"], "")
        self.assertEqual(failed, [])

    def test_a_reroute_after_a_stop_leaves_it_out(self):
        self.driving()
        self.at(0, 990)
        self.router._request(*self.router._dest, reroute=True)
        self.assertEqual(self.asked[-1], ([STOP_B], True))

    def test_a_reroute_on_its_way_at_a_stop_is_asked_again_without_it(self):
        self.driving()
        self.router._computing = True
        self.at(0, 990)
        self.assertEqual(self.asked[-1], ([STOP_B], True))

    def test_a_saved_route_keeps_the_stops_left(self):
        self.driving()
        saved = saved_route(self.settings.values["route"], time.time())
        self.assertEqual(saved["stops"], [STOP_A, STOP_B])
        self.at(0, 990)
        saved = saved_route(self.settings.values["route"], time.time())
        self.assertEqual(saved["stops"], [STOP_B])

    def test_old_saves_have_none(self):
        text = route_record("Shop", 1.0, 2.0, True, 1000.0)
        self.assertNotIn("stops", saved_route(text, 1000.0))
        old = json.dumps({"name": "Shop", "lon": 1.0, "lat": 2.0, "started": True, "at": 1000.0})
        self.assertEqual(saved_route(old, 1000.0),
                         {"name": "Shop", "lon": 1.0, "lat": 2.0, "started": True})

    def test_odd_saved_stops_are_no_route(self):
        text = json.dumps({"name": "Shop", "lon": 1.0, "lat": 2.0, "at": 1000.0, "stops": [["Gas"]]})
        self.assertIsNone(saved_route(text, 1000.0))

    def resumed_router(self, here, stops):
        self.gps.lon, self.gps.lat = ll(*here)
        self.settings.values["route"] = route_record("Shop", *ll(*SHOP), True, time.time(), stops)
        router = Router(self.gps, self.settings)
        router.speak.connect(self.said.append)
        asked = []
        router._request = lambda *a, **k: asked.append(list(router._stops))
        router._on_status(True)
        return router, asked

    def test_resuming_brings_the_stops_back(self):
        router, asked = self.resumed_router((0, 500), [STOP_A, STOP_B])
        self.assertEqual(asked, [[STOP_A, STOP_B]])
        answer(router, TWO_STOPS, "", "Shop", False)
        self.assertTrue(router.active)
        self.assertTrue(self.said[0].startswith("Continuing to Gas. "))

    def test_near_the_destination_with_a_stop_left_still_resumes(self):
        router, asked = self.resumed_router((480, 2000), [STOP_B])
        self.assertEqual(asked, [[STOP_B]])

    def test_a_new_route_option_carries_the_stops(self):
        self.driving()
        self.router.setAvoid("avoidTolls", True)
        self.assertEqual(self.asked[-1], ([STOP_A, STOP_B], True))

    def test_off_the_line_carries_the_stops(self):
        self.driving()
        self.router._last_reroute = float("-inf")
        self.router._clock = mock.Mock(side_effect=[0.0, 1.0, 2.0, 3.0])
        for n in (300, 305, 310):
            self.gps.at(*ll(200, n))
            self.router._on_fix()
        self.assertEqual(self.asked[-1], ([STOP_A, STOP_B], True))


if __name__ == "__main__":
    unittest.main()
