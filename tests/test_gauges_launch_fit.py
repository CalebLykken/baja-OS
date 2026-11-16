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
 property var codes: []; property bool milOn: false; property int codeCount: 0
 property real zeroToSixty: 7.3; property real zeroToHundred: 12.4
 property var limits: ({rpmHigh: 6000, boostHigh: 15, coolantHigh: 230, intakeHigh: 150,
                        coolantCold: 160, voltageHigh: 15, voltageLow: 11.5}) }""", QUrl.fromLocalFile(str(ROOT / "v.qml")))
vehicle = component.create()
view.rootContext().setContextProperty("vehicle", vehicle)
# An optional coolant reading (degrees F) for this run; the default is 190.
if len(sys.argv) > 5:
    vehicle.setProperty("coolant", float(sys.argv[5]))
# Optional trouble-code state for this run: {"milOn": ..., "codeCount": ..., "codes": [...]}.
if len(sys.argv) > 6:
    for name, value in json.loads(sys.argv[6]).items():
        vehicle.setProperty(name, value)

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
# The Coolant gauge's own note ("warming up" while the engine is cold).
coolant_gauge = [g for g in gauges if str(g.property("label")) == "Coolant"][0]
coolant_note = find(coolant_gauge, lambda i: i.objectName() == "gaugeNote")[0]
out["coolant_note"] = coolant_note.property("text")
out["coolant_note_visible"] = coolant_note.isVisible()


def text_of(item):
    return item.property("text") if item is not None else None


# The trouble-code strip under the grid, and the grid above it.
strip_items = find(page, lambda i: i.objectName() == "codeStrip")
lamp = find(page, lambda i: i.objectName() == "lampLabel")
more = find(page, lambda i: i.objectName() == "moreLabel")
grid_items = find(page, lambda i: i.objectName() == "gaugeGrid")
out["strip_visible"] = bool(strip_items) and strip_items[0].isVisible()
out["lamp_visible"] = bool(lamp) and lamp[0].isVisible()
out["lamp_text"] = text_of(lamp[0]) if lamp else None
out["more_visible"] = bool(more) and more[0].isVisible()
out["more_text"] = text_of(more[0]) if more else None
out["grid_h"] = grid_items[0].height() if grid_items else None
print(json.dumps(out))
'''


def measure(units, style, coolant=None, state=None):
    env = dict(os.environ, QT_QPA_PLATFORM="offscreen")
    extra = [] if coolant is None else [str(coolant)]
    if state is not None:
        extra = [str(coolant if coolant is not None else 190.0), json.dumps(state)]
    with tempfile.TemporaryDirectory() as tmp:
        result = subprocess.run([sys.executable, "-c", SCRIPT, str(ROOT), units, style, tmp, *extra],
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

    def test_warm_engine_has_no_coolant_note(self):
        self.every(lambda o: self.assertEqual(o["coolant_note"], ""))

    def test_readout_stays_clear_of_the_hub(self):
        def check(o):
            if o["value"]["y"] > o["hub_bottom"] - 40:  # the needle look puts it under the hub
                self.assertGreaterEqual(o["value"]["y"], o["hub_bottom"])
        self.every(check)


class SpeedGaugeFitMetricTests(SpeedGaugeFitTests):
    units = "metric"


class CoolantWarmingTests(unittest.TestCase):
    """The Coolant gauge says "warming up" under its unit while the engine is
    cold (120 F, where the demo starts) and nothing at 190 F."""
    units = "imperial"

    @classmethod
    def setUpClass(cls):
        cls.cold = {style: measure(cls.units, style, 120.0) for style in STYLES}

    def test_cold_engine_says_warming_up(self):
        for style, out in self.cold.items():
            with self.subTest(style=style, units=self.units):
                self.assertTrue(out["coolant_note_visible"])
                self.assertEqual(out["coolant_note"], "warming up")


class CoolantWarmingMetricTests(CoolantWarmingTests):
    units = "metric"


class CheckEngineStripTests(unittest.TestCase):
    """The strip under the grid says so while the check-engine light is on, even
    before the codes are read; it is hidden when there is no lamp and no code."""
    units = "imperial"
    STORED = [{"code": "P0301", "text": "Cylinder 1 misfire", "pending": False},
              {"code": "P0171", "text": "System too lean", "pending": False},
              {"code": "P0420", "text": "Catalyst efficiency", "pending": True},
              {"code": "P0442", "text": "EVAP leak", "pending": False}]

    @classmethod
    def setUpClass(cls):
        style = STYLES[0]
        cls.style = style
        cls.clear = measure(cls.units, style, 190.0, {"milOn": False, "codeCount": 0, "codes": []})
        cls.lamp_no_codes = measure(cls.units, style, 190.0, {"milOn": True, "codeCount": 0, "codes": []})
        cls.lamp_counted = measure(cls.units, style, 190.0,
                                   {"milOn": True, "codeCount": 6, "codes": cls.STORED})
        cls.codes_no_lamp = measure(cls.units, style, 190.0,
                                    {"milOn": False, "codeCount": 1, "codes": cls.STORED[:1]})

    def test_no_lamp_and_no_codes_hides_the_strip(self):
        o = self.clear
        self.assertFalse(o["strip_visible"])
        self.assertFalse(o["lamp_visible"])
        self.assertFalse(o["more_visible"])

    def test_lamp_on_without_codes_shows_the_strip_and_the_line(self):
        o = self.lamp_no_codes
        self.assertTrue(o["strip_visible"])
        self.assertTrue(o["lamp_visible"])
        self.assertEqual(o["lamp_text"], "Check engine light on")
        self.assertFalse(o["more_visible"])

    def test_lamp_on_with_codes_counts_them_and_adds_more_line(self):
        o = self.lamp_counted
        self.assertTrue(o["strip_visible"])
        self.assertEqual(o["lamp_text"], "Check engine light on  \u00b7  6 codes")
        self.assertTrue(o["more_visible"])
        self.assertEqual(o["more_text"], "+2 more")

    def test_codes_without_lamp_still_show_the_strip_without_the_line(self):
        o = self.codes_no_lamp
        self.assertTrue(o["strip_visible"])
        self.assertFalse(o["lamp_visible"])
        self.assertFalse(o["more_visible"])

    def test_strip_shrinks_the_grid_only_when_shown(self):
        self.assertGreater(self.clear["grid_h"], self.lamp_no_codes["grid_h"])
        # Four code rows and the "+2 more" line make the strip taller, so the grid is shorter.
        self.assertGreater(self.lamp_no_codes["grid_h"], self.lamp_counted["grid_h"])


if __name__ == "__main__":
    unittest.main()
