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


class PanelBacklightTests(unittest.TestCase):
    """Screen off writes 0 to the panel; wake writes the level back."""

    def hw_display(self, current=30):
        d = display_mod.Display()
        run_probe(d, ddc=lambda path: FakeDdc(path, current=current))
        d._pending = None
        d.setBrightness(40)
        self.flush(d)
        return d

    def flush(self, d):
        """Do what the writer thread does with the newest pending value."""
        value, d._pending = d._pending, None
        if value is not None:
            d._write(value)

    def test_screen_off_writes_zero_and_keeps_brightness(self):
        d = self.hw_display()
        d._ddc.sets.clear()
        d.setScreenOff(True)
        self.flush(d)
        self.assertEqual(d._ddc.sets, [0])
        self.assertEqual(d.brightness, 40)

    def test_check_sun_while_off_writes_nothing(self):
        d = self.hw_display()
        d.setScreenOff(True)
        self.flush(d)
        d._ddc.sets.clear()
        d._check_sun()
        self.assertIsNone(d._pending)
        d.setBrightness(60)  # the slider still updates the level, not the panel
        self.assertIsNone(d._pending)
        self.assertEqual(d.brightness, 60)
        self.assertEqual(d._ddc.sets, [])

    def test_wake_writes_the_current_level(self):
        d = self.hw_display()
        d.setScreenOff(True)
        self.flush(d)
        d._ddc.sets.clear()
        d.wake()
        self.flush(d)
        self.assertEqual(d._ddc.sets, [40])

    def test_wake_after_night_change_writes_night_level(self):
        d = self.hw_display()
        d.setScreenOff(True)
        self.flush(d)
        d._night = True
        d._levels[True] = 25
        d.wake()
        self.flush(d)
        self.assertEqual(d._ddc.sets[-1], 25)

    def test_software_dim_screen_off_writes_nothing(self):
        d = display_mod.Display()
        run_probe(d, bus=None)
        d.setScreenOff(True)
        self.assertTrue(d.screenOff)
        self.assertIsNone(d._pending)
        d.wake()
        self.assertFalse(d.screenOff)
        self.assertIsNone(d._pending)

    def test_panel_failure_never_changes_screen_state(self):
        d = self.hw_display()
        with mock.patch.object(d, "_drive_panel", side_effect=OSError("x")):
            d.setScreenOff(True)
        self.assertTrue(d.screenOff)

    def test_probe_reading_zero_keeps_day_level_and_writes_it(self):
        d = display_mod.Display()
        run_probe(d, ddc=lambda path: FakeDdc(path, current=0))
        self.assertTrue(d.hardware)
        self.assertEqual(d._levels[False], 100)
        self.assertEqual(d._pending, 100)

    def test_screen_off_before_probe_settles_dims_after(self):
        d = display_mod.Display()
        d._probing = True
        d.setScreenOff(True)
        run_probe(d)
        self.assertEqual(d._pending, 0)


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


class ProbeRetryTests(unittest.TestCase):
    """The writer thread tries the probe again when a bus exists but failed."""

    def run_writer(self, opens, bus="/dev/i2c-9", before=None):
        """Run the writer thread with PROBE_RETRY_S patched; `opens` is how
        many opens fail before one works (None: all fail). Returns the
        display, the sleep mock and the thread."""
        count = [0]

        def ddc(path):
            count[0] += 1
            if opens is None or count[0] <= opens:
                raise OSError("panel still waking")
            return FakeDdc(path)

        d = display_mod.Display()
        d._probing = True
        if before:
            before(d)
        with mock.patch.object(display_mod, "find_ddc_bus", return_value=bus), \
                mock.patch.object(display_mod, "DdcBrightness", ddc), \
                mock.patch.object(display_mod.time, "sleep") as sleep:
            t = threading.Thread(target=d._writer, daemon=True)
            t.start()
            if opens is None or bus is None:
                t.join(5)
            else:
                for _ in range(500):  # _probe_done is queued to this thread
                    app.processEvents()
                    if d.hardware:
                        break
                    time.sleep(0.01)
            app.processEvents()
        return d, sleep, t

    def test_late_success_turns_hardware_on(self):
        d, sleep, t = self.run_writer(2)
        self.assertTrue(d.hardware)
        self.assertEqual(d.brightness, 30)  # the panel's own level
        self.assertEqual(sleep.call_count, 2)

    def test_all_retries_fail_and_thread_ends(self):
        d, sleep, t = self.run_writer(None)
        self.assertFalse(t.is_alive())
        self.assertFalse(d.hardware)
        self.assertEqual(sleep.call_count, 5)

    def test_no_bus_never_sleeps(self):
        d, sleep, t = self.run_writer(None, bus=None)
        self.assertFalse(t.is_alive())
        sleep.assert_not_called()

    def test_failure_is_announced_once(self):
        d = display_mod.Display()
        d._probing = True
        emitted = []
        d._probe_done.connect(lambda *a: emitted.append(a))
        with mock.patch.object(display_mod, "find_ddc_bus", return_value="/dev/i2c-9"), \
                mock.patch.object(display_mod, "DdcBrightness",
                                  lambda p: FakeDdc(p, fail=True)), \
                mock.patch.object(display_mod.time, "sleep"):
            d._writer()
        app.processEvents()
        self.assertEqual(emitted, [(False, 0, 100)])

    def test_level_set_during_retries_is_written_after_success(self):
        def before(d):
            d.setBrightness(55)  # the panel is not known yet: kept in _levels

        d, sleep, t = self.run_writer(1, before=before)
        self.assertTrue(d.hardware)
        self.assertEqual(d.brightness, 55)
        for _ in range(500):
            if d._ddc.sets:
                break
            time.sleep(0.01)
        self.assertEqual(d._ddc.sets[-1], 55)


class RampTests(unittest.TestCase):
    """The automatic day/night flip fades instead of jumping."""

    def setUp(self):
        self.d = make()
        self.d._levels[False] = 100
        self.d._levels[True] = 40
        self.seen = []
        self.d.brightnessChanged.connect(lambda: self.seen.append(self.d.brightness))

    def sun_at(self, alt):
        return mock.patch.object(display_mod.sun, "altitude", return_value=alt)

    def run_ramp(self, limit=100):
        for _ in range(limit):
            if not self.d._ramp.isActive():
                return
            self.d._ramp_step()  # what the timer does, by hand
        self.fail("ramp never finished")

    def test_forced_check_applies_at_once(self):
        with self.sun_at(-10):
            self.d._check_sun(force=True)
        self.assertEqual(self.seen, [40])
        self.assertFalse(self.d._ramp.isActive())

    def test_flip_fades_monotonically_and_stops(self):
        with self.sun_at(30):
            self.d._check_sun(force=True)
        self.seen.clear()
        with self.sun_at(-10):
            self.d._check_sun()
        self.assertTrue(self.d._night)
        self.assertTrue(self.d._ramp.isActive())
        self.run_ramp()
        steps = [100] + self.seen
        self.assertEqual(steps[-1], 40)
        self.assertEqual(self.d.brightness, 40)
        self.assertGreater(len(self.seen), 1)
        for a, b in zip(steps, steps[1:]):
            self.assertLess(b, a)
            self.assertLessEqual(a - b, 5)  # ceil(60 / 12)
        self.assertFalse(self.d._ramp.isActive())

    def test_fades_back_up_at_dawn(self):
        with self.sun_at(-10):
            self.d._check_sun(force=True)
        self.seen.clear()
        with self.sun_at(30):
            self.d._check_sun()
        self.run_ramp()
        self.assertEqual(self.d.brightness, 100)
        self.assertEqual(self.seen, sorted(self.seen))

    def test_set_brightness_mid_ramp_cancels_and_keeps_value(self):
        with self.sun_at(30):
            self.d._check_sun(force=True)
        with self.sun_at(-10):
            self.d._check_sun()
        self.d._ramp_step()
        self.d.setBrightness(70)
        self.assertFalse(self.d._ramp.isActive())
        self.assertEqual(self.d.brightness, 70)
        self.assertEqual(self.d._levels[True], 70)

    def test_periodic_check_does_not_jump_a_running_ramp(self):
        with self.sun_at(30):
            self.d._check_sun(force=True)
        with self.sun_at(-10):
            self.d._check_sun()
            mid = self.d.brightness
            self.d._check_sun()
        self.assertEqual(self.d.brightness, mid)
        self.assertTrue(self.d._ramp.isActive())

    def test_screen_off_mid_ramp_settles_on_the_target(self):
        with self.sun_at(30):
            self.d._check_sun(force=True)
        with self.sun_at(-10):
            self.d._check_sun()
        self.d.setScreenOff(True)
        self.assertFalse(self.d._ramp.isActive())
        self.assertEqual(self.d.brightness, 40)

    def test_timer_drives_the_ramp(self):
        with mock.patch.object(display_mod, "RAMP_MS", 24), \
                mock.patch.object(display_mod, "RAMP_STEPS", 12):
            d = make()
        d._levels[True] = 40
        with self.sun_at(-10):
            d._check_sun()
        deadline = time.time() + 3
        while d._ramp.isActive() and time.time() < deadline:
            app.processEvents()
        self.assertEqual(d.brightness, 40)
        self.assertFalse(d._ramp.isActive())


if __name__ == "__main__":
    unittest.main()
