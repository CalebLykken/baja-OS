"""Off-Pi tests for solar noon and the golden hour (backend/sun.py), checked
against the sun's own height: each crossing should land where altitude()
says the sun is at the target height.

    python3 -m unittest tests.test_sun_golden
"""

import unittest
from datetime import date, datetime, timedelta, timezone

from backend.sun import GOLDEN_HIGH, GOLDEN_LOW, HORIZON, altitude, crossings, golden_hour, rise_set, solar_noon

SEATTLE = (47.6062, -122.3321)
TROMSO = (69.65, 18.96)
QUITO = (0.0, -78.5)
PDT = timezone(timedelta(hours=-7))
DAYS = [date(2024, 3, 20), date(2024, 6, 20), date(2024, 12, 21)]


class GoldenHourTest(unittest.TestCase):
    def test_crossings_land_at_the_target_height(self):
        for day in DAYS:
            for target in (GOLDEN_LOW, GOLDEN_HIGH, HORIZON):
                for t in crossings(*SEATTLE, target, day):
                    self.assertAlmostEqual(altitude(*SEATTLE, t), target, delta=0.3, msg=f"{day} {target}")

    def test_the_bands_are_in_order(self):
        for day in DAYS:
            (ms, me), (es, ee) = golden_hour(*SEATTLE, day)
            self.assertLess(ms, me)
            self.assertLess(me, solar_noon(*SEATTLE, day))
            self.assertLess(solar_noon(*SEATTLE, day), es)
            self.assertLess(es, ee)

    def test_solar_noon_is_the_peak(self):
        for day in DAYS:
            noon = solar_noon(*SEATTLE, day)
            high = altitude(*SEATTLE, noon)
            for shift in (-20, 20):
                self.assertGreater(high, altitude(*SEATTLE, noon + timedelta(minutes=shift)))

    def test_solar_noon_in_seattle_in_june(self):
        want = datetime(2024, 6, 20, 13, 10, tzinfo=PDT)
        self.assertLess(abs(solar_noon(*SEATTLE, date(2024, 6, 20)) - want), timedelta(minutes=3))

    def test_summer_evening_lasts_about_an_hour(self):
        _, (start, end) = golden_hour(*SEATTLE, date(2024, 6, 20))
        self.assertTrue(timedelta(minutes=45) < end - start < timedelta(minutes=90))

    def test_the_horizon_crossing_is_rise_set(self):
        for day in DAYS + [date(2024, 9, 1)]:
            self.assertEqual(crossings(*SEATTLE, HORIZON, day), rise_set(*SEATTLE, day))

    def test_far_north_winter(self):
        day = date(2024, 12, 21)
        # Tromso is in polar night: the sun never gets above -4 here, so the
        # whole band is missing. The asserts follow what altitude() shows.
        peak = altitude(*TROMSO, solar_noon(*TROMSO, day))
        (ms, me), (es, ee) = golden_hour(*TROMSO, day)
        if peak < GOLDEN_LOW:
            self.assertEqual(((ms, me), (es, ee)), ((None, None), (None, None)))
        else:
            self.assertIsNotNone(ms)
            self.assertIsNotNone(ee)
            self.assertIsNone(me)
            self.assertIsNone(es)

    def test_near_the_equator_the_bands_are_short(self):
        # 10 degrees at 15 degrees an hour is 40 minutes at the equinox.
        (ms, me), (es, ee) = golden_hour(*QUITO, date(2024, 3, 20))
        self.assertLess(me - ms, timedelta(minutes=45))
        self.assertLess(ee - es, timedelta(minutes=45))


if __name__ == "__main__":
    unittest.main()
