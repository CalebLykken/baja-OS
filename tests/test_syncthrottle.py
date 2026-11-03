import unittest

from backend.syncthrottle import SyncThrottle


class Clock:
    def __init__(self):
        self.t = 1000.0

    def __call__(self):
        return self.t


class SyncThrottleTest(unittest.TestCase):
    def setUp(self):
        self.clock = Clock()
        self.th = SyncThrottle(0.25, self.clock)

    def test_first_change_syncs_now(self):
        self.assertEqual(self.th.changed(), "now")
        self.assertFalse(self.th.pending)

    def test_change_soon_after_is_deferred(self):
        self.th.changed()
        self.th.synced()
        self.clock.t += 0.1
        self.assertEqual(self.th.changed(), "later")
        self.assertTrue(self.th.pending)
        self.assertAlmostEqual(self.th.due_in(), 0.15)

    def test_burst_coalesces_to_one_pending(self):
        self.th.synced()
        self.clock.t += 0.1
        self.th.changed()
        due = self.th.due_in()
        for _ in range(3):
            self.clock.t += 0.01
            self.assertEqual(self.th.changed(), "later")
        self.assertTrue(self.th.pending)
        self.assertAlmostEqual(self.th.due_in(), due - 0.03)

    def test_idle_after_sync_is_now_again(self):
        self.th.synced()
        self.clock.t += 0.1
        self.th.changed()
        self.th.synced()
        self.assertFalse(self.th.pending)
        self.clock.t += 0.3
        self.assertEqual(self.th.changed(), "now")

    def test_due_in_never_negative(self):
        self.th.synced()
        self.clock.t += 5
        self.assertEqual(self.th.due_in(), 0.0)


if __name__ == "__main__":
    unittest.main()
