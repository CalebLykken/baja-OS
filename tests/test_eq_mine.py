"""Off-Pi tests for the equalizer's saved 'Mine' preset.

    python3 -m unittest tests.test_eq_mine
"""

import unittest

try:
    from PyQt6.QtCore import QCoreApplication

    from backend import eq
except ImportError as e:
    raise unittest.SkipTest(f"PyQt6 isn't installed ({e})")

app = QCoreApplication.instance() or QCoreApplication([])


class FakeSettings:
    def __init__(self):
        self.d = {}

    def get(self, k, default=None):
        return self.d.get(k, default)

    def set(self, k, v):
        self.d[k] = v


class MineTests(unittest.TestCase):
    def setUp(self):
        self.s = FakeSettings()
        self.eq = eq.Equalizer(self.s)

    def tune(self):
        self.eq.setGain(0, 3)
        self.eq.setGain(4, 1)

    def test_names_end_with_mine(self):
        self.assertEqual(self.eq.presetNames, list(eq.PRESETS) + ["Mine"])

    def test_hand_tuning_is_saved(self):
        self.tune()
        self.assertEqual(self.s.d["eqMine"], "3,0,0,0,1")

    def test_road_then_mine_restores(self):
        self.tune()
        self.eq.applyPreset("Road")
        self.assertEqual(self.eq.preset, "Road")
        self.eq.applyPreset("Mine")
        self.assertEqual(self.eq.gains, [3, 0, 0, 0, 1])
        self.assertEqual(self.eq.preset, "Mine")

    def test_flat_after_mine(self):
        self.tune()
        self.eq.applyPreset("Flat")
        self.assertEqual(self.eq.preset, "Flat")
        self.assertEqual(self.s.d["eqMine"], "3,0,0,0,1")

    def test_tuning_from_a_preset_is_mine(self):
        self.eq.applyPreset("Road")
        self.eq.setGain(0, 5)           # tunes away from Road: now Mine
        self.assertEqual(self.eq.preset, "Mine")

    def test_mine_survives_restart(self):
        self.tune()
        again = eq.Equalizer(self.s)
        again.applyPreset("Mine")
        self.assertEqual(again.gains, [3, 0, 0, 0, 1])

    def test_corrupt_setting_falls_back_to_flat(self):
        for raw in ("junk", "1,2", "a,b,c,d,e", ""):
            s = FakeSettings()
            s.d["eqMine"] = raw
            e = eq.Equalizer(s)
            e.applyPreset("Road")
            e.applyPreset("Mine")
            self.assertEqual(e.gains, [0, 0, 0, 0, 0], raw)

    def test_loaded_values_are_clamped(self):
        s = FakeSettings()
        s.d["eqMine"] = "99,-99,0,0,0"
        e = eq.Equalizer(s)
        e.applyPreset("Mine")
        self.assertEqual(e.gains, [12, -12, 0, 0, 0])

class UpgradeTests(unittest.TestCase):
    def test_old_hand_tuned_curve_becomes_mine(self):
        s = FakeSettings()
        s.d["eq"] = "3,0,0,0,1"
        e = eq.Equalizer(s)
        self.assertEqual(s.d["eqMine"], "3,0,0,0,1")
        e.applyPreset("Flat")
        e.applyPreset("Mine")
        self.assertEqual(e.gains, [3, 0, 0, 0, 1])

    def test_builtin_preset_is_not_saved_as_mine(self):
        s = FakeSettings()
        s.d["eq"] = "4,2,0,2,3"
        eq.Equalizer(s)
        self.assertNotIn("eqMine", s.d)

    def test_existing_mine_is_kept(self):
        s = FakeSettings()
        s.d["eq"] = "3,0,0,0,1"
        s.d["eqMine"] = "1,1,1,1,1"
        eq.Equalizer(s)
        self.assertEqual(s.d["eqMine"], "1,1,1,1,1")


if __name__ == "__main__":
    unittest.main()
