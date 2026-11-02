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


if __name__ == "__main__":
    unittest.main()
