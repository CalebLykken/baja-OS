"""Off-Pi tests for how backend/network.py reads nmcli's output: a visible
network whose name isn't valid UTF-8 must not make the check raise, and
terse-mode escapes ('\\:' and '\\\\') are undone in the Wi-Fi name. nmcli is
faked, so nothing runs.

    python3 -m unittest tests.test_network_nmcli_output
"""

import unittest
from types import SimpleNamespace
from unittest import mock

from backend.network import nm_connectivity, nmcli_unescape, wifi_name


def fake_nmcli(stdout="", code=0):
    return mock.patch("backend.network.subprocess.run",
                      return_value=SimpleNamespace(stdout=stdout, returncode=code))


NMCLI = mock.patch("backend.network.shutil.which", return_value="/usr/bin/nmcli")
BAD_UTF8 = UnicodeDecodeError("utf-8", b"\xff", 0, 1, "bad")


class WifiNameUnescapeTest(unittest.TestCase):
    def test_colon_in_name_is_unescaped(self):
        with NMCLI, fake_nmcli("no:Other\nyes:Cafe\\: Guest\n"):
            self.assertEqual(wifi_name(), "Cafe: Guest")

    def test_escaped_backslash_becomes_one_backslash(self):
        with NMCLI, fake_nmcli("yes:a\\\\b\n"):
            self.assertEqual(wifi_name(), "a\\b")

    def test_escaped_backslash_then_escaped_colon(self):
        # the text \\\: in the output is a backslash followed by an escaped colon
        with NMCLI, fake_nmcli("yes:x\\\\\\:y\n"):
            self.assertEqual(wifi_name(), "x\\:y")

    def test_plain_name_is_unchanged(self):
        with NMCLI, fake_nmcli("no:Cafe\nyes:Phone\n"):
            self.assertEqual(wifi_name(), "Phone")

    def test_no_active_network_is_empty(self):
        with NMCLI, fake_nmcli("no:Cafe\n"):
            self.assertEqual(wifi_name(), "")

    def test_unescape_helper(self):
        self.assertEqual(nmcli_unescape("Cafe\\: Guest"), "Cafe: Guest")
        self.assertEqual(nmcli_unescape("a\\\\b"), "a\\b")
        self.assertEqual(nmcli_unescape("trailing\\"), "trailing\\")
        self.assertEqual(nmcli_unescape(""), "")


class BadUtf8OutputTest(unittest.TestCase):
    def test_wifi_name_survives_undecodable_listing(self):
        with NMCLI, mock.patch("backend.network.subprocess.run", side_effect=BAD_UTF8):
            self.assertEqual(wifi_name(), "")

    def test_nm_connectivity_survives_undecodable_output(self):
        with NMCLI, mock.patch("backend.network.subprocess.run", side_effect=BAD_UTF8):
            self.assertIsNone(nm_connectivity())

    def test_value_error_from_run_is_caught_in_both(self):
        with NMCLI, mock.patch("backend.network.subprocess.run", side_effect=ValueError("bad")):
            self.assertEqual(wifi_name(), "")
            self.assertIsNone(nm_connectivity())

    def test_wifi_name_decodes_with_replace(self):
        with NMCLI, fake_nmcli("yes:Phone\n") as run:
            wifi_name()
        self.assertEqual(run.call_args.kwargs["errors"], "replace")
        self.assertTrue(run.call_args.kwargs["text"])
        self.assertTrue(run.call_args.kwargs["capture_output"])
        self.assertEqual(run.call_args.kwargs["timeout"], 3)

    def test_nm_connectivity_decodes_with_replace(self):
        with NMCLI, fake_nmcli("full\n") as run:
            self.assertEqual(nm_connectivity(), "full")
        self.assertEqual(run.call_args.kwargs["errors"], "replace")
        self.assertTrue(run.call_args.kwargs["text"])
        self.assertTrue(run.call_args.kwargs["capture_output"])
        self.assertEqual(run.call_args.kwargs["timeout"], 3)


if __name__ == "__main__":
    unittest.main()
