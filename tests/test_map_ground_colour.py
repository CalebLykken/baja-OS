"""The map's ground colour, before the page paints, must match the map's own.

Plain text checks (no WebEngine, no Qt): MapView.qml's backgroundColor is what
shows while the map page loads, MapsPage.qml's ground Rectangle is what shows
behind the map, and map.js LOOKS sets the real colours. They must agree, and
web/map/index.html must give a day boot its day ground instead of night.

    python3 -m unittest tests.test_map_ground_colour
"""

import os
import re
import unittest

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))


def read(*parts):
    with open(os.path.join(ROOT, *parts), encoding="utf-8") as f:
        return f.read()


def look_page(look):
    """The `page:` colour of LOOKS.<look> in web/map/map.js."""
    js = read("web", "map", "map.js")
    looks = js[js.index("const LOOKS"):]    # the flavor objects nest braces, so scan from the block
    m = re.search(r"\b%s:\s*\{.*?\bpage:\s*\"(#[0-9a-fA-F]{6})\"" % look, looks, re.S)
    if m is None:
        raise AssertionError("no page colour for LOOKS.%s in map.js" % look)
    return m.group(1).lower()


class MapGroundColour(unittest.TestCase):

    def test_map_view_background_matches_the_map_ground(self):
        line = next(l for l in read("qml", "pages", "MapView.qml").splitlines() if "backgroundColor:" in l)
        m = re.search(r'mode === "day" \? "(#[0-9a-fA-F]{6})" : "(#[0-9a-fA-F]{6})"', line)
        self.assertIsNotNone(m, line)
        day, night = m.group(1).lower(), m.group(2).lower()
        self.assertEqual(day, look_page("day"))
        self.assertEqual(night, look_page("night"))

    def test_maps_page_ground_matches_the_map_ground(self):
        line = next(l for l in read("qml", "pages", "MapsPage.qml").splitlines() if "the map's own ground" in l)
        m = re.search(r'Theme\.dark \? "(#[0-9a-fA-F]{6})" : "(#[0-9a-fA-F]{6})"', line)
        self.assertIsNotNone(m, line)
        night, day = m.group(1).lower(), m.group(2).lower()
        self.assertEqual(day, look_page("day"))
        self.assertEqual(night, look_page("night"))

    def test_index_gives_day_its_ground_and_map_is_transparent(self):
        html = read("web", "map", "index.html")
        # The day rule on the html element, applied by the script from ?mode=day.
        self.assertRegex(html, r"html\.day,\s*html\.day body\s*\{[^}]*background:\s*#ebe7df")
        self.assertIn('get("mode") === "day"', html)
        self.assertIn('classList.add("day")', html)
        # #map must not carry the night background any more; it shows the body's.
        self.assertRegex(html, r"#map\s*\{\s*background:\s*transparent")
        base = re.search(r"html, body, #map\s*\{([^}]*)\}", html)
        self.assertIsNotNone(base)
        self.assertNotIn("background", base.group(1))
        self.assertIn("html, body", html)

    def test_map_js_switches_the_day_class_with_the_look(self):
        js = read("web", "map", "map.js")
        self.assertIn('classList.toggle("day", m === "day")', js)


class GpsLostChip(unittest.TestCase):
    """The 'GPS signal lost' chip on the Maps page: shown with gps.stale, not for the demo."""

    def test_chip_is_bound_to_gps_stale_and_not_the_demo(self):
        qml = read("qml", "pages", "MapsPage.qml")
        self.assertIn('text: "GPS signal lost"', qml)
        chip = qml[qml.index("id: gpsLostChip"):]
        chip = chip[:chip.index("MapLabel")]
        self.assertIn("gps.stale", chip)
        self.assertIn('gps.source !== "demo"', chip)
        self.assertIn("page.mapReady", chip)
        self.assertIn("border.color: page.cRed", chip)

    def test_chip_stacks_below_the_outside_chip_at_the_same_x(self):
        qml = read("qml", "pages", "MapsPage.qml")
        chip = qml[qml.index("id: gpsLostChip"):]
        chip = chip[:chip.index("MapLabel")]
        self.assertIn("x: outsideChip.x", chip)
        self.assertIn("y: outsideChip.y + (outsideChip.visible ? 64 : 0)", chip)
        self.assertIn("id: outsideChip", qml)


if __name__ == "__main__":
    unittest.main()
