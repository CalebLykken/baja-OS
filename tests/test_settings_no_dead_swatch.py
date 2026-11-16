"""Off-Pi check that Settings no longer carries the old inline StyleSwatch.

The Style picker moved to qml/components/themes/StylePicker in round 1; the
inline component was left behind unused. This keeps it from coming back
unnoticed.

    python3 -m unittest tests.test_settings_no_dead_swatch
"""

import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
PAGE = (ROOT / "qml/pages/SettingsPage.qml").read_text()


class NoDeadSwatchTest(unittest.TestCase):
    def test_no_inline_style_swatch(self):
        self.assertNotIn("StyleSwatch", PAGE)
        self.assertNotIn("swatch_", PAGE)

    def test_picker_still_used(self):
        self.assertIn("StylePicker {", PAGE)


if __name__ == "__main__":
    unittest.main()
