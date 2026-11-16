"""Off-Pi tests for qml/components/Backdrop.qml: every style's backdrop kind has
a paint branch, the file stays free of anything that animates or ticks, and
each style paints in dark and light without QML warnings.

    python3 -m unittest tests.test_backdrop
"""

import json
import os
import re
import subprocess
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
BACKDROP = (ROOT / "qml/components/Backdrop.qml").read_text()
THEME = (ROOT / "qml/components/Theme.qml").read_text()


class BackdropTextTest(unittest.TestCase):
    def test_every_style_backdrop_has_a_paint_branch(self):
        styles = THEME.split("readonly property var styles:")[1].split("lightStyles")[0]
        kinds = set(re.findall(r'backdrop:\s*"(\w+)"', styles))
        self.assertTrue(kinds)
        painted = set(re.findall(r'kind === "(\w+)"', BACKDROP)) | {"none"}
        self.assertLessEqual(kinds, painted)

    def test_new_styles_use_their_own_backdrops(self):
        self.assertRegex(THEME, r'gauge: "arc", backdrop: "grid"')
        self.assertRegex(THEME, r'gauge: "needle", backdrop: "dial"')

    def test_waves_and_dunes_are_painted_and_deterministic(self):
        self.assertIn("function paintWaves(ctx)", BACKDROP)
        self.assertIn("function paintDunes(ctx)", BACKDROP)
        self.assertIn('kind === "waves"', BACKDROP)
        self.assertIn('kind === "dunes"', BACKDROP)
        self.assertNotIn("Math.random", BACKDROP)

    def test_atlantic_uses_waves(self):
        self.assertRegex(THEME, r'gauge: "arc", backdrop: "waves"')

    def test_facets_and_scanlines_are_painted_and_deterministic(self):
        self.assertIn("function paintFacets(ctx)", BACKDROP)
        self.assertIn("function paintScanlines(ctx)", BACKDROP)
        self.assertIn('kind === "facets"', BACKDROP)
        self.assertIn('kind === "scanlines"', BACKDROP)
        self.assertRegex(THEME, r'glacier: \{[^}]*backdrop: "facets"')
        self.assertRegex(THEME, r'lcd: \{[^}]*backdrop: "scanlines"')

    def test_sunset_paints_a_horizon_sun_once(self):
        self.assertIn("function paintHorizon(ctx)", BACKDROP)
        self.assertIn('kind === "horizon"', BACKDROP)
        self.assertRegex(THEME, r'sunset: \{[^}]*backdrop: "horizon"')
        # The clip is balanced by a restore so later kinds can't inherit it.
        self.assertEqual(BACKDROP.count("ctx.save()"), BACKDROP.count("ctx.restore()"))

    def test_nothing_runs_while_idle(self):
        for word in ("Timer", "Animation", "Behavior", "running:"):
            self.assertNotIn(word, BACKDROP)


try:
    import PyQt6.QtQml  # noqa: F401
    HAVE_QT = True
except ImportError:
    HAVE_QT = False

SCRIPT = r'''
import json, sys
from pathlib import Path
from PyQt6.QtCore import QEventLoop, QTimer, QUrl, qInstallMessageHandler
from PyQt6.QtGui import QGuiApplication
from PyQt6.QtQml import QQmlComponent, QQmlEngine

ROOT = Path(sys.argv[1])
messages = []
qInstallMessageHandler(lambda mode, ctx, msg: messages.append(msg))
app = QGuiApplication(sys.argv)
engine = QQmlEngine()
warnings = []
engine.warnings.connect(lambda errs: warnings.extend(e.toString() for e in errs))

component = QQmlComponent(engine)
component.setData(
    b'import QtQuick\nimport "qml/components"\n'
    b'Item { property alias bd: b; width: 800; height: 480\n'
    b'  Backdrop { id: b; width: 800; height: 480 }\n'
    b'  property string st: "trail"; property bool dk: true\n'
    b'  onStChanged: Theme.style = st\n'
    b'  onDkChanged: Theme.dark = dk }',
    QUrl.fromLocalFile(str(ROOT / "x.qml")))
obj = component.create()
theme = None
if obj is None:
    print(json.dumps({"fatal": [e.toString() for e in component.errors()]}))
    sys.exit(0)
bd = obj.property("bd")
tc = QQmlComponent(engine)
tc.setData(b'import QtQuick\nimport "qml/components"\nItem { property var th: Theme }',
           QUrl.fromLocalFile(str(ROOT / "x.qml")))
theme = tc.create().property("th")
styles = theme.property("styles").toVariant()


def wait(ms):
    loop = QEventLoop()
    QTimer.singleShot(ms, loop.quit)
    loop.exec()


out = {}
for style in list(theme.property("styleNames").toVariant()):
    for dark in (True, False):
        obj.setProperty("st", style)
        obj.setProperty("dk", dark)
        wait(50)
        out["%s/%s" % (style, dark)] = bd.property("kind")
out["expected"] = {n: styles[n]["backdrop"] for n in styles}
out["warnings"] = warnings + [m for m in messages if "qml" in m.lower()]
print(json.dumps(out))
'''


@unittest.skipUnless(HAVE_QT, "PyQt6 isn't installed")
class BackdropQmlTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        env = dict(os.environ, QT_QPA_PLATFORM="offscreen")
        result = subprocess.run([sys.executable, "-c", SCRIPT, str(ROOT)], cwd=ROOT,
                                capture_output=True, text=True, timeout=60, env=env)
        if result.returncode != 0:
            raise AssertionError(result.stdout + result.stderr)
        cls.out = json.loads(result.stdout.strip().splitlines()[-1])

    def test_loads(self):
        self.assertNotIn("fatal", self.out)

    def test_kind_follows_style_in_both_modes(self):
        expected = self.out["expected"]
        self.assertTrue(expected)
        for style, kind in expected.items():
            for dark in (True, False):
                self.assertEqual(self.out["%s/%s" % (style, dark)], kind)

    def test_no_qml_warnings(self):
        self.assertEqual(self.out["warnings"], [])


if __name__ == "__main__":
    unittest.main()
