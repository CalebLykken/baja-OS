"""Off-Pi tests for the key-off watcher (backend/ignition.py), with a fake
key and a clock that jumps ahead instead of sleeping.

    python3 -m unittest tests.test_ignition
"""

import unittest

from backend import ignition

DELAY_S = 5.0


class Finished(Exception):
    pass


class FakeKey:
    """The key over time: `on` at the start, then (time, on) changes.
    wait() moves the clock on instead of sleeping, and stops early at a
    change, the way an edge wakes the real pin."""

    def __init__(self, changes, on=True, until=120.0):
        self.t, self.on = 0.0, on
        self.changes = sorted(changes)
        self.until = until
        self.waits = 0

    def clock(self):
        return self.t

    def key_on(self):
        return self.on

    def wait(self, seconds):
        assert 0 <= seconds <= ignition.POLL_S, seconds
        self.waits += 1
        assert self.waits < 10000, "watch() is spinning"
        end = self.t + seconds
        if self.changes and self.changes[0][0] <= end:
            self.t, self.on = self.changes.pop(0)
        else:
            self.t = end
        if self.t >= self.until:
            raise Finished


def power_offs(changes, on=True, dry_run=False, until=120.0, delay_s=DELAY_S):
    """When watch() would power off over `until` seconds of the key doing `changes`."""
    key = FakeKey(changes, on, until)
    times = []

    def key_off():
        times.append(round(key.t, 6))
        return not dry_run

    try:
        ignition.watch(key, key_off, delay_s=delay_s, clock=key.clock, log=lambda msg: None)
    except Finished:
        pass
    return times


class KeyOffTest(unittest.TestCase):
    def test_key_on_the_whole_time(self):
        self.assertEqual(power_offs([]), [])

    def test_key_off_powers_off_after_the_delay(self):
        self.assertEqual(power_offs([(20, False)]), [25.0])

    def test_key_off_at_an_odd_time(self):
        self.assertEqual(power_offs([(20.37, False)]), [25.37])

    def test_acts_on_time_not_at_the_next_poll(self):
        self.assertEqual(power_offs([(20, False)], delay_s=7.3), [27.3])

    def test_cranking_drop_is_ignored(self):
        self.assertEqual(power_offs([(10, False), (11.5, True)]), [])

    def test_drop_just_under_the_delay_is_ignored(self):
        self.assertEqual(power_offs([(10, False), (14.9, True)]), [])

    def test_stuttering_crank_is_ignored(self):
        self.assertEqual(power_offs([(10, False), (10.3, True), (10.6, False),
                                     (11.2, True), (11.4, False), (13, True)]), [])

    def test_crank_then_real_key_off(self):
        self.assertEqual(power_offs([(10, False), (12, True), (60, False)]), [65.0])

    def test_delay_starts_again_after_the_key_comes_back(self):
        # Off for 4 s, on briefly, then off for good: 5 s from the last off.
        self.assertEqual(power_offs([(20, False), (24, True), (24.2, False)]), [29.2])

    def test_powers_off_once(self):
        self.assertEqual(power_offs([(20, False)], until=300), [25.0])

    def test_nothing_until_the_key_has_been_on(self):
        # A bench Pi with the module wired backwards reads "off" forever.
        self.assertEqual(power_offs([], on=False), [])

    def test_key_off_at_start_then_on_then_off(self):
        self.assertEqual(power_offs([(30, True), (40, False)], on=False), [45.0])

    def test_dry_run_says_so_once_per_key_off(self):
        self.assertEqual(power_offs([(20, False), (60, True), (70, False)], dry_run=True),
                         [25.0, 75.0])

    def test_delay_of_zero_acts_straight_away(self):
        key = FakeKey([(20, False)])
        times = []
        try:
            ignition.watch(key, lambda: times.append(key.t) or True, delay_s=0,
                           clock=key.clock, log=lambda msg: None)
        except Finished:
            pass
        self.assertEqual(times, [20])


if __name__ == "__main__":
    unittest.main()
