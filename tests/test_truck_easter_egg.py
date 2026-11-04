"""The Truck page's easter egg (five taps on the name) must stay free at
runtime: one-shot animations only, no new timers or looping animations,
which would cost CPU while the page sits idle."""
import re
import unittest
from pathlib import Path

QML = Path(__file__).resolve().parent.parent / "qml" / "pages" / "TruckPage.qml"


class TruckEasterEgg(unittest.TestCase):
    def setUp(self):
        self.src = QML.read_text()

    def test_title_has_a_tap_handler_and_the_aside(self):
        self.assertIn("TapHandler", self.src)
        self.assertIn("Half car. Half truck. All Baja.", self.src)

    def test_no_new_idle_work(self):
        # Only the turntable loops, and only the resume Timer exists.
        self.assertEqual(self.src.count("Animation.Infinite"), 1)
        self.assertEqual(len(re.findall(r"\bTimer\s*\{", self.src)), 1)
        self.assertNotIn("repeat: true", self.src)


if __name__ == "__main__":
    unittest.main()
