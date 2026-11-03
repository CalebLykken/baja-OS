"""Off-Pi tests for the OBD reader (backend/obd.py): the PID support bitmaps,
the outside air pressure that boost is measured against, and what it keeps
for a restart with the engine already running. The adapter is a canned set
of ELM327 replies.

    python3 -m unittest tests.test_obd
"""

import contextlib
import io
import time
import unittest
from unittest import mock

from PyQt6.QtCore import QCoreApplication

from backend import obd
from backend.obd import (BARO_DEFAULT, DTC_TEXT, Elm, ObdReader, convert, describe, parse_dtcs,
                         pid_supported, refuse_writes)

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

    def lines(self, command, timeout=3.0):
        return [self.send(command, timeout)]


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


class Clock:
    """A clock that only the reader's sleeps move."""

    def __init__(self):
        self.now = 1000.0

    def monotonic(self):
        return self.now

    def sleep(self, seconds):
        self.now += seconds


class RetryWaitTest(unittest.TestCase):
    def wait_after(self, quiet_s):
        with mock.patch.object(obd.time, "monotonic", lambda: 1000.0 + quiet_s):
            return obd.retry_wait(1000.0)

    def test_often_then_rarely_then_very_rarely(self):
        self.assertEqual(self.wait_after(0), obd.RETRY_S)
        self.assertEqual(self.wait_after(obd.SLOW_AFTER_S - 1), obd.RETRY_S)
        self.assertEqual(self.wait_after(obd.SLOW_AFTER_S), obd.RETRY_SLOW_S)
        self.assertEqual(self.wait_after(obd.SLOWEST_AFTER_S - 1), obd.RETRY_SLOW_S)
        self.assertEqual(self.wait_after(obd.SLOWEST_AFTER_S), obd.RETRY_SLOWEST_S)
        self.assertEqual(self.wait_after(86400), obd.RETRY_SLOWEST_S)

    def test_a_charging_battery_keeps_the_slow_tier(self):
        with mock.patch.object(obd.time, "monotonic", lambda: 1000.0 + 86400):
            self.assertEqual(obd.retry_wait(1000.0, charging=True), obd.RETRY_SLOW_S)
            self.assertEqual(obd.retry_wait(1000.0, charging=False), obd.RETRY_SLOWEST_S)

    def test_the_reader_stays_slow_while_its_last_battery_reading_is_charging(self):
        reader = ObdReader()
        reader._since = 1000.0
        with mock.patch.object(obd.time, "monotonic", lambda: 1000.0 + 86400):
            reader._volts(CannedElm({"ATRV": "14.1V"}))
            self.assertEqual(reader._retry(), obd.RETRY_SLOW_S)
            reader._volts(CannedElm({"ATRV": "12.5V"}))
            self.assertEqual(reader._retry(), obd.RETRY_SLOWEST_S)

    def test_the_longest_wait_is_at_most_two_minutes(self):
        self.assertLessEqual(obd.RETRY_SLOWEST_S, 120.0)
        self.assertGreater(obd.RETRY_SLOWEST_S, obd.RETRY_SLOW_S)


class Stop(Exception):
    pass


class HungUpPortTest(unittest.TestCase):
    """An unplugged adapter's tty reads empty at once; that is an error, not a wait."""

    def elm(self):
        elm = Elm.__new__(Elm)
        elm.fd = 99
        return elm

    def patched(self, read):
        stack = contextlib.ExitStack()
        self.addCleanup(stack.close)
        stack.enter_context(mock.patch.object(obd.termios, "tcflush"))
        stack.enter_context(mock.patch.object(obd.os, "write"))
        stack.enter_context(mock.patch.object(obd.select, "select", lambda r, w, x, t: (r, [], [])))
        return stack.enter_context(mock.patch.object(obd.os, "read", read))

    def test_eof_raises_at_once_without_spinning(self):
        read = self.patched(mock.Mock(return_value=b""))
        started = time.monotonic()
        with self.assertRaises(OSError):
            self.elm().send("010C", timeout=3.0)
        self.assertEqual(read.call_count, 1)
        self.assertLess(time.monotonic() - started, 1.0)

    def test_a_normal_reply_still_works(self):
        self.patched(mock.Mock(return_value=b"41 0C 1A F8\r\r>"))
        self.assertEqual(self.elm().send("010C"), "41 0C 1A F8")


class GoneAdapterSessionTest(unittest.TestCase):
    """If the port is gone when the readings stop, that is `lost`, not `quiet`."""

    class FakeElm:
        def __init__(self, path):
            pass

        def send(self, command, timeout=3.0):
            return "OK"

        def close(self):
            pass

    def test_port_gone_raises_and_does_not_say_quiet(self):
        reader = ObdReader()
        events = []
        reader.quiet.connect(lambda: events.append("quiet"))
        reader._protocol = "0"
        reader._wait = lambda elm, path: True
        reader._poll = lambda elm: None
        with mock.patch.object(obd, "Elm", self.FakeElm), \
                mock.patch.object(obd.time, "sleep", lambda s: None), \
                mock.patch.object(obd.os.path, "exists", lambda p: False), \
                contextlib.redirect_stdout(io.StringIO()):
            with self.assertRaises(OSError):
                reader._session("/dev/x")
        self.assertEqual(events, [])


class HoldTest(unittest.TestCase):
    """A held reader sends nothing; released, it carries on."""

    def setUp(self):
        self.clock = Clock()
        self.sleeps = []
        self.on_sleep = lambda n: None
        p = mock.patch.object(obd.time, "monotonic", self.clock.monotonic)
        p.start()
        self.addCleanup(p.stop)
        p = mock.patch.object(obd.time, "sleep", self.sleep)
        p.start()
        self.addCleanup(p.stop)
        p = mock.patch.object(obd.os.path, "exists", lambda path: True)
        p.start()
        self.addCleanup(p.stop)
        self.reader = ObdReader()
        self.reader._since = self.clock.now
        self.volts = []
        self.reader.voltage.connect(self.volts.append)

    def sleep(self, seconds):
        self.clock.sleep(seconds)
        self.sleeps.append(seconds)
        self.on_sleep(len(self.sleeps))

    def test_held_wait_sends_nothing_then_resumes(self):
        elm = CannedElm({"ATRV": "12.5V", "0100": "41 00 98 3A 80 13"})

        def on_sleep(n):
            if n == 20:
                self.assertEqual(elm.asked, [])
                self.reader.release()
        self.on_sleep = on_sleep
        self.reader.hold()
        self.assertTrue(self.reader._wait(elm, "/dev/x"))
        self.assertEqual(elm.asked, ["ATRV", "0100"])
        self.assertEqual(self.volts, [12.5])
        self.assertLessEqual(max(self.sleeps), 1.0)

    def test_a_long_wait_sleeps_in_short_slices_and_asks_every_two_minutes(self):
        elm = CannedElm({"ATRV": "12.5V"})
        self.clock.now += obd.SLOWEST_AFTER_S + 1       # parked a long while
        self.reader._since = 1000.0

        def on_sleep(n):
            if self.clock.now > 1000.0 + obd.SLOWEST_AFTER_S + 300:
                raise Stop
        self.on_sleep = on_sleep
        with self.assertRaises(Stop):
            self.reader._wait(elm, "/dev/x")
        self.assertLessEqual(max(self.sleeps), 1.0)
        asks = elm.asked.count("0100")
        self.assertIn(asks, (3, 4))                     # about every 120 s over 300 s
        self.assertEqual(elm.asked.count("ATRV"), asks)  # the battery with each try

    def test_hold_stops_the_battery_reads_too(self):
        elm = CannedElm({"ATRV": "12.5V"})

        def on_sleep(n):
            if n == 3:
                self.reader.hold()
                self.asked_at_hold = len(elm.asked)
            if n == 50:
                raise Stop
        self.on_sleep = on_sleep
        with self.assertRaises(Stop):
            self.reader._wait(elm, "/dev/x")
        self.assertGreater(self.asked_at_hold, 0)
        self.assertEqual(len(elm.asked), self.asked_at_hold)

    def test_held_poll_sends_nothing_then_resumes(self):
        elm = CannedElm(IDLING, rounds=3)
        readings = []
        self.reader.reading.connect(readings.append)

        def on_sleep(n):
            if n == 10:
                self.assertEqual(elm.asked, [])
                self.reader.release()
        self.on_sleep = on_sleep
        self.reader.hold()
        with contextlib.redirect_stdout(io.StringIO()):
            self.reader._poll(elm)
        self.assertTrue(readings)

    def test_a_hold_mid_round_sends_no_more(self):
        elm = CannedElm(IDLING)
        self.reader._start_baro = lambda elm: None
        self.reader._read_codes = lambda elm, state: self.reader.hold()
        readings = []
        self.reader.reading.connect(readings.append)

        def on_sleep(n):
            raise Stop
        self.on_sleep = on_sleep
        with self.assertRaises(Stop):
            self.reader._poll(elm)
        self.assertEqual(elm.asked, [])
        self.assertEqual(readings, [])


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


class WireElm(Elm):
    """A real Elm (its guard and reply handling) without a serial port:
    `_io` is the only thing replaced, and records what would be sent.
    `replies` maps a command to the reply's lines."""

    def __init__(self, replies, rounds=None):
        self.replies, self.rounds, self.sent = dict(replies), rounds, []

    def _io(self, command, timeout):
        self.sent.append(command)
        if self.rounds is not None and self.sent.count("010C") > self.rounds:
            return ["NO DATA"]
        return list(self.replies.get(command, ["NO DATA"]))


class RefuseWritesTest(unittest.TestCase):
    def test_anything_but_modes_01_03_07_is_refused(self):
        for command in ("04", "0400", "04 ", " 04", "14", "0A", "02", "05", "08", "09", "0405", "10", "",
                        "0", "ZZ", "01ZZ", "ST", "ST04", "ATZ\r04", "0100\r04", "03\n04", "ATZ\n04", "ATZ\r"):
            with self.subTest(command=command), self.assertRaises(ValueError):
                refuse_writes(command)

    def test_reads_and_adapter_commands_pass(self):
        for command in ("0100", "0105", "010C", "03", "07", "03 ", "ATRV", "ATZ", "atsp0", "AT SP 0"):
            with self.subTest(command=command):
                refuse_writes(command)

    def test_a_real_elm_never_writes_a_clear(self):
        elm = Elm.__new__(Elm)
        elm.fd = 99
        with mock.patch.object(obd.os, "write") as write, mock.patch.object(obd.termios, "tcflush"):
            for command in ("04", "0400", "04 "):
                with self.assertRaises(ValueError):
                    elm.send(command)
                with self.assertRaises(ValueError):
                    elm.lines(command)
        write.assert_not_called()

    def test_a_real_elm_writes_a_read(self):
        elm = Elm.__new__(Elm)
        elm.fd = 99
        with mock.patch.object(obd.os, "write") as write, mock.patch.object(obd.termios, "tcflush"), \
                mock.patch.object(obd.select, "select", return_value=([99], [], [])), \
                mock.patch.object(obd.os, "read", return_value=b"43 00\r\r>"):
            self.assertEqual(elm.send("03"), "43 00")
        write.assert_called_once_with(99, b"03\r")


class DtcParseTest(unittest.TestCase):
    def test_a_k_line_reply_with_padding(self):
        self.assertEqual(parse_dtcs(["43 03 01 00 00 00 00"], "43"), ["P0301"])   # no count byte: 6 bytes
        self.assertEqual(parse_dtcs(["43 01 33 02 01 00 00"], "43"), ["P0133", "P0201"])

    def test_the_letters_and_digits(self):
        for hexes, code in (("0123", "P0123"), ("1234", "P1234"), ("2345", "P2345"), ("3456", "P3456"),
                            ("4123", "C0123"), ("7FFF", "C3FFF"), ("8123", "B0123"), ("A123", "B2123"),
                            ("C123", "U0123"), ("FFFF", "U3FFF")):
            with self.subTest(code=code):
                self.assertEqual(parse_dtcs(["43 " + hexes + " 00 00 00 00"], "43"), [code])

    def test_pending_uses_head_47(self):
        self.assertEqual(parse_dtcs(["47 04 20 00 00 00 00"], "47"), ["P0420"])
        self.assertEqual(parse_dtcs(["47 04 20 00 00 00 00"], "43"), [])

    def test_a_can_count_byte_is_skipped(self):
        self.assertEqual(parse_dtcs(["43 01 03 01 00 00"], "43"), ["P0301"])
        self.assertEqual(parse_dtcs(["43 02 03 01 04 20"], "43"), ["P0301", "P0420"])
        self.assertEqual(parse_dtcs(["43 00"], "43"), [])

    def test_a_multi_frame_reply(self):
        lines = ["00A", "0: 43 03 01 33 01 71", "1: 04 20 00 00 00 00 00"]
        self.assertEqual(parse_dtcs(lines, "43"), ["P0133", "P0171", "P0420"])

    def test_a_multi_frame_reply_with_an_even_length(self):
        lines = ["00B", "0: 43 04 01 33 01 71", "1: 04 20 03 01 00 00 00"]
        self.assertEqual(parse_dtcs(lines, "43"), ["P0133", "P0171", "P0420", "P0301"])
        self.assertEqual(parse_dtcs(["008", "0: 43 00 00 00 00 00", "1: 00 00 00 00"], "43"), [])

    def test_several_engine_computers_and_repeats(self):
        lines = ["43 03 01 00 00 00 00", "43 03 01 01 71 00 00"]
        self.assertEqual(parse_dtcs(lines, "43"), ["P0301", "P0171"])

    def test_no_data_and_junk_give_none(self):
        for junk in (["NO DATA"], [], ["SEARCHING..."], ["43 0Z 01"], ["UNABLE TO CONNECT"], ["43 0"], ["?"],
                     ["43"], ["1: 43 03 01"]):
            with self.subTest(junk=junk):
                self.assertEqual(parse_dtcs(junk, "43"), [])

    def test_a_banner_before_the_reply(self):
        self.assertEqual(parse_dtcs(["SEARCHING...", "43 03 01 00 00 00 00"], "43"), ["P0301"])


class DtcTextTest(unittest.TestCase):
    def test_known_codes_have_text(self):
        self.assertEqual(describe("P0301"), "Cylinder 1 misfire")
        self.assertEqual(describe("p0420"), "Catalyst efficiency low")

    def test_others_have_none(self):
        self.assertEqual(describe("P1234"), "")
        self.assertEqual(describe(""), "")

    def test_the_table_is_short_and_generic(self):
        self.assertGreaterEqual(len(DTC_TEXT), 40)
        for code, text in DTC_TEXT.items():
            self.assertRegex(code, r"^P0[0-9A-F]{3}$")
            self.assertTrue(text)
            self.assertLess(len(text), 45)


class MilTest(unittest.TestCase):
    def mil(self, reply):
        return WireElm({"0101": [reply]}).mil()

    def test_lamp_on_and_the_count(self):
        self.assertEqual(self.mil("41 01 83 07 E5 00"), (True, 3))

    def test_two_computers_the_lamp_and_counts_combine(self):
        elm = WireElm({"0101": ["41 01 00 00 00 00", "41 01 82 07 E5 00"]})     # the transmission first
        self.assertEqual(elm.mil(), (True, 2))
        elm = WireElm({"0101": ["41 01 81 07 E5 00", "41 01 02 00 00 00"]})
        self.assertEqual(elm.mil(), (True, 3))

    def test_a_transmission_computer_alone(self):
        self.assertEqual(self.mil("41 01 00 00 00 00"), (False, 0))

    def test_lamp_off(self):
        self.assertEqual(self.mil("41 01 00 07 65 00"), (False, 0))
        self.assertEqual(self.mil("41 01 02 07 65 00"), (False, 2))     # stored but not lit

    def test_no_answer(self):
        self.assertIsNone(self.mil("NO DATA"))
        self.assertIsNone(WireElm({}).mil())

    def test_dtcs_ask_the_right_modes_and_only_those(self):
        elm = WireElm({"03": ["43 01 33 00 00 00 00"], "07": ["47 03 01 00 00 00 00"]})
        self.assertEqual(elm.dtcs("03"), ["P0133"])
        self.assertEqual(elm.dtcs("07"), ["P0301"])
        self.assertEqual(elm.sent, ["03", "07"])
        with self.assertRaises(ValueError):
            elm.dtcs("04")
        self.assertEqual(elm.sent, ["03", "07"])


class ReadingCodesTest(unittest.TestCase):
    WITH_CODES = {**IDLING, "0101": ["41 01 82 07 E5 00"], "03": ["43 03 01 01 71 00 00"],
                  "07": ["47 04 20 00 00 00 00"]}

    def collect(self, reader):
        got = []
        reader.codes.connect(got.append)
        return got

    def test_a_poll_reads_the_codes_once_and_never_sends_mode_04(self):
        reader, elm = ObdReader(), WireElm(self.WITH_CODES, rounds=6)
        got = self.collect(reader)
        poll(reader, elm)
        self.assertEqual(got, [{"mil": True, "count": 2, "stored": ["P0301", "P0171"], "pending": ["P0420"]}])
        self.assertEqual(elm.sent.count("0101"), 1)             # a minute hasn't passed
        self.assertFalse([c for c in elm.sent if c.startswith("04")])
        self.assertTrue(all(c[:2] in ("01", "03", "07") or c.startswith("AT") for c in elm.sent))

    def test_a_car_without_pid_01_isnt_given_up_on(self):
        reader, elm = ObdReader(), WireElm(IDLING, rounds=6)
        got = self.collect(reader)
        readings, _ = poll(reader, elm)
        self.assertEqual(got, [])
        self.assertEqual(len(readings), 6)

    def test_codes_are_emitted_only_when_the_count_changes(self):
        reader, elm, state = ObdReader(), WireElm(self.WITH_CODES), [None, None, None]
        got = self.collect(reader)
        with mock.patch.object(obd, "CODES_EVERY_S", 0):
            reader._read_codes(elm, state)
            reader._read_codes(elm, state)                      # same count: nothing new
            self.assertEqual(got[0], got[1])                    # said again, not read again
            self.assertEqual(elm.sent, ["0101", "03", "07", "0101"])
            elm.replies["0101"] = ["41 01 00 07 E5 00"]         # cleared at the shop
            elm.replies["07"] = ["NO DATA"]
            reader._read_codes(elm, state)
        self.assertEqual(got[2], {"mil": False, "count": 0, "stored": [], "pending": []})
        self.assertNotIn("03", elm.sent[4:])                    # nothing stored to read

    def test_the_lamp_changing_with_the_same_count_reads_again(self):
        reader, elm, state = ObdReader(), WireElm(self.WITH_CODES), [None, None, None]
        got = self.collect(reader)
        with mock.patch.object(obd, "CODES_EVERY_S", 0):
            reader._read_codes(elm, state)
            elm.replies["0101"] = ["41 01 02 07 E5 00"]         # same count, lamp out
            reader._read_codes(elm, state)
        self.assertEqual([g["mil"] for g in got], [True, False])
        self.assertEqual(elm.sent.count("03"), 2)

    def test_stored_codes_that_didnt_come_are_asked_for_again(self):
        reader, elm, state = ObdReader(), WireElm({**self.WITH_CODES, "03": ["NO DATA"]}), [None, None, None]
        got = self.collect(reader)
        with mock.patch.object(obd, "CODES_EVERY_S", 0):
            reader._read_codes(elm, state)
            self.assertEqual(got[0]["mil"], True)               # the lamp is still said
            self.assertEqual(got[0]["stored"], [])
            elm.replies["03"] = ["43 03 01 01 71 00 00"]
            reader._read_codes(elm, state)
        self.assertEqual(got[1]["stored"], ["P0301", "P0171"])
        self.assertEqual(elm.sent.count("03"), 2)

    def test_the_last_result_is_said_again_when_the_car_doesnt_answer_pid_01(self):
        reader, elm, state = ObdReader(), WireElm(self.WITH_CODES), [None, None, None]
        got = self.collect(reader)
        with mock.patch.object(obd, "CODES_EVERY_S", 0):
            reader._read_codes(elm, state)
            elm.replies["0101"] = ["NO DATA"]
            reader._read_codes(elm, state)
        self.assertEqual(len(got), 2)
        self.assertEqual(got[0], got[1])

    def test_not_asked_again_within_the_interval(self):
        reader, elm, state = ObdReader(), WireElm(self.WITH_CODES), [None, None, None]
        reader._read_codes(elm, state)
        elm.sent.clear()
        reader._read_codes(elm, state)
        self.assertEqual(elm.sent, [])

    def test_a_failed_first_read_is_tried_again_later(self):
        reader, elm, state = ObdReader(), WireElm(IDLING), [None, None, None]
        got = self.collect(reader)
        with mock.patch.object(obd, "CODES_EVERY_S", 0):
            reader._read_codes(elm, state)
            elm.replies["0101"] = ["41 01 00 00 00 00"]
            reader._read_codes(elm, state)
        self.assertEqual(got, [{"mil": False, "count": 0, "stored": [], "pending": []}])


class ReaderSurvivesTest(unittest.TestCase):
    def test_an_unexpected_error_in_a_session_does_not_end_the_thread(self):
        reader = ObdReader()
        lost = []
        reader.lost.connect(lambda: lost.append(1))
        naps = []

        def nap(seconds):
            naps.append(seconds)
            raise Stop()                  # ends the loop after the first pass

        with mock.patch.object(obd, "find_port", return_value="/dev/ttyUSB0"), \
                mock.patch.object(ObdReader, "_session", side_effect=RuntimeError("bad reply")), \
                mock.patch.object(reader, "_nap", nap), \
                mock.patch.object(obd.errorlog.log, "report") as report:
            with self.assertRaises(Stop):
                reader._run()
        report.assert_called_once()
        self.assertEqual(lost, [1])
        self.assertEqual(len(naps), 1)

    def test_the_port_is_closed_when_it_will_not_set_up(self):
        with mock.patch.object(obd.os, "open", return_value=77), \
                mock.patch.object(obd.os, "close") as close, \
                mock.patch.object(obd.termios, "tcgetattr", side_effect=obd.termios.error("no")):
            with self.assertRaises(obd.termios.error):
                Elm("/dev/ttyUSB9")
        close.assert_called_once_with(77)


if __name__ == "__main__":
    unittest.main()
