"""Off-Pi tests for the knob's presses (backend/knob.py): single, double and
long, what the reader does when its pins drop out, and what the hub does with
a mute.

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


class Stop(BaseException):
    """Ends the knob's loop in a test. _run catches Exception, so this gets out."""


class FakeValue:
    ACTIVE, INACTIVE = "active", "inactive"


def legs(state):
    """The knob's two legs as libgpiod reports them: both open (high) at rest."""
    a, b = state >> 1 & 1, state & 1
    return (FakeValue.ACTIVE if a else FakeValue.INACTIVE, FakeValue.ACTIVE if b else FakeValue.INACTIVE)


class FakeLines:
    """A libgpiod request. Each edge wait takes the next frame, a (knob state,
    button pressed) pair, or raises the exception it holds. Reading the legs
    raises for each entry of `read_errors`, in order, before it works again."""

    def __init__(self, frames, read_errors=()):
        self.frames = list(frames)
        self.read_errors = list(read_errors)
        self.legs, self.button = legs(knob.REST), FakeValue.ACTIVE

    def get_values(self, lines):
        if self.read_errors:
            raise self.read_errors.pop(0)
        return list(self.legs)

    def get_value(self, line):
        return self.button

    def wait_edge_events(self, timeout):
        if not self.frames:
            raise Stop()
        frame = self.frames.pop(0)
        if isinstance(frame, BaseException):
            raise frame
        state, pressed = frame
        self.legs = legs(state)
        self.button = FakeValue.INACTIVE if pressed else FakeValue.ACTIVE
        return True

    def read_edge_events(self):
        pass

    def release(self):
        pass


def frame(state, pressed=False):
    return (state, pressed)


class KnobRecoveryTest(unittest.TestCase):
    # Steps of -1 each, so -4 in all: one click, which the knob reports as turned(+1)
    CLICK = [frame(1), frame(0), frame(2), frame(knob.REST)]

    def start(self, request_results):
        """A knob on fake pins. request_lines gives each result in turn: lines, or an OSError."""
        self.gpiod = mock.Mock()
        self.gpiod.request_lines.side_effect = request_results
        patches = [
            mock.patch.multiple(knob, create=True, gpiod=self.gpiod, Direction=mock.Mock(),
                                Bias=mock.Mock(), Edge=mock.Mock(), Value=FakeValue),
            mock.patch.object(knob.time, "sleep"),
            mock.patch.object(knob.errorlog, "log"),
        ]
        started = [p.start() for p in patches]
        for p in patches:
            self.addCleanup(p.stop)
        self.sleep, self.log = started[1], started[2]
        self.knob = knob.Knob()
        self.seen = []
        self.knob.turned.connect(lambda n: self.seen.append(("turned", n)))
        self.knob.pressed.connect(lambda: self.seen.append("pressed"))
        self.knob.released.connect(lambda: self.seen.append("released"))

    def test_a_read_error_as_the_knob_starts_does_not_end_it(self):
        lines = FakeLines(self.CLICK, read_errors=[OSError("gpio hiccup")])
        self.start([lines])
        with self.assertRaises(Stop):
            self.knob._run()
        self.log.report.assert_called_once()
        self.assertEqual(self.seen, [("turned", 1)])

    def test_a_press_held_through_a_lost_pin_is_released_and_the_knob_carries_on(self):
        lines = FakeLines([frame(knob.REST, pressed=True), OSError("gpio hiccup")] + self.CLICK)
        # the first request works, the re-request fails twice, then works
        self.start([lines, OSError("busy"), OSError("busy"), lines])
        with self.assertRaises(Stop):
            self.knob._run()
        self.assertEqual(self.seen, ["pressed", "released", ("turned", 1)])
        self.assertEqual(self.sleep.call_args_list, [mock.call(1.0), mock.call(1)])

    def test_while_the_pins_are_gone_it_keeps_trying_with_growing_pauses(self):
        lines = FakeLines([frame(knob.REST), OSError("gpio hiccup"), frame(knob.REST)])
        # the re-request fails five times in a row (each try is two request_lines calls), then works
        self.start([lines] + [OSError("busy")] * 10 + [lines])
        with self.assertRaises(Stop):
            self.knob._run()
        self.assertEqual([c.args[0] for c in self.sleep.call_args_list], [1.0, 1, 2, 5, 10, 10])
        self.assertEqual(self.seen, [])

    def test_at_start_no_pins_means_no_knob_and_no_retrying(self):
        self.start([OSError("no pins"), OSError("no pins")])
        self.knob._run()                 # returns, rather than retrying forever
        self.assertEqual(self.gpiod.request_lines.call_count, 2)     # the two debounce tries, no more
        self.sleep.assert_not_called()
        self.assertEqual(self.seen, [])


if __name__ == "__main__":
    unittest.main()
