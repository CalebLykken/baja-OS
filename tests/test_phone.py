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
import socket
import stat
import subprocess
import sys
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

    def test_a_file_of_junk_bytes_gets_a_new_token(self):
        self.file.parent.mkdir(parents=True)
        self.file.write_bytes(b"\xff\xfe\x80" * 20)           # not UTF-8
        token = phone.load_token()
        self.assertGreaterEqual(len(token), 32)
        self.assertEqual(self.file.read_text().strip(), token)

    def test_an_unwritable_folder_still_gives_a_token(self):
        with mock.patch.object(phone.tempfile, "mkstemp", side_effect=PermissionError("read-only")):
            token = phone.load_token()
            svc = self.service()
        self.assertGreaterEqual(len(token), 32)
        self.assertGreaterEqual(len(svc.token), 32)
        self.assertFalse(self.file.exists())

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


class QuietConnectionTest(TempTokenFile):
    """A peer that goes quiet must not hold a server thread and socket forever."""

    def setUp(self):
        super().setUp()
        patch = mock.patch.object(phone._Handler, "timeout", 0.3)
        patch.start()
        self.addCleanup(patch.stop)
        self.svc = self.service()
        self.server = phone._Server(("127.0.0.1", 0), phone._Handler)
        self.server.service = self.svc
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()
        self.addCleanup(self.thread.join, 5)
        self.addCleanup(self.server.server_close)
        self.addCleanup(self.server.shutdown)

    def connect(self):
        s = socket.create_connection(("127.0.0.1", self.server.server_address[1]), timeout=5)
        self.addCleanup(s.close)
        return s

    def test_the_real_timeout_is_set(self):
        self.assertEqual(phone.REQUEST_TIMEOUT, 15)

    def test_a_silent_connection_is_closed(self):
        s = self.connect()
        self.assertEqual(s.recv(1), b"")        # the server hung up on us; no reply, no hang

    def test_a_stalled_body_is_closed(self):
        s = self.connect()
        s.sendall((f"POST /api/v1/destination HTTP/1.1\r\nHost: x\r\nAuthorization: Bearer {self.svc.token}\r\n"
                   "Content-Length: 100\r\n\r\n{").encode())
        self.assertEqual(s.recv(1), b"")

    def test_strangers_get_no_thread(self):
        with mock.patch.object(phone, "ALLOWED_NETS", []):
            s = self.connect()
            s.sendall(b"GET /send HTTP/1.1\r\nHost: x\r\n\r\n")
            try:
                data = s.recv(1)
            except ConnectionResetError:        # unread request data at close: also a drop
                data = b""
            self.assertEqual(data, b"")         # dropped before any request was read


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

    def test_an_unexpected_error_in_resolve_gets_a_json_500(self):
        with mock.patch.object(phone, "resolve", side_effect=TypeError("odd")), \
                mock.patch.object(phone.errorlog.log, "report") as report:
            status, _, body = self.request(
                "POST", "/api/v1/destination",
                {"Authorization": "Bearer " + self.svc.token, "Content-Type": "application/json"},
                json.dumps(PLACE))
        self.assertEqual(status, 500)
        self.assertEqual(json.loads(body), {"ok": False, "message": "Something went wrong reading that"})
        report.assert_called_once()

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


class FakeAccount:
    def authorize_url(self, nonce):
        return "https://accounts.spotify.com/authorize?x=1" if nonce == "good" else ""

    def callback(self, code, state, error):
        self.got = (code, state, error)
        return (True, "Linked <ok>") if state == "right" else (False, "Expired")


class SpotifyLinkTest(ServerTest):
    def setUp(self):
        super().setUp()
        self.svc.spotify = self.account = FakeAccount()

    def location(self, path):
        conn = http.client.HTTPConnection("127.0.0.1", self.server.server_address[1], timeout=5)
        try:
            conn.request("GET", path)
            r = conn.getresponse()
            r.read()
            return r.status, r.getheader("Location")
        finally:
            conn.close()

    def test_the_code_sends_the_phone_to_spotify(self):
        self.assertEqual(self.location("/spotify/link?s=good"),
                         (303, "https://accounts.spotify.com/authorize?x=1"))

    def test_a_wrong_code_is_refused(self):
        self.assertEqual(self.location("/spotify/link?s=bad"), (403, None))

    def test_the_callback_reaches_the_account_and_escapes_its_answer(self):
        status, _, body = self.request("GET", "/spotify/callback?code=c&state=right")
        self.assertEqual(status, 200)
        self.assertEqual(self.account.got, ("c", "right", ""))
        self.assertIn("Linked &lt;ok&gt;", body)

    def test_a_forged_callback_is_refused(self):
        self.assertEqual(self.request("GET", "/spotify/callback?code=c&state=wrong")[0], 403)

    def test_guessing_gets_the_phone_blocked(self):
        for _ in range(10):
            self.location("/spotify/link?s=bad")
        self.assertEqual(self.location("/spotify/link?s=good"), (403, None))

    def test_no_account_wired_up(self):
        self.svc.spotify = None
        self.assertEqual(self.location("/spotify/link?s=good"), (403, None))

    def test_the_send_page_still_wants_its_token(self):
        self.assertEqual(self.request("GET", "/send")[0], 403)


def _encode_geohash(lat, lon, length):
    """An independent geohash encoder, to check decode_geohash against."""
    alphabet = "0123456789bcdefghjkmnpqrstuvwxyz"
    lat_r, lon_r, out, bits, even = [-90.0, 90.0], [-180.0, 180.0], "", [], True
    while len(out) < length:
        rng, value = (lon_r, lon) if even else (lat_r, lat)
        mid = (rng[0] + rng[1]) / 2
        bits.append(1 if value >= mid else 0)
        rng[0 if value >= mid else 1] = mid
        even = not even
        if len(bits) == 5:
            out += alphabet[int("".join(map(str, bits)), 2)]
            bits = []
    return out


class WazeOsmLinkTest(unittest.TestCase):
    def test_geohash_round_trip(self):
        code = _encode_geohash(47.6062, -122.3321, 9)
        self.assertTrue(code.startswith("c23nb"))
        lat, lon = phone.decode_geohash(code)
        self.assertAlmostEqual(lat, 47.6062, delta=0.001)
        self.assertAlmostEqual(lon, -122.3321, delta=0.001)
        lat, lon = phone.decode_geohash("c23nb62w2")
        self.assertAlmostEqual(lat, 47.6062, delta=0.001)
        self.assertAlmostEqual(lon, -122.3321, delta=0.001)

    def test_geohash_junk(self):
        self.assertIsNone(phone.decode_geohash("a!?"))
        self.assertIsNone(phone.decode_geohash(""))
        self.assertIsNone(phone.decode_geohash(None))

    def test_waze_ll(self):
        self.assertEqual(phone.parse_map_url("https://waze.com/ul?ll=47.6062%2C-122.3321&navigate=yes"),
                         ((47.6062, -122.3321), ""))

    def test_waze_to_prefix_and_label(self):
        self.assertEqual(phone.parse_map_url("https://www.waze.com/ul?to=ll.47.6,-122.3&q=Pike%20Place"),
                         ((47.6, -122.3), "Pike Place"))

    def test_waze_geohash_path(self):
        ll, label = phone.parse_map_url("https://waze.com/ul/hc23nb62w2")
        self.assertAlmostEqual(ll[0], 47.6062, delta=0.001)
        self.assertAlmostEqual(ll[1], -122.3321, delta=0.001)
        self.assertEqual(label, "")

    def test_waze_junk(self):
        self.assertEqual(phone.parse_map_url("https://waze.com/ul?ll=abc"), (None, ""))
        self.assertEqual(phone.parse_map_url("https://waze.com/ul/h!!"), (None, ""))

    def test_osm_marker(self):
        self.assertEqual(phone.parse_map_url("https://www.openstreetmap.org/?mlat=47.6&mlon=-122.3"),
                         ((47.6, -122.3), ""))

    def test_osm_fragment_view(self):
        self.assertEqual(phone.parse_map_url("https://www.openstreetmap.org/#map=17/47.6/-122.3"),
                         ((47.6, -122.3), ""))

    def test_osm_junk(self):
        self.assertEqual(phone.parse_map_url("https://www.openstreetmap.org/?mlat=x&mlon=y"), (None, ""))


class ParseMapUrlTest(unittest.TestCase):
    PIKE = (47.6097, -122.3422)

    def test_apple_with_a_position_and_a_name(self):
        self.assertEqual(phone.parse_map_url("https://maps.apple.com/?ll=47.6097,-122.3422&q=Pike%20Place%20Market"),
                         (self.PIKE, "Pike Place Market"))

    def test_apple_place_with_name_and_address(self):
        url = ("https://maps.apple.com/place?coordinate=47.6097,-122.3422"
               "&name=Pike%20Place%20Market&address=85%20Pike%20St,%20Seattle,%20WA")
        self.assertEqual(phone.parse_map_url(url), (self.PIKE, "Pike Place Market, 85 Pike St, Seattle, WA"))

    def test_apple_directions_to_a_name(self):
        self.assertEqual(phone.parse_map_url("https://maps.apple.com/?daddr=Space%20Needle&dirflg=d"),
                         (None, "Space Needle"))

    def test_apple_directions_to_a_position(self):
        # A daddr that is a position is the position, not the label.
        self.assertEqual(phone.parse_map_url("https://maps.apple.com/?daddr=47.6097,-122.3422"), (self.PIKE, ""))

    def test_google_place_page(self):
        url = ("https://www.google.com/maps/place/Pike+Place+Market/@47.6101,-122.3421,17z/"
               "data=!3m1!4b1!4m6!3m5!1s0x0:0x0!8m2!3d47.6097!4d-122.3422")
        self.assertEqual(phone.parse_map_url(url), (self.PIKE, "Pike Place Market"))

    def test_google_place_without_exact_coordinates_uses_the_view(self):
        ll, label = phone.parse_map_url("https://www.google.com/maps/place/Pike+Place+Market/@47.6101,-122.3421,17z")
        self.assertEqual((ll, label), ((47.6101, -122.3421), "Pike Place Market"))

    def test_google_query_with_a_position(self):
        self.assertEqual(phone.parse_map_url("https://www.google.com/maps?q=47.6097,-122.3422"), (self.PIKE, ""))

    def test_google_search_by_words(self):
        self.assertEqual(phone.parse_map_url("https://www.google.com/maps/search/?api=1&query=Space+Needle"),
                         (None, "Space Needle"))

    def test_google_directions_end_at_the_last_stop(self):
        # The @ is the map view, not the destination, so the name is left for offline search.
        ll, label = phone.parse_map_url("https://www.google.com/maps/dir/Current+Location/Space+Needle/@47.62,-122.35,14z")
        self.assertEqual((ll, label), (None, "Space Needle"))

    def test_apple_view_centre_is_not_used_when_there_is_a_name(self):
        self.assertEqual(phone.parse_map_url("https://maps.apple.com/?q=Space%20Needle&center=47.62,-122.35"),
                         (None, "Space Needle"))
        self.assertEqual(phone.parse_map_url("https://maps.apple.com/?center=47.62,-122.35"), ((47.62, -122.35), ""))

    def test_geo_with_a_position(self):
        self.assertEqual(phone.parse_map_url("geo:47.6097,-122.3422"), (self.PIKE, ""))
        self.assertEqual(phone.parse_map_url("geo:47.6097,-122.3422;u=35"), (self.PIKE, ""))

    def test_geo_with_a_label(self):
        self.assertEqual(phone.parse_map_url("geo:47.6097,-122.3422?q=47.6097,-122.3422(Pike+Place+Market)"),
                         (self.PIKE, "Pike Place Market"))
        self.assertEqual(phone.parse_map_url("geo:47.6097,-122.3422?q=Coffee"), (self.PIKE, "Coffee"))

    def test_geo_zero_zero_with_a_label_takes_the_position_from_the_query(self):
        # The usual Android form: geo:0,0 means "look at q".
        self.assertEqual(phone.parse_map_url("geo:0,0?q=47.6097,-122.3422(Pike+Place+Market)"),
                         (self.PIKE, "Pike Place Market"))

    def test_geo_zero_zero_with_words_has_no_position(self):
        # (0, 0) is not a position: the words in q are searched instead.
        self.assertEqual(phone.parse_map_url("geo:0,0?q=Space+Needle"), (None, "Space Needle"))

    def test_other_sites_and_junk(self):
        for url in ("https://example.com/?ll=47.6,-122.3", "", "not a link"):
            self.assertEqual(phone.parse_map_url(url), (None, ""), url)

    def test_an_impossible_position_is_ignored(self):
        self.assertEqual(phone.parse_map_url("https://maps.apple.com/?ll=147.6,-322.3&q=Nowhere"), (None, "Nowhere"))


class ResolveTest(unittest.TestCase):
    PIKE = "https://www.google.com/maps/place/Pike+Place+Market/@47.6097,-122.3422,17z"

    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.maps = Path(tmp.name)
        (self.maps / "region.json").write_text(json.dumps({"region": "Washington", "bbox": [-125.0, 45.5, -116.9, 49.1]}))

    def test_a_place_inside_the_map(self):
        self.assertEqual(phone.resolve({"urls": [self.PIKE]}, self.maps),
                         {"name": "Pike Place Market", "label": "Sent from your phone",
                          "lon": -122.3422, "lat": 47.6097})

    def test_a_place_outside_the_map_says_where_the_map_is(self):
        with self.assertRaisesRegex(ValueError, r"outside the offline map \(Washington\)"):
            phone.resolve({"urls": ["https://maps.apple.com/?ll=40.7128,-74.0060&q=Times+Square"]}, self.maps)

    def test_the_edge_of_the_map_is_inside(self):
        place = phone.resolve({"lat": 49.1, "lon": -125.0, "name": "Corner"}, self.maps)
        self.assertEqual((place["lat"], place["lon"]), (49.1, -125.0))
        for lat, lon in ((49.2, -122.0), (47.0, -126.0), (45.0, -122.0), (47.0, -116.0)):
            with self.assertRaises(ValueError, msg=(lat, lon)):
                phone.resolve({"lat": lat, "lon": lon}, self.maps)

    def test_without_a_region_file_nowhere_is_outside(self):
        (self.maps / "region.json").unlink()
        place = phone.resolve({"urls": ["geo:40.7128,-74.0060"]}, self.maps)
        self.assertEqual(place["lon"], -74.006)

    def test_a_region_file_of_the_wrong_shape_is_like_none(self):
        (self.maps / "region.json").write_text("[1, 2]")
        place = phone.resolve({"urls": ["geo:40.7128,-74.0060"]}, self.maps)
        self.assertEqual(place["lon"], -74.006)
        (self.maps / "region.json").write_text(json.dumps({"region": 5, "bbox": [1, 2, 3]}))
        self.assertEqual(phone.resolve({"lat": 40.7, "lon": -74.0}, self.maps)["lon"], -74.0)

    def test_urls_that_are_not_strings_are_ignored(self):
        for urls in ([123, None], {"a": 1}, 5):
            place = phone.resolve({"urls": urls, "lat": 47.6, "lon": -122.3, "name": "Here"}, self.maps)
            self.assertEqual((place["name"], place["lat"]), ("Here", 47.6), urls)

    def test_a_link_inside_the_shared_text(self):
        place = phone.resolve({"text": f"Look at this: {self.PIKE} nice place"}, self.maps)
        self.assertEqual((place["name"], place["lat"]), ("Pike Place Market", 47.6097))

    def test_a_name_and_address_split_into_name_and_label(self):
        url = ("https://maps.apple.com/place?coordinate=47.6097,-122.3422"
               "&name=Pike%20Place%20Market&address=85%20Pike%20St,%20Seattle,%20WA")
        place = phone.resolve({"urls": url}, self.maps)
        self.assertEqual((place["name"], place["label"]), ("Pike Place Market", "85 Pike St, Seattle, WA"))

    def test_the_position_and_name_the_phone_sent_stand_in(self):
        place = phone.resolve({"lat": "47.6097", "lon": "-122.3422", "name": "Pike Place Market"}, self.maps)
        self.assertEqual((place["name"], place["lon"], place["lat"]), ("Pike Place Market", -122.3422, 47.6097))

    def test_a_bare_coordinate_in_the_text(self):
        place = phone.resolve({"text": "meet at 47.6097, -122.3422 ok"}, self.maps)
        self.assertEqual((place["lat"], place["lon"], place["name"]), (47.6097, -122.3422, "Dropped pin"))

    def test_a_list_is_not_a_place(self):
        with self.assertRaisesRegex(ValueError, "list"):
            phone.resolve({"urls": ["https://maps.apple.com/guides/?guide=123"]}, self.maps)
        with self.assertRaisesRegex(ValueError, "list"):
            phone.resolve({"urls": ["https://www.google.com/maps/@/data=!/lists/abc"]}, self.maps)

    def test_nothing_to_go_on(self):
        with self.assertRaisesRegex(ValueError, "offline map"):
            phone.resolve({"text": "see you soon"}, self.maps)
        with self.assertRaises(ValueError):
            phone.resolve({}, self.maps)


class QrForTest(TempTokenFile):
    def test_a_code_is_drawn_to_a_png_file(self):
        svc = self.service()
        self.assertEqual(svc.qrFor(""), "")
        url = svc.qrFor("http://192.168.1.2:8765/send?k=x")
        self.assertTrue(url.startswith("file://"))
        path = Path(QUrl(url).toLocalFile())
        self.assertEqual(path.suffix, ".png")
        self.assertEqual(path.read_bytes()[:8], b"\x89PNG\r\n\x1a\n")


class StartupImportTest(unittest.TestCase):
    def test_qr_code_and_gzip_stay_off_the_startup_path(self):
        # A subprocess, so other tests' imports don't show up in sys.modules.
        code = ('import sys, backend.phone; '
                'print("backend.vendor.qrcodegen" in sys.modules, "gzip" in sys.modules)')
        env = dict(os.environ, QT_QPA_PLATFORM="offscreen")
        repo = Path(__file__).resolve().parent.parent
        out = subprocess.run([sys.executable, "-c", code], cwd=repo, env=env,
                             capture_output=True, text=True, check=True).stdout
        self.assertEqual(out.split(), ["False", "False"])


if __name__ == "__main__":
    unittest.main()
