"""Off-Pi test that the Speed gauge on the Gauges page still fits its card once
there is a 0-60 (0-100) time to show. The time used to go into the gauge's
legend ("SPEED · GEAR 5 · 0-60 7.3 S"), which in capitals with letter spacing
is wider than a card and spilled onto the RPM and Boost gauges. Now the legend
keeps the gear and the time is its own line above it.

The QML runs in its own process, like tests/test_progress_bar.py. The fit is
measured in DejaVu Sans, the widest of the fonts the Pi can fall back to, when
the machine has it.

    python3 -m unittest tests.test_gauges_launch_fit
"""

import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

try:
    import PyQt6.QtQuick  # noqa: F401
except ImportError:
    raise unittest.SkipTest("PyQt6 isn't installed")

ROOT = Path(__file__).resolve().parent.parent

SCRIPT = r'''
import json, sys
from pathlib import Path
from PyQt6.QtCore import QEventLoop, QTimer, QUrl
from PyQt6.QtGui import QFont, QFontDatabase, QGuiApplication
from PyQt6.QtQml import QQmlComponent
from PyQt6.QtQuick import QQuickItem, QQuickView

ROOT = Path(sys.argv[1])
app = QGuiApplication(sys.argv)
if "DejaVu Sans" in QFontDatabase.families():
    app.setFont(QFont("DejaVu Sans"))

view = QQuickView()
component = QQmlComponent(view.engine())
component.setData(b"""import QtQuick
QtObject { property real rpm: 3000; property string gear: "5"; property bool engineKnown: true
 property bool speedKnown: true; property real speed: 45; property real boost: 5; property real coolant: 190
 property real intake: 90; property real voltage: 13.8; property bool voltageKnown: true
 property var codes: []; property real zeroToSixty: 7.3; property real zeroToHundred: 12.4
 property var limits: ({rpmHigh: 6000, boostHigh: 15, coolantHigh: 230, intakeHigh: 150,
                        voltageHigh: 15, voltageLow: 11.5}) }""", QUrl.fromLocalFile(str(ROOT / "v.qml")))
vehicle = component.create()
view.rootContext().setContextProperty("vehicle", vehicle)

metric = sys.argv[2] == "metric"
wrapper = Path(sys.argv[3]) / "wrapper.qml"
wrapper.write_text("""import QtQuick
import "file://%s/qml/components"
import "file://%s/qml/pages"
Item { width: 1168; height: 640
  Component.onCompleted: Units.metric = %s
  GaugesPage { anchors.fill: parent } }
""" % (ROOT, ROOT, "true" if metric else "false"))
try:
    view.setSource(QUrl.fromLocalFile(str(wrapper)))
    view.resize(1168, 640)
    view.show()
    loop = QEventLoop()
    QTimer.singleShot(400, loop.quit)
    loop.exec()
finally:
    wrapper.unlink()
if view.status() != QQuickView.Status.Ready:
    print([e.toString() for e in view.errors()])
    sys.exit(1)


def walk(item):
    yield item
    for child in item.childItems():
        yield from walk(child)


def find(root, pred):
    return [i for i in walk(root) if pred(i)]


page = view.rootObject().childItems()[0]
gauges = find(page, lambda i: i.property("label") is not None and i.property("unit") is not None)
speed = [g for g in gauges if str(g.property("label")).startswith("Speed")][0]
out = {"card_width": speed.width(), "legend_label": speed.property("label")}
legend = [i for i in speed.childItems() if i.property("font") is not None
          and i.property("text") == speed.property("label")][0]
launch = [i for i in speed.childItems() if i.objectName() == "launchTime"][0]
out.update(legend_text=legend.property("text"),
           legend_x=legend.x(), legend_width=legend.width(), legend_top=legend.y(),
           launch_visible=launch.isVisible(), launch_text=launch.property("text"),
           launch_x=launch.x(), launch_width=launch.width(),
           launch_top=launch.y(), launch_bottom=launch.y() + launch.height(),
           launch_implicit=launch.implicitWidth(),
           other_card_widths=[g.width() for g in gauges if g is not speed])
print(json.dumps(out))
'''


def measure(units):
    env = dict(os.environ, QT_QPA_PLATFORM="offscreen")
    with tempfile.TemporaryDirectory() as tmp:
        result = subprocess.run([sys.executable, "-c", SCRIPT, str(ROOT), units, tmp], cwd=ROOT,
                                capture_output=True, text=True, timeout=60, env=env)
    if result.returncode != 0:
        raise AssertionError(result.stdout + result.stderr)
    return json.loads(result.stdout.strip().splitlines()[-1])


class SpeedGaugeFitTests(unittest.TestCase):
    units = "imperial"

    @classmethod
    def setUpClass(cls):
        cls.out = measure(cls.units)

    def test_legend_is_only_the_name_and_gear(self):
        self.assertIn("gear", self.out["legend_text"])
        self.assertNotIn("0-", self.out["legend_text"])

    def test_legend_fits_inside_the_card(self):
        o = self.out
        self.assertGreaterEqual(o["legend_x"], 0)
        self.assertLessEqual(o["legend_x"] + o["legend_width"], o["card_width"])

    def test_launch_time_is_shown_inside_the_card(self):
        o = self.out
        self.assertTrue(o["launch_visible"])
        self.assertRegex(o["launch_text"], r"^0-(100|60)\s+\d+\.\d s$")
        self.assertTrue(o["launch_text"].startswith("0-100" if self.units == "metric" else "0-60"))
        self.assertGreaterEqual(o["launch_x"], 0)
        self.assertLessEqual(o["launch_x"] + o["launch_width"], o["card_width"])
        # Whole, not elided.
        self.assertGreaterEqual(o["launch_width"], o["launch_implicit"] - 0.5)

    def test_launch_time_clears_the_legend(self):
        self.assertLessEqual(self.out["launch_bottom"], self.out["legend_top"])


class SpeedGaugeFitMetricTests(SpeedGaugeFitTests):
    units = "metric"


if __name__ == "__main__":
    unittest.main()
