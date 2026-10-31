"""Off-Pi tests for offline place search (backend/places.py): what counts as
an address, how the typed words become an FTS query, and the order results
come back in, on a tiny in-memory index with the real table layout.

    python3 -m unittest tests.test_places
"""

import math
import sqlite3
import time
import unittest

from backend.places import _fts_query, along_route, looks_like_address, nearby, search, search_addresses, street_part

SEATTLE = (-122.3321, 47.6062)


def index(rows):
    """An in-memory places table; rows are (name, kind, area, weight, lon, lat)."""
    db = sqlite3.connect(":memory:")
    db.execute("CREATE VIRTUAL TABLE places USING fts5(name, kind UNINDEXED, area UNINDEXED,"
               " weight UNINDEXED, lon UNINDEXED, lat UNINDEXED, tokenize='unicode61 remove_diacritics 2')")
    db.executemany("INSERT INTO places VALUES (?, ?, ?, ?, ?, ?)", rows)
    return db


def names(results):
    return [r["name"] for r in results]


class AddressTest(unittest.TestCase):
    def test_a_number_then_a_street(self):
        for text in ("4500 aurora ave n", "  1200 3rd Ave ", "12B Baker St", "99 Main"):
            self.assertTrue(looks_like_address(text), text)

    def test_a_place_name_is_not(self):
        for text in ("aurora ave", "Pike Place Market", "Pier 54", "4500", "", "   "):
            self.assertFalse(looks_like_address(text), text)

    def test_the_street_part(self):
        self.assertEqual(street_part("4500  aurora ave n"), "aurora ave n")
        self.assertEqual(street_part("4500"), "")


class FtsQueryTest(unittest.TestCase):
    def test_every_word_is_a_prefix(self):
        self.assertEqual(_fts_query("gas works"), '"gas"* AND "works"*')

    def test_case_and_punctuation_go(self):
        self.assertEqual(_fts_query("  St. Mark's, Cathedral! "), '"st"* AND "mark"* AND "s"* AND "cathedral"*')

    def test_quotes_and_operators_cannot_break_the_query(self):
        self.assertEqual(_fts_query('a" OR "b'), '"a"* AND "or"* AND "b"*')
        self.assertEqual(_fts_query("x*)(NEAR"), '"x"* AND "near"*')

    def test_digits_and_accents_stay(self):
        self.assertEqual(_fts_query("5th Café"), '"5th"* AND "café"*')

    def test_nothing_to_search_for(self):
        for text in ("", "   ", "!?-"):
            self.assertEqual(_fts_query(text), "")


class SearchTest(unittest.TestCase):
    def test_nothing_typed_finds_nothing(self):
        db = index([("Gas Works Park", "park", "Seattle", 1, -122.33, 47.64)])
        self.assertEqual(search(db, ""), [])
        self.assertEqual(search(db, " ?! "), [])

    def test_a_prefix_of_each_word_matches(self):
        db = index([("Gas Works Park", "park", "Seattle", 1, -122.33, 47.64),
                    ("Space Needle", "attraction", "Seattle", 1, -122.349, 47.62)])
        self.assertEqual(names(search(db, "gas wor")), ["Gas Works Park"])
        self.assertEqual(names(search(db, "park gas")), ["Gas Works Park"])
        self.assertEqual(search(db, "gas needle"), [])

    def test_accents_and_case_dont_matter(self):
        db = index([("Café Allegro", "cafe", "Seattle", 1, -122.31, 47.66)])
        self.assertEqual(names(search(db, "CAFE alle")), ["Café Allegro"])

    def test_the_exact_name_comes_first(self):
        db = index([("Seattle Center", "attraction", "Seattle", 1, -122.35, 47.62),
                    ("Seattle", "locality", "", 0, -122.33, 47.61),
                    ("Seattle Art Museum", "museum", "Seattle", 1, -122.338, 47.607)])
        self.assertEqual(names(search(db, "seattle"))[0], "Seattle")
        self.assertEqual(names(search(db, "SEATTLE"))[0], "Seattle")

    def test_a_name_that_starts_with_it_beats_one_that_only_contains_it(self):
        db = index([("The Home Depot", "doityourself", "Seattle", 1, -122.33, 47.61),
                    ("Depot Coffee", "cafe", "Seattle", 1, -122.33, 47.61)])
        self.assertEqual(names(search(db, "depot")), ["Depot Coffee", "The Home Depot"])

    def test_the_closer_of_two_equal_names_comes_first(self):
        db = index([("Starbucks", "cafe", "Tacoma", 1, -122.44, 47.25),
                    ("Starbucks", "cafe", "Seattle", 1, -122.33, 47.61),
                    ("Starbucks", "cafe", "Bellevue", 1, -122.20, 47.61)])
        self.assertEqual([r["area"] for r in search(db, "starbucks", near=SEATTLE)],
                         ["Seattle", "Bellevue", "Tacoma"])

    def test_a_near_branch_beats_a_far_one_with_a_longer_name(self):
        # The case in the code's own comment.
        db = index([("Home Depot Garden Center", "doityourself", "Kent", 1, -122.23, 47.38),
                    ("The Home Depot", "doityourself", "Seattle", 1, -122.30, 47.58)])
        self.assertEqual(names(search(db, "home depot", near=SEATTLE)), ["The Home Depot", "Home Depot Garden Center"])

    def test_a_town_beats_a_street_of_the_same_name(self):
        db = index([("Kent", "street", "Seattle", 2, -122.33, 47.60),
                    ("Kent", "locality", "", 0, -122.23, 47.38)])
        self.assertEqual([r["kind"] for r in search(db, "kent")], ["locality", "street"])

    def test_the_distance_is_in_metres_or_minus_one(self):
        db = index([("Pike Place Market", "market", "Seattle", 1, -122.3422, 47.6097)])
        self.assertEqual(search(db, "pike")[0]["distance"], -1)
        d = search(db, "pike", near=SEATTLE)[0]["distance"]
        self.assertTrue(500 < d < 1500, d)

    def test_the_same_name_in_the_same_area_shows_once(self):
        db = index([("Main Street", "street", "Seattle", 1, -122.33, 47.60),
                    ("Main Street", "street", "Seattle", 1, -122.34, 47.61),
                    ("Main Street", "street", "Bellevue", 1, -122.20, 47.61)])
        self.assertEqual(len(search(db, "main street")), 2)

    def test_a_limit(self):
        db = index([(f"Oak {n}", "street", "Seattle", 1, -122.33, 47.6) for n in range(20)])
        self.assertEqual(len(search(db, "oak")), 12)
        self.assertEqual(len(search(db, "oak", limit=3)), 3)

    def test_what_comes_back(self):
        db = index([("Gas Works Park", "park", "Seattle", 1, -122.33, 47.64)])
        self.assertEqual(search(db, "gas"), [{"name": "Gas Works Park", "kind": "park", "area": "Seattle",
                                              "lon": -122.33, "lat": 47.64, "distance": -1}])


class NearbyTest(unittest.TestCase):
    def test_the_nearest_of_a_category_first(self):
        db = index([("Far Gas", "fuel", "Tacoma", 1, -122.44, 47.25),
                    ("Near Gas", "fuel", "Seattle", 1, -122.33, 47.61),
                    ("A Cafe", "cafe", "Seattle", 1, -122.33, 47.6063)])
        self.assertEqual(names(nearby(db, "gas", SEATTLE)), ["Near Gas", "Far Gas"])

    def test_an_unknown_category_or_no_position(self):
        db = index([("Near Gas", "fuel", "Seattle", 1, -122.33, 47.61)])
        self.assertEqual(nearby(db, "nope", SEATTLE), [])
        self.assertEqual(nearby(db, "gas", None), [])


class AlongRouteTest(unittest.TestCase):
    # A road due north from (-122.3, 47.5): 0.001 degrees of latitude is 110.54 m.
    LON = -122.3
    ROAD = [(-122.3, 47.5 + i * 0.001) for i in range(0, 101)]    # about 11 km

    def gas(self, name, lat, east_m=0.0, area="Town"):
        lon = self.LON + east_m / (111320 * math.cos(math.radians(47.5)))
        return (name, "fuel", area, 1, lon, lat)

    def test_ahead_close_to_the_road_in_order(self):
        db = index([self.gas("Far", 47.55), self.gas("Near", 47.52, 100),
                    self.gas("Too Far Off", 47.53, 1000)])
        got = along_route(db, "gas", self.ROAD, 0)
        self.assertEqual(names(got), ["Near", "Far"])
        self.assertAlmostEqual(got[0]["distance"], 0.02 * 110540, delta=5)
        self.assertAlmostEqual(got[0]["off"], 100, delta=2)

    def test_behind_the_truck_is_left_out(self):
        db = index([self.gas("Behind", 47.51), self.gas("Ahead", 47.53)])
        self.assertEqual(names(along_route(db, "gas", self.ROAD, 20)), ["Ahead"])

    def test_distance_counts_from_the_trucks_segment(self):
        db = index([self.gas("Ahead", 47.53)])
        got = along_route(db, "gas", self.ROAD, 20)
        self.assertAlmostEqual(got[0]["distance"], 0.01 * 110540, delta=5)

    def test_other_kinds_and_repeats(self):
        db = index([self.gas("Shell", 47.52), self.gas("Shell", 47.53),
                    self.gas("Shell", 47.54, area="Elsewhere"),
                    ("A Cafe", "cafe", "Town", 1, self.LON, 47.52)])
        got = along_route(db, "gas", self.ROAD, 0)
        self.assertEqual([r["area"] for r in got], ["Town", "Elsewhere"])
        self.assertEqual(names(along_route(db, "coffee", self.ROAD, 0)), ["A Cafe"])

    def test_nothing_to_search(self):
        db = index([self.gas("Near", 47.52)])
        self.assertEqual(along_route(db, "nope", self.ROAD, 0), [])
        self.assertEqual(along_route(db, "gas", [], 0), [])
        self.assertEqual(along_route(db, "gas", self.ROAD[:1], 0), [])
        self.assertEqual(along_route(db, "gas", self.ROAD, 500), [])
        self.assertEqual(along_route(db, "gas", [("x", "y")], 0), [])

    def test_only_the_next_stretch_counts(self):
        # 300 km north: a station 200 km on is past the reach.
        road = [(self.LON, 47.5 + i * 0.01) for i in range(0, 271)]
        db = index([self.gas("Soon", 47.6), self.gas("Much Later", 49.4)])
        self.assertEqual(names(along_route(db, "gas", road, 0)), ["Soon"])

    def test_the_trucks_place_on_its_segment(self):
        # 50 m into the first 110 m segment: a station 30 m back is behind, one 200 m on is ahead.
        db = index([self.gas("Just Passed", 47.5 + 0.0002), self.gas("Ahead", 47.5 + 0.0020)])
        got = along_route(db, "gas", self.ROAD, 0, 50)
        self.assertEqual(names(got), ["Ahead"])
        self.assertAlmostEqual(got[0]["distance"], 0.002 * 110540 - 50, delta=5)

    def test_behind_the_start_of_the_first_segment_is_not_ahead(self):
        road = [(self.LON, 47.5), (self.LON, 47.51)]
        db = index([self.gas("Behind", 47.5 - 0.0025), self.gas("Ahead", 47.505)])      # 277 m back
        self.assertEqual(names(along_route(db, "gas", road, 0)), ["Ahead"])

    def test_behind_the_truck_on_a_road_of_short_segments(self):
        # 276 m behind a truck 50 m into segment 20: the next segment's start is within the corridor.
        db = index([self.gas("Behind", 47.52 - 0.0025, area="A"), self.gas("Ahead", 47.53, area="B")])
        self.assertEqual(names(along_route(db, "gas", self.ROAD, 20, 50)), ["Ahead"])

    def test_an_outer_corner_is_still_found(self):
        # North 500 m then east: a station just past the corner, off both legs' ends by 100 m.
        road = [(self.LON, 47.5), (self.LON, 47.5045), (self.LON + 0.01, 47.5045)]
        db = index([self.gas("Corner", 47.5055, -20)])
        self.assertEqual(names(along_route(db, "gas", road, 0)), ["Corner"])

    def test_a_dead_end_station_just_passed_is_found_on_the_way_back(self):
        # Out 1 km (truck 800 m along) and back: the station at 700 m is behind now, ahead on the return.
        road = [(self.LON, 47.5), (self.LON, 47.509), (self.LON + 0.0000001, 47.5), ]
        db = index([self.gas("Passed", 47.5 + 700 / 110540, 100)])
        got = along_route(db, "gas", road, 0, 800)
        self.assertEqual(names(got), ["Passed"])
        self.assertGreater(got[0]["distance"], 200)

    def test_a_spur_reports_the_first_pass(self):
        # Out 1 km north and back down the same way: the place is passed twice.
        road = [(self.LON, 47.5), (self.LON, 47.51), (self.LON + 0.0000001, 47.5101), (self.LON, 47.5)]
        db = index([self.gas("Spur", 47.505)])
        got = along_route(db, "gas", road, 0)
        self.assertAlmostEqual(got[0]["distance"], 0.005 * 110540, delta=5)

    def test_a_long_route_is_quick(self):
        road = [(self.LON + 0.00001 * (i % 7), 47.0 + i * 0.0001) for i in range(12000)]
        rows = [self.gas(f"G{i}", 47.0 + i * 0.00024, 50 * (i % 5)) for i in range(5000)]
        db = index(rows)
        start = time.monotonic()
        got = along_route(db, "gas", road, 0, limit=5)
        self.assertEqual(len(got), 5)
        self.assertLess(time.monotonic() - start, 1.0)


class AddressSearchTest(unittest.TestCase):
    def db(self, rows):
        db = sqlite3.connect(":memory:")
        db.execute("CREATE VIRTUAL TABLE addresses USING fts5(number, street, city, postcode UNINDEXED,"
                   " lon UNINDEXED, lat UNINDEXED, tokenize='unicode61 remove_diacritics 2')")
        db.executemany("INSERT INTO addresses VALUES (?, ?, ?, ?, ?, ?)", rows)
        return db

    def test_abbreviations_and_directions(self):
        db = self.db([("4500", "Aurora Avenue North", "Seattle", "98103", -122.344, 47.662),
                      ("4500", "Aurora Avenue South", "Seattle", "98108", -122.31, 47.52)])
        self.assertEqual([r["name"] for r in search_addresses(db, "4500 aurora ave n")], ["4500 Aurora Avenue North"])
        self.assertEqual(len(search_addresses(db, "4500 aurora")), 2)

    def test_the_number_must_match_whole(self):
        db = self.db([("4500", "Aurora Avenue North", "Seattle", "98103", -122.344, 47.662)])
        self.assertEqual(search_addresses(db, "450 aurora"), [])
        self.assertEqual(search_addresses(db, "45000 aurora"), [])

    def test_a_number_alone_is_not_enough(self):
        db = self.db([("4500", "Aurora Avenue North", "Seattle", "98103", -122.344, 47.662)])
        self.assertEqual(search_addresses(db, "4500"), [])

    def test_a_point_and_a_building_show_once_with_the_city(self):
        db = self.db([("4500", "Aurora Avenue North", "", "", -122.3441, 47.6621),
                      ("4500", "Aurora Avenue North", "Seattle", "98103", -122.3440, 47.6620)])
        found = search_addresses(db, "4500 aurora ave n")
        self.assertEqual(len(found), 1)
        self.assertEqual(found[0]["area"], "Seattle")

    def test_nearest_first(self):
        db = self.db([("100", "Pine Street", "Tacoma", "98402", -122.44, 47.25),
                      ("100", "Pine Avenue", "Seattle", "98101", -122.33, 47.61)])
        found = search_addresses(db, "100 pine", near=SEATTLE)
        self.assertEqual([r["area"] for r in found], ["Seattle", "Tacoma"])
        self.assertEqual(search_addresses(db, "100 pine")[0]["distance"], -1)


if __name__ == "__main__":
    unittest.main()
