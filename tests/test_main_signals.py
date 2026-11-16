"""SIGTERM reaches its handler while the event loop is idle, with no polling timer."""
import os
import signal
import threading
import time
import unittest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PyQt6.QtCore import QCoreApplication, QEventLoop, QTimer

import main


class SigtermWakeTests(unittest.TestCase):
    def setUp(self):
        self.app = QCoreApplication.instance() or QCoreApplication([])
        self.old_handler = signal.getsignal(signal.SIGTERM)
        self.old_fd = signal.set_wakeup_fd(-1)
        signal.set_wakeup_fd(self.old_fd)

    def tearDown(self):
        signal.set_wakeup_fd(self.old_fd)
        signal.signal(signal.SIGTERM, self.old_handler)

    def test_idle_loop_delivers_sigterm(self):
        loop = QEventLoop()
        ran = []

        def on_term(*_):
            ran.append(time.monotonic())
            loop.quit()
        keep = main.install_sigterm(on_term)
        safety = QTimer(singleShot=True, interval=3000, timeout=loop.quit)
        safety.start()
        started = time.monotonic()
        threading.Timer(0.1, os.kill, (os.getpid(), signal.SIGTERM)).start()
        loop.exec()
        self.assertTrue(ran, "handler never ran")
        self.assertLess(ran[0] - started, 1.5)
        del keep

    def test_no_polling_timer_in_main(self):
        with open(main.__file__) as f:
            self.assertNotIn("interval=250", f.read())


if __name__ == "__main__":
    unittest.main()
