"""Off-Pi checks for the Bluetooth pairing steps on Settings' Phone card: three
numbered steps that follow the pairing state, hidden when the adapter is
missing, and no new timer or animation. Reads the source, so it runs without
PyQt.

    python3 -m unittest tests.test_settings_bt_steps
"""

import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
PAGE = (ROOT / "qml/pages/SettingsPage.qml").read_text()


def phone_card():
    start = PAGE.index('id: btCard')
    end = PAGE.index('heading: "Paired"', start)
    return PAGE[start:end]


class BluetoothStepsTest(unittest.TestCase):
    def setUp(self):
        self.card = phone_card()
        start = self.card.index("// Pairing steps")
        self.steps = self.card[start:]

    def test_old_paragraph_is_gone(self):
        self.assertNotIn("Pairing stays open for two minutes", self.card)

    def test_three_numbered_steps(self):
        for n in ("1  Tap Pair phone",
                  "2  On the phone, open Bluetooth settings and pick Baja OS",
                  "3  Tap Pair here when the codes match"):
            self.assertIn(n, self.steps)

    def test_steps_hidden_without_adapter_and_after_pairing(self):
        # Gated on adapterPresent too: with Bluetooth off the Pair button is
        # hidden, so "Tap Pair phone" would point at nothing.
        self.assertIn(
            "visible: bluetooth.available && bluetooth.adapterPresent\n"
            "                             && (bluetooth.paired.length === 0 || bluetooth.pairing)",
            self.steps)

    def test_paired_phone_gets_one_dim_line(self):
        start = self.steps.index("Label {\n                    Layout.fillWidth: true\n                    visible: bluetooth.available && bluetooth.adapterPresent\n"
                                  "                             && bluetooth.paired.length > 0")
        line = self.steps[start:]
        self.assertIn("color: Theme.textDim", line[:400])
        self.assertIn("Once paired, the phone reconnects by itself", line[:600])

    def test_bold_follows_pairing_state(self):
        self.assertIn("font.weight: bluetooth.pairing ? Font.Normal : Font.DemiBold", self.steps)
        self.assertEqual(self.steps.count("font.weight: bluetooth.pairing ? Font.DemiBold : Font.Normal"), 2)

    def test_steps_use_body_font_size(self):
        self.assertEqual(self.steps.count("font.pixelSize: Theme.fontBody"), 4)

    def test_no_new_timer_or_animation(self):
        # The card keeps its one existing timer (the pairing countdown).
        self.assertEqual(self.card.count("Timer {"), 1)
        self.assertNotIn("Animation", self.card)
        self.assertNotIn("Behavior on", self.card)


if __name__ == "__main__":
    unittest.main()
