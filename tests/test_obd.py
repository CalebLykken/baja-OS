"""Off-Pi tests for the OBD reader (backend/obd.py): the PID support bitmaps,
the outside air pressure that boost is measured against, and what it keeps
for a restart with the engine already running. The adapter is a canned set
of ELM327 replies.

    python3 -m unittest tests.test_obd
"""

import contextlib
import io
import unittest
from unittest import mock

from PyQt6.QtCore import QCoreApplication

from backend import obd
from backend.obd import BARO_DEFAULT, Elm, ObdReader, convert, pid_supported

app = QCoreApplication.instance() or QCoreApplication([])

PSI = 0.145038                    # psi per kPa

# What a 2005 Baja's engine computer might say it supports. PID 0x00 lists
# 01-20 (the last bit says 0x20 is there), PID 0x20 lists 21-40.
LOW = "41 00 98 3A 80 13"         # includes 0x0B, 0x0C, 0x0D, 0x20
HIGH_WITH_BARO = "41 20 00 00 20 00"     # 0x33
HIGH_WITHOUT = "41 20 00 00 00 01"       # only 0x40
IDLING = {"010C": "41 0C 0C 80", "010B": "41 0B 28", "010D": "41 0D 00",   # 800 rpm, 40 kPa
          "0105": "41 05 5F", "010F": "41 0F 3C", "ATRV": "13.8V"}


class CannedElm(Elm):
    """The adapter's replies without a serial port: `replies` maps a command
    to its reply text, or to a list of replies to give one after another
    (the last one repeats). Anything else says NO DATA, as does everything
    once RPM has been asked for more than `rounds` times."""

    def __init__(self, replies, rounds=None):
        self.replies = {c: list(r) if isinstance(r, list) else [r] for c, r in replies.items()}
        self.rounds = rounds
        self.asked = []

    def send(self, command, timeout=3.0):
        self.asked.append(command)
        if self.rounds is not None and self.asked.count("010C") > self.rounds:
            return "NO DATA"
        replies = self.replies.get(command)
        if not replies:
            return "NO DATA"
        return replies.pop(0) if len(replies) > 1 else replies[0]


def support(low=LOW, high=HIGH_WITH_BARO):
    return {"0100": low, "0120": high}


def poll(reader, elm):
    """Run the reader's polling loop over `elm` until the car stops
    answering; returns the readings and the baros it asked to keep."""
    readings, kept = [], []
    reader.reading.connect(readings.append)
    reader.baro.connect(kept.append)
    with mock.patch.object(obd, "ROUND_MIN_S", 0), contextlib.redirect_stdout(io.StringIO()):
        reader._poll(elm)
    return readings, kept


def last_boost(readings):
    return [r["boost"] for r in readings if "boost" in r][-1]


class BitmapTest(unittest.TestCase):
    def test_a_bit_per_pid_from_the_top(self):
        bitmap = [0x98, 0x3A, 0x80, 0x13]
        listed = [p for p in range(0x01, 0x21) if pid_supported(bitmap, 0x00, p)]
        self.assertEqual(listed, [0x01, 0x04, 0x05, 0x0B, 0x0C, 0x0D, 0x0F, 0x11, 0x1C, 0x1F, 0x20])

    def test_the_second_bitmap_starts_at_0x21(self):
        self.assertTrue(pid_supported([0x80, 0, 0, 0], 0x20, 0x21))
        self.assertTrue(pid_supported([0, 0, 0x20, 0], 0x20, 0x33))
        self.assertFalse(pid_supported([0xFF, 0xFF, 0xDF, 0xFF], 0x20, 0x33))
        self.assertTrue(pid_supported([0, 0, 0, 0x01], 0x20, 0x40))

    def test_a_pid_outside_the_bitmap_or_no_bitmap(self):
        self.assertFalse(pid_supported([0xFF] * 4, 0x20, 0x20))
        self.assertFalse(pid_supported([0xFF] * 4, 0x20, 0x41))
        self.assertFalse(pid_supported([0xFF] * 4, 0x00, 0x33))
        self.assertFalse(pid_supported(None, 0x20, 0x33))
        self.assertFalse(pid_supported([0xFF, 0xFF], 0x20, 0x33))


class FindingBaroPidTest(unittest.TestCase):
    """Whether the car answers PID 0x33, from the two support bitmaps."""

    def ask(self, replies):
        elm = CannedElm(replies)
        with contextlib.redirect_stdout(io.StringIO()) as out:
            found = ObdReader()._ask_baro_pid(elm)
        return found, elm.asked, out.getvalue()

    def test_supported(self):
        found, asked, out = self.ask(support())
        self.assertIs(found, True)
        self.assertEqual(asked, ["0100", "0120"])
        self.assertIn("98 3a 80 13", out)                # the journal shows what the car supports
        self.assertIn("00 00 20 00", out)
        self.assertIn("barometric pressure: yes", out)

    def test_not_in_the_second_bitmap(self):
        found, asked, out = self.ask(support(high=HIGH_WITHOUT))
        self.assertIs(found, False)
        self.assertIn("barometric pressure: no", out)

    def test_no_second_bitmap(self):
        found, asked, out = self.ask(support(low="41 00 98 3A 80 12"))
        self.assertIs(found, False)
        self.assertEqual(asked, ["0100"])                # it never asked for 21-40
        self.assertIn("21-40 none", out)

    def test_the_car_not_saying_is_not_a_no(self):
        self.assertIsNone(self.ask({})[0])                          # nothing answered
        self.assertIsNone(self.ask({"0100": LOW})[0])               # promised a second bitmap, gave none
        self.assertIsNone(self.ask(support(low="SEARCHING... UNABLE TO CONNECT"))[0])

    def test_a_search_banner_before_the_answer(self):
        found, _, _ = self.ask(support(low="SEARCHING... " + LOW))
        self.assertIs(found, True)


class SavedBaroTest(unittest.TestCase):
    def test_what_it_starts_from(self):
        self.assertEqual(ObdReader()._baro, BARO_DEFAULT)
        self.assertEqual(ObdReader(baro="92.5")._baro, 92.5)          # settings give strings back
        self.assertEqual(ObdReader(baro=88.0)._baro, 88.0)

    def test_what_isnt_air_pressure_is_ignored(self):
        for bad in (None, "", "abc", "0", "5", "300", "-90", float("nan")):
            self.assertEqual(ObdReader(baro=bad)._baro, BARO_DEFAULT, bad)

    def test_a_first_measurement_is_kept(self):
        reader = ObdReader()
        kept = []
        reader.baro.connect(kept.append)
        reader._note_baro(95)
        self.assertEqual((reader._baro, kept), (95.0, [95.0]))

    def test_the_same_pressure_isnt_written_again(self):
        reader = ObdReader(baro="95")
        kept = []
        reader.baro.connect(kept.append)
        reader._note_baro(95)                 # the same as before
        self.assertEqual(kept, [])
        reader._note_baro(96)                 # a kPa matters: 0.15 psi of boost
        self.assertEqual(kept, [96.0])
        reader._note_baro(93, keep=False)     # used, not kept
        self.assertEqual((reader._baro, kept), (93.0, [96.0]))

    def test_a_reading_that_isnt_air_pressure_changes_nothing(self):
        reader = ObdReader(baro="95")
        kept = []
        reader.baro.connect(kept.append)
        for bad in (0, 255, None):
            reader._note_baro(bad)
        self.assertEqual((reader._baro, kept), (95.0, []))


class StartingBaroTest(unittest.TestCase):
    def start(self, replies, reader=None):
        reader = reader or ObdReader()
        elm = CannedElm(replies)
        kept = []
        reader.baro.connect(kept.append)
        with contextlib.redirect_stdout(io.StringIO()):
            reader._start_baro(elm)
        return reader, elm, kept

    def test_the_cars_own_reading(self):
        reader, elm, kept = self.start({**support(), "0133": "41 33 5A"})
        self.assertEqual((reader._baro, kept), (90.0, [90.0]))
        self.assertEqual(elm.asked, ["0100", "0120", "0133"])

    def test_the_cars_reading_beats_a_saved_one(self):
        reader, _, kept = self.start({**support(), "0133": "41 33 5A"}, ObdReader(baro="101"))
        self.assertEqual(reader._baro, 90.0)

    def test_a_car_without_it_starts_from_the_saved_one(self):
        reader, elm, kept = self.start(support(high=HIGH_WITHOUT), ObdReader(baro="91.5"))
        self.assertEqual((reader._baro, kept), (91.5, []))
        self.assertNotIn("0133", elm.asked)               # it never asks a car without it

    def test_a_car_without_it_and_nothing_saved_starts_at_sea_level(self):
        reader, _, kept = self.start(support(high=HIGH_WITHOUT))
        self.assertEqual((reader._baro, kept), (BARO_DEFAULT, []))

    def test_a_supported_pid_that_doesnt_answer_this_time(self):
        reader, _, kept = self.start(support(), ObdReader(baro="91.5"))     # no "0133" reply
        self.assertEqual((reader._baro, kept), (91.5, []))

    def test_a_reading_that_cant_be_air_pressure_is_ignored(self):
        reader, _, kept = self.start({**support(), "0133": "41 33 00"}, ObdReader(baro="91.5"))
        self.assertEqual((reader._baro, kept), (91.5, []))

    def test_the_bitmaps_are_read_once(self):
        reader, elm, _ = self.start({**support(), "0133": "41 33 5A"})
        elm.asked.clear()
        with contextlib.redirect_stdout(io.StringIO()):
            reader._start_baro(elm)                       # the car came back after a key off
        self.assertEqual(elm.asked, ["0133"])

    def test_a_car_that_didnt_say_is_asked_again(self):
        reader, elm, _ = self.start({})
        self.assertIsNone(reader._baro_pid)
        elm.replies = {c: [r] for c, r in support().items()}
        with contextlib.redirect_stdout(io.StringIO()):
            reader._start_baro(elm)
        self.assertIs(reader._baro_pid, True)


class BoostTest(unittest.TestCase):
    """The same idle reading however the dashboard started."""

    # Three rounds with the key on and the manifold at 90 kPa, then idling.
    KEY_ON_THEN_IDLE = {**IDLING, "010C": ["41 0C 00 00"] * 3 + ["41 0C 0C 80"],
                        "010B": ["41 0B 5A"] * 3 + ["41 0B 28"]}
    WANT = (40 - 90) * PSI                                # 40 kPa in the manifold, 90 outside

    def test_after_a_key_on_start(self):
        readings, kept = poll(ObdReader(), CannedElm(self.KEY_ON_THEN_IDLE, rounds=5))
        self.assertAlmostEqual(last_boost(readings), self.WANT, places=3)
        self.assertEqual(kept, [90.0])                    # the key-on measurement is kept

    def test_a_restart_with_the_engine_running_asks_the_car(self):
        replies = {**IDLING, **support(), "0133": "41 33 5A"}
        readings, kept = poll(ObdReader(), CannedElm(replies, rounds=3))
        self.assertAlmostEqual(last_boost(readings), self.WANT, places=3)
        self.assertEqual(kept, [90.0])

    def test_a_restart_with_the_engine_running_uses_the_saved_pressure(self):
        replies = {**IDLING, **support(high=HIGH_WITHOUT)}
        readings, kept = poll(ObdReader(baro="90"), CannedElm(replies, rounds=3))
        self.assertAlmostEqual(last_boost(readings), self.WANT, places=3)
        self.assertEqual(kept, [])                        # nothing new to keep

    def test_without_either_it_is_off_by_the_elevation(self):
        replies = {**IDLING, **support(high=HIGH_WITHOUT)}
        readings, _ = poll(ObdReader(), CannedElm(replies, rounds=3))
        self.assertAlmostEqual(last_boost(readings), (40 - BARO_DEFAULT) * PSI, places=3)

    def test_a_key_on_later_corrects_a_saved_pressure_that_was_off(self):
        replies = {**self.KEY_ON_THEN_IDLE, **support(high=HIGH_WITHOUT)}
        readings, kept = poll(ObdReader(baro="101"), CannedElm(replies, rounds=5))
        self.assertAlmostEqual(last_boost(readings), self.WANT, places=3)
        self.assertEqual(kept, [90.0])

    def test_the_pressure_outlasts_a_key_off(self):
        reader = ObdReader()
        poll(reader, CannedElm(self.KEY_ON_THEN_IDLE, rounds=5))
        readings, _ = poll(reader, CannedElm({**IDLING, **support(high=HIGH_WITHOUT)}, rounds=3))
        self.assertAlmostEqual(last_boost(readings), self.WANT, places=3)


class StoppedEngineTest(unittest.TestCase):
    """The manifold is the outside air only once it has settled."""

    def stopped(self, kpas, baro="95"):
        """Rounds with the engine stopped and the manifold reading `kpas`,
        then idling; returns the reader and what it kept."""
        rpm = ["41 0C 00 00"] * len(kpas) + ["41 0C 0C 80"]
        manifold = [f"41 0B {k:02X}" for k in kpas] + ["41 0B 28"]
        replies = {**IDLING, **support(high=HIGH_WITHOUT), "010C": rpm, "010B": manifold}
        reader = ObdReader(baro=baro)
        _, kept = poll(reader, CannedElm(replies, rounds=len(kpas) + 2))
        return reader, kept

    def test_after_a_stall_it_waits_for_the_manifold_to_settle(self):
        reader, kept = self.stopped([35, 60, 75, 88])     # filling back up, then the engine restarts
        self.assertEqual((reader._baro, kept), (95.0, []))
        reader, kept = self.stopped([35, 60, 75, 88, 92, 92, 92])
        self.assertEqual((reader._baro, kept), (92.0, [92.0]))

    def test_a_flickering_reading_is_kept_once_a_stop(self):
        reader, kept = self.stopped([92, 93, 92, 93, 92, 93])
        self.assertEqual(kept, [92.0])
        self.assertEqual(reader._baro, 93.0)              # still used, round by round

    def test_a_reading_that_isnt_steady_never_counts(self):
        reader, kept = self.stopped([90, 92, 94, 96, 98])
        self.assertEqual((reader._baro, kept), (95.0, []))


class ConvertTest(unittest.TestCase):
    def test_rpm_is_quarters(self):
        self.assertEqual(convert(0x0C, [0x0C, 0x80]), ("rpm", 800.0))
        self.assertEqual(convert(0x0C, [0x1A, 0xF8]), ("rpm", 1726.0))
        self.assertEqual(convert(0x0C, [0, 0]), ("rpm", 0.0))

    def test_manifold_pressure_is_kpa_as_is(self):
        self.assertEqual(convert(0x0B, [40]), ("map", 40))

    def test_speed_is_mph(self):
        self.assertEqual(convert(0x0D, [0]), ("speed", 0.0))
        name, mph = convert(0x0D, [100])
        self.assertEqual(name, "speed")
        self.assertAlmostEqual(mph, 62.1371, places=3)

    def test_temperatures_are_fahrenheit_from_an_offset_celsius(self):
        for pid, name in ((0x05, "coolant"), (0x0F, "intake")):
            self.assertEqual(convert(pid, [40]), (name, 32.0))          # 0 C
            self.assertEqual(convert(pid, [140]), (name, 212.0))        # 100 C
            self.assertEqual(convert(pid, [0]), (name, -40.0))          # -40 C is -40 F

    def test_a_pid_it_doesnt_know(self):
        self.assertEqual(convert(0x33, [100]), (None, None))


class PidReplyTest(unittest.TestCase):
    """Elm.pid finds the data bytes in whatever the adapter sends back."""

    def pid(self, pid, reply):
        return CannedElm({f"01{pid:02X}": reply}).pid(pid)

    def test_with_spaces(self):
        self.assertEqual(self.pid(0x0C, "41 0C 1A F8"), [0x1A, 0xF8])

    def test_without_spaces(self):
        self.assertEqual(self.pid(0x0C, "410C1AF8"), [0x1A, 0xF8])

    def test_a_header_before_the_answer(self):
        # The adapter is set to ATH0, so headers shouldn't appear, but if a CAN id and
        # length or K-line header bytes do, the answer is still found. (Real K-line
        # frames end in a checksum, which ATH0 also strips; the byte after the
        # data here is just more data.)
        self.assertEqual(self.pid(0x0C, "7E8 04 41 0C 1A F8"), [0x1A, 0xF8])
        self.assertEqual(self.pid(0x0D, "48 6B 10 41 0D 32 AB"), [0x32, 0xAB])

    def test_a_search_banner_before_the_answer(self):
        self.assertEqual(self.pid(0x0B, "SEARCHING... 41 0B 28"), [0x28])

    def test_no_answer(self):
        for reply in ("NO DATA", "UNABLE TO CONNECT", "?", "", "BUS INIT: ERROR"):
            self.assertIsNone(self.pid(0x0C, reply), reply)

    def test_the_answer_to_another_pid(self):
        self.assertIsNone(self.pid(0x0C, "41 0D 32"))

    def test_a_head_with_no_data(self):
        self.assertIsNone(self.pid(0x0C, "41 0C"))

    def test_junk_after_the_data_ends_it(self):
        self.assertEqual(self.pid(0x0C, "41 0C 1A F8 ZZ"), [0x1A, 0xF8])

    def test_an_odd_nibble_at_the_end_is_ignored(self):
        self.assertEqual(self.pid(0x0C, "41 0C 1A F"), [0x1A])

    def test_a_single_digit_pid_is_padded_in_the_request(self):
        elm = CannedElm({"0105": "41 05 5F"})
        self.assertEqual(elm.pid(0x05), [0x5F])
        self.assertEqual(elm.asked, ["0105"])


if __name__ == "__main__":
    unittest.main()
