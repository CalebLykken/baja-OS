"""Off-Pi tests for qml/components/Prompt.qml: hidden until shown, fades and
scales in once, and swallows taps. Runs in a subprocess because other test
modules hold a QCoreApplication.

    python3 -m unittest tests.test_prompt
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
PROMPT = ROOT / "qml" / "components" / "Prompt.qml"

SCRIPT = r'''
import json, sys
from pathlib import Path
from PyQt6.QtCore import QEventLoop, QObject, QTimer, QUrl
from PyQt6.QtGui import QGuiApplication
from PyQt6.QtQml import QQmlComponent, QQmlEngine
from PyQt6.QtQuick import QQuickItem

ROOT = Path(sys.argv[1])
app = QGuiApplication(sys.argv)
engine = QQmlEngine()

QML = """import QtQuick
import "qml/components"
Item {
    width: 1280; height: 800
    Prompt { objectName: "p"; anchors.fill: parent; title: "Hello"
        Rectangle { objectName: "body"; width: 10; height: 10 } }
}
"""

component = QQmlComponent(engine)
component.setData(QML.encode(), QUrl.fromLocalFile(str(ROOT / "x.qml")))
root = component.create()
if root is None:
    print([e.toString() for e in component.errors()])
    sys.exit(1)


def wait(ms):
    loop = QEventLoop()
    QTimer.singleShot(ms, loop.quit)
    loop.exec()


p = root.findChild(QQuickItem, "p")
card = root.findChild(QQuickItem, "promptCard")
out = {}
wait(50)
out["hidden_visible"] = p.property("visible")
out["hidden_scale"] = card.property("scale")
p.setProperty("shown", True)
wait(400)
out["shown_visible"] = p.property("visible")
out["shown_opacity"] = p.property("opacity")
out["shown_scale"] = card.property("scale")
out["body_parent_in_card"] = root.findChild(QQuickItem, "body") is not None
p.setProperty("shown", False)
wait(400)
out["after_visible"] = p.property("visible")
print(json.dumps(out))
'''


class PromptTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        env = dict(os.environ, QT_QPA_PLATFORM="offscreen")
        result = subprocess.run([sys.executable, "-c", SCRIPT, str(ROOT)], cwd=ROOT,
                                capture_output=True, text=True, timeout=60, env=env)
        if result.returncode != 0:
            raise AssertionError(result.stdout + result.stderr)
        cls.out = json.loads(result.stdout.strip().splitlines()[-1])

    def test_invisible_when_not_shown(self):
        self.assertFalse(self.out["hidden_visible"])
        self.assertAlmostEqual(self.out["hidden_scale"], 0.96)

    def test_shown_becomes_visible_at_full_scale(self):
        self.assertTrue(self.out["shown_visible"])
        self.assertAlmostEqual(self.out["shown_opacity"], 1.0)
        self.assertAlmostEqual(self.out["shown_scale"], 1.0)
        self.assertTrue(self.out["body_parent_in_card"])

    def test_hides_again_after_fading(self):
        self.assertFalse(self.out["after_visible"])

    def test_source_swallows_taps_and_has_no_timer(self):
        src = PROMPT.read_text()
        self.assertIn("MouseArea", src)
        self.assertNotIn("Timer", src)
        self.assertNotIn("loops", src)

    def test_main_uses_prompt_for_all_three_dialogs(self):
        main = (ROOT / "qml" / "Main.qml").read_text()
        for name in ("updateNotice", "pairPrompt", "keyOffPrompt"):
            self.assertRegex(main, r"Prompt\s*\{\s*id:\s*" + name + r"\b")
        self.assertLess(main.index("id: keyOffPrompt"), main.index("id: splash"))
        self.assertLess(main.index("id: updateNotice"), main.index("id: pairPrompt"))


if __name__ == "__main__":
    unittest.main()
