"""Off-Pi tests for the knob's presses (backend/knob.py): single, double and
long, and what the hub does with a mute.

    python3 -m unittest tests.test_knob
"""

import unittest
from unittest import mock

try:
    from PyQt6.QtCore import QCoreApplication, QEventLoop, QTimer
    from backend import hub as hub_module, knob
    from backend.hub import MediaHub
    from backend.knob import Gestures, double_press
    from backend.media import MediaPlayer
except ImportError as e:
    raise unittest.SkipTest(f"PyQt6 isn't installed ({e})")

app = QCoreApplication.instance() or QCoreApplication([])


def spin(ms):
    loop = QEventLoop()
    QTimer.singleShot(ms, loop.quit)
    loop.exec()


class GesturesTest(unittest.TestCase):
    LONG, DOUBLE = 200, 100             # shortened: the real ones are LONG_PRESS_MS, DOUBLE_PRESS_MS

    def setUp(self):
        with mock.patch.object(knob, "LONG_PRESS_MS", self.LONG), \
                mock.patch.object(knob, "DOUBLE_PRESS_MS", self.DOUBLE):
            self.g = Gestures()
        self.seen = []
        for name in ("single", "double", "long"):
            getattr(self.g, name).connect(lambda n=name: self.seen.append(n))

    def press(self, hold_ms=20):
        self.g.down()
        spin(hold_ms)
        self.g.up()

    def test_the_real_timings(self):
        self.assertEqual((knob.LONG_PRESS_MS, knob.DOUBLE_PRESS_MS), (700, 300))
        g = Gestures()
        self.assertEqual((g._hold.interval(), g._wait.interval()), (700, 300))

    def test_a_press_is_a_single_once_a_second_can_no_longer_follow(self):
        self.press()
        spin(self.DOUBLE // 2)
        self.assertEqual(self.seen, [])                     # still waiting for a second press
        spin(self.DOUBLE)
        self.assertEqual(self.seen, ["single"])

    def test_two_presses_are_a_double_and_nothing_else(self):
        self.press()
        spin(self.DOUBLE // 3)
        self.g.down()
        self.assertEqual(self.seen, ["double"])             # on the second press going down
        spin(self.LONG * 2)                                 # held on: not also a long press
        self.g.up()
        spin(self.DOUBLE * 3)
        self.assertEqual(self.seen, ["double"])

    def test_holding_is_a_long_press_while_still_held(self):
        self.g.down()
        spin(self.LONG + 60)
        self.assertEqual(self.seen, ["long"])
        self.g.up()
        spin(self.DOUBLE * 3)
        self.assertEqual(self.seen, ["long"])               # the release is not a single

    def test_a_third_press_starts_over(self):
        self.press()
        self.g.down()
        self.g.up()
        spin(self.DOUBLE * 2)
        self.press()
        spin(self.DOUBLE * 2)
        self.assertEqual(self.seen, ["double", "single"])

    def test_a_late_second_press_is_a_new_press(self):
        self.press()
        spin(self.DOUBLE * 2)
        self.press()
        spin(self.DOUBLE * 2)
        self.assertEqual(self.seen, ["single", "single"])

    def test_stray_releases_and_repeated_downs_do_nothing(self):
        self.g.up()
        self.g.down()
        self.g.down()                                       # a missed release, or a bounce
        self.g.up()
        spin(self.DOUBLE * 2)
        self.assertEqual(self.seen, ["single"])


class DoublePressTest(unittest.TestCase):
    def test_while_navigating_it_repeats_the_last_direction(self):
        routing, media = mock.Mock(active=True), mock.Mock()
        double_press(routing, media)
        routing.repeatLast.assert_called_once_with()
        media.next.assert_not_called()

    def test_otherwise_it_skips(self):
        routing, media = mock.Mock(active=False), mock.Mock()
        double_press(routing, media)
        media.next.assert_called_once_with()
        routing.repeatLast.assert_not_called()


class MuteTest(unittest.TestCase):
    def make(self, wpctl):
        local = MediaPlayer()
        self.addCleanup(local._timer.stop)
        phone, spotify = mock.MagicMock(), mock.MagicMock()
        for src in (phone, spotify):
            src.deviceName = ""
        with mock.patch.object(hub_module.shutil, "which", return_value="/usr/bin/wpctl" if wpctl else None):
            hub = MediaHub(local, phone, spotify, volume=50, max_volume=80)
        self.addCleanup(hub._mute_timer.stop)
        return hub, local

    def ramp(self, hub, ms=hub_module.MUTE_MS + 100):
        for _ in range(ms // hub_module.FADE_STEP_MS + 1):
            if not hub._mute_timer.isActive():
                break
            hub._mute_tick()

    def test_a_long_press_mutes_and_another_unmutes(self):
        hub, local = self.make(wpctl=False)
        self.assertEqual(local.volume, 40)                  # 50% of the 80% ceiling
        hub.toggleMute()
        self.assertTrue(hub.muted)
        self.ramp(hub)
        self.assertEqual(local.volume, 0)
        self.assertEqual(hub.volume, 50)                    # the slider still says where it was
        hub.toggleMute()
        self.assertFalse(hub.muted)
        self.ramp(hub)
        self.assertEqual(local.volume, 40)

    def test_it_ramps_instead_of_cutting_off(self):
        hub, local = self.make(wpctl=False)
        hub.toggleMute()
        hub._mute_tick()
        self.assertTrue(0 < local.volume < 40)

    def test_turning_the_knob_unmutes_and_moves_the_volume(self):
        hub, local = self.make(wpctl=False)
        hub.toggleMute()
        self.ramp(hub)
        hub.volumeUp()
        self.assertFalse(hub.muted)
        self.assertEqual(hub.volume, 54)
        self.ramp(hub)
        self.assertEqual(local.volume, round(54 * 0.8))

    def test_the_output_level_goes_to_zero_on_the_pi(self):
        hub, _ = self.make(wpctl=True)
        hub.toggleMute()
        self.ramp(hub)
        self.assertEqual(hub._pending_level, 0.0)
        hub.toggleMute()
        self.ramp(hub)
        self.assertAlmostEqual(hub._pending_level, 0.5 * 0.8)

    def test_mute_does_not_pause(self):
        hub, local = self.make(wpctl=False)
        playing = hub.playing
        hub.toggleMute()
        self.assertEqual(hub.playing, playing)

    def test_a_mute_is_announced_once(self):
        hub, _ = self.make(wpctl=False)
        seen = []
        hub.mutedChanged.connect(lambda: seen.append(hub.muted))
        hub.toggleMute()
        hub.setVolume(30)
        hub.setVolume(31)
        self.assertEqual(seen, [True, False])


if __name__ == "__main__":
    unittest.main()
