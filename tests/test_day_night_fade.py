"""Off-Pi tests for qml/components/DayNightFade.qml with the real Theme
singleton: hidden at creation; nothing happens on a flip before it is armed;
once armed, a flip starts at full opacity in the colour of the scheme just
left and fades to nothing in about half a second; Main.qml arms it after the
splash. Runs in a subprocess because other test modules hold a
QCoreApplication.

    python3 -m unittest tests.test_day_night_fade
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
FADE = ROOT / "qml" / "components" / "DayNightFade.qml"
MAIN = ROOT / "qml" / "Main.qml"

SCRIPT = r'''
import json, sys
from pathlib import Path
from PyQt6.QtCore import QEventLoop, QMetaObject, Q_ARG, Qt, QTimer, QUrl
from PyQt6.QtGui import QGuiApplication
from PyQt6.QtQml import QQmlComponent, QQmlEngine
from PyQt6.QtQuick import QQuickItem

ROOT = Path(sys.argv[1])
app = QGuiApplication(sys.argv)
engine = QQmlEngine()

QML = """import QtQuick
import QtQuick.Window
import "qml/components"
Window {
    width: 1280; height: 800; visible: true
    DayNightFade { objectName: "fade"; anchors.fill: parent }
    Item {
        objectName: "probe"
        property color lightBg: Theme.lightStyles[Theme.style].bg
        property color darkBg: Theme.base.bg
    }
    Item {
        objectName: "driver"
        function setDark(v) { Theme.dark = v }
        function setStyle(s) { Theme.style = s }
    }
}
"""

component = QQmlComponent(engine)
component.setData(QML.encode(), QUrl.fromLocalFile(str(ROOT / "x.qml")))
root = component.create()
if root is None:
    print([e.toString() for e in component.errors()])
    sys.exit(1)


def wait(ms):
    loop = QEventLoop()
    QTimer.singleShot(ms, loop.quit)
    loop.exec()


def invoke(item, name, *args):
    QMetaObject.invokeMethod(item, name, Qt.ConnectionType.DirectConnection,
                             *[Q_ARG("QVariant", a) for a in args])


def colour(item):
    return item.property("color").name()


fade = root.findChild(QQuickItem, "fade")
probe = root.findChild(QQuickItem, "probe")
driver = root.findChild(QQuickItem, "driver")
out = {}
wait(50)
invoke(driver, "setStyle", "trail")
out["light_bg"] = probe.property("lightBg").name()
out["dark_bg"] = probe.property("darkBg").name()
out["created_visible"] = fade.property("visible")
out["created_opacity"] = fade.property("opacity")

# Before armed: a flip (the start-up setting) shows nothing.
invoke(driver, "setDark", False)
wait(50)
out["unarmed_visible"] = fade.property("visible")
out["unarmed_opacity"] = fade.property("opacity")

# Armed: the next flip to night starts at full opacity in the day colour.
fade.setProperty("armed", True)
invoke(driver, "setDark", True)
out["night_opacity_at_once"] = fade.property("opacity")
out["night_visible_at_once"] = fade.property("visible")
out["night_colour"] = colour(fade)
wait(150)
out["night_opacity_mid"] = fade.property("opacity")
wait(650)
out["night_opacity_end"] = fade.property("opacity")
out["night_visible_end"] = fade.property("visible")

# And back to day: the night colour is held, then it fades away.
invoke(driver, "setDark", False)
out["day_opacity_at_once"] = fade.property("opacity")
out["day_colour"] = colour(fade)
wait(700)
out["day_opacity_end"] = fade.property("opacity")
out["day_visible_end"] = fade.property("visible")
print(json.dumps(out))
'''


class DayNightFadeTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        env = dict(os.environ, QT_QPA_PLATFORM="offscreen")
        result = subprocess.run([sys.executable, "-c", SCRIPT, str(ROOT)], cwd=ROOT,
                                capture_output=True, text=True, timeout=60, env=env)
        if result.returncode != 0:
            raise AssertionError(result.stdout + result.stderr)
        cls.out = json.loads(result.stdout.strip().splitlines()[-1])

    def test_not_drawn_at_creation(self):
        self.assertFalse(self.out["created_visible"])
        self.assertEqual(self.out["created_opacity"], 0)

    def test_a_flip_before_armed_shows_nothing(self):
        self.assertFalse(self.out["unarmed_visible"])
        self.assertEqual(self.out["unarmed_opacity"], 0)

    def test_flip_to_night_starts_at_full_opacity_in_the_day_colour(self):
        self.assertAlmostEqual(self.out["night_opacity_at_once"], 1.0)
        self.assertTrue(self.out["night_visible_at_once"])
        self.assertEqual(self.out["night_colour"], self.out["light_bg"])

    def test_it_fades_out_and_is_not_drawn_at_the_end(self):
        self.assertLess(self.out["night_opacity_mid"], 1.0)
        self.assertGreater(self.out["night_opacity_mid"], 0.0)
        self.assertEqual(self.out["night_opacity_end"], 0)
        self.assertFalse(self.out["night_visible_end"])

    def test_flip_to_day_holds_the_night_colour_then_fades(self):
        self.assertAlmostEqual(self.out["day_opacity_at_once"], 1.0)
        self.assertEqual(self.out["day_colour"], self.out["dark_bg"])
        self.assertEqual(self.out["day_opacity_end"], 0)
        self.assertFalse(self.out["day_visible_end"])

    def test_source_takes_no_taps_and_has_no_timer(self):
        src = FADE.read_text()
        self.assertNotIn("MouseArea {", src)
        self.assertNotIn("Timer", src)
        self.assertNotIn("running: true", src)
        self.assertIn("property bool armed: false", src)

    def test_main_arms_it_after_the_splash_and_places_it_under_the_volume_panel(self):
        src = MAIN.read_text()
        self.assertEqual(src.count("DayNightFade {"), 1)
        self.assertLess(src.index("DayNightFade {"), src.index("VolumeOverlay {"))
        self.assertGreater(src.index("DayNightFade {"), src.index("Toast {"))
        body = src.split("Timer {\n        interval: 600", 1)[1].split("\n    }", 1)[0]
        self.assertIn("running: !splash.visible && !dayNightFade.armed", body)
        self.assertIn("dayNightFade.armed = true", body)

    def test_qmldir_registers_it(self):
        qmldir = (ROOT / "qml" / "components" / "qmldir").read_text()
        self.assertIn("DayNightFade 1.0 DayNightFade.qml", qmldir)


if __name__ == "__main__":
    unittest.main()
