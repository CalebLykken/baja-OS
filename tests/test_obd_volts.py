"""Off-Pi tests for the battery reading (`Elm.volts`, backend/obd.py): only a
plausible ATRV reply becomes a voltage. A garbled, cut-short or impossible
reply is None, and the reader emits nothing and keeps its last good reading.

    python3 -m unittest tests.test_obd_volts
"""

import unittest

from PyQt6.QtCore import QCoreApplication

from backend.obd import Elm, ObdReader

app = QCoreApplication.instance() or QCoreApplication([])


class RepliesElm(Elm):
    """An adapter that answers ATRV with `reply`, without a serial port."""

    def __init__(self, reply):
        self.reply = reply
        self.asked = []

    def send(self, command, timeout=3.0):
        self.asked.append(command)
        return self.reply


def volts_of(reply):
    return RepliesElm(reply).volts()


class VoltsParsingTests(unittest.TestCase):

    def test_a_plausible_reply_is_the_voltage(self):
        self.assertEqual(volts_of("12.6V"), 12.6)
        self.assertEqual(volts_of("14.1V"), 14.1)
        self.assertEqual(volts_of("12.6"), 12.6)            # no V
        self.assertEqual(volts_of(" 13.8V "), 13.8)         # padding stripped
        self.assertEqual(volts_of("12V"), 12.0)

    def test_the_command_still_goes_through_send(self):
        elm = RepliesElm("12.6V")
        elm.volts()
        self.assertEqual(elm.asked, ["ATRV"])

    def test_garbled_replies_are_none(self):
        for reply in ("nan", "NANV", "inf", "1e3", "12_6", "?", "NO DATA", "", "ATRV 12.6V"):
            with self.subTest(reply=reply):
                self.assertIsNone(volts_of(reply))

    def test_truncated_replies_are_none(self):
        for reply in ("1", "12.", "1.", "12.6V5"):
            with self.subTest(reply=reply):
                self.assertIsNone(volts_of(reply))

    def test_impossible_voltages_are_none(self):
        for reply in ("99.9V", "0.0V", "0V", "5.9V", "20.5V"):
            with self.subTest(reply=reply):
                self.assertIsNone(volts_of(reply))

    def test_the_range_ends_are_kept(self):
        self.assertEqual(volts_of("6.0V"), 6.0)
        self.assertEqual(volts_of("20V"), 20.0)


class VoltsReaderTests(unittest.TestCase):

    def test_a_junk_reading_is_not_emitted_and_the_last_good_one_stands(self):
        reader = ObdReader()
        emitted = []
        reader.voltage.connect(emitted.append)
        reader._volts(RepliesElm("12.6V"))
        self.assertEqual(reader._volts_last, 12.6)
        reader._volts(RepliesElm("1"))                      # truncated reply
        reader._volts(RepliesElm("nan"))
        reader._volts(RepliesElm("99.9V"))
        self.assertEqual(emitted, [12.6])
        self.assertEqual(reader._volts_last, 12.6)


if __name__ == "__main__":
    unittest.main()
