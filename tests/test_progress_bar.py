"""Off-Pi tests for qml/components/ProgressBar.qml: it sweeps back to the
start when the value falls from far along to near zero, and snaps otherwise.
Runs in a subprocess because other test modules hold a QCoreApplication.

    python3 -m unittest tests.test_progress_bar
"""

import json
import os
import subprocess
import sys
import unittest
from pathlib import Path

try:
    import PyQt6.QtQml  # noqa: F401
except ImportError:
    raise unittest.SkipTest("PyQt6 isn't installed")

ROOT = Path(__file__).resolve().parent.parent

SCRIPT = r'''
import json, sys
from pathlib import Path
from PyQt6.QtCore import QEventLoop, QMetaObject, QObject, QTimer, QUrl
from PyQt6.QtGui import QGuiApplication
from PyQt6.QtQml import QQmlComponent, QQmlEngine

ROOT = Path(sys.argv[1])
app = QGuiApplication(sys.argv)
engine = QQmlEngine()


def make(initial):
    component = QQmlComponent(engine)
    component.setData(
        ('import QtQuick\nimport "qml/components"\nProgressBar { width: 200; value: %s }' % initial).encode(),
        QUrl.fromLocalFile(str(ROOT / "x.qml")))
    obj = component.create()
    if obj is None:
        print([e.toString() for e in component.errors()])
        sys.exit(1)
    return obj


def wait(ms):
    loop = QEventLoop()
    QTimer.singleShot(ms, loop.quit)
    loop.exec()


def shown(obj):
    return obj.property("shown")


out = {}
obj = make(0.4)
out["initial"] = shown(obj)

obj = make(0.30)
obj.setProperty("value", 0.31)
out["small_step"] = shown(obj)

obj = make(0.9)
obj.setProperty("value", 0.4)
out["backward"] = shown(obj)

obj = make(0.2)
obj.setProperty("value", 0.95)
out["forward"] = shown(obj)

obj = make(0.95)
obj.setProperty("value", 0.0)
out["sweep_start"] = shown(obj)
wait(500)
out["sweep_end"] = shown(obj)

obj = make(0.95)
obj.setProperty("value", 0.0)
wait(30)
obj.setProperty("value", 0.01)
out["interrupt_now"] = shown(obj)
wait(500)
out["interrupt_later"] = shown(obj)

obj = make(0.5)
obj.setProperty("value", 1.5)
out["above"] = shown(obj)
obj.setProperty("value", -0.5)
wait(500)
out["below"] = shown(obj)

def flash(obj):
    return obj.findChild(QObject, "seekFlash")


obj = make(0.4)
out["fresh_flash"] = flash(obj).property("opacity")

# Value changes alone never flash, however big or small.
obj = make(0.2)
obj.setProperty("value", 0.6)
out["fwd_value_flash"] = flash(obj).property("opacity")

obj = make(0.9)
obj.setProperty("value", 0.4)
out["back_value_flash"] = flash(obj).property("opacity")

obj = make(0.3)
obj.setProperty("value", 0.0)
out["restart_value_flash"] = flash(obj).property("opacity")

obj = make(0.0)
for i in range(1, 11):
    obj.setProperty("value", i / 10.0)
    out["tick_flash_%d" % i] = flash(obj).property("opacity")

obj = make(0.95)
obj.setProperty("value", 0.0)
out["sweep_flash"] = flash(obj).property("opacity")

# flashSeek() flashes once without moving the fill, then clears.
obj = make(0.6)
f = flash(obj)
QMetaObject.invokeMethod(obj, "flashSeek")
out["seek_flash_now"] = f.property("opacity")
out["seek_flash_vis_now"] = f.property("visible")
out["seek_flash_shown"] = shown(obj)
wait(500)
out["seek_flash_later"] = f.property("opacity")
out["seek_flash_vis_later"] = f.property("visible")

obj = make(0.2)
obj.setProperty("visible", False)
QMetaObject.invokeMethod(obj, "flashSeek")
out["hidden_flash"] = flash(obj).property("opacity")

print(json.dumps(out))
'''


class ProgressBarTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        env = dict(os.environ, QT_QPA_PLATFORM="offscreen")
        result = subprocess.run([sys.executable, "-c", SCRIPT, str(ROOT)], cwd=ROOT,
                                capture_output=True, text=True, timeout=60, env=env)
        if result.returncode != 0:
            raise AssertionError(result.stdout + result.stderr)
        cls.out = json.loads(result.stdout.strip().splitlines()[-1])

    def test_initial_value_shows_at_once(self):
        self.assertAlmostEqual(self.out["initial"], 0.4)

    def test_small_step_snaps(self):
        self.assertAlmostEqual(self.out["small_step"], 0.31)

    def test_backward_jump_snaps(self):
        self.assertAlmostEqual(self.out["backward"], 0.4)

    def test_forward_jump_snaps(self):
        self.assertAlmostEqual(self.out["forward"], 0.95)

    def test_new_track_sweeps_to_start(self):
        self.assertGreater(self.out["sweep_start"], 0.5)
        self.assertEqual(self.out["sweep_end"], 0.0)

    def test_tick_during_sweep_snaps_and_stays(self):
        self.assertAlmostEqual(self.out["interrupt_now"], 0.01)
        self.assertAlmostEqual(self.out["interrupt_later"], 0.01)

    def test_values_are_clamped(self):
        self.assertEqual(self.out["above"], 1.0)
        self.assertEqual(self.out["below"], 0.0)

    def test_fresh_bar_has_no_flash(self):
        self.assertEqual(self.out["fresh_flash"], 0)

    def test_value_changes_never_flash(self):
        self.assertEqual(self.out["fwd_value_flash"], 0)
        self.assertEqual(self.out["back_value_flash"], 0)
        self.assertEqual(self.out["restart_value_flash"], 0)

    def test_one_second_ticks_on_a_short_track_do_not_flash(self):
        for i in range(1, 11):
            self.assertEqual(self.out["tick_flash_%d" % i], 0)

    def test_new_track_sweep_does_not_flash(self):
        self.assertEqual(self.out["sweep_flash"], 0)

    def test_flash_seek_flashes_without_moving_then_clears(self):
        self.assertGreater(self.out["seek_flash_now"], 0)
        self.assertTrue(self.out["seek_flash_vis_now"])
        self.assertAlmostEqual(self.out["seek_flash_shown"], 0.6)
        self.assertEqual(self.out["seek_flash_later"], 0)
        self.assertFalse(self.out["seek_flash_vis_later"])

    def test_invisible_bar_does_not_flash(self):
        self.assertEqual(self.out["hidden_flash"], 0)

    def test_music_page_flashes_only_on_seek_release(self):
        src = (ROOT / "qml" / "pages" / "MusicPage.qml").read_text()
        self.assertEqual(src.count("flashSeek()"), 1)
        released = src[src.index("onReleased"):]
        self.assertIn("seekBar.flashSeek()", released[:300])


if __name__ == "__main__":
    unittest.main()
