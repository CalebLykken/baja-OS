"""The check-engine chip (qml/components/EngineWarning.qml) has its own glyph, so it
no longer looks like the Truck button above it in the nav rail.

    python3 -m unittest tests.test_engine_warning_glyph
"""

import re
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
PATHS = (ROOT / "qml" / "components" / "IconPaths.js").read_text()
CHIP = (ROOT / "qml" / "components" / "EngineWarning.qml").read_text()


def path_of(name):
    m = re.search(r'^\s*%s:\s*"([^"]*)"' % re.escape(name), PATHS, re.M)
    return m.group(1) if m else None


class EngineWarningGlyph(unittest.TestCase):
    def test_glyph_exists_and_is_a_path(self):
        d = path_of("engine_check")
        self.assertIsNotNone(d)
        self.assertRegex(d, r"^[Mm]")
        self.assertRegex(d, r"^[MmLlHhVvCcSsQqTtAaZz0-9 ,.\-]+$")

    def test_glyph_is_not_the_truck_icon(self):
        self.assertNotEqual(path_of("engine_check"), path_of("car"))

    def test_mil_uses_it(self):
        self.assertIn('chip.shown === "mil" ? "engine_check"', CHIP)
        self.assertNotIn('"mil" ? "car"', CHIP)


if __name__ == "__main__":
    unittest.main()
