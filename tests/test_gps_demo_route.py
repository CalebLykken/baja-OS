"""Off-Pi tests for the demo drive's DemoRoute: the heading at a one-way
route's end, the bisect lookups, and refusing routes with nothing to drive.

    python3 -m unittest tests.test_gps_demo_route
"""

import unittest

from PyQt6.QtCore import QCoreApplication

from backend.gps import DemoRoute, Gps

app = QCoreApplication.instance() or QCoreApplication([])


def ref_point(r, distance):
    """The old linear scan of DemoRoute._point."""
    d = distance % r.length if r.loop else min(distance, r.length)
    for i in range(len(r.cum) - 1):
        if r.cum[i + 1] >= d:
            a, b = r.points[i], r.points[i + 1]
            f = (d - r.cum[i]) / ((r.cum[i + 1] - r.cum[i]) or 1.0)
            return a[0] + (b[0] - a[0]) * f, a[1] + (b[1] - a[1]) * f
    return r.points[-1]


def ref_segment(r, d):
    """The old hand-written binary search in DemoRoute.at."""
    lo, hi = 0, len(r.cum) - 1
    while lo < hi - 1:
        mid = (lo + hi) // 2
        if r.cum[mid] <= d:
            lo = mid
        else:
            hi = mid
    return lo


class EndHeadingTest(unittest.TestCase):
    def check(self, points, heading):
        r = DemoRoute(points=points, loop=False)
        for extra in (0, 5000):
            self.assertAlmostEqual(r.at(r.length + extra)[2], heading, delta=1)

    def test_east(self):
        self.check([(-122.0, 47.0), (-121.99, 47.0)], 90)

    def test_south(self):
        self.check([(-122.0, 47.0), (-122.0, 46.99)], 180)

    def test_l_shape_ending_west(self):
        self.check([(-122.0, 47.0), (-122.0, 47.01), (-122.01, 47.01)], 270)

    def test_short_route_keeps_last_segment_heading(self):
        r = DemoRoute(points=[(-122.0, 47.0), (-121.9999, 47.0)], loop=False)
        self.assertAlmostEqual(r.at(r.length)[2], 90, delta=1)


class LookupTest(unittest.TestCase):
    def test_same_answers_as_linear_scan(self):
        r = DemoRoute()
        for d in (-5, 0, 0.001, 10, 123.4, r.cum[10], r.cum[500] + 0.5, r.length / 2,
                  r.length - 1, r.length, r.length + 77, r.length * 3 + 12.5):
            self.assertEqual(r._point(d), ref_point(r, d))
            dd = d % r.length
            lon, lat, _ = r.at(d)
            i = ref_segment(r, dd)
            a, b = r.points[i], r.points[i + 1]
            f = (dd - r.cum[i]) / (r.cum[i + 1] - r.cum[i] or 1.0)
            self.assertEqual((lon, lat), (a[0] + (b[0] - a[0]) * f, a[1] + (b[1] - a[1]) * f))

    def test_one_way_beyond_the_ends(self):
        r = DemoRoute(points=[(-122.0, 47.0), (-121.99, 47.0), (-121.99, 47.01)], loop=False)
        for d in (-3, 0, 100, r.length, r.length + 1000):
            self.assertEqual(r._point(d), ref_point(r, d))


class EmptyRouteTest(unittest.TestCase):
    def test_refused(self):
        with self.assertRaises(ValueError):
            DemoRoute(points=[(1, 2), (1, 2)], loop=True)
        with self.assertRaises(ValueError):
            DemoRoute(points=[(1, 2)])


class FollowPathTest(unittest.TestCase):
    def test_bad_paths_leave_the_loop(self):
        g = Gps(demo=True)
        g.followPath([[1, 2], [1, 2]])
        self.assertIsNone(g._path)
        g.followPath([["x", "y"], [1]])
        self.assertIsNone(g._path)

    def test_valid_path(self):
        g = Gps(demo=True)
        g.followPath([[-122.0, 47.0], [-121.99, 47.0]])
        self.assertIsNotNone(g._path)


if __name__ == "__main__":
    unittest.main()
