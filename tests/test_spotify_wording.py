"""Off-Pi check that the Spotify messages the driver sees read the same way:
a short plain statement, a hint only as a second sentence, no ';' or ': '
joining clauses, and no full stop at the end. Every message path the other
Spotify tests fake is driven here, and each message is checked.

    python3 -m unittest tests.test_spotify_wording
"""

import contextlib
import io
import json
import tempfile
import unittest
import urllib.error
from pathlib import Path
from types import SimpleNamespace
from unittest import mock

try:
    from PyQt6.QtCore import QCoreApplication
    from backend import spotifysearch
    from backend.spotify import SpotifyPlayer
    from backend.spotifysearch import SpotifySearch
    from tests.test_spotifyaccount import AccountCase, http_error
except ImportError as e:
    raise unittest.SkipTest(f"PyQt6 isn't installed ({e})")

app = QCoreApplication.instance() or QCoreApplication([])


class InlineThread:
    def __init__(self, target=None, daemon=None):
        self.target = target

    def start(self):
        self.target()


def assertHouseStyle(test, message):
    test.assertTrue(message, "every message path must say something")
    test.assertNotIn(";", message)
    test.assertNotIn(": ", message)
    test.assertFalse(message.endswith("."), message)
    test.assertLessEqual(message.count(". "), 1, message)


class PlayerWordingTest(unittest.TestCase):
    def test_error_messages(self):
        sp = SpotifyPlayer()
        for message in ("429 too many requests", "authentication required"):
            with contextlib.redirect_stdout(io.StringIO()):
                sp._on_message(json.dumps({"type": "error", "message": message}))
            assertHouseStyle(self, sp.error)


class SearchWordingTest(unittest.TestCase):
    def setUp(self):
        folder = tempfile.TemporaryDirectory()
        self.addCleanup(folder.cleanup)
        self.path = Path(folder.name) / "search.env"
        self.path.write_text("SPOTIFY_CLIENT_ID=abc\nSPOTIFY_CLIENT_SECRET=def\n")
        self.search = SpotifySearch(self.path)
        self.answers = {}
        self.addCleanup(mock.patch.stopall)
        mock.patch.object(spotifysearch.urllib.request, "urlopen", self.urlopen).start()
        mock.patch.object(spotifysearch, "threading", SimpleNamespace(
            Thread=InlineThread, Lock=spotifysearch.threading.Lock)).start()
        mock.patch("backend.retry.time.sleep").start()
        mock.patch("builtins.print").start()

    def urlopen(self, req, timeout=None):
        answer = self.answers.get("token" if "token" in req.full_url else "search")
        if isinstance(answer, Exception):
            raise answer
        if answer is None:
            answer = {"access_token": "tok", "expires_in": 3600} if "token" in req.full_url else {}
        return mock.MagicMock(__enter__=lambda s: io.BytesIO(json.dumps(answer).encode()))

    def test_search_messages(self):
        cases = [
            ({"search": {}}, "zzz"),
            ({"search": http_error(429)}, "a"),
            ({"token": http_error(400)}, "a"),
            ({"token": urllib.error.URLError("offline")}, "a"),
        ]
        for answers, text in cases:
            self.answers = answers
            self.search.search(text)
            assertHouseStyle(self, self.search.message)
        with mock.patch.object(spotifysearch, "parse_results", side_effect=RuntimeError("boom")), \
                mock.patch.object(spotifysearch.errorlog.log, "report"):
            self.answers = {"search": {"tracks": {"items": []}}}
            self.search.search("a")
        assertHouseStyle(self, self.search.message)


class AccountWordingTest(AccountCase):
    def test_library_messages(self):
        a = self.linked_account()
        self.now += 7200
        self.token_answer = urllib.error.URLError("offline")
        a.refresh()
        assertHouseStyle(self, a.message)

        a = self.linked_account()
        self.answers["playlists"] = TypeError("odd shape")
        a.refresh()
        assertHouseStyle(self, a.message)

        a = self.linked_account()
        self.answers["playlists"] = http_error(401)
        self.token_answer = http_error(400, b"invalid_grant")
        a._access = ""
        a.refresh()
        assertHouseStyle(self, a.message)
