"""Off-Pi tests for the knob when libgpiod raises something other than the
OSError or ValueError it used to expect while requesting its pins
(backend/knob.py): the knob keeps going, and the failure is named once.

    python3 -m unittest tests.test_knob_request_errors
"""

import contextlib
import io
import unittest
from unittest import mock

try:
    from backend import knob
    from tests.test_knob import FakeLines, FakeValue, Stop, frame
except ImportError as e:
    raise unittest.SkipTest(f"PyQt6 isn't installed ({e})")


class RequestErrorsTest(unittest.TestCase):
    # Steps of -1 each, so -4 in all: one click, which the knob reports as turned(+1)
    CLICK = [frame(1), frame(0), frame(2), frame(knob.REST)]

    def start(self, request_results):
        """A knob on fake pins. request_lines gives each result in turn: lines, or an exception."""
        self.gpiod = mock.Mock()
        self.gpiod.request_lines.side_effect = request_results
        patches = [
            mock.patch.multiple(knob, create=True, gpiod=self.gpiod, Direction=mock.Mock(),
                                Bias=mock.Mock(), Edge=mock.Mock(), Value=FakeValue),
            mock.patch.object(knob.time, "sleep"),
            mock.patch.object(knob.errorlog, "log"),
        ]
        started = [p.start() for p in patches]
        for p in patches:
            self.addCleanup(p.stop)
        self.sleep, self.log = started[1], started[2]
        self.knob = knob.Knob()
        self.seen = []
        self.knob.turned.connect(lambda n: self.seen.append(("turned", n)))
        self.knob.pressed.connect(lambda: self.seen.append("pressed"))
        self.knob.released.connect(lambda: self.seen.append("released"))

    def test_an_unexpected_error_while_re_requesting_the_pins_does_not_end_the_knob(self):
        lines = FakeLines([frame(knob.REST), OSError("gpio hiccup")] + self.CLICK)
        # the re-request fails twice (one failed try, both debounce attempts), then works
        self.start([lines, RuntimeError("chip gone"), RuntimeError("chip gone"), lines])
        with self.assertRaises(Stop):
            self.knob._run()
        self.assertEqual(self.seen, [("turned", 1)])

    def test_at_start_an_unexpected_error_means_no_knob_and_no_exception(self):
        self.start([RuntimeError("no pins"), TypeError("half torn down")])
        self.knob._run()                 # returns normally, rather than raising into the thread
        self.assertEqual(self.gpiod.request_lines.call_count, 2)     # the two debounce tries, no more
        self.sleep.assert_not_called()
        self.assertEqual(self.seen, [])

    def test_the_same_failure_is_printed_once_not_on_every_retry(self):
        lines = FakeLines([frame(knob.REST), OSError("gpio hiccup")] + self.CLICK)
        # three failed tries (six calls) with the same error, then the pins come back
        self.start([lines] + [RuntimeError("chip gone")] * 6 + [lines])
        out = io.StringIO()
        with contextlib.redirect_stdout(out), self.assertRaises(Stop):
            self.knob._run()
        printed = out.getvalue().splitlines()
        self.assertEqual(printed.count("Knob: couldn't request the pins: RuntimeError: chip gone"), 1)
        self.assertEqual(self.seen, [("turned", 1)])


if __name__ == "__main__":
    unittest.main()
