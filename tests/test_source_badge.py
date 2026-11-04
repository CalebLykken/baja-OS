"""Off-Pi tests for the source badge's change animation (qml/components/
SourceBadge.qml): a real change of source swaps the text and icon through a
short fade and slide, and nothing animates at load or on a repeat.

The QML runs in its own process, like tests/test_errors.py, so the QCoreApplication
other test modules create at import time doesn't get in the way.

    python3 -m unittest tests.test_source_badge
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
from PyQt6.QtCore import QEventLoop, QObject, QTimer, QUrl, pyqtProperty, pyqtSignal
from PyQt6.QtGui import QGuiApplication
from PyQt6.QtQml import QQmlComponent, QQmlEngine

app = QGuiApplication(sys.argv)
ROOT = Path.cwd()


class Media(QObject):
    sourceChanged = pyqtSignal()

    def __init__(self):
        super().__init__()
        self._source = "local"
        self._name = ""

    @pyqtProperty(str, notify=sourceChanged)
    def source(self):
        return self._source

    @pyqtProperty(str, notify=sourceChanged)
    def sourceName(self):
        return self._name

    def set(self, source, name=""):
        self._source, self._name = source, name
        self.sourceChanged.emit()


def wait(ms):
    loop = QEventLoop()
    QTimer.singleShot(ms, loop.quit)
    loop.exec()


media = Media()
engine = QQmlEngine()
engine.rootContext().setContextProperty("media", media)
component = QQmlComponent(engine)
component.setData(b'import QtQuick\nimport "qml/components"\nSourceBadge {}',
                  QUrl.fromLocalFile(str(ROOT / "x.qml")))
if component.isError():
    for error in component.errors():
        print(error.toString(), file=sys.stderr)
    sys.exit(1)
obj = component.create()
if obj is None:
    for error in component.errors():
        print(error.toString(), file=sys.stderr)
    sys.exit(1)

results = {}
results["initial_text"] = obj.property("shownText")
results["initial_opacity"] = obj.property("opacity")
wait(50)
results["initial_opacity_50ms"] = obj.property("opacity")

# Case 2: a real change to the phone. Nothing swaps until the swap runs.
media.set("phone", "Caleb's iPhone")
results["change_immediate_text"] = obj.property("shownText")
wait(60)
results["change_mid_opacity"] = obj.property("opacity")
wait(390)
results["change_done_text"] = obj.property("shownText")
results["change_done_icon"] = obj.property("shownIcon")
results["change_done_opacity"] = obj.property("opacity")

# Case 3: the same source again, a status refresh with identical values.
media.set("phone", "Caleb's iPhone")
wait(60)
results["repeat_opacity"] = obj.property("opacity")
results["repeat_text"] = obj.property("shownText")

# Case 4: two changes 30 ms apart must land on the latest one.
media.set("spotify", "Spotify")
wait(30)
media.set("local", "")
wait(500)
results["double_text"] = obj.property("shownText")
results["double_icon"] = obj.property("shownIcon")
results["double_opacity"] = obj.property("opacity")

print(json.dumps(results))
sys.stdout.flush()
'''


def run():
    return subprocess.run([sys.executable, "-c", SCRIPT], cwd=ROOT,
                          capture_output=True, text=True, timeout=60,
                          env={**os.environ, "QT_QPA_PLATFORM": "offscreen"})


class SourceBadgeTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        result = run()
        cls.stderr = result.stderr
        cls.returncode = result.returncode
        cls.results = json.loads(result.stdout.strip().splitlines()[-1]) if result.returncode == 0 else {}

    def setUp(self):
        self.assertEqual(self.returncode, 0, self.stderr)

    def test_load_shows_source_without_animating(self):
        self.assertEqual(self.results["initial_text"], "On this Pi")
        self.assertEqual(self.results["initial_opacity"], 1.0)
        self.assertEqual(self.results["initial_opacity_50ms"], 1.0)

    def test_change_waits_for_the_fade_out_then_swaps(self):
        # The old text stays until the fade out has run.
        self.assertEqual(self.results["change_immediate_text"], "On this Pi")
        # Partway through the fade out, the badge is dimming.
        self.assertLess(self.results["change_mid_opacity"], 1.0)
        # After both halves, the new text and icon are in and fully opaque.
        self.assertEqual(self.results["change_done_text"], "Caleb's iPhone")
        self.assertEqual(self.results["change_done_icon"], "bluetooth")
        self.assertEqual(self.results["change_done_opacity"], 1.0)

    def test_repeat_of_same_source_does_not_dip(self):
        self.assertEqual(self.results["repeat_opacity"], 1.0)
        self.assertEqual(self.results["repeat_text"], "Caleb's iPhone")

    def test_quick_second_change_ends_on_the_latest(self):
        self.assertEqual(self.results["double_text"], "On this Pi")
        self.assertEqual(self.results["double_icon"], "music")
        self.assertEqual(self.results["double_opacity"], 1.0)


if __name__ == "__main__":
    unittest.main()
