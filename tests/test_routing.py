"""Off-Pi tests for following a route (backend/routing.py) with a fake GPS:
no reroute and nothing said while the position is stale.

    python3 -m unittest tests.test_routing
"""

import unittest

from backend.routing import OFF_ROUTE_FIXES, Router

# North 2.2 km, then right (east) for 760 m.
START, CORNER, END = (-122.0, 47.0), (-122.0, 47.02), (-121.99, 47.02)


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


class Changed:
    def connect(self, slot):
        pass


class FakeGps:
    """What the router reads from backend.gps.Gps."""
    changed = Changed()

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
        self.gps = FakeGps()
        self.router = Router(self.gps)
        self.said, self.asked = [], []
        self.router.speak.connect(self.said.append)
        self.router._request = lambda *a, **k: self.asked.append(k.get("reroute", False))
        self.router._last_reroute = float("-inf")   # the clock may have just started
        self.router.routeTo("Shop", *END)
        self.router._on_route(ROUTE, "", "Shop", False)
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
        self.router._on_fix()
        self.gps.at(-122.003, 47.005)
        for _ in range(OFF_ROUTE_FIXES - 1):
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
        self.router._on_route(ROUTE, "", "Shop", True)
        self.assertEqual(self.said, [])
        self.assertTrue(self.router.active)


if __name__ == "__main__":
    unittest.main()
