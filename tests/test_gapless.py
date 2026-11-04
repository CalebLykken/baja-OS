"""Off-Pi tests for how much the gapless engine decodes ahead (backend/gapless.py).

A FakeSink and a FakeDecoder, both driven by hand: no audio device, no real
decoding, no waiting on real time. So a 3-hour file takes a moment.
"""

import types
import unittest
from array import array
from collections import deque
from unittest import mock

try:
    from PyQt6 import sip
    from PyQt6.QtCore import QCoreApplication, QObject, pyqtSignal
    from PyQt6.QtMultimedia import QAudio

    from backend import gapless
except ImportError as e:
    raise unittest.SkipTest(f"PyQt6 isn't installed ({e})")

app = QCoreApplication.instance() or QCoreApplication([])

S = gapless.BYTES_PER_S
MODULO = 32749                  # samples count up, so a skipped or repeated frame shows
COUNT = array("h", [f % MODULO for f in range(MODULO * 2) for _ in "lr"]).tobytes()


def counting(first, n):
    """`n` bytes of frames counting up from sample value `first`."""
    start = first % MODULO * gapless.FRAME
    data = COUNT[start:start + n]
    while len(data) < n:                    # longer than the table: go round again
        data += counting(first + len(data) // gapless.FRAME, n - len(data))
    return data


class FakeSink(QObject):
    """Stands in for QAudioSink: it never asks the feed for anything."""
    stateChanged = pyqtSignal(object)

    made = []

    def __init__(self, device, fmt, parent=None):
        super().__init__(parent)
        self._size = 0
        self.dev = device
        self.err = QAudio.Error.NoError
        FakeSink.made.append(self)

    def device(self):
        return self.dev

    def setBufferSize(self, n):
        self._size = n

    def bufferSize(self):
        return self._size

    def bytesFree(self):
        return self._size

    def setVolume(self, v):
        pass

    def start(self, feed):
        pass

    def stop(self):
        pass

    def error(self):
        return self.err


class FakeBuffer:
    def __init__(self, data):
        self.data = data

    def byteCount(self):
        return len(self.data)

    def constData(self):
        return self

    def asstring(self, n):
        return self.data[:n]


class FakeDecoder(QObject):
    """QAudioDecoder, one buffer per pump. `waits`: makes no more until its
    buffer is read, as Qt's FFmpeg backend does. Otherwise it never lets up."""
    bufferReady = pyqtSignal()
    finished = pyqtSignal()
    error = pyqtSignal(object)
    made = []
    waits = True
    songs = {}                  # path: (first sample value, bytes long)
    pattern = True
    size = 19200                # 100 ms
    failing = set()             # paths that report an error instead of sound

    def __init__(self, parent=None):
        super().__init__(parent)
        FakeDecoder.made.append(self)
        self.queue = deque()
        self.at = 0
        self.permits = 0
        self.live = False

    def setAudioFormat(self, fmt):
        pass

    def setSource(self, url):
        self.path = url.toLocalFile()
        self.first, self.length = self.songs[self.path]

    def start(self):
        self.live, self.permits = True, 1

    def stop(self):
        self.live = False

    def errorString(self):
        return "no good"

    def bufferAvailable(self):
        return bool(self.queue)

    def read(self):
        self.permits += 1
        return self.queue.popleft()

    def _make(self, n):
        if not self.pattern:
            return bytes(n)
        return counting(self.first + self.at // gapless.FRAME, n)

    def pump(self):
        if not self.live or (self.waits and self.permits <= 0):
            return False
        if self.path in self.failing:
            self.live = False
            self.error.emit(0)
            return True
        self.permits -= 1
        n = min(self.size, self.length - self.at)
        if n <= 0:
            self.live = False
            self.finished.emit()
            return True
        self.queue.append(FakeBuffer(self._make(n)))
        self.at += n
        self.bufferReady.emit()
        return True


class Base(unittest.TestCase):
    def setUp(self):
        for name, fake in (("QAudioSink", FakeSink), ("QAudioDecoder", FakeDecoder)):
            patch = mock.patch.object(gapless, name, fake)
            patch.start()
            self.addCleanup(patch.stop)
        FakeDecoder.made = []
        FakeDecoder.waits, FakeDecoder.pattern, FakeDecoder.size = True, True, 19200
        FakeDecoder.songs = {}
        FakeDecoder.failing = set()

    def engine(self, *songs):
        """An engine playing `songs`, each (first sample value, seconds long)."""
        paths = [f"/music/{i}.flac" for i in range(len(songs))]
        for path, (first, seconds) in zip(paths, songs):
            FakeDecoder.songs[path] = (first, int(seconds * S))
        after = lambda i, failed=False: i + 1 if i + 1 < len(paths) else None
        engine = gapless.GaplessEngine(paths.__getitem__, lambda: len(paths), None, after=after)
        self.addCleanup(engine._shutdown)
        # Run from here it would land on the lock the pull holds (it's queued on the Pi).
        engine._out.wantDecode.disconnect()
        return engine

    def decode(self, engine):
        """What the main thread would be doing: run decoders until they've nothing more."""
        engine._decode_more()
        while any([d.pump() for d in FakeDecoder.made]):
            engine._decode_more()

    def held(self, engine):
        return sum(len(c) for s in engine._songs for c in s.chunks)

    def play(self, engine, seconds, step=1.0):
        """Listen for `seconds`, keeping decoding going; the most held, and what was heard."""
        most, heard = 0, bytearray()
        for _ in range(round(seconds / step)):
            self.decode(engine)
            most = max(most, self.held(engine))
            heard += engine._out.pull(int(step * S))
        return most, heard

    def assert_counts_up(self, heard, first):
        """Every frame follows the last, from sample value `first`."""
        self.assertTrue(bytes(heard) == counting(first, len(heard)))


def old_ramp(data, g, target):
    """The first _ramp: a per-sample loop over the whole buffer. (bytes, gain)."""
    samples = array("h")
    samples.frombytes(bytes(data))
    step = 1.0 / gapless.RAMP_FRAMES
    for f in range(0, len(samples), gapless.CHANNELS):
        if g != target:
            g = min(target, g + step) if target > g else max(target, g - step)
        for c in range(gapless.CHANNELS):
            samples[f + c] = int(samples[f + c] * g)
    return samples.tobytes(), g


class RampTest(unittest.TestCase):
    def check(self, samples, g, target):
        data = array("h", samples).tobytes()
        e = types.SimpleNamespace(_gain=g, _target=target)
        got = gapless._Output._ramp(types.SimpleNamespace(e=e), data)
        want, want_gain = old_ramp(data, g, target)
        self.assertEqual(got, want)
        self.assertEqual(e._gain, want_gain)

    def loud(self, frames):
        return [(-32768, 32767, -1, 12345, -7, 1)[i % 6] for i in range(frames * gapless.CHANNELS)]

    def test_fade_in_and_out_match_the_full_loop(self):
        n = gapless.RAMP_FRAMES * 3
        self.check(self.loud(n), 0.0, 1.0)
        self.check(self.loud(n), 1.0, 0.0)

    def test_buffer_shorter_than_the_ramp(self):
        self.check(self.loud(100), 0.0, 1.0)
        self.check(self.loud(100), 1.0, 0.0)

    def test_buffer_longer_than_the_ramp(self):
        self.check(self.loud(gapless.RAMP_FRAMES + 1), 0.0, 1.0)
        self.check(self.loud(4800), 1.0, 0.0)

    def test_starting_mid_ramp(self):
        self.check(self.loud(4800), 0.4, 1.0)
        self.check(self.loud(4800), 0.4, 0.0)

    def test_already_at_target(self):
        self.check(self.loud(4800), 0.0, 0.0)
        self.check(self.loud(4800), 1.0, 1.0)

    def test_odd_negative_samples(self):
        self.check([-32768, -1] * 3000, 0.0, 1.0)
        self.check([-32768, -1] * 3000, 1.0, 0.0)

    def test_other_target(self):
        self.check(self.loud(4800), 1.0, 0.5)
        self.check(self.loud(4800), 0.2, 0.5)


class BudgetTest(Base):
    LIMIT = (gapless.AHEAD_S + gapless.NEXT_S) * S + FakeDecoder.size

    def test_a_three_hour_file_stays_in_budget_with_one_pass_of_decoding(self):
        FakeDecoder.pattern, FakeDecoder.size = False, S // 10
        engine = self.engine((0, 3 * 3600), (0, 60))
        engine.play_from(0)
        most, _ = self.play(engine, 3 * 3600)
        self.assertLessEqual(most, self.LIMIT)
        self.assertGreater(most, (gapless.AHEAD_S - 1) * S)
        # Waited rather than restarted: the file was gone through just the once.
        self.assertEqual(len([d for d in FakeDecoder.made if d.path.endswith("0.flac")]), 1)

    def test_two_long_files_in_a_row_stay_in_budget(self):
        FakeDecoder.pattern, FakeDecoder.size = False, S // 10
        engine = self.engine((0, 1800), (0, 1800))
        engine.play_from(0)
        most, _ = self.play(engine, 1900)
        self.assertLessEqual(most, self.LIMIT)
        self.assertEqual(engine._songs[0].index, 1)

    def test_only_the_start_of_the_next_song_waits_ready(self):
        engine = self.engine((0, 20), (0, 600))
        engine.play_from(0)
        self.decode(engine)
        self.assertTrue(engine._songs[0].done)
        nxt = engine._songs[1]
        self.assertEqual(nxt.index, 1)
        self.assertTrue(nxt.held)
        self.assertLessEqual(sum(map(len, nxt.chunks)), gapless.NEXT_S * S + FakeDecoder.size)

    def test_it_only_tops_up_once_it_has_played_down_to_the_mark(self):
        engine = self.engine((0, 600))
        engine.play_from(0)
        self.decode(engine)
        full = self.held(engine)
        self.play(engine, gapless.AHEAD_S - gapless.REFILL_S - 2)
        self.assertLess(self.held(engine), full)         # not topped up yet
        self.play(engine, 4)
        self.assertGreaterEqual(self.held(engine), (gapless.AHEAD_S - 2) * S)

    def test_paused_it_doesnt_decode_past_the_limit(self):
        engine = self.engine((0, 600))
        engine.play_from(0, play=False)
        self.decode(engine)
        self.decode(engine)
        self.assertLessEqual(self.held(engine), gapless.AHEAD_S * S + FakeDecoder.size)


class GaplessTest(Base):
    def test_the_next_song_follows_on_the_very_next_frame(self):
        # The second song counts on from where the first stops: a gap, a lost
        # frame or a repeated one all break the count. Pulled in odd-sized reads.
        engine = self.engine((0, 70), (int(70 * gapless.RATE) % MODULO, 40))
        engine.play_from(0)
        _, heard = self.play(engine, 100, step=0.37)
        ramp = gapless.RAMP_FRAMES * gapless.FRAME
        self.assert_counts_up(heard[ramp:], gapless.RAMP_FRAMES)
        self.assertEqual(engine._songs[0].index, 1)

    def test_a_long_song_held_at_its_start_carries_on_once_its_turn_comes(self):
        engine = self.engine((0, 5), (int(5 * gapless.RATE) % MODULO, 200))
        engine.play_from(0)
        _, heard = self.play(engine, 120, step=0.5)
        ramp = gapless.RAMP_FRAMES * gapless.FRAME
        self.assert_counts_up(heard[ramp:], gapless.RAMP_FRAMES)


class BadSongTest(Base):
    def on_repeat(self, *bad):
        """Three one-second songs going round, the `bad` ones undecodable."""
        engine = self.engine((0, 1), (0, 1), (0, 1))
        engine._after = lambda i, failed=False: (i + 1) % 3
        FakeDecoder.failing = {f"/music/{i}.flac" for i in bad}
        with mock.patch("builtins.print"):
            engine.play_from(0)
            self.play(engine, 8, step=0.25)
        return engine

    def test_two_bad_songs_dont_stop_a_good_one_going_round(self):
        engine = self.on_repeat(1, 2)
        self.assertTrue(engine._songs)              # still going on lap 8
        self.assertGreaterEqual(sum(d.path == "/music/0.flac" for d in FakeDecoder.made), 7)

    def test_a_queue_of_nothing_but_bad_songs_still_stops(self):
        engine = self.on_repeat(0, 1, 2)
        self.assertFalse(engine._songs)

    def test_a_song_that_decodes_to_nothing_doesnt_end_a_run_of_bad_ones(self):
        engine = self.engine((0, 1), (0, 1), (0, 0))        # the third is empty
        engine._after = lambda i, failed=False: (i + 1) % 3
        FakeDecoder.failing = {"/music/0.flac", "/music/1.flac"}
        with mock.patch("builtins.print"):
            engine.play_from(0)
            self.play(engine, 3, step=0.25)
        self.assertFalse(engine._songs)

    def test_a_song_that_decodes_to_nothing_on_repeat_one_stops_instead_of_looping(self):
        engine = self.engine((0, 0))                        # empty, and no error
        engine._after = lambda i, failed=False: i           # repeat-one
        with mock.patch("builtins.print"):
            engine.play_from(0)
            self.play(engine, 3, step=0.25)
        self.assertFalse(engine._songs)
        self.assertLessEqual(len(FakeDecoder.made), 3)

    def test_a_good_song_still_clears_the_bad_run_after_an_empty_one(self):
        engine = self.engine((0, 0), (0, 1))
        engine._after = lambda i, failed=False: (i + 1) % 2
        with mock.patch("builtins.print"):
            engine.play_from(0)
            self.play(engine, 4, step=0.25)
        self.assertTrue(engine._songs)                      # the empty one is skipped, the good one goes round
        self.assertGreaterEqual(sum(d.path == "/music/1.flac" for d in FakeDecoder.made), 3)


class RestartTest(Base):
    def test_a_decoder_that_wont_wait_restarts_at_the_right_frame(self):
        FakeDecoder.waits = False
        engine = self.engine((0, 200))
        engine.play_from(0)
        most, heard = self.play(engine, 150)
        ramp = gapless.RAMP_FRAMES * gapless.FRAME
        self.assert_counts_up(heard[ramp:], gapless.RAMP_FRAMES)
        self.assertGreater(len(FakeDecoder.made), 1)
        limit = gapless.AHEAD_S * S + (gapless.STRAYS + 2) * FakeDecoder.size
        self.assertLessEqual(most, limit)

    def test_a_decoder_that_wont_wait_still_plays_to_the_end(self):
        FakeDecoder.waits = False
        engine = self.engine((0, 130))
        engine.play_from(0)
        _, heard = self.play(engine, 130)
        self.assertEqual(len(heard), 130 * S)
        self.assertEqual(heard[-4:], array("h", [(130 * gapless.RATE - 1) % MODULO] * 2).tobytes())

    def test_seek_goes_to_the_exact_frame_either_way(self):
        engine = self.engine((0, 600))
        engine.play_from(0)
        self.play(engine, 5)
        for seconds in (400, 12.5):
            engine.seek(seconds)
            engine._out.pull(S)                          # the fade out
            engine._out.pull(S)                          # the switch, into silence: fades in on it
            _, heard = self.play(engine, 3)
            self.assert_counts_up(heard, int(seconds * gapless.RATE))
            self.assertEqual(engine.position(), int(seconds) + 3)

    def test_seek_keeps_a_trackstarted_on_its_way_and_stays_paused(self):
        engine = self.engine((0, 600))
        engine.play_from(0, play=False)
        gen = engine._gen
        engine.seek(30)
        self.assertEqual(engine._gen, gen)
        self.assertFalse(engine.playing)
        self.decode(engine)
        self.assertEqual(engine._target, 0.0)
        self.assertEqual(engine._songs[0].played, 30 * S)

    def test_seek_with_nothing_playing_does_nothing(self):
        engine = self.engine((0, 10))
        engine.seek(5)
        self.assertFalse(engine._songs)


class TeardownTest(Base):
    def test_shutting_down_with_a_decoder_held_stops_it(self):
        engine = self.engine((0, 600))
        engine.play_from(0)
        self.decode(engine)
        dec = FakeDecoder.made[-1]
        self.assertTrue(dec.live)
        engine._shutdown()
        self.assertFalse(dec.live)
        self.assertIsNone(engine._decoder)
        engine._shutdown()                               # and again, as the app quits

    def test_skipping_a_held_song_stops_its_decoder(self):
        engine = self.engine((0, 600), (0, 600))
        engine.play_from(0)
        self.decode(engine)
        dec = FakeDecoder.made[-1]
        with engine._lock:
            engine._gain = 0.0                           # already faded out
        engine.play_from(1)
        self.assertFalse(dec.live)
        self.assertEqual(engine._decoding.index, 1)


class SinkRetryTest(Base):
    def setUp(self):
        super().setUp()
        FakeSink.made = []
        self.retries = []
        patch = mock.patch.object(gapless.QTimer, "singleShot",
                                  lambda ms, fn: self.retries.append(fn))
        patch.start()
        self.addCleanup(patch.stop)
        # Its own output on this thread, not the engine's, which is on the audio
        # thread making a sink of its own.
        self.out = gapless._Output(types.SimpleNamespace())
        self.out.make_sink("A")

    def fail(self, sink):
        sink.err = QAudio.Error.IOError
        sink.stateChanged.emit(QAudio.State.StoppedState)

    def test_retry_after_new_device_is_dropped(self):
        a = self.out.sink
        self.fail(a)
        self.assertEqual(len(self.retries), 1)
        self.out.make_sink("B")
        b = self.out.sink
        self.retries[0]()
        self.assertIs(self.out.sink, b)
        self.assertEqual([s.dev for s in FakeSink.made if s.dev == "A"], ["A"])

    def test_retry_with_nothing_else_remakes_sink(self):
        self.fail(self.out.sink)
        self.retries[0]()
        self.assertEqual([s.dev for s in FakeSink.made][-2:], ["A", "A"])
        self.assertIs(self.out.sink, FakeSink.made[-1])

    def test_old_sink_error_schedules_nothing(self):
        a = self.out.sink
        self.out.make_sink("B")
        self.fail(a)
        self.assertEqual(self.retries, [])

    def test_stopping_old_sink_schedules_nothing(self):
        a = self.out.sink
        a.err = QAudio.Error.IOError
        a.stop = lambda: a.stateChanged.emit(QAudio.State.StoppedState)
        self.out.make_sink("B")
        self.assertEqual(self.retries, [])

    def test_deleted_sink_reporting_a_stop_is_ignored(self):
        a = self.out.sink
        a.err = QAudio.Error.IOError
        sip.delete(a)
        self.out._state(a, QAudio.State.StoppedState)
        self.assertEqual(self.retries, [])

    def test_retry_after_output_is_deleted_does_nothing(self):
        self.fail(self.out.sink)
        made = len(FakeSink.made)
        sip.delete(self.out)
        self.retries[0]()
        self.assertEqual(len(FakeSink.made), made)


if __name__ == "__main__":
    unittest.main()
