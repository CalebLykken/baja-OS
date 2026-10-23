"""Off-Pi tests for the key-off decision (backend/ignition.py), with a
clock that's just a number.

    python3 -m unittest tests.test_ignition
"""

import unittest

from backend.ignition import KeyOffLogic

QUIET_S, WARN_S = 15.0, 10.0


def logic():
    return KeyOffLogic(quiet_s=QUIET_S, warn_s=WARN_S)


class KeyOffTest(unittest.TestCase):
    def test_nothing_before_the_car_has_answered(self):
        k = logic()
        k.quiet(0)                                 # a bench Pi, or the key never on
        for t in range(0, 120):
            self.assertIsNone(k.seconds_left(t))

    def test_counts_down_after_the_quiet_wait(self):
        k = logic()
        k.answered(0)
        k.quiet(100)
        self.assertIsNone(k.seconds_left(100))
        self.assertIsNone(k.seconds_left(114.9))   # still waiting: no prompt yet
        self.assertEqual(k.seconds_left(115), 10)  # the prompt appears
        self.assertEqual(k.seconds_left(120.5), 5)
        self.assertEqual(k.seconds_left(125), 0)   # power off
        self.assertEqual(k.seconds_left(130), 0)

    def test_the_car_answering_again_cancels(self):
        k = logic()
        k.answered(0)
        k.quiet(0)
        self.assertEqual(k.seconds_left(18), 7)
        k.answered(0)                              # a hiccup, or cranking
        self.assertIsNone(k.seconds_left(30))
        k.quiet(40)                                # the real key-off: a fresh wait
        self.assertIsNone(k.seconds_left(50))
        self.assertEqual(k.seconds_left(65), 0)

    def test_repeated_quiet_doesnt_restart_the_wait(self):
        k = logic()
        k.answered(0)
        k.quiet(0)
        k.quiet(10)                                # the reader reports it again
        self.assertEqual(k.seconds_left(25), 0)

    def test_keep_on_lasts_until_the_car_answers_again(self):
        k = logic()
        k.answered(0)
        k.quiet(0)
        self.assertEqual(k.seconds_left(16), 9)
        k.keep_on()
        self.assertIsNone(k.seconds_left(30))
        self.assertIsNone(k.seconds_left(600))
        k.answered(0)
        k.quiet(700)
        self.assertEqual(k.seconds_left(725), 0)

    def test_keep_on_with_nothing_pending_does_nothing(self):
        k = logic()
        k.answered(0)
        k.keep_on()
        k.quiet(0)
        self.assertEqual(k.seconds_left(25), 0)

    def test_not_while_the_car_last_said_it_was_moving(self):
        k = logic()
        k.answered(40.0)                           # quiet at 40 mph: a glitch
        k.quiet(0)
        self.assertIsNone(k.seconds_left(60))
        k.answered(0.0)                            # parked, then the key goes off
        k.quiet(100)
        self.assertEqual(k.seconds_left(125), 0)

    def test_answers_without_speed_keep_the_last_one(self):
        k = logic()
        k.answered(0.0)
        k.answered(None)                           # a round without the speed
        k.quiet(0)
        self.assertEqual(k.seconds_left(25), 0)

    def test_gps_movement_starts_the_wait_again(self):
        k = logic()
        k.answered(0)
        k.quiet(0)
        self.assertEqual(k.seconds_left(16), 9)
        self.assertIsNone(k.seconds_left(17, moving=True))
        self.assertIsNone(k.seconds_left(30))      # 13 s since it stopped moving
        self.assertEqual(k.seconds_left(32), 10)
        self.assertEqual(k.seconds_left(42), 0)


if __name__ == "__main__":
    unittest.main()
