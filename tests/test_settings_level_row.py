"""Source test: the three level sliders in Settings share one LevelRow."""
import unittest
from pathlib import Path

SRC = (Path(__file__).resolve().parent.parent / "qml/pages/SettingsPage.qml").read_text()


class LevelRowTest(unittest.TestCase):
    def test_level_bar_only_inside_level_row(self):
        self.assertEqual(SRC.count("LevelBar {"), 1)
        self.assertLess(SRC.index("component LevelRow"), SRC.index("LevelBar {"))

    def test_three_uses(self):
        self.assertEqual(SRC.count("LevelRow {"), 3)

    def test_sound_rows_labelled(self):
        self.assertIn('label: "Resume Spotify"', SRC)
        self.assertIn('label: "Spoken directions"', SRC)


if __name__ == "__main__":
    unittest.main()
