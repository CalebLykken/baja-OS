"""Off-Pi checks for the attention dots in Settings' section list: a small
warning dot on Wi-Fi, Bluetooth and System when that section needs looking
at. Reads the source, so it runs without PyQt.

    python3 -m unittest tests.test_settings_attention
"""

import re
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
PAGE = (ROOT / "qml/pages/SettingsPage.qml").read_text()


def attention_body():
    start = PAGE.index("function attention(i)")
    end = PAGE.index("\n    }\n", start)
    return PAGE[start:end]


class AttentionDotTest(unittest.TestCase):
    def test_wifi_flags_offline_only_after_a_check(self):
        body = attention_body()
        self.assertIn("i === 2", body)
        self.assertRegex(body, r"network\.checked && !network\.online")

    def test_bluetooth_flags_a_broken_agent(self):
        body = attention_body()
        self.assertIn("i === 3", body)
        self.assertRegex(body, r"!bluetooth\.agentOk && bluetooth\.agentProblem !== \"\"")

    def test_system_flags_power_warnings(self):
        body = attention_body()
        self.assertIn("i === 5", body)
        self.assertIn('system.power !== ""', body)
        self.assertRegex(body, r"powerLog\.supply >= 0 && powerLog\.lowest < 4\.8")

    def test_other_sections_never_flag(self):
        body = attention_body()
        self.assertIn("return false", body)
        self.assertEqual(len(re.findall(r"if \(i === ", body)), 3)

    def test_dot_is_small_warn_coloured_and_at_the_right(self):
        self.assertIn('objectName: "attentionDot"', PAGE)
        dot = PAGE[PAGE.index('objectName: "attentionDot"') - 120:PAGE.index('objectName: "attentionDot"') + 420]
        self.assertIn("rightMargin: 16", dot)
        self.assertIn("width: 12", dot)
        self.assertIn("radius: 6", dot)
        self.assertIn("color: Theme.warn", dot)

    def test_dot_has_no_animation_or_timer(self):
        start = PAGE.index('objectName: "attentionDot"') - 400
        chunk = PAGE[start:PAGE.index('objectName: "attentionDot"') + 300]
        for word in ("Animation", "Behavior", "Timer"):
            self.assertNotIn(word, chunk)


if __name__ == "__main__":
    unittest.main()
