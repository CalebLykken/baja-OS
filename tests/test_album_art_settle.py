"""Off-Pi tests for qml/components/AlbumArt.qml: a new cover grows from slightly
small to full size while it fades in, never stays below full size, and is
skipped when the card isn't visible. Runs in a subprocess because other test
modules hold a QCoreApplication.

    python3 -m unittest tests.test_album_art_settle
"""

import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

try:
    import PyQt6.QtQml  # noqa: F401
except ImportError:
    raise unittest.SkipTest("PyQt6 isn't installed")

ROOT = Path(__file__).resolve().parent.parent

SCRIPT = r'''
import json, sys, tempfile
from pathlib import Path
from PyQt6.QtCore import QEventLoop, QTimer, QUrl
from PyQt6.QtGui import QColor, QGuiApplication, QImage
from PyQt6.QtQml import QQmlComponent, QQmlEngine

ROOT = Path(sys.argv[1])
app = QGuiApplication(sys.argv)
engine = QQmlEngine()
tmp = Path(tempfile.mkdtemp())
urls = []
for i, colour in enumerate(("red", "blue", "green")):
    img = QImage(32, 32, QImage.Format.Format_ARGB32)
    img.fill(QColor(colour))
    path = tmp / ("c%d.png" % i)
    img.save(str(path))
    urls.append(QUrl.fromLocalFile(str(path)).toString())


def make(extra=""):
    component = QQmlComponent(engine)
    component.setData(
        ('import QtQuick\nimport "qml/components"\nAlbumArt { width: 200; height: 200; %s }' % extra).encode(),
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


def snap(obj):
    front = obj.property("front")
    return {"scale": obj.property("frontScale"), "opacity": front.property("opacity"),
            "running": obj.property("fadeRunning")}


out = {}
obj = make()
obj.setProperty("source", urls[0])
wait(500)
out["first"] = snap(obj)

obj.setProperty("source", urls[1])
wait(90)
back = obj.property("back")
out["mid"] = {"scale": back.property("scale"), "opacity": back.property("opacity"),
              "running": obj.property("fadeRunning")}
wait(500)
out["end"] = snap(obj)

hidden = make("visible: false")
hidden.setProperty("source", urls[0])
wait(300)
hidden.setProperty("source", urls[1])
wait(60)
out["hidden"] = snap(hidden)

quick = make()
quick.setProperty("source", urls[0])
wait(500)
quick.setProperty("source", urls[1])
wait(100)
quick.setProperty("source", urls[2])
wait(600)
out["quick"] = snap(quick)
print("RESULT" + json.dumps(out))
'''


class AlbumArtSettleTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        env = dict(os.environ, QT_QPA_PLATFORM="offscreen")
        proc = subprocess.run([sys.executable, "-c", SCRIPT, str(ROOT)],
                              capture_output=True, text=True, env=env, timeout=120)
        line = [l for l in proc.stdout.splitlines() if l.startswith("RESULT")]
        if not line:
            raise AssertionError(proc.stdout + proc.stderr)
        cls.out = json.loads(line[-1][6:])

    def test_first_cover_full_size(self):
        self.assertEqual(self.out["first"]["scale"], 1.0)
        self.assertEqual(self.out["first"]["opacity"], 1.0)
        self.assertFalse(self.out["first"]["running"])

    def test_incoming_cover_is_mid_settle(self):
        mid = self.out["mid"]
        self.assertTrue(mid["running"])
        self.assertTrue(mid["scale"] < 1.0 or mid["opacity"] < 1.0)

    def test_ends_at_full_size(self):
        end = self.out["end"]
        self.assertEqual(end["scale"], 1.0)
        self.assertEqual(end["opacity"], 1.0)
        self.assertFalse(end["running"])

    def test_hidden_skips_animation(self):
        h = self.out["hidden"]
        self.assertEqual(h["scale"], 1.0)
        self.assertEqual(h["opacity"], 1.0)
        self.assertFalse(h["running"])

    def test_quick_second_change_ends_full_size(self):
        q = self.out["quick"]
        self.assertEqual(q["scale"], 1.0)
        self.assertEqual(q["opacity"], 1.0)
        self.assertFalse(q["running"])


if __name__ == "__main__":
    unittest.main()
