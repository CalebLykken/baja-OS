"""Off-Pi test that the Speed gauge on the Gauges page still fits its card once
there is a 0-60 (0-100) time to show. The time used to go into the gauge's
legend ("SPEED · GEAR 5 · 0-60 7.3 S"), which in capitals with letter spacing
is wider than a card and spilled onto the RPM and Boost gauges. Now the legend
keeps the gear and the time is a third line of the gauge's value column, under
the number and the unit. The needle look (cluster) puts that column low on the
card, under the hub, so the check runs in every style and both unit systems:
the time must not touch the number, the unit, the legend or the hub, and must
fit inside the card without eliding.

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

# Theme's own list of looks, read once in its own process, so a look added
# later is covered without touching this test.
NAMES_SCRIPT = r'''
import json, sys
from pathlib import Path
from PyQt6.QtCore import QUrl
from PyQt6.QtGui import QGuiApplication
from PyQt6.QtQml import QQmlComponent, QQmlEngine

ROOT = Path(sys.argv[1])
app = QGuiApplication(sys.argv)
engine = QQmlEngine()
component = QQmlComponent(engine)
component.setData(b'import QtQuick\nimport "qml/components"\nItem { property var th: Theme }',
                  QUrl.fromLocalFile(str(ROOT / "x.qml")))
obj = component.create()
if obj is None:
    print([e.toString() for e in component.errors()])
    sys.exit(1)
print(json.dumps(list(obj.property("th").property("styleNames").toVariant())))
'''


def style_names():
    env = dict(os.environ, QT_QPA_PLATFORM="offscreen")
    result = subprocess.run([sys.executable, "-c", NAMES_SCRIPT, str(ROOT)],
                            cwd=ROOT, capture_output=True, text=True, timeout=60, env=env)
    if result.returncode != 0:
        raise AssertionError(result.stdout + result.stderr)
    return json.loads(result.stdout.strip().splitlines()[-1])


STYLES = style_names()

SCRIPT = r'''
import json, sys
from pathlib import Path
from PyQt6.QtCore import QEventLoop, QPointF, QTimer, QUrl
from PyQt6.QtGui import QFont, QFontDatabase, QFontMetricsF, QGuiApplication
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
style = sys.argv[3]
wrapper = Path(sys.argv[4]) / "wrapper.qml"
wrapper.write_text("""import QtQuick
import "file://%s/qml/components"
import "file://%s/qml/pages"
Item { width: 1168; height: 640
  Component.onCompleted: { Units.metric = %s; Theme.style = "%s" }
  GaugesPage { anchors.fill: parent } }
""" % (ROOT, ROOT, "true" if metric else "false", style))
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


def named(name):
    return find(speed, lambda i: i.objectName() == name)[0]


def rect(item):
    p = item.mapToItem(speed, QPointF(0, 0))
    return {"x": p.x(), "y": p.y(), "w": item.width(), "h": item.height()}


note = named("gaugeNote")
# The widest the line can get, in DejaVu Sans Bold (wider than the Mac's fonts)
# at the note's size, for the metric wording with the longest time.
wide = QFont("DejaVu Sans" if "DejaVu Sans" in QFontDatabase.families() else app.font().family())
wide.setBold(True)
wide.setPixelSize(int(note.property("font").pixelSize()))
out = {"card": {"x": 0, "y": 0, "w": speed.width(), "h": speed.height()},
       "legend_text": named("gaugeLegend").property("text"),
       "note_visible": note.isVisible(), "note_text": note.property("text"),
       "note_implicit": note.implicitWidth(),
       "note_worst": QFontMetricsF(wide).horizontalAdvance("0-100  12.4 s"),
       "legend": rect(named("gaugeLegend")), "value": rect(named("gaugeNumber")),
       "unit": rect(named("gaugeUnit")), "note": rect(note),
       "hub_bottom": speed.height() / 2 + 8 + 13,
       "other_card_widths": [g.width() for g in gauges if g is not speed]}
print(json.dumps(out))
'''


def measure(units, style):
    env = dict(os.environ, QT_QPA_PLATFORM="offscreen")
    with tempfile.TemporaryDirectory() as tmp:
        result = subprocess.run([sys.executable, "-c", SCRIPT, str(ROOT), units, style, tmp],
                                cwd=ROOT, capture_output=True, text=True, timeout=60, env=env)
    if result.returncode != 0:
        raise AssertionError(result.stdout + result.stderr)
    return json.loads(result.stdout.strip().splitlines()[-1])


def bottom(r):
    return r["y"] + r["h"]


def right(r):
    return r["x"] + r["w"]


class SpeedGaugeFitTests(unittest.TestCase):
    units = "imperial"

    def test_every_theme_is_measured(self):
        self.assertIn("atlantic", STYLES)
        self.assertEqual(set(self.outs), set(STYLES))

    @classmethod
    def setUpClass(cls):
        cls.outs = {style: measure(cls.units, style) for style in STYLES}

    def every(self, check):
        """Run a check on the measurements of each style."""
        for style, out in self.outs.items():
            with self.subTest(style=style, units=self.units):
                check(out)

    def test_legend_is_only_the_name_and_gear(self):
        def check(o):
            self.assertIn("gear", o["legend_text"])
            self.assertNotIn("0-", o["legend_text"])
        self.every(check)

    def test_legend_fits_inside_the_card(self):
        def check(o):
            self.assertGreaterEqual(o["legend"]["x"], 0)
            self.assertLessEqual(right(o["legend"]), o["card"]["w"])
        self.every(check)

    def test_launch_time_is_shown(self):
        def check(o):
            self.assertTrue(o["note_visible"])
            self.assertRegex(o["note_text"], r"^0-(100|60)\s+\d+\.\d s$")
            self.assertTrue(o["note_text"].startswith("0-100" if self.units == "metric" else "0-60"))
        self.every(check)

    def test_launch_time_fits_inside_the_card_whole(self):
        def check(o):
            n, card = o["note"], o["card"]
            self.assertGreaterEqual(n["x"], 0)
            self.assertLessEqual(right(n), card["w"])
            self.assertGreaterEqual(n["y"], 0)
            self.assertLessEqual(bottom(n), card["h"])
            # Not elided or clipped: the item is as wide as its text.
            self.assertGreaterEqual(n["w"], o["note_implicit"] - 0.5)
            # And the widest wording in the widest font would still fit with room.
            self.assertLessEqual(o["note_worst"] + 24, card["w"])
        self.every(check)

    def test_launch_time_does_not_overlap_the_number_unit_or_legend(self):
        def check(o):
            n = o["note"]
            self.assertGreaterEqual(n["y"], bottom(o["value"]))
            self.assertGreaterEqual(n["y"], bottom(o["unit"]))
            self.assertLessEqual(bottom(n), o["legend"]["y"])
        self.every(check)

    def test_readout_stays_clear_of_the_hub(self):
        def check(o):
            if o["value"]["y"] > o["hub_bottom"] - 40:  # the needle look puts it under the hub
                self.assertGreaterEqual(o["value"]["y"], o["hub_bottom"])
        self.every(check)


class SpeedGaugeFitMetricTests(SpeedGaugeFitTests):
    units = "metric"


if __name__ == "__main__":
    unittest.main()
