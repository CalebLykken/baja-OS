"""Off-Pi tests for the systemd notifier and watchdog (backend/systemd.py):
sd_notify over NOTIFY_SOCKET, and the watchdog timer's interval and start.

Needs PyQt6 (QTimer, QObject), so it skips where that isn't installed. The
socket is mocked except for one real AF_UNIX round trip.

    python3 -m unittest tests.test_systemd
"""

import os
import shutil
import socket
import tempfile
import unittest
from unittest import mock

try:
    from PyQt6.QtCore import QCoreApplication

    from backend import systemd
except ImportError as e:
    raise unittest.SkipTest(f"PyQt6 isn't installed ({e})")

app = QCoreApplication.instance() or QCoreApplication([])


class EnvTest(unittest.TestCase):
    """Each test edits os.environ through mock.patch.dict, so the real
    environment is put back afterwards."""

    def setUp(self):
        env = mock.patch.dict(os.environ)
        env.start()
        self.addCleanup(env.stop)
        os.environ.pop("NOTIFY_SOCKET", None)
        os.environ.pop("WATCHDOG_USEC", None)


class NotifyTest(EnvTest):
    def fake_socket(self):
        """A socket.socket stand-in that works as a context manager."""
        patcher = mock.patch("backend.systemd.socket.socket")
        m = patcher.start()
        self.addCleanup(patcher.stop)
        sock = mock.MagicMock()
        m.return_value.__enter__.return_value = sock
        return m, sock

    def test_no_socket_means_no_op(self):
        m, _ = self.fake_socket()
        systemd.notify("READY=1")
        m.assert_not_called()

    def test_at_name_is_abstract_namespace(self):
        m, sock = self.fake_socket()
        os.environ["NOTIFY_SOCKET"] = "@baja-test"
        systemd.notify("READY=1")
        m.assert_called_once_with(socket.AF_UNIX, socket.SOCK_DGRAM)
        sock.connect.assert_called_once_with("\0baja-test")
        sock.sendall.assert_called_once_with(b"READY=1")

    def test_plain_path_is_used_unchanged(self):
        m, sock = self.fake_socket()
        os.environ["NOTIFY_SOCKET"] = "/run/systemd/notify"
        systemd.notify("WATCHDOG=1")
        sock.connect.assert_called_once_with("/run/systemd/notify")
        sock.sendall.assert_called_once_with(b"WATCHDOG=1")

    def test_connect_error_returns_quietly(self):
        m, sock = self.fake_socket()
        os.environ["NOTIFY_SOCKET"] = "@baja-test"
        sock.connect.side_effect = OSError("no listener")
        systemd.notify("READY=1")          # must not raise
        sock.sendall.assert_not_called()

    def test_round_trip_over_a_real_socket(self):
        # macOS limits socket paths to 104 bytes, so keep the directory short
        tmp = tempfile.mkdtemp(dir="/tmp")
        self.addCleanup(shutil.rmtree, tmp, True)
        path = os.path.join(tmp, "n.sock")
        server = socket.socket(socket.AF_UNIX, socket.SOCK_DGRAM)
        self.addCleanup(server.close)
        try:
            server.bind(path)
        except OSError as e:
            self.skipTest(f"can't bind a unix socket here ({e})")
        server.settimeout(2)
        os.environ["NOTIFY_SOCKET"] = path
        systemd.notify("READY=1")
        data, _ = server.recvfrom(1024)
        self.assertEqual(data, b"READY=1")


class WatchdogTest(EnvTest):
    """Watchdog() reads WATCHDOG_USEC when it is built. Its timer is at
    w._timer. A non-numeric WATCHDOG_USEC would raise in Watchdog(); systemd
    never sets one, so that isn't tested."""

    def make(self, usec=None):
        if usec is not None:
            os.environ["WATCHDOG_USEC"] = usec
        return systemd.Watchdog()

    def test_interval_is_half_the_timeout_in_ms(self):
        w = self.make("10000000")          # 10 s -> ping every 5 s
        self.assertEqual(w._timer.interval(), 5000)

    def test_interval_is_clamped_to_one_second(self):
        w = self.make("1000000")           # 1 s -> half is 500 ms, clamped
        self.assertEqual(w._timer.interval(), 1000)

    def test_unset_or_zero_watchdog_does_not_run_the_timer(self):
        for usec in (None, "0"):
            with self.subTest(WATCHDOG_USEC=usec):
                os.environ.pop("WATCHDOG_USEC", None)
                if usec is not None:
                    os.environ["WATCHDOG_USEC"] = usec
                w = systemd.Watchdog()
                with mock.patch("backend.systemd.notify") as notify:
                    w.start()
                notify.assert_called_once_with("READY=1")
                self.assertFalse(w._timer.isActive())

    def test_set_watchdog_starts_the_timer(self):
        w = self.make("10000000")
        self.addCleanup(lambda: w._timer.stop())   # keeps w, and its timer, alive
        with mock.patch("backend.systemd.notify") as notify:
            w.start()
        notify.assert_called_once_with("READY=1")
        self.assertTrue(w._timer.isActive())


if __name__ == "__main__":
    unittest.main()
