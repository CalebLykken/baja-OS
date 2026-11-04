"""Off-Pi tests for the shared press-and-release feel (qml/components: Card,
TextButton, IconButton, Keyboard, SegmentedControl). A press dips in 70 ms
with OutQuad, a release springs back in 180 ms with OutBack, and nothing
runs while idle: no loops, layer effects or new timers. The static checks
read the QML text; the load check creates each component in a child process,
like tests/test_source_badge.py, and checks it loads with no QML warnings and
rests at scale 1. The behaviour check presses a real TextButton in a
QQuickView and samples its scale while the animations run.

    python3 -m unittest tests.test_press_feedback
"""

import json
import os
import re
import subprocess
import sys
import unittest
from pathlib import Path

try:
    import PyQt6.QtQml  # noqa: F401
except ImportError:
    raise unittest.SkipTest("PyQt6 isn't installed")

ROOT = Path(__file__).resolve().parent.parent
COMPONENTS = ROOT / "qml" / "components"
FILES = ["Card.qml", "TextButton.qml", "IconButton.qml", "Keyboard.qml", "SegmentedControl.qml"]
LOADED = {"card": "Card", "text_button": "TextButton", "icon_button": "IconButton",
          "segmented": "SegmentedControl", "keyboard": "Keyboard"}

# The one Timer in Keyboard.qml is the hold-to-delete repeat, which runs only
# while the delete key is down. It was there before this change.
TIMERS_ALLOWED = {"Keyboard.qml": 1}

SCRIPT = r'''
import json, sys
from pathlib import Path
from PyQt6.QtCore import QUrl, qInstallMessageHandler, QtMsgType
from PyQt6.QtGui import QGuiApplication
from PyQt6.QtQml import QQmlComponent, QQmlEngine

app = QGuiApplication(sys.argv)
ROOT = Path.cwd()
messages = []


def on_message(mode, context, message):
    # QML warnings only; the host's font setup can print its own notes.
    if mode in (QtMsgType.QtWarningMsg, QtMsgType.QtCriticalMsg, QtMsgType.QtFatalMsg) \
            and (context.category or "").startswith("qml"):
        messages.append(message)


qInstallMessageHandler(on_message)

CASES = {
    "card": 'Card { tappable: true }',
    "text_button": 'TextButton { text: "Go" }',
    "icon_button": 'IconButton { icon: "play" }',
    "segmented": 'SegmentedControl { options: [{ label: "A", value: 1 }, { label: "B", value: 2 }]; current: 1 }',
    "keyboard": 'Keyboard {}',
}

engine = QQmlEngine()
results = {}
for name, body in CASES.items():
    messages.clear()
    component = QQmlComponent(engine)
    component.setData(('import QtQuick\nimport "qml/components"\n' + body).encode(),
                      QUrl.fromLocalFile(str(ROOT / "x.qml")))
    obj = component.create() if not component.isError() else None
    errors = [error.toString() for error in component.errors()]
    results[name] = {
        "created": obj is not None,
        "errors": errors + list(messages),
        "scale": obj.property("scale") if obj is not None else None,
    }

print(json.dumps(results))
sys.stdout.flush()
'''


def read(name):
    return (COMPONENTS / name).read_text()


def run():
    return subprocess.run([sys.executable, "-c", SCRIPT], cwd=ROOT,
                          capture_output=True, text=True, timeout=60,
                          env={**os.environ, "QT_QPA_PLATFORM": "offscreen"})


class PressFeedbackStaticTest(unittest.TestCase):
    def test_each_file_springs_back_with_outback_in_a_scale_behavior(self):
        pattern = re.compile(r"Behavior on scale\s*\{[^}]*Easing\.OutBack")
        for name in FILES:
            with self.subTest(file=name):
                self.assertRegex(read(name), pattern)

    def test_each_file_dropped_the_old_bare_press_behavior(self):
        for name in FILES:
            with self.subTest(file=name):
                self.assertNotIn("NumberAnimation { duration: 70 }", read(name))

    def test_press_and_release_numbers_are_the_shared_ones(self):
        for name in FILES:
            with self.subTest(file=name):
                text = read(name)
                self.assertIn("pressSpring.targetValue < 1 ? 70 : 180", text)
                self.assertIn("id: pressSpring", text)
                self.assertIn("easing.overshoot: 2.5", text)

    def test_segmented_label_dips_only_when_pressed_and_not_selected(self):
        self.assertIn("scale: tap.pressed && !parent.selected ? 0.94 : 1", read("SegmentedControl.qml"))

    def test_no_idle_work_was_added(self):
        for name in FILES:
            text = read(name)
            with self.subTest(file=name):
                self.assertNotIn("loops:", text)
                self.assertNotIn("layer.enabled", text)
                self.assertEqual(text.count("Timer"), TIMERS_ALLOWED.get(name, 0))


BEHAVIOUR_SCRIPT = r'''
import sys, time, json
from pathlib import Path
from PyQt6.QtCore import QPoint, Qt, QUrl
from PyQt6.QtGui import QGuiApplication
from PyQt6.QtQuick import QQuickView
from PyQt6.QtTest import QTest

app = QGuiApplication(sys.argv[:1])
ROOT = Path(sys.argv[1])

view = QQuickView()
view.setResizeMode(QQuickView.ResizeMode.SizeRootObjectToView)
view.setSource(QUrl.fromLocalFile(str(ROOT / "qml" / "components" / "TextButton.qml")))
view.resize(320, 120)
view.show()
deadline = time.monotonic() + 10
while not view.isExposed() and time.monotonic() < deadline:
    app.processEvents()
    time.sleep(0.01)
button = view.rootObject()
if button is None:
    print(json.dumps({"error": "TextButton did not load"}))
    sys.exit(0)
button.setProperty("text", "Go")
centre = QPoint(160, 60)


def sample(ms):
    values = []
    end = time.monotonic() + ms / 1000.0
    while time.monotonic() < end:
        app.processEvents()
        values.append(float(button.property("scale")))
        time.sleep(0.002)
    return values


press, release = [], []
rest = float(button.property("scale"))
for _ in range(2):
    QTest.mousePress(view, Qt.MouseButton.LeftButton, Qt.KeyboardModifier.NoModifier, centre)
    press += sample(250)
    QTest.mouseRelease(view, Qt.MouseButton.LeftButton, Qt.KeyboardModifier.NoModifier, centre)
    release += sample(250)

print(json.dumps({
    "rest": rest,
    "press_min": min(press),
    "release_max": max(release),
    "press_samples": len(press),
    "release_samples": len(release),
}))
sys.stdout.flush()
'''


class PressFeedbackBehaviourTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        result = subprocess.run([sys.executable, "-c", BEHAVIOUR_SCRIPT, str(ROOT)], cwd=ROOT,
                                capture_output=True, text=True, timeout=120,
                                env={**os.environ, "QT_QPA_PLATFORM": "offscreen"})
        cls.stderr = result.stderr
        cls.returncode = result.returncode
        lines = result.stdout.strip().splitlines()
        cls.data = json.loads(lines[-1]) if result.returncode == 0 and lines else {}

    def setUp(self):
        self.assertEqual(self.returncode, 0, self.stderr)
        self.assertNotIn("error", self.data, self.data.get("error"))

    def test_a_press_dips_shallowly(self):
        self.assertGreaterEqual(self.data["press_min"], 0.97 - 1e-3)

    def test_a_press_really_moves_the_button(self):
        # Guards against the press check passing because nothing animated.
        self.assertLess(self.data["press_min"], 1.0)

    def test_a_release_springs_past_rest(self):
        self.assertGreater(self.data["release_max"], 1.001)


class PressFeedbackLoadTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        result = run()
        cls.stderr = result.stderr
        cls.returncode = result.returncode
        cls.results = json.loads(result.stdout.strip().splitlines()[-1]) if result.returncode == 0 else {}

    def setUp(self):
        self.assertEqual(self.returncode, 0, self.stderr)

    def test_every_component_is_created_without_errors_or_warnings(self):
        for name in LOADED:
            with self.subTest(component=name):
                self.assertTrue(self.results[name]["created"])
                self.assertEqual(self.results[name]["errors"], [])

    def test_every_root_rests_at_scale_one(self):
        for name in LOADED:
            with self.subTest(component=name):
                self.assertEqual(self.results[name]["scale"], 1.0)


if __name__ == "__main__":
    unittest.main()
