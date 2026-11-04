"""Off-Pi tests for qml/components/EmptyState.qml: it creates cleanly and
hides the hint line when there is no hint. Runs in a subprocess because other
test modules hold a QCoreApplication.

    python3 -m unittest tests.test_empty_state
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
from PyQt6.QtCore import QUrl
from PyQt6.QtGui import QGuiApplication
from PyQt6.QtQml import QQmlComponent, QQmlEngine

ROOT = Path(sys.argv[1])
app = QGuiApplication(sys.argv)
engine = QQmlEngine()


def make(body):
    component = QQmlComponent(engine)
    component.setData(
        ('import QtQuick\nimport "qml/components"\nEmptyState { width: 600; height: 400; %s }' % body).encode(),
        QUrl.fromLocalFile(str(ROOT / "x.qml")))
    obj = component.create()
    if obj is None:
        print([e.toString() for e in component.errors()])
        sys.exit(1)
    return obj


out = {}
obj = make('icon: "album"; title: "x"; hint: ""')
out["empty_hint"] = obj.property("hintShown")
obj.setProperty("hint", "fill me")
out["with_hint"] = obj.property("hintShown")

out["centred_y"] = obj.property("contentY")
obj.setProperty("alignTop", True)
out["top_y"] = obj.property("contentY")

print(json.dumps(out))
'''


class EmptyStateTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        env = dict(os.environ, QT_QPA_PLATFORM="offscreen")
        result = subprocess.run([sys.executable, "-c", SCRIPT, str(ROOT)], cwd=ROOT,
                                capture_output=True, text=True, timeout=60, env=env)
        if result.returncode != 0:
            raise AssertionError(result.stdout + result.stderr)
        cls.out = json.loads(result.stdout.strip().splitlines()[-1])

    def test_hint_hidden_when_empty(self):
        self.assertFalse(self.out["empty_hint"])

    def test_hint_shown_when_set(self):
        self.assertTrue(self.out["with_hint"])

    def test_align_top_pins_block_to_top(self):
        self.assertGreater(self.out["centred_y"], 40)
        self.assertLess(self.out["top_y"], 20)


if __name__ == "__main__":
    unittest.main()
