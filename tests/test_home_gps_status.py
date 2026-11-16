"""Off-Pi tests for the GPS status pill on Home's map tile
(qml/components/HomeGpsStatus.qml): the words for no receiver, finding satellites
and a lost signal, and hidden for the demo drive or a healthy fix.

The QML runs in its own process, like tests/test_home_turn.py.

    python3 -m unittest tests.test_home_gps_status
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


class Gps(QObject):
    changed = pyqtSignal()

    def __init__(self):
        super().__init__()
        self.v = dict(hasFix=False, stale=False, source="", receiverConnected=False, satellites=0)

    @pyqtProperty(bool, notify=changed)
    def hasFix(self):
        return self.v["hasFix"]

    @pyqtProperty(bool, notify=changed)
    def stale(self):
        return self.v["stale"]

    @pyqtProperty(str, notify=changed)
    def source(self):
        return self.v["source"]

    @pyqtProperty(bool, notify=changed)
    def receiverConnected(self):
        return self.v["receiverConnected"]

    @pyqtProperty(int, notify=changed)
    def satellites(self):
        return self.v["satellites"]

    def set(self, **kw):
        self.v.update(kw)
        self.changed.emit()


def wait(ms):
    loop = QEventLoop()
    QTimer.singleShot(ms, loop.quit)
    loop.exec()


gps = Gps()
engine = QQmlEngine()
engine.rootContext().setContextProperty("gps", gps)
component = QQmlComponent(engine)
component.setData(b'import QtQuick\nimport "qml/components"\nHomeGpsStatus { }',
                  QUrl.fromLocalFile(str(ROOT / "x.qml")))
obj = component.create()
if obj is None:
    for error in component.errors():
        print(error.toString(), file=sys.stderr)
    sys.exit(1)


def snap(**kw):
    gps.set(**kw)
    wait(400)
    return {"visible": obj.property("visible"), "text": obj.property("shownText"),
            "height": obj.property("height")}


results = {}
results["no_receiver"] = snap()
results["finding"] = snap(receiverConnected=True)
results["finding_sats"] = snap(satellites=4)
results["lost"] = snap(hasFix=True, stale=True, source="gps")
results["good"] = snap(stale=False)
results["demo"] = snap(hasFix=True, stale=True, source="demo", receiverConnected=False)

print(json.dumps(results))
sys.stdout.flush()
'''


def run():
    return subprocess.run([sys.executable, "-c", SCRIPT], cwd=ROOT,
                          capture_output=True, text=True, timeout=60,
                          env={**os.environ, "QT_QPA_PLATFORM": "offscreen"})


class HomeGpsStatusTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        result = run()
        cls.stderr = result.stderr
        cls.returncode = result.returncode
        cls.results = json.loads(result.stdout.strip().splitlines()[-1]) if result.returncode == 0 else {}

    def setUp(self):
        self.assertEqual(self.returncode, 0, self.stderr)

    def test_no_receiver(self):
        r = self.results["no_receiver"]
        self.assertIs(r["visible"], True)
        self.assertEqual(r["text"], "No GPS receiver")
        self.assertEqual(r["height"], 56)

    def test_finding_satellites(self):
        self.assertEqual(self.results["finding"]["text"], "Finding satellites")
        self.assertIs(self.results["finding"]["visible"], True)

    def test_finding_shows_satellite_count(self):
        self.assertEqual(self.results["finding_sats"]["text"], "Finding satellites · 4")

    def test_signal_lost(self):
        self.assertEqual(self.results["lost"]["text"], "GPS signal lost")
        self.assertIs(self.results["lost"]["visible"], True)

    def test_hidden_with_good_fix(self):
        self.assertIs(self.results["good"]["visible"], False)

    def test_hidden_for_demo(self):
        self.assertIs(self.results["demo"]["visible"], False)


if __name__ == "__main__":
    unittest.main()
