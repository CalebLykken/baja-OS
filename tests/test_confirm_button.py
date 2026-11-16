"""Source checks for the Settings ConfirmButton: it looks armed through
TextButton, keeps one width, adds no animation, and Restart asks first.

    python3 -m unittest tests.test_confirm_button
"""

import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
PAGE = (ROOT / "qml/pages/SettingsPage.qml").read_text()
BUTTON = (ROOT / "qml/components/TextButton.qml").read_text()


def confirm_body():
    start = PAGE.index("component ConfirmButton:")
    end = PAGE.index("// ====", start)
    return PAGE[start:end]


class ConfirmButtonTest(unittest.TestCase):
    def test_no_extra_animation(self):
        body = confirm_body()
        self.assertNotIn("Behavior", body)
        self.assertNotIn("Animation", body)
        self.assertEqual(BUTTON.count("Behavior on"), 1)

    def test_armed_lives_in_text_button(self):
        self.assertIn("property bool armed: false", BUTTON)
        self.assertNotIn("property bool armed", confirm_body())
        self.assertIn("armed ? Theme.warn", BUTTON)

    def test_width_fixed_to_widest_text(self):
        body = confirm_body()
        self.assertIn("implicitWidth: Math.max(plainProbe.implicitWidth, confirmProbe.implicitWidth)", body)

    def test_restart_asks_first(self):
        self.assertRegex(PAGE, r'ConfirmButton \{[^\n]*text: "Restart dashboard"[^\n]*confirmText: "Tap again to restart"')
        self.assertNotRegex(PAGE, r'TextButton \{[^\n]*Restart dashboard')

    def test_forget_is_touch_sized(self):
        self.assertNotIn("implicitHeight: 48", PAGE)


if __name__ == "__main__":
    unittest.main()
