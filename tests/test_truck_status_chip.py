"""The Truck page's engine status chip: a Card at the top right that jumps
to Gauges, shown only while the car answers, and made of bindings alone."""
import re
import unittest
from pathlib import Path

QML = Path(__file__).resolve().parent.parent / "qml" / "pages" / "TruckPage.qml"


class TruckStatusChip(unittest.TestCase):
    def setUp(self):
        src = QML.read_text()
        self.chip = src.split("id: status", 1)[1].split("id: readouts", 1)[0]

    def test_tap_opens_gauges(self):
        self.assertIn("tappable: true", self.chip)
        self.assertIn("onTapped: page.navigate(3)", self.chip)

    def test_hidden_unless_live_and_guarded(self):
        self.assertIn('typeof vehicle !== "undefined"', self.chip)
        self.assertIn("vehicle.engineKnown && vehicle.live", self.chip)
        self.assertIn("visible: have", self.chip)

    def test_states_and_colours(self):
        for text in ("Engine OK", "Check engine", "Overheating", "Battery", "Overboost"):
            self.assertIn(text, self.chip)
        self.assertIn("Theme.warn", self.chip)
        self.assertIn("Theme.ok", self.chip)
        self.assertIn("vehicle.milOn", self.chip)
        self.assertIn("vehicle.codeCount", self.chip)

    def test_big_enough_and_idle_free(self):
        self.assertGreaterEqual(int(re.search(r"height: (\d+)", self.chip).group(1)), 56)
        self.assertNotRegex(self.chip, r"\bTimer\s*\{|Animation|repeat: true")


if __name__ == "__main__":
    unittest.main()
