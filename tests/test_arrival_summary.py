"""Off-Pi tests for the line under "You've arrived" (backend/routing.py):
how long the drive took against the first ETA, worked out once on arrival.

    python3 -m unittest tests.test_arrival_summary
"""

import time
import unittest
from pathlib import Path

from backend.routing import Router, route_record
from tests.test_route_following import ll, response, step
from tests.test_routing import FakeGps, FakeSettings, answer

ROUTE = response([(0, 0), (0, 500)], [step(1, 0, "Drive north."), step(4, 1, "You have arrived.")])   # 100 s
ROOT = Path(__file__).resolve().parent.parent


class ArrivalSummaryTest(unittest.TestCase):
    def setUp(self):
        self.gps = FakeGps()
        self.gps.lon, self.gps.lat = ll(0, 0)
        self.router = Router(self.gps)
        self.router._request = lambda *a, **k: None
        self.now = 1000.0
        self.router._clock = lambda: self.now
        self.router.routeTo("Shop", *ll(0, 500))
        answer(self.router, ROUTE, "", "Shop", False)
        self.router.go()

    def fix(self, n):
        self.gps.lon, self.gps.lat = ll(0, n)
        self.gps.heading, self.gps.speed = 0, 5.0
        self.router._on_fix()

    def arrive_after(self, seconds):
        self.fix(250)
        self.assertEqual(self.router.arrivalSummary, "")
        self.now += seconds
        self.fix(498)
        self.assertTrue(self.router.arrived)
        return self.router.arrivalSummary

    def test_early(self):
        self.router._go_eta = 1800.0
        self.assertEqual(self.arrive_after(1620), "27 min · 3 min early")

    def test_on_time(self):
        self.assertEqual(self.arrive_after(160), "3 min · right on time")      # 60 s over

    def test_late(self):
        self.assertEqual(self.arrive_after(340), "6 min · 4 min late")

    def test_under_a_minute(self):
        self.assertEqual(self.arrive_after(40), "under a minute · right on time")

    def test_reroute_keeps_the_first_eta(self):
        self.now += 10
        answer(self.router, ROUTE, "", "Shop", True)       # a reroute with a fresh 100 s
        self.assertEqual(self.router._go_eta, 100.0)
        self.assertEqual(self.arrive_after(340), "6 min · 4 min late")   # from the first go, 350 s in all

    def test_cleared_by_a_new_route_and_by_the_end(self):
        self.arrive_after(100)
        self.router.routeTo("Elsewhere", *ll(0, 900))
        self.assertEqual(self.router.arrivalSummary, "")
        self.assertIsNone(self.router._go_at)
        self.router.stop()
        self.assertEqual(self.router.arrivalSummary, "")

    def test_stop_clears_the_stored_summary(self):
        self.arrive_after(100)
        self.router.stop()
        self.assertEqual(self.router._arrival_summary, "")


class ResumedTest(unittest.TestCase):
    def test_a_resumed_route_has_no_summary(self):
        gps = FakeGps()
        gps.lon, gps.lat = ll(0, 0)
        settings = FakeSettings()
        settings.values["route"] = route_record("Shop", *ll(0, 500), True, time.time())
        router = Router(gps, settings)
        router._request = lambda *a, **k: None
        router._clock = lambda: 5.0
        router._on_status(True)
        answer(router, ROUTE, "", "Shop", False)
        self.assertTrue(router.active)
        self.assertIsNone(router._go_at)
        gps.heading, gps.speed = 0, 3.0
        gps.lat = ll(0, 499)[1]
        router._on_fix()
        self.assertTrue(router.arrived)
        self.assertEqual(router.arrivalSummary, "")


class QmlTest(unittest.TestCase):
    def test_the_turn_card_shows_it(self):
        self.assertIn("routing.arrivalSummary", (ROOT / "qml/pages/MapsPage.qml").read_text())


if __name__ == "__main__":
    unittest.main()
