import threading
import time
import unittest
from unittest import mock

from PyQt6.QtCore import QCoreApplication

from backend import display as display_mod

app = QCoreApplication.instance() or QCoreApplication([])


class FakeSettings:
    def __init__(self):
        self.data = {}
        self.sets = []

    def get(self, key, default=None):
        return self.data.get(key, default)

    def set(self, key, value):
        self.sets.append(key)
        self.data[key] = value


def make(settings=None):
    with mock.patch.object(display_mod, "find_ddc_bus", return_value=None):
        return display_mod.Display(settings)


class ScreenOffTests(unittest.TestCase):
    def test_starts_on(self):
        self.assertFalse(make().screenOff)

    def test_off_and_wake_emit_once_each(self):
        d = make()
        seen = []
        d.screenOffChanged.connect(lambda: seen.append(d.screenOff))
        d.setScreenOff(True)
        d.setScreenOff(True)
        self.assertEqual(seen, [True])
        d.wake()
        d.wake()
        self.assertEqual(seen, [True, False])

    def test_wake_when_on_is_noop(self):
        d = make()
        seen = []
        d.screenOffChanged.connect(lambda: seen.append(1))
        with mock.patch.object(d, "_drive_panel") as drive:
            d.wake()
        self.assertEqual(seen, [])
        drive.assert_not_called()

    def test_drive_panel_called_on_each_change(self):
        d = make()
        with mock.patch.object(d, "_drive_panel") as drive:
            d.setScreenOff(True)
            d.setScreenOff(True)
            d.wake()
        self.assertEqual([c.args for c in drive.call_args_list], [(True,), (False,)])

    def test_drive_panel_exception_swallowed(self):
        d = make()
        with mock.patch.object(d, "_drive_panel", side_effect=RuntimeError("boom")):
            d.setScreenOff(True)
        self.assertTrue(d.screenOff)

    def test_not_persisted(self):
        s = FakeSettings()
        d = make(s)
        d.setScreenOff(True)
        d.wake()
        self.assertEqual(s.sets, [])
        d.setScreenOff(True)
        self.assertFalse(make(s).screenOff)


class BrightnessWithoutDdcTests(unittest.TestCase):
    def test_software_dim(self):
        s = FakeSettings()
        d = make(s)
        self.assertFalse(d.hardware)
        self.assertEqual(d.brightness, 100)
        d.setBrightness(50)
        self.assertEqual(d.brightness, 50)
        d.setBrightness(1)
        self.assertEqual(d.brightness, 5)
        self.assertIn("brightnessDay", s.sets)

    def test_screen_off_leaves_brightness(self):
        d = make()
        d.setBrightness(60)
        d.setScreenOff(True)
        d.wake()
        self.assertEqual(d.brightness, 60)


class FakeDdc:
    def __init__(self, path, current=30, maximum=100, fail=False):
        if fail:
            raise OSError("no reply")
        self.cur, self.max, self.sets = current, maximum, []

    def get(self):
        return self.cur, self.max

    def set(self, value):
        self.sets.append(value)


def run_probe(d, bus="/dev/i2c-9", ddc=FakeDdc):
    """Run the probe synchronously, as start() would on the writer thread."""
    d._probing = True
    with mock.patch.object(display_mod, "find_ddc_bus", return_value=bus), \
            mock.patch.object(display_mod, "DdcBrightness", ddc):
        d._probe()


class ProbeTests(unittest.TestCase):
    def test_constructor_does_no_hardware_io(self):
        with mock.patch.object(display_mod, "find_ddc_bus") as find:
            d = display_mod.Display()
        find.assert_not_called()
        self.assertFalse(d.hardware)
        self.assertEqual(d.brightness, 100)

    def test_overlay_stays_clear_while_probing(self):
        d = display_mod.Display()
        d._probing = True
        d.setBrightness(40)
        self.assertEqual(d.brightness, 100)
        self.assertFalse(d.hardware)

    def test_success_adopts_panel_level(self):
        seen = []
        d = display_mod.Display()
        d.hardwareChanged.connect(lambda: seen.append(d.hardware))
        run_probe(d)
        self.assertTrue(d.hardware)
        self.assertEqual(seen, [True])
        self.assertEqual(d.brightness, 30)
        self.assertEqual(d._levels[False], 30)  # day level follows the panel

    def test_saved_day_level_wins_over_panel(self):
        s = FakeSettings()
        s.data["brightnessDay"] = 70
        d = display_mod.Display(s)
        run_probe(d)
        self.assertEqual(d.brightness, 70)
        self.assertEqual(d._pending, 70)  # queued for the writer thread

    def test_oserror_falls_back_to_software_dim(self):
        d = display_mod.Display()
        run_probe(d, ddc=lambda path: FakeDdc(path, fail=True))
        self.assertFalse(d.hardware)
        self.assertIsNone(d._ddc)
        self.assertEqual(d.brightness, 100)
        d.setBrightness(50)
        self.assertEqual(d.brightness, 50)

    def test_no_bus_is_software_dim(self):
        d = display_mod.Display()
        run_probe(d, bus=None)
        self.assertFalse(d.hardware)
        self.assertEqual(d.brightness, 100)

    def test_change_before_probe_is_applied_after(self):
        d = display_mod.Display()
        d._probing = True
        d.setBrightness(55)
        self.assertEqual(d.brightness, 100)
        run_probe(d)
        self.assertEqual(d.brightness, 55)
        self.assertEqual(d._pending, 55)  # queued for the DDC write

    def test_change_before_failed_probe_is_kept(self):
        d = display_mod.Display()
        d._probing = True
        d.setBrightness(55)
        run_probe(d, bus=None)
        self.assertEqual(d.brightness, 55)

    def test_zero_maximum_is_software_dim(self):
        made = []

        def ddc(path):
            made.append(FakeDdc(path, current=50, maximum=0))
            made[0].closed = False
            made[0].close = lambda: setattr(made[0], "closed", True)
            return made[0]

        d = display_mod.Display()
        run_probe(d, ddc=ddc)
        self.assertFalse(d.hardware)
        self.assertIsNone(d._ddc)
        self.assertTrue(made[0].closed)
        self.assertEqual(d.brightness, 100)
        d.setBrightness(50)
        self.assertEqual(d.brightness, 50)
        self.assertEqual(made[0].sets, [])

    def test_current_above_maximum_is_clamped(self):
        d = display_mod.Display()
        run_probe(d, ddc=lambda path: FakeDdc(path, current=0xFFFF, maximum=100))
        self.assertTrue(d.hardware)
        self.assertEqual(d.brightness, 100)

    def test_ioctl_failure_closes_the_fd(self):
        with mock.patch.object(display_mod.os, "open", return_value=7), \
                mock.patch.object(display_mod.os, "close") as close, \
                mock.patch.object(display_mod.fcntl, "ioctl", side_effect=OSError("no")):
            with self.assertRaises(OSError):
                display_mod.DdcBrightness("/dev/i2c-9")
        close.assert_called_once_with(7)

    def test_close_ignores_oserror(self):
        with mock.patch.object(display_mod.os, "open", return_value=7), \
                mock.patch.object(display_mod.fcntl, "ioctl"):
            ddc = display_mod.DdcBrightness("/dev/i2c-9")
        with mock.patch.object(display_mod.os, "close", side_effect=OSError("bad")):
            ddc.close()


class WriteFailureTests(unittest.TestCase):
    def hw_display(self):
        d = display_mod.Display()
        run_probe(d)
        d._pending = None
        return d

    def test_write_retries_a_nak(self):
        d = self.hw_display()
        calls = []

        def flaky(value):
            calls.append(value)
            if len(calls) < 3:
                raise OSError("nak")

        d._ddc.set = flaky
        with mock.patch.object(display_mod.time, "sleep"):
            d._write(40)
        self.assertEqual(calls, [40, 40, 40])
        self.assertEqual(d._written, 40)

    def test_failed_write_is_resent_by_the_next_apply(self):
        d = self.hw_display()
        d._ddc.set = mock.Mock(side_effect=OSError("nak"))
        d._apply(40)
        self.assertEqual(d._pending, 40)
        d._pending = None
        with mock.patch.object(display_mod.time, "sleep") as nap:
            d._write(40)
        self.assertEqual(d._ddc.set.call_count, display_mod.DDC_TRIES)
        self.assertEqual(nap.call_count, display_mod.DDC_TRIES - 1)
        self.assertEqual(d._written, 30)  # the panel still shows the old level
        d._apply(40)  # same level again: must be queued, not dropped
        self.assertEqual(d._pending, 40)

    def test_accepted_write_is_not_resent(self):
        d = self.hw_display()
        d._apply(40)
        d._pending = None
        d._write(40)
        d._apply(40)
        self.assertIsNone(d._pending)

    def test_periodic_check_resends_stale_level(self):
        d = self.hw_display()
        d._levels[False] = 40
        d._brightness = 40  # UI says 40, the panel never took it
        d._check_sun()
        self.assertEqual(d._pending, 40)

    def test_odd_exception_is_retried_and_writer_survives(self):
        d = self.hw_display()
        calls = []

        def odd(value):
            calls.append(value)
            if len(calls) == 1:
                raise RuntimeError("odd")

        d._ddc.set = odd
        d._probe = lambda: None  # the thread under test starts at the write loop
        with mock.patch.object(display_mod.time, "sleep"):
            d._write(40)
        self.assertEqual(calls, [40, 40])
        self.assertEqual(d._written, 40)
        t = threading.Thread(target=d._writer, daemon=True)
        t.start()
        d._apply(60)
        for _ in range(200):
            if 60 in calls:
                break
            time.sleep(0.01)
        self.assertTrue(t.is_alive())
        self.assertEqual(calls[-1], 60)
        d._apply(70)
        for _ in range(200):
            if 70 in calls:
                break
            time.sleep(0.01)
        self.assertEqual(calls[-1], 70)


if __name__ == "__main__":
    unittest.main()
