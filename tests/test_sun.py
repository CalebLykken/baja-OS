"""Off-Pi tests for the sun's position (backend/sun.py), which dims the
screen after dark: sunrise and sunset in Seattle against published times,
the sun's height at noon and midnight, and the far north where it doesn't
rise or set.

    python3 -m unittest tests.test_sun
"""

import unittest
from datetime import date, datetime, timedelta, timezone

from backend.sun import altitude, rise_set

SEATTLE = (47.6062, -122.3321)
PDT = timezone(timedelta(hours=-7))
PST = timezone(timedelta(hours=-8))
TROMSO = (69.65, 18.96)
TOLERANCE = timedelta(minutes=5)


def near(test, got, want):
    test.assertLess(abs(got - want), TOLERANCE, f"{got.astimezone(want.tzinfo)} is not near {want}")


class RiseSetTest(unittest.TestCase):
    def test_the_summer_solstice(self):
        rise, sset = rise_set(*SEATTLE, day=date(2024, 6, 20))
        near(self, rise, datetime(2024, 6, 20, 5, 11, tzinfo=PDT))
        near(self, sset, datetime(2024, 6, 20, 21, 11, tzinfo=PDT))

    def test_the_winter_solstice(self):
        rise, sset = rise_set(*SEATTLE, day=date(2024, 12, 21))
        near(self, rise, datetime(2024, 12, 21, 7, 55, tzinfo=PST))
        near(self, sset, datetime(2024, 12, 21, 16, 20, tzinfo=PST))

    def test_the_equinox(self):
        rise, sset = rise_set(*SEATTLE, day=date(2024, 3, 20))
        near(self, rise, datetime(2024, 3, 20, 7, 12, tzinfo=PDT))
        near(self, sset, datetime(2024, 3, 20, 19, 21, tzinfo=PDT))

    def test_the_answers_are_utc_and_the_evening_can_land_on_the_next_utc_day(self):
        rise, sset = rise_set(*SEATTLE, day=date(2024, 6, 20))
        self.assertEqual(rise.utcoffset(), timedelta(0))
        self.assertEqual(sset.utcoffset(), timedelta(0))
        self.assertEqual((rise.date(), sset.date()), (date(2024, 6, 20), date(2024, 6, 21)))

    def test_a_long_summer_day_and_a_short_winter_one(self):
        rise, sset = rise_set(*SEATTLE, day=date(2024, 6, 20))
        self.assertAlmostEqual((sset - rise).total_seconds() / 3600, 16.0, delta=0.15)
        rise, sset = rise_set(*SEATTLE, day=date(2024, 12, 21))
        self.assertAlmostEqual((sset - rise).total_seconds() / 3600, 8.4, delta=0.15)

    def test_east_of_seattle_the_sun_rises_earlier(self):
        a = rise_set(*SEATTLE, day=date(2024, 6, 20))[0]
        b = rise_set(SEATTLE[0], SEATTLE[1] + 15, day=date(2024, 6, 20))[0]
        self.assertAlmostEqual((a - b).total_seconds() / 60, 60, delta=3)

    def test_the_sun_that_does_not_set_or_rise(self):
        self.assertEqual(rise_set(*TROMSO, day=date(2024, 6, 20)), (None, None))      # midnight sun
        self.assertEqual(rise_set(*TROMSO, day=date(2024, 12, 21)), (None, None))     # polar night

    def test_the_equator_has_twelve_hours_all_year(self):
        for day in (date(2024, 3, 20), date(2024, 6, 20), date(2024, 12, 21)):
            rise, sset = rise_set(0.0, 0.0, day=day)
            self.assertAlmostEqual((sset - rise).total_seconds() / 3600, 12.1, delta=0.2)


class AltitudeTest(unittest.TestCase):
    def test_noon_on_the_summer_solstice(self):
        # Solar noon in Seattle is about 13:10 PDT; the sun is 90 - 47.6 + 23.4 degrees up.
        noon = datetime(2024, 6, 20, 13, 10, tzinfo=PDT)
        self.assertAlmostEqual(altitude(*SEATTLE, noon), 65.8, delta=1.0)

    def test_noon_on_the_winter_solstice(self):
        noon = datetime(2024, 12, 21, 12, 15, tzinfo=PST)       # 90 - 47.6 - 23.4
        self.assertAlmostEqual(altitude(*SEATTLE, noon), 19.0, delta=1.0)

    def test_midnight_is_well_below_the_horizon(self):
        self.assertAlmostEqual(altitude(*SEATTLE, datetime(2024, 6, 21, 1, 10, tzinfo=PDT)), -19.0, delta=1.0)
        self.assertLess(altitude(*SEATTLE, datetime(2024, 12, 21, 0, 15, tzinfo=PST)), -60)  # solar midnight

    def test_at_sunrise_and_sunset_it_is_on_the_horizon(self):
        rise, sset = rise_set(*SEATTLE, day=date(2024, 6, 20))
        for moment in (rise, sset):
            self.assertAlmostEqual(altitude(*SEATTLE, moment), -0.83, delta=1.0)

    def test_it_climbs_through_the_morning_and_falls_after_noon(self):
        heights = [altitude(*SEATTLE, datetime(2024, 6, 20, h, 0, tzinfo=PDT)) for h in (6, 9, 12, 15, 18, 21)]
        self.assertEqual(heights, sorted(heights[:3]) + sorted(heights[3:], reverse=True))
        self.assertGreater(heights[2], heights[0])

    def test_the_zone_of_the_time_does_not_matter(self):
        utc = datetime(2024, 6, 20, 20, 10, tzinfo=timezone.utc)
        self.assertAlmostEqual(altitude(*SEATTLE, utc), altitude(*SEATTLE, utc.astimezone(PDT)), places=9)

    def test_the_poles_and_the_equator_dont_break_the_arithmetic(self):
        for lat in (90.0, -90.0, 0.0):
            self.assertTrue(-90 <= altitude(lat, 0.0, datetime(2024, 3, 20, 12, tzinfo=timezone.utc)) <= 90)

    def test_no_time_means_now(self):
        self.assertTrue(-90 <= altitude(*SEATTLE) <= 90)


if __name__ == "__main__":
    unittest.main()
