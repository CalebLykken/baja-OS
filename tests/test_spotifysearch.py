"""Off-Pi tests for backend/spotifysearch.py: Spotify's answers are read
without tripping over its nulls, the app token is kept and renewed, a stale
answer isn't shown, and each way of failing says something useful. Nothing
leaves the machine: urlopen is faked, and the worker runs where it's started.

    python3 -m unittest tests.test_spotifysearch
"""

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
    from backend.spotifysearch import SpotifySearch, parse_results, read_credentials
except ImportError as e:
    raise unittest.SkipTest(f"PyQt6 isn't installed ({e})")

app = QCoreApplication.instance() or QCoreApplication([])

COVERS = [{"url": "https://i/640", "width": 640}, {"url": "https://i/300", "width": 300},
          {"url": "https://i/64", "width": 64}]
ANSWER = {"tracks": {"items": [{"uri": "spotify:track:t", "name": "Song", "artists": [{"name": "A"}, {"name": "B"}],
                                "album": {"images": COVERS}}]},
          "albums": {"items": [{"uri": "spotify:album:a", "name": "LP", "artists": [{"name": "A"}], "images": COVERS}]},
          "playlists": {"items": [None, {"uri": "spotify:playlist:p", "name": "Mix",
                                         "owner": {"display_name": "Sam"}, "images": None}]}}


def reply(data):
    return mock.MagicMock(__enter__=lambda s: io.BytesIO(json.dumps(data).encode()))


def http_error(code):
    return urllib.error.HTTPError("https://x", code, "no", {}, None)


class InlineThread:
    def __init__(self, target=None, daemon=None):
        self.target = target

    def start(self):
        self.target()


class ReadingAnswersTest(unittest.TestCase):
    def test_songs_then_albums_then_playlists(self):
        out = parse_results(ANSWER)
        self.assertEqual([r["kind"] for r in out], ["track", "album", "playlist"])
        self.assertEqual(out[0], {"uri": "spotify:track:t", "kind": "track", "title": "Song",
                                  "subtitle": "A, B", "art": "https://i/64"})
        self.assertEqual(out[1]["subtitle"], "Album, A")
        self.assertEqual((out[2]["subtitle"], out[2]["art"]), ("Playlist, Sam", ""))

    def test_odd_answers_show_nothing_rather_than_raise(self):
        for odd in ({}, [], None, {"tracks": None}, {"tracks": {"items": None}},
                    {"tracks": {"items": [None, 7, {}, {"uri": "x"}]}}):
            self.assertEqual(parse_results(odd), [])

    def test_a_song_with_no_album_or_artists(self):
        out = parse_results({"tracks": {"items": [{"uri": "u", "name": "n", "album": None, "artists": None}]}})
        self.assertEqual((out[0]["art"], out[0]["subtitle"]), ("", ""))

    def test_a_section_that_is_not_a_list_of_items_is_skipped(self):
        self.assertEqual(parse_results({"tracks": [1, 2], "albums": "x",
                                        "playlists": {"items": [None, {"uri": 5, "name": "n"}]}}), [])

    def test_a_cover_width_given_as_text_counts_as_zero(self):
        images = [{"url": "a", "width": "300"}, {"url": "b", "width": "64"}]
        out = parse_results({"tracks": {"items": [{"uri": "u", "name": "n", "album": {"images": images}}]}})
        self.assertEqual(out[0]["art"], "b")

    def test_odd_shapes_inside_an_item_do_not_raise(self):
        item = {"uri": "u", "name": "n", "artists": [{"name": 3}, "x", {"name": "A"}],
                "album": ["not", "a", "dict"], "owner": ["x"], "images": 7}
        out = parse_results({"tracks": {"items": [item]}, "albums": {"items": [dict(item, images="abc")]},
                             "playlists": {"items": [dict(item, uri=["u"])]}})
        self.assertEqual([r["subtitle"] for r in out], ["A", "Album, A"])
        self.assertEqual([r["art"] for r in out], ["", ""])


class CredentialsTest(unittest.TestCase):
    def setUp(self):
        folder = tempfile.TemporaryDirectory()
        self.addCleanup(folder.cleanup)
        self.path = Path(folder.name) / "search.env"

    def test_read(self):
        self.path.write_text("SPOTIFY_CLIENT_ID=abc\nSPOTIFY_CLIENT_SECRET=d=ef\n")
        self.assertEqual(read_credentials(self.path), ("abc", "d=ef"))

    def test_missing_or_partial(self):
        self.assertEqual(read_credentials(self.path), ("", ""))
        self.path.write_text("SPOTIFY_CLIENT_ID=abc\n")
        self.assertEqual(read_credentials(self.path), ("", ""))


class SearchTest(unittest.TestCase):
    def setUp(self):
        folder = tempfile.TemporaryDirectory()
        self.addCleanup(folder.cleanup)
        self.path = Path(folder.name) / "search.env"
        self.path.write_text("SPOTIFY_CLIENT_ID=abc\nSPOTIFY_CLIENT_SECRET=def\n")
        self.search = SpotifySearch(self.path)
        self.urls = []
        self.answers = {}
        self.now = 100.0
        self.addCleanup(mock.patch.stopall)
        mock.patch.object(spotifysearch.urllib.request, "urlopen", self.urlopen).start()
        mock.patch.object(spotifysearch, "threading", SimpleNamespace(
            Thread=InlineThread, Lock=spotifysearch.threading.Lock)).start()
        mock.patch.object(spotifysearch.time, "monotonic", lambda: self.now).start()
        mock.patch("backend.retry.time.sleep").start()
        self.print = mock.patch("builtins.print").start()

    def urlopen(self, req, timeout=None):
        token = "token" in req.full_url
        self.urls.append(req)
        answer = self.answers.get("token" if token else "search")
        if isinstance(answer, list):
            answer = answer.pop(0)
        if isinstance(answer, Exception):
            raise answer
        return reply(answer if answer is not None else
                     ({"access_token": "tok", "expires_in": 3600} if token else ANSWER))

    def token_calls(self):
        return sum("token" in r.full_url for r in self.urls)

    def test_a_search(self):
        self.search.search("  song  ")
        self.assertEqual([r["title"] for r in self.search.results], ["Song", "LP", "Mix"])
        self.assertFalse(self.search.searching)
        asked = self.urls[-1]
        self.assertEqual(asked.get_header("Authorization"), "Bearer tok")
        self.assertIn("q=song&type=track%2Calbum%2Cplaylist&limit=6", asked.full_url)

    def test_the_limit_is_within_developer_mode(self):
        self.assertLessEqual(spotifysearch.LIMIT, 10)

    def test_the_token_is_kept_then_renewed(self):
        self.search.search("a")
        self.search.search("b")
        self.assertEqual(self.token_calls(), 1)
        self.now += 3600
        self.search.search("c")
        self.assertEqual(self.token_calls(), 2)

    def test_a_token_turned_down_early_is_replaced_once(self):
        self.answers["search"] = [http_error(401), ANSWER]
        self.search.search("a")
        self.assertEqual(self.token_calls(), 2)
        self.assertEqual(len(self.search.results), 3)

    def test_a_token_answer_with_no_token_is_a_failure_to_reach(self):
        self.answers["token"] = [[]]
        self.search.search("a")
        self.assertIn("hotspot", self.search.message)
        self.assertFalse(self.search.searching)

    def test_an_unexpected_error_says_so_and_stops_searching(self):
        report = mock.patch.object(spotifysearch.errorlog.log, "report").start()
        with mock.patch.object(spotifysearch, "parse_results", side_effect=RuntimeError("boom")):
            self.search.search("a")
        self.assertFalse(self.search.searching)
        self.assertEqual(self.search.message, "Spotify search went wrong; try again")
        self.assertEqual(report.call_args.kwargs["label"], "Spotify search failed:")

    def test_nothing_found(self):
        self.answers["search"] = {}
        self.search.search("zzz")
        self.assertEqual(self.search.message, "Nothing on Spotify for zzz")

    def test_rate_limited(self):
        self.answers["search"] = http_error(429)
        self.search.search("a")
        self.assertIn("busy", self.search.message)

    def test_a_wrong_secret(self):
        self.answers["token"] = http_error(400)
        self.search.search("a")
        self.assertIn("app key", self.search.message)

    def test_no_internet(self):
        self.answers["token"] = urllib.error.URLError("offline")
        self.search.search("a")
        self.assertIn("hotspot", self.search.message)
        self.assertFalse(self.search.searching)

    def test_the_secret_never_reaches_the_log(self):
        self.answers["token"] = http_error(400)
        self.search.search("a")
        self.assertNotIn("def", str(self.print.call_args_list).replace("default", ""))

    def test_a_stale_answer_is_dropped(self):
        self.search._newest = 2
        self.search._on_answered(1, [{"title": "old"}], "")
        self.assertEqual(self.search.results, [])

    def test_clearing_drops_an_answer_on_its_way(self):
        self.search._newest = 1
        self.search.clear()
        self.search._on_answered(1, [{"title": "late"}], "")
        self.assertEqual(self.search.results, [])

    def test_blank_or_unset_does_nothing(self):
        self.search.search("   ")
        self.path.unlink()
        self.assertFalse(self.search.available)
        self.search.search("song")
        self.assertEqual(self.urls, [])


if __name__ == "__main__":
    unittest.main()
