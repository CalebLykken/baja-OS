"""Off-Pi tests that an uncaught error is logged and the app keeps running
(main.log_exception). Each case runs in its own process, since without the
hook PyQt aborts the whole process.

    python3 -m unittest tests.test_errors
"""

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
import sys, threading
from PyQt6.QtCore import QCoreApplication, QObject, QTimer, QUrl, pyqtProperty, pyqtSignal
from PyQt6.QtQml import QQmlComponent, QQmlEngine
import main

sys.excepthook = main.log_exception
threading.excepthook = main.log_thread_exception
app = QCoreApplication(sys.argv)


class Source(QObject):
    poke = pyqtSignal()

    @pyqtProperty(str, constant=True)
    def broken(self):
        raise AttributeError("broken getter")


def fail():
    raise KeyError("missing")


src = Source()
case = sys.argv[1]
if case == "slot":
    src.poke.connect(fail)
    QTimer.singleShot(0, src.poke.emit)
elif case == "timer":
    QTimer.singleShot(0, fail)
elif case == "property":
    engine = QQmlEngine()
    engine.rootContext().setContextProperty("src", src)
    component = QQmlComponent(engine)
    component.setData(b"import QtQml\nQtObject { property string text: src.broken }", QUrl())
    obj = component.create()
elif case == "thread":
    threading.Thread(target=fail, name="poller").start()
QTimer.singleShot(300, app.quit)
app.exec()
print("still running")
'''


def run(case):
    return subprocess.run([sys.executable, "-c", SCRIPT, case], cwd=ROOT,
                          capture_output=True, text=True, timeout=60)


class UncaughtErrorTest(unittest.TestCase):
    def check_logged(self, case, error):
        result = run(case)
        self.assertEqual(result.returncode, 0, result.stderr)  # 134 is PyQt's abort
        self.assertIn("still running", result.stdout)
        self.assertIn("Uncaught error #1:", result.stderr)
        self.assertIn(error, result.stderr)

    def test_slot(self):
        self.check_logged("slot", "KeyError: 'missing'")

    def test_timer(self):
        self.check_logged("timer", "KeyError: 'missing'")

    def test_property_read_by_qml(self):
        self.check_logged("property", "AttributeError: broken getter")

    def test_worker_thread_is_named(self):
        result = run("thread")
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("still running", result.stdout)
        self.assertIn("Thread poller stopped on an error:", result.stderr)
        self.assertIn("KeyError: 'missing'", result.stderr)


if __name__ == "__main__":
    unittest.main()
