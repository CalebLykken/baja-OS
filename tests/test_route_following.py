"""Off-Pi tests for where the truck is put on a route that comes back near
itself (backend/routing.py): a U-turn to a place across a divided road and
a cloverleaf loop ramp, where a little GPS error is nearer a later part of
the route than the road the truck is on (#77). Also ordinary driving, so
the truck still moves along, and arrival only near the destination.

    python3 -m unittest tests.test_route_following
"""

import math
import unittest

from PyQt6.QtCore import QCoreApplication

from backend.routing import JUMP_FIXES, Route, Router
from tests.test_routing import FakeGps, polyline6

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
        self.router._on_route(data, "", "Shop", False)
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


if __name__ == "__main__":
    unittest.main()
