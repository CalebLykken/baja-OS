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

    def test_turntable_rests_after_90_seconds(self):
        # The rest is a one-shot PauseAnimation, not a Timer, and the
        # turntable's running binding must respect it.
        turntable = self.src.split("NumberAnimation on spin", 1)[1].split("loops:", 1)[0]
        self.assertIn("!page.resting", turntable)
        self.assertRegex(self.src, r"PauseAnimation\s*\{\s*duration:\s*90000\s*\}")
        self.assertIn("page.resting = true", self.src)

    def test_touch_and_reopen_wake_the_turntable(self):
        self.assertIn("function wake()", self.src)
        self.assertIn("TapHandler { onTapped: page.wake() }", self.src)
        for fn in ("onVisibleChanged", "Component.onCompleted", "onActiveChanged", "function eggTap()"):
            start = self.src.index(fn)
            self.assertIn("wake()", self.src[start:start + 400], fn)

    def test_spins_stop_the_running_intro_before_restarting_it(self):
        # start() on a running animation is a no-op and property changes only
        # apply on restart, so a tap during an open spin or an earlier egg spin
        # would change the caption but never spin. Stop first, then retarget.
        for fn in ("playIntro", "eggTap"):
            body = self.src.split("function %s()" % fn, 1)[1].split("\n    }\n", 1)[0]
            self.assertRegex(body, r"intro\.stop\(\)[\s\S]*intro\.from\s*=[\s\S]*intro\.start\(\)",
                             fn)


if __name__ == "__main__":
    unittest.main()
