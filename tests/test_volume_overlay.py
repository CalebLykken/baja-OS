"""Off-Pi tests for the knob's volume panel (qml/components/VolumeOverlay.qml):
it starts hidden, a volume or mute change shows it (muted swaps the icon),
it hides itself again after about two seconds, and changes before `ready`
(the saved volume being restored at start-up) show nothing.

The QML runs in its own process, like tests/test_signal_bars.py, with a stub
`media` object in the context.

    python3 -m unittest tests.test_volume_overlay
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
COMPONENT = ROOT / "qml" / "components" / "VolumeOverlay.qml"

SCRIPT = r'''
import json, sys, time
from pathlib import Path
from PyQt6.QtCore import QUrl, QCoreApplication
from PyQt6.QtGui import QGuiApplication
from PyQt6.QtQml import QQmlComponent, QQmlEngine

app = QGuiApplication(sys.argv)
ROOT = Path.cwd()
engine = QQmlEngine()

def make(source):
    component = QQmlComponent(engine)
    component.setData(source, QUrl.fromLocalFile(str(ROOT / "x.qml")))
    obj = component.create()
    if obj is None:
        for error in component.errors():
            print(error.toString(), file=sys.stderr)
        sys.exit(1)
    return obj

def wait(ms):
    end = time.monotonic() + ms / 1000
    while time.monotonic() < end:
        QCoreApplication.processEvents()
        time.sleep(0.005)

media = make(b'import QtQuick\nQtObject { property real volume: 40; property bool muted: false }')
engine.rootContext().setContextProperty("media", media)
# In a window, so that `visible` means what it does on the dash.
window = make(b'import QtQuick\nimport QtQuick.Window\nimport "qml/components"\n'
              b'Window { width: 800; height: 400; visible: true\n'
              b'  property alias overlay: o\n  VolumeOverlay { id: o; ready: false } }')
overlay = window.property("overlay")
wait(100)

def state():
    return [overlay.property("opacity"), overlay.property("visible"), overlay.property("level")]

results = {"start": state()}

media.setProperty("volume", 50)          # before ready: nothing
wait(400)
results["before_ready"] = state()

overlay.setProperty("ready", True)
media.setProperty("volume", 63)
wait(400)
results["shown"] = state()

media.setProperty("muted", True)
wait(50)
results["muted"] = overlay.property("muted")

wait(2400)
results["after"] = state()

overlay.setProperty("quiet", True)       # Music page: its own bar
media.setProperty("volume", 70)
wait(400)
results["quiet"] = state()

print(json.dumps(results))
sys.stdout.flush()
'''


def run():
    return subprocess.run([sys.executable, "-c", SCRIPT], cwd=ROOT,
                          capture_output=True, text=True, timeout=60,
                          env={**os.environ, "QT_QPA_PLATFORM": "offscreen"})


class VolumeOverlayTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        result = run()
        cls.stderr = result.stderr
        cls.returncode = result.returncode
        cls.results = json.loads(result.stdout.strip().splitlines()[-1]) if result.returncode == 0 else {}

    def setUp(self):
        self.assertEqual(self.returncode, 0, self.stderr)

    def test_starts_hidden(self):
        opacity, visible, _ = self.results["start"]
        self.assertEqual(opacity, 0)
        self.assertFalse(visible)

    def test_change_before_ready_shows_nothing(self):
        opacity, visible, _ = self.results["before_ready"]
        self.assertEqual(opacity, 0)
        self.assertFalse(visible)

    def test_volume_change_shows_it_with_the_new_number(self):
        opacity, visible, level = self.results["shown"]
        self.assertGreater(opacity, 0)
        self.assertTrue(visible)
        self.assertEqual(level, 63)

    def test_mute_is_reported(self):
        self.assertTrue(self.results["muted"])

    def test_hides_itself_again(self):
        opacity, visible, _ = self.results["after"]
        self.assertEqual(opacity, 0)
        self.assertFalse(visible)

    def test_quiet_page_shows_nothing(self):
        opacity, visible, _ = self.results["quiet"]
        self.assertEqual(opacity, 0)
        self.assertFalse(visible)

    def test_icon_follows_mute_and_nothing_loops(self):
        text = COMPONENT.read_text(encoding="utf-8")
        self.assertIn('overlay.muted ? "volume_off" : "volume"', text)
        for word in ("Timer", "repeat", "loops", "MouseArea", "TapHandler", "PointHandler"):
            self.assertNotIn(word, text)


if __name__ == "__main__":
    unittest.main()
