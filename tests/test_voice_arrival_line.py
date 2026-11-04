"""Spoken arrival lines: variety on the destination line only."""
import unittest
from datetime import datetime

from backend import voice
from backend.voice import arrival_line

FIRST = lambda options: options[0]
DEST = "You have arrived at Cabin."


def at(hour, minute=0):
    return datetime(2026, 11, 4, hour, minute)


class ArrivalLineTests(unittest.TestCase):
    def test_time_buckets(self):
        self.assertEqual(arrival_line(DEST, at(8), FIRST),
                         "Made it to Cabin. Have a good morning.")
        self.assertEqual(arrival_line(DEST, at(19), FIRST),
                         "Here we are, Cabin. Enjoy your evening.")
        self.assertEqual(arrival_line(DEST, at(23, 30), FIRST),
                         "Cabin. Made it, drive safe getting in.")

    def test_home(self):
        out = arrival_line("You have arrived at  home .", at(8), FIRST)
        self.assertEqual(out, "Home sweet home.")

    def test_other_lines_unchanged(self):
        for line in ("You have arrived at A. Continuing to B.",
                     "Turn left onto Main Street."):
            self.assertEqual(arrival_line(line, at(8), FIRST), line)

    def test_every_option_has_name_and_no_braces(self):
        for hour in (3, 8, 13, 19, 23):
            options = []

            def collect(opts):
                options.extend(opts)
                return opts[0]
            arrival_line(DEST, at(hour), collect)
            self.assertTrue(options)
            self.assertIn("You have arrived at {n}.", options)
            for opt in options:
                out = opt.replace("{n}", "Cabin")
                self.assertIn("Cabin", out)
                self.assertNotIn("{", out)
                self.assertNotIn("}", out)

    def test_pick_that_raises_returns_original(self):
        def boom(_):
            raise RuntimeError("x")
        self.assertEqual(arrival_line(DEST, at(8), boom), DEST)


if __name__ == "__main__":
    unittest.main()
