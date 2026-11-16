"""Off-Pi tests for qml/components/Readout.qml: placeholder values draw as a
dim dash with no unit, and warning marks the legend. Runs in a subprocess
because other test modules hold a QCoreApplication.

    python3 -m unittest tests.test_readout
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
from PyQt6.QtCore import QEventLoop, QObject, QTimer, QUrl
from PyQt6.QtGui import QGuiApplication
from PyQt6.QtQml import QQmlComponent, QQmlEngine

ROOT = Path(sys.argv[1])
app = QGuiApplication(sys.argv)
engine = QQmlEngine()


def build(data):
    component = QQmlComponent(engine)
    component.setData(data.encode(), QUrl.fromLocalFile(str(ROOT / "x.qml")))
    obj = component.create()
    if obj is None:
        print([e.toString() for e in component.errors()])
        sys.exit(1)
    return obj


def make(props):
    return build('import QtQuick\nimport "qml/components"\n'
                 'Readout { label: "Boost"; unit: "psi"; %s }' % props)


def wait(ms):
    loop = QEventLoop()
    QTimer.singleShot(ms, loop.quit)
    loop.exec()


def col(c):
    return c.name().lower()


ref = build('import QtQuick\nimport "qml/components"\n'
            'Item { property int fr: Theme.fontReadout; property color t: Theme.text; property color d: Theme.textDim; '
            'property color w: Theme.warn }')
out = {"ref": {"readout": ref.property("fr"), "text": col(ref.property("t")), "dim": col(ref.property("d")),
               "warn": col(ref.property("w"))}}


def snap(key, props):
    obj = make(props)
    wait(300)
    num = obj.findChild(QObject, "readoutNumeral")
    unit = obj.findChild(QObject, "readoutUnit")
    leg = obj.findChild(QObject, "readoutLegend")
    out[key] = {"text": num.property("text"), "color": col(num.property("color")),
                "scale": num.property("scale"), "size": num.property("font").pixelSize(), "unit": unit.property("visible"),
                "legend": col(leg.property("color"))}


snap("real", 'value: "12.3"')
snap("em", 'value: "—"')
snap("en", 'value: "–"')
snap("empty", 'value: ""')
snap("warn", 'value: "12.3"; warning: true')
snap("big", 'value: "123"; numeralSize: 76')
snap("pwarn", 'value: "—"; warning: true')

print(json.dumps(out))
'''


class ReadoutTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        env = dict(os.environ, QT_QPA_PLATFORM="offscreen")
        result = subprocess.run([sys.executable, "-c", SCRIPT, str(ROOT)], cwd=ROOT,
                                capture_output=True, text=True, timeout=60, env=env)
        if result.returncode != 0:
            raise AssertionError(result.stdout + result.stderr)
        cls.out = json.loads(result.stdout.strip().splitlines()[-1])

    def test_real_value(self):
        r, ref = self.out["real"], self.out["ref"]
        self.assertEqual(r["text"], "12.3")
        self.assertTrue(r["unit"])
        self.assertEqual(r["color"], ref["text"])
        self.assertEqual(r["legend"], ref["dim"])

    def test_placeholders_are_dim_dash_without_unit(self):
        for key in ("em", "en", "empty"):
            r = self.out[key]
            self.assertEqual(r["text"], "—", key)
            self.assertFalse(r["unit"], key)
            self.assertEqual(r["color"], self.out["ref"]["dim"], key)

    def test_warning_marks_numeral_and_legend(self):
        r = self.out["warn"]
        self.assertEqual(r["color"], self.out["ref"]["warn"])
        self.assertEqual(r["legend"], self.out["ref"]["warn"])

    def test_numeral_size(self):
        self.assertEqual(self.out["real"]["size"], self.out["ref"]["readout"])
        self.assertEqual(self.out["real"]["size"], 56)
        self.assertEqual(self.out["big"]["size"], 76)

    def test_placeholder_never_warns(self):
        r = self.out["pwarn"]
        self.assertEqual(r["color"], self.out["ref"]["dim"])
        self.assertEqual(r["legend"], self.out["ref"]["dim"])
        self.assertEqual(r["scale"], 1)


if __name__ == "__main__":
    unittest.main()
