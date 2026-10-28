"""Off-Pi tests for Send to Baja (backend/phone.py): the token file, and
Reset link shutting out the old QR link, its cookie and the Shortcut's
token, checked against a real server on 127.0.0.1. Nothing goes further
than this machine: the places sent carry a position, so nothing is looked up.

    python3 -m unittest tests.test_phone
"""

import contextlib
import http.client
import io
import json
import os
import stat
import tempfile
import threading
import unittest
from http.server import ThreadingHTTPServer
from pathlib import Path
from unittest import mock

try:
    from PyQt6.QtCore import QCoreApplication, QUrl
    from backend import phone
except ImportError as e:
    raise unittest.SkipTest(f"PyQt6 isn't installed ({e})")

app = QCoreApplication.instance() or QCoreApplication([])

PLACE = {"lat": 47.6097, "lon": -122.3422, "name": "Pike Place Market"}


class TempTokenFile(unittest.TestCase):
    """Each test gets its own token file in a temporary folder."""

    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.tmp = Path(tmp.name)
        self.file = self.tmp / "baja-os" / "send-token"
        patch = mock.patch.object(phone, "TOKEN_FILE", self.file)
        patch.start()
        self.addCleanup(patch.stop)

    def service(self):
        svc = phone.PhoneSend(self.tmp / "maps")    # no map installed: anywhere is in range
        svc._qr_dir = self.tmp
        return svc


class TokenFileTest(TempTokenFile):
    def test_made_on_first_use_for_this_user_only(self):
        token = phone.load_token()
        self.assertGreaterEqual(len(token), 32)
        self.assertEqual(self.file.read_text().strip(), token)
        self.assertEqual(stat.S_IMODE(self.file.stat().st_mode), 0o600)
        self.assertEqual(phone.load_token(), token)            # and kept from then on

    def test_an_empty_file_gets_a_new_token(self):
        self.file.parent.mkdir(parents=True)
        self.file.write_text("\n")
        token = phone.load_token()
        self.assertGreaterEqual(len(token), 32)
        self.assertEqual(self.file.read_text().strip(), token)

    def test_a_new_token_replaces_the_file_whole(self):
        old = phone.load_token()
        new = phone.new_token()
        self.assertNotEqual(new, old)
        self.assertEqual(phone.load_token(), new)
        self.assertEqual(stat.S_IMODE(self.file.stat().st_mode), 0o600)
        self.assertEqual(os.listdir(self.file.parent), ["send-token"])     # no temporary file left

    def test_a_failed_save_leaves_the_old_file(self):
        old = phone.load_token()
        with mock.patch.object(phone.os, "replace", side_effect=OSError("disk full")):
            with self.assertRaises(OSError):
                phone.new_token()
        self.assertEqual(phone.load_token(), old)
        self.assertEqual(os.listdir(self.file.parent), ["send-token"])


class ResetTest(TempTokenFile):
    def setUp(self):
        super().setUp()
        self.svc = self.service()

    def test_reset_saves_a_new_token(self):
        old = self.svc.token
        self.svc.resetToken()
        self.assertNotEqual(self.svc.token, old)
        self.assertEqual(self.file.read_text().strip(), self.svc.token)      # for the next run too
        self.assertIn("k=" + self.svc.token, self.svc.pageUrl("192.168.1.30"))

    def test_a_failed_save_keeps_the_old_token(self):
        old = self.svc.token
        with mock.patch.object(phone.os, "replace", side_effect=OSError("read-only")), \
                contextlib.redirect_stdout(io.StringIO()) as out:
            self.svc.resetToken()
        self.assertIn("keeping the old one", out.getvalue())
        self.assertEqual(self.svc.token, old)
        self.assertEqual(self.file.read_text().strip(), old)
        self.assertEqual(self.svc.revision, 0)

    def test_reset_draws_a_new_code_and_deletes_the_old_one(self):
        first = self.svc.qrImage("192.168.1.30", self.svc.revision)
        old_file = Path(QUrl(first).toLocalFile())
        self.assertTrue(old_file.is_file())
        self.assertEqual(self.svc.qrImage("192.168.1.30", self.svc.revision), first)    # drawn once
        changes = []
        self.svc.changed.connect(lambda: changes.append(self.svc.revision))
        self.svc.resetToken()
        self.assertEqual(changes, [1])                      # QML's binding asks again
        self.assertFalse(old_file.exists())                 # it had the old token in it
        second = self.svc.qrImage("192.168.1.30", self.svc.revision)
        self.assertNotEqual(second, first)
        self.assertTrue(Path(QUrl(second).toLocalFile()).is_file())

    def test_the_last_place_comes_over_to_the_ui_thread(self):
        self.assertEqual(self.svc.lastSent, {})
        place = {"name": "Pike Place Market", "label": "", "lon": -122.3422, "lat": 47.6097}
        t = threading.Thread(target=self.svc.deliver, args=(place, "192.168.1.20"))
        t.start()
        t.join()
        self.assertEqual(self.svc.lastSent, {})             # not until the UI thread gets to it
        app.processEvents()
        last = self.svc.lastSent
        self.assertEqual((last["name"], last["ip"]), ("Pike Place Market", "192.168.1.20"))
        self.assertGreater(last["at"], 0)


class ServerTest(TempTokenFile):
    """The real request handler on 127.0.0.1 (an allowed address), on a free port."""

    def setUp(self):
        super().setUp()
        self.svc = self.service()
        self.server = ThreadingHTTPServer(("127.0.0.1", 0), phone._Handler)
        self.server.daemon_threads = True
        self.server.service = self.svc
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()

    def tearDown(self):
        self.server.shutdown()
        self.server.server_close()
        self.thread.join(5)

    def request(self, method, path, headers=(), body=None):
        conn = http.client.HTTPConnection("127.0.0.1", self.server.server_address[1], timeout=5)
        try:
            conn.request(method, path, body=body, headers=dict(headers))
            r = conn.getresponse()
            return r.status, (r.getheader("Set-Cookie") or "").split(";")[0], r.read().decode()
        finally:
            conn.close()

    def scan(self, token):
        """Open the QR code's link: (status, the cookie it hands out)."""
        status, cookie, _ = self.request("GET", "/send?k=" + token)
        return status, cookie

    def page(self, cookie):
        status, _, body = self.request("GET", "/send", {"Cookie": cookie})
        return status, body

    def send(self, **headers):
        """Send PLACE the way the page (Cookie=) or the Shortcut (Authorization=) does."""
        headers["Content-Type"] = "application/json"
        return self.request("POST", "/api/v1/destination", headers, json.dumps(PLACE))[0]

    def test_after_a_reset_only_the_new_code_works(self):
        old = self.svc.token
        status, old_cookie = self.scan(old)
        self.assertEqual((status, old_cookie), (303, "baja_send=" + old))
        status, body = self.page(old_cookie)
        self.assertEqual(status, 200)
        self.assertIn(old, body)                             # the token, for the Shortcut
        self.assertEqual(self.send(Cookie=old_cookie), 200)
        self.assertEqual(self.send(Authorization="Bearer " + old), 200)

        self.svc.resetToken()
        new = self.svc.token

        self.assertEqual(self.scan(old), (403, ""))          # the old QR link
        self.assertEqual(self.page(old_cookie)[0], 403)      # a cookie made from it, on the page
        self.assertEqual(self.send(Cookie=old_cookie), 401)  # and on the API
        self.assertEqual(self.send(Authorization="Bearer " + old), 401)    # the old Shortcut

        status, new_cookie = self.scan(new)
        self.assertEqual((status, new_cookie), (303, "baja_send=" + new))
        status, body = self.page(new_cookie)
        self.assertEqual(status, 200)
        self.assertIn(new, body)
        self.assertNotIn(old, body)
        self.assertEqual(self.send(Cookie=new_cookie), 200)
        self.assertEqual(self.send(Authorization="Bearer " + new), 200)

        app.processEvents()
        self.assertEqual(self.svc.lastSent["name"], "Pike Place Market")
        self.assertEqual(self.svc.lastSent["ip"], "127.0.0.1")

    def test_an_old_phone_cant_lock_itself_out_of_the_new_code(self):
        old = self.svc.token
        self.svc.resetToken()
        for _ in range(15):                                  # the old Shortcut, used again and again
            self.assertEqual(self.send(Authorization="Bearer " + old), 401)
            self.assertEqual(self.page("baja_send=" + old)[0], 403)
        self.assertEqual(self.scan(self.svc.token)[0], 303)

    def test_guessing_is_still_blocked_until_a_reset(self):
        for i in range(10):
            self.assertEqual(self.send(Authorization=f"Bearer guess{i}"), 401)
        self.assertEqual(self.scan(self.svc.token)[0], 403)  # for ten minutes, even the right link
        self.assertEqual(self.send(Authorization="Bearer " + self.svc.token), 401)
        self.svc.resetToken()                                # a fresh start for every phone
        self.assertEqual(self.scan(self.svc.token)[0], 303)


if __name__ == "__main__":
    unittest.main()
