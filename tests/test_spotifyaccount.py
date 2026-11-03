"""Off-Pi tests for backend/spotifyaccount.py: linking takes one use of the
code on screen, the login survives a restart and is lost only when Spotify
ends it, and the library comes through odd answers and a refused list. Nothing
leaves the machine: urlopen is faked, and the worker runs where it's started.

    python3 -m unittest tests.test_spotifyaccount
"""

import base64
import hashlib
import io
import json
import stat
import tempfile
import unittest
import urllib.error
import urllib.parse
from pathlib import Path
from types import SimpleNamespace
from unittest import mock

try:
    from PyQt6.QtCore import QCoreApplication
    from backend import spotifyaccount
    from backend.spotifyaccount import LINK_LASTS_S, REFRESH_EVERY_S, RETRY_FIRST_S, RETRY_MAX_S, SpotifyAccount
except ImportError as e:
    raise unittest.SkipTest(f"PyQt6 isn't installed ({e})")

app = QCoreApplication.instance() or QCoreApplication([])

PLAYLISTS = {"items": [None, {"uri": "spotify:playlist:p", "name": "Mix", "images": []}]}
ALBUMS = {"items": [{"album": {"uri": "spotify:album:a", "name": "LP", "artists": [{"name": "A"}]}}, {"album": None}]}
TRACKS = {"items": [{"track": {"uri": "spotify:track:t", "name": "Song", "artists": [{"name": "A"}]}}]}


def reply(data):
    return mock.MagicMock(__enter__=lambda s: io.BytesIO(json.dumps(data).encode()))


def http_error(code, body=b""):
    return urllib.error.HTTPError("https://x", code, "no", {}, io.BytesIO(body))


class InlineThread:
    def __init__(self, target=None, daemon=None):
        self.target = target

    def start(self):
        self.target()


class FakeSettings(dict):
    def set(self, key, value):
        self[key] = value


class AccountCase(unittest.TestCase):
    def setUp(self):
        folder = tempfile.TemporaryDirectory()
        self.addCleanup(folder.cleanup)
        self.folder = Path(folder.name)
        self.env = self.folder / "search.env"
        self.env.write_text("SPOTIFY_CLIENT_ID=app\nSPOTIFY_CLIENT_SECRET=s\n")
        self.login = self.folder / "login.json"
        self.settings = FakeSettings(saved="yes")
        self.requests = []
        self.during = None                  # called with each request as it goes out: a sign-out can land mid-flight
        self.token_answer = {"access_token": "acc", "refresh_token": "ref", "expires_in": 3600}
        self.answers = {}
        self.now = 100.0
        self.addCleanup(mock.patch.stopall)
        mock.patch.object(spotifyaccount.urllib.request, "urlopen", self.urlopen).start()
        mock.patch.object(spotifyaccount, "threading", SimpleNamespace(
            Thread=InlineThread, Lock=spotifyaccount.threading.Lock)).start()
        mock.patch.object(spotifyaccount.time, "monotonic", lambda: self.now).start()
        mock.patch("backend.retry.time.sleep").start()
        self.print = mock.patch("builtins.print").start()

    def account(self):
        return SpotifyAccount(self.settings, self.env, self.login)

    def urlopen(self, req, timeout=None):
        self.requests.append(req)
        if self.during:
            self.during(req)
        if "api/token" in req.full_url:
            answer = self.token_answer
        else:
            name = req.full_url.split("/me/")[1].split("?")[0]
            answer = self.answers.get(name, {"playlists": PLAYLISTS, "albums": ALBUMS, "tracks": TRACKS}[name])
        if isinstance(answer, list):
            answer = answer.pop(0)
        if isinstance(answer, Exception):
            raise answer
        return reply(answer)

    def token_posts(self):
        return [dict(urllib.parse.parse_qsl(r.data.decode())) for r in self.requests if "api/token" in r.full_url]

    def linked_account(self):
        a = self.account()
        a.startLink("172.20.10.14", 8780)
        a.callback("code", a._link["state"], "")
        return a


class LinkingTest(AccountCase):
    def nonce(self, a):
        return urllib.parse.parse_qs(urllib.parse.urlsplit(a.linkUrl).query)["s"][0]

    def test_the_code_points_at_this_pi(self):
        a = self.account()
        a.startLink("172.20.10.14", 8780)
        self.assertTrue(a.linkUrl.startswith("http://172.20.10.14:8780/spotify/link?s="))
        self.assertTrue(a._link["state"].endswith("~172.20.10.14~8780"))

    def test_spotify_is_asked_with_pkce_and_no_secret(self):
        a = self.account()
        a.startLink("10.0.0.2", 8780)
        asked = dict(urllib.parse.parse_qsl(urllib.parse.urlsplit(a.authorize_url(self.nonce(a))).query))
        expect = base64.urlsafe_b64encode(hashlib.sha256(a._link["verifier"].encode()).digest()).rstrip(b"=").decode()
        self.assertEqual((asked["client_id"], asked["code_challenge"], asked["code_challenge_method"]),
                         ("app", expect, "S256"))
        self.assertEqual(asked["redirect_uri"], spotifyaccount.REDIRECT_URI)
        self.assertNotIn("client_secret", asked)

    def test_a_wrong_or_late_code_goes_nowhere(self):
        a = self.account()
        a.startLink("10.0.0.2", 8780)
        self.assertEqual(a.authorize_url("guess"), "")
        nonce = self.nonce(a)
        self.now += LINK_LASTS_S + 1
        self.assertEqual(a.authorize_url(nonce), "")

    def test_a_good_callback_saves_the_login_and_reads_the_library(self):
        a = self.linked_account()
        self.assertTrue(a.linked)
        self.assertEqual(self.token_posts()[0]["grant_type"], "authorization_code")
        self.assertIn("code_verifier", self.token_posts()[0])
        self.assertEqual(json.loads(self.login.read_text()), {"refresh_token": "ref"})
        self.assertEqual(stat.S_IMODE(self.login.stat().st_mode), 0o600)
        self.assertEqual(a.linkUrl, "")
        self.assertEqual([len(x) for x in (a.playlists, a.albums, a.songs)], [1, 1, 1])

    def test_the_wrong_state_is_refused(self):
        a = self.account()
        a.startLink("10.0.0.2", 8780)
        self.assertFalse(a.callback("code", "forged", "")[0])
        self.assertFalse(a.linked)
        self.assertEqual(self.requests, [])

    def test_a_callback_works_once(self):
        a = self.account()
        a.startLink("10.0.0.2", 8780)
        state = a._link["state"]
        self.assertTrue(a.callback("code", state, "")[0])
        self.assertFalse(a.callback("code", state, "")[0])

    def test_saying_no_on_the_phone(self):
        a = self.account()
        a.startLink("10.0.0.2", 8780)
        self.assertFalse(a.callback("", a._link["state"], "access_denied")[0])
        self.assertEqual((a.linked, a.message), (False, "Spotify wasn't linked"))

    def test_no_app_id_no_code(self):
        self.env.unlink()
        a = self.account()
        a.startLink("10.0.0.2", 8780)
        self.assertEqual(a.linkUrl, "")

    def test_a_reply_without_a_usable_lifetime_still_links(self):
        for lifetime in (None, "soon", float("nan"), float("inf")):
            with self.subTest(expires_in=lifetime):
                answer = {"access_token": "a", "refresh_token": "r", "expires_in": lifetime}
                with mock.patch.object(spotifyaccount, "_post_form", return_value=answer):
                    a = self.account()
                    a.startLink("10.0.0.2", 8780)
                    a.callback("code", a._link["state"], "")
                self.assertTrue(a.linked)
                self.assertEqual(a._access, "a")
                self.assertEqual(a._access_until, self.now + 3600 - spotifyaccount.TOKEN_MARGIN_S)

    def test_a_reply_that_is_not_an_object_still_says_so_on_the_phone(self):
        for junk in ([], "tokens", None):
            with self.subTest(reply=junk):
                with mock.patch.object(spotifyaccount, "_post_form", return_value=junk):
                    a = self.account()
                    a.startLink("10.0.0.2", 8780)
                    a.callback("code", a._link["state"], "")
                self.assertEqual((a.linked, a.message, a.linkUrl),
                                 (False, "Couldn't finish linking Spotify", ""))


class StayingLinkedTest(AccountCase):
    def test_a_restart_needs_no_new_link(self):
        self.linked_account()
        self.requests.clear()
        again = self.account()
        self.assertTrue(again.linked)
        self.assertEqual(len(again.songs), 1)         # the last copy, before any network
        again.start()
        self.assertEqual(self.token_posts()[0], {"grant_type": "refresh_token", "client_id": "app",
                                                 "refresh_token": "ref"})

    def test_a_new_refresh_token_replaces_the_old(self):
        a = self.linked_account()
        self.now += 7200
        self.token_answer = {"access_token": "acc2", "refresh_token": "ref2", "expires_in": 3600}
        a.refresh()
        self.assertEqual(json.loads(self.login.read_text()), {"refresh_token": "ref2"})

    def test_a_refresh_without_one_keeps_the_old(self):
        a = self.linked_account()
        self.now += 7200
        self.token_answer = {"access_token": "acc2", "expires_in": 3600}
        a.refresh()
        self.assertEqual(json.loads(self.login.read_text()), {"refresh_token": "ref"})

    def test_no_signal_never_loses_the_login(self):
        a = self.linked_account()
        self.now += 7200
        self.token_answer = urllib.error.URLError("offline")
        a.refresh()
        self.assertTrue(a.linked)
        self.assertTrue(self.login.exists())
        self.assertEqual(len(a.songs), 1)
        self.assertEqual(a.message, "Can't reach Spotify right now")

    def test_a_server_error_never_loses_the_login(self):
        a = self.linked_account()
        self.now += 7200
        self.token_answer = http_error(503)
        a.refresh()
        self.assertTrue(self.login.exists())

    def test_spotify_ending_it_brings_the_code_back(self):
        a = self.linked_account()
        self.now += 7200
        self.token_answer = http_error(400, b'{"error":"invalid_grant"}')
        a.refresh()
        self.assertFalse(a.linked)
        self.assertFalse(self.login.exists())
        self.assertIn("scan the code", a.message)

    def test_signing_out_forgets_everything(self):
        a = self.linked_account()
        a.signOut()
        self.assertFalse(self.login.exists())
        self.assertEqual((a.linked, a.songs), (False, []))
        self.assertEqual(self.settings["spotifyLibrary"], "{}")

    def test_signing_out_during_a_token_renewal_stays_signed_out(self):
        a = self.linked_account()
        self.now += 7200
        self.token_answer = {"access_token": "acc2", "refresh_token": "ref2", "expires_in": 3600}
        self.during = lambda req: a.signOut() if "api/token" in req.full_url else None
        a.refresh()
        self.assertFalse(a.linked)
        self.assertFalse(self.login.exists())            # the rotated token isn't saved back
        self.assertEqual(a.songs, [])
        self.assertEqual(self.settings["spotifyLibrary"], "{}")
        self.assertFalse(a.loading)

    def test_signing_out_during_a_library_read_stays_signed_out(self):
        a = self.linked_account()
        self.now += 7200
        self.during = lambda req: a.signOut() if "/me/tracks" in req.full_url else None
        a.refresh()
        self.assertFalse(a.linked)
        self.assertFalse(self.login.exists())
        self.assertEqual((a.playlists, a.albums, a.songs), ([], [], []))
        self.assertEqual(self.settings["spotifyLibrary"], "{}")
        self.assertFalse(a.loading)

    def test_signing_out_while_linking_finishes_unlinked(self):
        a = self.account()
        a.startLink("172.20.10.14", 8780)
        self.during = lambda req: a.signOut()
        a.callback("code", a._link["state"], "")
        self.assertFalse(a.linked)
        self.assertFalse(self.login.exists())
        self.assertEqual(a.songs, [])

    def test_an_old_answer_doesnt_undo_a_new_link(self):
        a = self.linked_account()
        a.signOut()
        a._loaded.emit({"playlists": [], "albums": [], "songs": [{"name": "old"}]}, "", False, 0)
        self.assertEqual(a.songs, [])
        a.startLink("172.20.10.14", 8780)
        a.callback("code", a._link["state"], "")
        a._loaded.emit(None, "x", True, 0)               # the old refresh reporting a sign-out
        self.assertTrue(a.linked)

    def test_relinking_during_a_stale_library_read_still_loads_the_library(self):
        a = self.linked_account()
        self.now += 7200

        def relink(req):
            if "/me/tracks" in req.full_url:
                self.during = None
                a.signOut()
                a.startLink("172.20.10.14", 8780)
                a.callback("code", a._link["state"], "")   # its own refresh is skipped: the old one is running
        self.during = relink
        a.refresh()
        self.assertTrue(a.linked)
        self.assertEqual(len(a.songs), 1)
        self.assertFalse(a.loading)

    def test_no_login_means_no_renewal(self):
        a = self.account()
        self.assertFalse(a.linked)
        a.refresh()
        self.assertEqual(self.token_posts(), [])

    def test_a_broken_login_file_just_means_not_linked(self):
        self.login.write_text("{nonsense")
        self.assertFalse(self.account().linked)

    def test_tokens_stay_out_of_the_log(self):
        a = self.linked_account()
        self.now += 7200
        self.token_answer = KeyError("refresh")
        a.refresh()
        self.assertNotIn("ref", str([c for c in self.print.call_args_list if "acc" in str(c)]))


class LibraryTest(AccountCase):
    def test_one_refused_list_keeps_the_others(self):
        a = self.linked_account()
        self.answers["tracks"] = http_error(403)
        self.answers["playlists"] = {"items": []}
        a.refresh()
        self.assertEqual((a.playlists, len(a.songs)), ([], 1))

    def test_an_expired_token_is_replaced_once(self):
        a = self.linked_account()
        self.answers["playlists"] = [http_error(401), PLAYLISTS]
        a.refresh()
        self.assertEqual(a.message, "")

    def test_it_catches_up_when_online_but_not_every_time(self):
        a = self.linked_account()
        count = len(self.requests)
        a.set_online(True)
        self.assertEqual(len(self.requests), count)
        self.now += REFRESH_EVERY_S + 1
        a.set_online(True)
        self.assertGreater(len(self.requests), count)

    def test_a_failed_read_is_retried_with_backing_off(self):
        a = self.linked_account()
        self.answers["playlists"] = http_error(503)
        a.refresh()
        self.assertEqual(a.message, "Can't reach Spotify right now")
        waits = []
        for _ in range(8):
            self.assertTrue(a._retry.isActive())
            waits.append(a._retry.interval() / 1000)
            a._retry.stop()
            a._retry.timeout.emit()               # the timer fires and the read fails again
        self.assertEqual(waits[:3], [RETRY_FIRST_S, RETRY_FIRST_S * 2, RETRY_FIRST_S * 4])
        self.assertEqual(waits[-1], RETRY_MAX_S)

    def test_the_retry_reads_the_library_when_spotify_is_back(self):
        a = self.linked_account()
        self.answers["playlists"] = [http_error(503), http_error(503), http_error(503), PLAYLISTS]
        a.refresh()
        self.assertTrue(a._retry.isActive())
        a._retry.stop()
        a._retry.timeout.emit()
        self.assertEqual((a.message, len(a.songs)), ("", 1))
        self.assertFalse(a._retry.isActive())
        self.assertEqual(a._retry_s, RETRY_FIRST_S)

    def test_a_manual_refresh_cancels_the_waiting_retry(self):
        a = self.linked_account()
        self.answers["playlists"] = [http_error(503)] * 3
        a.refresh()
        self.assertTrue(a._retry.isActive())
        self.answers["playlists"] = {"items": []}
        a.refresh()
        self.assertFalse(a._retry.isActive())

    def test_signing_out_stops_retrying(self):
        a = self.linked_account()
        self.answers["playlists"] = http_error(503)
        a.refresh()
        self.assertTrue(a._retry.isActive())
        a.signOut()
        self.assertFalse(a._retry.isActive())

    def test_spotify_ending_the_sign_in_is_not_retried(self):
        a = self.linked_account()
        self.answers["playlists"] = http_error(401)
        self.token_answer = http_error(400, b"invalid_grant")
        a._access = ""
        a.refresh()
        self.assertFalse(a.linked)
        self.assertFalse(a._retry.isActive())

    def test_not_linked_it_reads_nothing(self):
        a = self.account()
        a.start()
        a.set_online(True)
        self.assertEqual(self.requests, [])


if __name__ == "__main__":
    unittest.main()
