"""Off-Pi tests for backend/powerlog.py: reading the power chip's report and
the firmware's flags, picking kernel lines, and dropping old logs.

    python3 -m unittest tests.test_powerlog
"""

import os
import tempfile
import unittest
from pathlib import Path

from backend.powerlog import KERNEL_WORTH_KEEPING, flag_names, parse_pmic, prune

PMIC = """\
     3V7_WL_SW_A current(0)=0.10000000A
       VDD_CORE_A current(7)=2.00000000A
   HDMI_A current(13)=0.01000000A
     3V7_WL_SW_V volt(8)=3.70000000V
       VDD_CORE_V volt(15)=0.80000000V
   HDMI_V volt(23)=5.00000000V
        EXT5V_V volt(24)=4.81250000V
         BATT_V volt(25)=0.00000000V
"""


class ParseTest(unittest.TestCase):
    def test_input_volts_and_watts(self):
        volts, watts = parse_pmic(PMIC)
        self.assertAlmostEqual(volts, 4.8125)
        self.assertAlmostEqual(watts, 0.1 * 3.7 + 2 * 0.8 + 0.01 * 5, places=2)

    def test_nothing_to_read(self):
        self.assertEqual(parse_pmic(""), (None, None))


class FlagsTest(unittest.TestCase):
    def test_now_and_since_boot(self):
        self.assertEqual(flag_names(0x50001),
                         "under-voltage now, under-voltage since boot, throttled since boot")

    def test_none(self):
        self.assertEqual(flag_names(0), "none")


class KernelTest(unittest.TestCase):
    def test_keeps_what_points_at_power_or_the_screen(self):
        for line in ("hwmon hwmon2: Undervoltage detected!",
                     "usb 3-1: USB disconnect, device number 4",
                     "usb 1-1-port2: over-current condition",
                     "vc4-drm axi:gpu: [drm] flip_done timed out"):
            self.assertTrue(KERNEL_WORTH_KEEPING.search(line), line)

    def test_drops_the_rest(self):
        self.assertFalse(KERNEL_WORTH_KEEPING.search("EXT4-fs (mmcblk0p2): re-mounted"))


class PruneTest(unittest.TestCase):
    def test_keeps_the_newest(self):
        with tempfile.TemporaryDirectory() as d:
            for i in range(4):
                f = Path(d, f"{i}.log")
                f.write_text("x")
                os.utime(f, (i, i))
            prune(d, keep=2)
            self.assertEqual(sorted(p.name for p in Path(d).iterdir()), ["2.log", "3.log"])


if __name__ == "__main__":
    unittest.main()
