"""DemoDrive: the scripted simulated drive. Plain Python, no Qt."""
import math
import os
import subprocess
import sys
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

from backend.demo import GEARS, DemoDrive  # noqa: E402

DT = 0.2
SEEDS = (1, 2, 3, 42)
KEYS = {"speed", "rpm", "gear", "throttle", "boost", "coolant", "intake"}


def run(seed, seconds, limit=None):
    d = DemoDrive(seed=seed)
    return [d.step(DT, limit) for _ in range(int(seconds / DT))]


class DemoDriveTest(unittest.TestCase):
    def test_cold_start_state(self):
        s = DemoDrive(seed=1).step(DT)
        self.assertEqual(set(s), KEYS)
        self.assertEqual(s["speed"], 0)
        self.assertAlmostEqual(s["rpm"], 800, delta=50)
        self.assertEqual(s["gear"], 1)
        self.assertAlmostEqual(s["boost"], -18, delta=0.5)
        self.assertAlmostEqual(s["coolant"], 120, delta=1)
        self.assertAlmostEqual(s["intake"], 72, delta=1)

    def test_warm_up(self):
        for seed in SEEDS:
            r = run(seed, 1200)
            for i, s in enumerate(r):
                if i * DT <= 90:
                    self.assertLess(s["coolant"], 150, (seed, i))
            first155 = next(i for i, s in enumerate(r) if s["coolant"] >= 155)
            self.assertLessEqual(first155 * DT, 300)
            for s in r[int(780 / DT):]:
                self.assertTrue(190 <= s["coolant"] <= 200, (seed, s["coolant"]))

    def test_launch_every_cycle(self):
        for seed in SEEDS:
            armed = None
            times = []
            for i, s in enumerate(run(seed, 900)):
                t = i * DT
                if s["speed"] < 1:
                    armed = t
                elif armed is not None and s["speed"] >= 60:
                    times.append(t - armed)
                    armed = None
            self.assertGreaterEqual(len(times), 3, seed)
            self.assertTrue(all(x < 30 for x in times), times)
            self.assertTrue(any(6 <= x <= 10 for x in times), times)

    def test_launch_is_full_throttle_and_rpm_drops_at_shifts(self):
        d = DemoDrive(seed=1)
        prev = d.step(DT)
        drops = full = 0
        for _ in range(int(60 / DT)):
            s = d.step(DT)
            if s["gear"] > prev["gear"]:
                self.assertLess(s["rpm"], prev["rpm"])
                drops += 1
            if s["throttle"] >= 0.99:
                full += 1
            prev = s
        self.assertGreaterEqual(drops, 2)
        self.assertGreater(full, 5 / DT)

    def test_real_stops(self):
        for seed in SEEDS:
            streak = longest = 0
            for s in run(seed, 900):
                if s["speed"] == 0:
                    self.assertLess(s["rpm"], 900)
                    streak += 1
                    longest = max(longest, streak)
                else:
                    streak = 0
            self.assertGreaterEqual(longest * DT, 4, seed)

    def test_speed_is_smooth(self):
        for seed in SEEDS:
            prev = 0.0
            for s in run(seed, 900):
                self.assertLessEqual(abs(s["speed"] - prev), 6)
                self.assertGreaterEqual(s["speed"], 0)
                prev = s["speed"]

    def test_rpm_agrees_with_speed_and_gear(self):
        for seed in SEEDS:
            for s in run(seed, 900):
                if s["speed"] < 8:
                    continue
                base = s["speed"] / GEARS[s["gear"] - 1] * 1000
                self.assertAlmostEqual(s["rpm"], base, delta=650)

    def test_ranges(self):
        for seed in SEEDS:
            for s in run(seed, 900):
                for k, v in s.items():
                    self.assertTrue(math.isfinite(v), k)
                self.assertTrue(800 <= s["rpm"] <= 6800)
                self.assertIn(s["gear"], (1, 2, 3, 4, 5))
                self.assertTrue(0 <= s["throttle"] <= 1)
                self.assertTrue(-18.5 <= s["boost"] <= 14.5)
                self.assertLessEqual(s["boost"], 15)
                self.assertLessEqual(s["coolant"], 205)
                self.assertLess(s["speed"], 100)

    def test_intake_rises_with_boost(self):
        r = run(1, 900)
        self.assertGreater(max(s["boost"] for s in r), 5)
        self.assertGreater(max(s["intake"] for s in r), 85)
        self.assertLess(min(s["intake"] for s in r), 75)

    def test_same_seed_same_drive(self):
        self.assertEqual(run(7, 120), run(7, 120))
        self.assertNotEqual(run(7, 120), run(8, 120))

    def test_limit_pulls_speed_down(self):
        d = DemoDrive(seed=1)
        t = 0.0
        while d.step(DT)["speed"] < 50:
            t += DT
            self.assertLess(t, 60)
        s = None
        for _ in range(int(8 / DT)):
            s = d.step(DT, limit_mph=25)
        self.assertLess(s["speed"], 29)
        self.assertGreater(s["speed"], 15)
        # and without a limit the script carries on regardless
        for _ in range(int(60 / DT)):
            s = d.step(DT)
        self.assertTrue(math.isfinite(s["speed"]))

    def test_limit_never_wedges_the_script(self):
        for s in run(1, 600, limit=15):
            self.assertLess(s["speed"], 22)

    def test_import_has_no_qt(self):
        code = "import sys, backend.demo; sys.exit('PyQt6' in sys.modules)"
        r = subprocess.run([sys.executable, "-c", code], cwd=ROOT)
        self.assertEqual(r.returncode, 0)


if __name__ == "__main__":
    unittest.main()
