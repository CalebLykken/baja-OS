"""Off-Pi test that the Gauges page holds a peak tell-tale on the Coolant and
Intake gauges as well as RPM, Speed and Boost, and not on Battery. The peak
machinery lives in qml/components/Gauge.qml (peakHold); this only checks which
gauges the page turns it on for, by reading qml/pages/GaugesPage.qml. Each
Gauge { ... } block is matched by its braces and its label is read from it.

    python3 -m unittest tests.test_gauge_peak_hold_pages
"""

import re
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
PAGE = ROOT / "qml" / "pages" / "GaugesPage.qml"

PEAK_GAUGES = {"RPM", "Speed", "Boost", "Coolant", "Intake"}


def gauge_blocks(text):
    """Yield (label, block) for each Gauge { ... } in the QML text."""
    for match in re.finditer(r"\bGauge\s*\{", text):
        depth = 0
        for end in range(match.end() - 1, len(text)):
            if text[end] == "{":
                depth += 1
            elif text[end] == "}":
                depth -= 1
                if depth == 0:
                    break
        block = text[match.start():end + 1]
        label = re.search(r'label:\s*"([^"]*)"', block)
        # The Speed gauge's label is "Speed  ·  gear N", so compare its first word.
        name = label.group(1).split("  ")[0] if label else ""
        yield name, block


class GaugePeakHoldPageTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.blocks = dict(gauge_blocks(PAGE.read_text(encoding="utf-8")))

    def test_every_gauge_is_found(self):
        self.assertEqual(set(self.blocks), {"RPM", "Speed", "Boost", "Coolant", "Intake", "Battery"})

    def test_exactly_the_peak_gauges_hold_a_peak(self):
        held = {name for name, block in self.blocks.items()
                if re.search(r"\bpeakHold:\s*true\b", block)}
        self.assertEqual(held, PEAK_GAUGES)

    def test_battery_has_no_peak(self):
        self.assertNotRegex(self.blocks["Battery"], r"\bpeakHold\b")


if __name__ == "__main__":
    unittest.main()
