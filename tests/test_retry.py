"""Back-off helper and the short-link use of it: fake errors and a fake clock, no network."""

import email.message
import json
import tempfile
import unittest
import urllib.error
from pathlib import Path
from unittest import mock

try:
    from PyQt6.QtCore import QCoreApplication
    from backend import phone, retry
except ImportError as e:
    raise unittest.SkipTest(f"PyQt6 isn't installed ({e})")

app = QCoreApplication.instance() or QCoreApplication([])


def http_error(code, retry_after=None, location=None):
    headers = email.message.Message()
    if retry_after is not None:
        headers["Retry-After"] = str(retry_after)
    if location:
        headers["Location"] = location
    return urllib.error.HTTPError("https://x/", code, "err", headers, None)


class RetryTest(unittest.TestCase):
    def run_call(self, errors, **kw):
        """call() over a function that raises `errors` in turn, then returns 'ok'."""
        errors = list(errors)

        def fn():
            if errors:
                raise errors.pop(0)
            return "ok"
        with mock.patch.object(retry.time, "sleep") as sleep:
            try:
                result = retry.call(fn, **kw)
            except Exception as e:
                result = e
        return result, [c.args[0] for c in sleep.call_args_list]

    def test_backoff_doubles_and_is_capped(self):
        self.assertEqual([retry.backoff(n, 1, 5) for n in range(5)], [1, 2, 4, 5, 5])

    def test_timeouts_and_5xx_are_retried_with_growing_waits(self):
        result, waits = self.run_call([TimeoutError(), http_error(503), OSError("down")], tries=4)
        self.assertEqual((result, waits), ("ok", [1.0, 2.0, 4.0]))

    def test_429_honours_retry_after_within_the_cap(self):
        self.assertEqual(self.run_call([http_error(429, 3)])[1], [3.0])
        self.assertEqual(self.run_call([http_error(429, 600)], cap=8)[1], [8])
        self.assertEqual(self.run_call([http_error(429, "soon")])[1], [1.0])

    def test_a_404_is_not_retried(self):
        result, waits = self.run_call([http_error(404)])
        self.assertEqual((result.code, waits), (404, []))

    def test_gives_up_after_the_last_try(self):
        result, waits = self.run_call([http_error(500)] * 5, tries=3)
        self.assertEqual((result.code, len(waits)), (500, 2))


class ShortLinkTest(unittest.TestCase):
    URL = "https://maps.app.goo.gl/abc"
    PLACE = "https://www.google.com/maps/place/Pike/@47.6097,-122.3422,17z"

    def expand(self, outcomes):
        opener = mock.Mock()
        opener.open.side_effect = outcomes
        with mock.patch.object(phone.urllib.request, "build_opener", return_value=opener), \
                mock.patch.object(retry.time, "sleep") as sleep:
            try:
                got = phone.expand_short_link(self.URL)
            except phone.LinkUnreachable:
                got = "unreachable"
            return got, opener.open.call_count, sleep.call_count

    def test_redirect_location_is_the_answer(self):
        self.assertEqual(self.expand([http_error(302, location=self.PLACE)]), (self.PLACE, 1, 0))

    def test_a_429_then_a_redirect_works(self):
        self.assertEqual(self.expand([http_error(429, 1), http_error(302, location=self.PLACE)]),
                         (self.PLACE, 2, 1))

    def test_offline_is_reported_after_one_retry(self):
        self.assertEqual(self.expand([OSError("no route")] * 2), ("unreachable", 2, 1))

    def test_a_404_just_hands_the_link_back(self):
        self.assertEqual(self.expand([http_error(404)]), (self.URL, 1, 0))

    def test_resolve_says_the_link_could_not_be_opened(self):
        with tempfile.TemporaryDirectory() as tmp:
            Path(tmp, "region.json").write_text(json.dumps({"region": "WA", "bbox": [-125, 45, -116, 49]}))
            with mock.patch.object(phone, "expand_short_link", side_effect=phone.LinkUnreachable(self.URL)):
                with self.assertRaisesRegex(ValueError, "Couldn't open that link"):
                    phone.resolve({"urls": [self.URL]}, tmp)


if __name__ == "__main__":
    unittest.main()
