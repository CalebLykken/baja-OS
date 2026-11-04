"""Gapless playback for the Pi's own music.

Qt's media player closes its audio stream at the end of every song and
opens a new one for the next, which leaves a short gap and a click: wrong
for albums whose songs run into each other. Here there's one audio stream
that never closes. Songs are decoded to plain 48 kHz stereo samples
(QAudioDecoder, far faster than they play), the next one while the current
one plays, and fed into the stream back to back, so one ends on exactly
the sample the next begins.

The stream and what feeds it run on their own thread. Everything the
screen does (a new cover when a song starts, opening a page) happens on
the main thread, and if that held up the feed for longer than the little
audio queued ahead, you'd hear a crackle, right as a song starts.

Pausing and skipping fade over 30 ms instead of cutting mid-wave, and
while paused the stream plays silence rather than stopping, so nothing
clicks.

Decoded samples wait in memory until they've played (about 11 MB a minute),
but only a fixed amount of them: AHEAD_S past what's playing, plus NEXT_S of
the next song's start, so a 3-hour file costs what a short one does. There's
one decoder at a time, and the next song only starts once the current one
has decoded to its end. Reaching the limit, we stop reading: with Qt's FFmpeg
backend (and GStreamer's bounded queue) a decoder makes no more until its
buffer is read, so it simply waits there. That isn't promised by Qt, so a
decoder that keeps on regardless is stopped instead and later started again
from the top of the file, leaving out what it already gave us. That's also
how seeking works: QAudioDecoder can't seek, so the time to get to a spot
grows with how far into the file it is.
"""

import os
import threading
import time
from array import array
from collections import deque

from PyQt6.QtCore import (QCoreApplication, QIODevice, QObject, QThread, QTimer, QUrl,
                          pyqtSignal, pyqtSlot)
from PyQt6.QtMultimedia import QAudio, QAudioDecoder, QAudioFormat, QAudioSink

RATE, CHANNELS, SAMPLE_BYTES = 48000, 2, 2
FRAME = CHANNELS * SAMPLE_BYTES
BYTES_PER_S = RATE * FRAME
BUFFER_S = 0.3              # what the audio system holds ahead
RAMP_FRAMES = RATE * 30 // 1000
AHEAD_S = 60                # decoded ahead of what's playing, at most
REFILL_S = 45               # decode more once this little is left
NEXT_S = 15                 # how much of the next song waits ready
STRAYS = 32                 # buffers from a decoder told to wait: it isn't waiting
# Log stalls and starved reads: set BAJA_AUDIO_DEBUG, or create this file.
DEBUG = bool(os.environ.get("BAJA_AUDIO_DEBUG")
             or os.path.exists(os.path.expanduser("~/.config/baja-os/audio-debug")))


def audio_format():
    fmt = QAudioFormat()
    fmt.setSampleRate(RATE)
    fmt.setChannelCount(CHANNELS)
    fmt.setSampleFormat(QAudioFormat.SampleFormat.Int16)
    return fmt


class _Song:
    """One song's samples on their way to the speakers."""

    def __init__(self, index, gen, skip=0):
        self.index = index
        self.gen = gen              # the play_from it follows on from
        self.chunks = deque()       # decoder appends (main thread), feed pops (audio thread)
        self.done = False           # decoding finished (or failed)
        self.skip = skip            # bytes still to leave out from its start (resuming partway)
        self.played = skip          # bytes into the song handed to the stream so far
        self.end = 0                # bytes into the song the decoder has got to (main thread)
        self.held = False           # at its limit: not decoded further until the feed says
        self.strays = 0             # buffers that came while held


class _Feed(QIODevice):
    """What the audio stream reads from: always as much as it asks for."""

    def __init__(self, output):
        super().__init__(output)
        self._output = output

    def readData(self, maxlen):
        return self._output.pull(maxlen)

    def writeData(self, data):
        return 0

    def isSequential(self):
        return True

    def bytesAvailable(self):
        return BYTES_PER_S + super().bytesAvailable()


class _Output(QObject):
    """The stream and its feed. Lives on the audio thread; reads the songs
    and fade state the engine shares under its lock."""
    joined = pyqtSignal(int, int, int, int)  # a song took over: index, generation, rebases, ms until heard
    wantDecode = pyqtSignal()           # songs changed: the main thread decodes
    ran_out = pyqtSignal(int, int)      # nothing follows the last song: generation, ms until it's heard

    def __init__(self, engine):
        super().__init__()
        self.e = engine
        self.sink = None
        self.feed = None
        self.volume = 1.0
        self.last_pull = None

    @pyqtSlot(object)
    def make_sink(self, device):
        if self.feed is None:
            self.feed = _Feed(self)
            self.feed.open(QIODevice.OpenModeFlag.ReadOnly)
        if self.sink is not None:
            self.sink.stop()
            self.sink.deleteLater()
        self.sink = QAudioSink(device, audio_format(), self)
        self.sink.setBufferSize(int(BYTES_PER_S * BUFFER_S) // FRAME * FRAME)
        self.sink.setVolume(self.volume)
        self.sink.stateChanged.connect(self._state)
        self.sink.start(self.feed)

    def _state(self, state):
        if (state == QAudio.State.StoppedState and self.sink is not None
                and self.sink.error() != QAudio.Error.NoError):
            device = self.sink.device()
            QTimer.singleShot(1000, lambda: self.sink is not None and self.make_sink(device))

    @pyqtSlot(float)
    def set_volume(self, v):
        self.volume = v
        if self.sink is not None:
            self.sink.setVolume(v)

    def latency(self):
        return max(0, self.sink.bufferSize() - self.sink.bytesFree()) if self.sink else 0

    def pull(self, maxlen):
        e = self.e
        held = self.latency()
        e._latency = held
        if DEBUG:
            now = time.monotonic()
            if self.last_pull is not None and now - self.last_pull > 0.2:   # normal: ~0.1 s
                print(f"audio: {(now - self.last_pull) * 1000:.0f} ms between reads, "
                      f"{held * 1000 // BYTES_PER_S} ms still queued", flush=True)
            self.last_pull = now
        maxlen -= maxlen % FRAME
        if maxlen <= 0:
            return b""
        out = bytearray()
        with e._lock:
            if e._gain == 0.0 and e._target == 0.0:
                if e._pending is not None:      # faded out: now switch songs
                    (index, skip), e._pending = e._pending, None
                    e._songs.clear()
                    e._songs.append(_Song(index, e._gen, skip))
                    self.wantDecode.emit()
                    if e._want_play:
                        e._target = 1.0
                if e._target == 0.0:
                    return bytes(maxlen)        # paused: silence, stream stays open
            while len(out) < maxlen and e._songs:
                song = e._songs[0]
                if song.chunks:
                    chunk = song.chunks[0]
                    need = maxlen - len(out)
                    if len(chunk) <= need:
                        out += chunk
                        song.chunks.popleft()
                        song.played += len(chunk)
                    else:
                        out += chunk[:need]
                        song.chunks[0] = chunk[need:]
                        song.played += need
                elif song.done:                 # its end: straight into the next
                    e._songs.popleft()
                    if not e._songs:
                        nxt = e._next(song.index)
                        if nxt is not None:
                            e._songs.append(_Song(nxt, song.gen))
                        else:
                            self.ran_out.emit(song.gen, int((held + len(out)) * 1000 / BYTES_PER_S))
                    if e._songs:
                        ahead = held + len(out)
                        nxt = e._songs[0]
                        self.joined.emit(nxt.index, nxt.gen, e._epoch, int(ahead * 1000 / BYTES_PER_S))
                    self.wantDecode.emit()
                else:
                    break                       # decoding hasn't caught up
            if e._songs:
                song = e._songs[0]
                if song.held and song.end - song.played < REFILL_S * BYTES_PER_S:
                    song.held = False
                    song.strays = 0     # strays count per hold, not per song
                    self.wantDecode.emit()
            starved = len(out) < maxlen and e._gain == 1.0 and e._target == 1.0
        if DEBUG and starved:
            print(f"audio: starved, {(maxlen - len(out)) * 1000 // BYTES_PER_S} ms of silence", flush=True)
        out += bytes(maxlen - len(out))
        if e._gain != 1.0 or e._target != 1.0:
            out = self._ramp(out)
        return bytes(out)

    def _ramp(self, data):
        # Only the first RAMP_FRAMES frames change gain; once it reaches the
        # target the rest is a copy (1.0) or silence (0.0), so no per-sample work.
        e = self.e
        samples = array("h")
        samples.frombytes(bytes(data))
        g, target, step = e._gain, e._target, 1.0 / RAMP_FRAMES
        n = len(samples)
        i = 0
        while g != target and i < n:
            g = min(target, g + step) if target > g else max(target, g - step)
            for c in range(CHANNELS):
                samples[i + c] = int(samples[i + c] * g)
            i += CHANNELS
        e._gain = g
        if i < n:
            if target == 1.0:
                pass                    # the rest is unchanged
            elif target == 0.0:
                samples[i:] = array("h", bytes((n - i) * SAMPLE_BYTES))
            else:
                for j in range(i, n):
                    samples[j] = int(samples[j] * g)
        return samples.tobytes()


class GaplessEngine(QObject):
    """Plays songs from a list, one after another, without gaps.

    `path_of(i)` and `count()` describe the list (it can change: call
    `play_from` after). `trackStarted(i)` says song i is now being heard;
    it's never sent for a song from before the latest `play_from`."""
    trackStarted = pyqtSignal(int)
    ended = pyqtSignal()                # the last song has been heard and nothing follows
    _toDevice = pyqtSignal(object)
    _toVolume = pyqtSignal(float)

    def __init__(self, path_of, count, device, parent=None, after=None):
        """`after(i, failed)` is the song to play after song i, or None to stop
        (it runs on the audio thread, so it must only read); `failed`: song i
        couldn't be decoded, so it must not be followed by itself. By default
        the next one, round to the first at the end."""
        super().__init__(parent)
        self._path_of, self._count = path_of, count
        self._after = after or (lambda i, failed=False: (i + 1) % count() if count() else None)
        self._closed = False
        self._bad = set()           # songs that wouldn't decode, in a row (a good one clears it)
        self._lock = threading.Lock()
        self._songs = deque()
        self._want_play = False
        self._gain, self._target = 0.0, 0.0
        self._pending = None        # (song, bytes in) to switch to once faded out
        self._gen = 0               # counts play_from calls (the list may have changed)
        self._epoch = 0             # counts rebase calls (song numbers were renumbered)
        self._latency = 0           # bytes queued in the stream (set by the feed)
        self._decoder = None
        self._decoding = None       # the _Song being decoded

        self._thread = QThread(self)
        self._thread.setObjectName("audio")
        self._out = _Output(self)
        self._out.moveToThread(self._thread)
        self._out.joined.connect(self._joined)
        self._out.wantDecode.connect(self._decode_more)
        self._out.ran_out.connect(self._ran_out)
        self._toDevice.connect(self._out.make_sink)
        self._toVolume.connect(self._out.set_volume)
        # The stream and its feed belong to the audio thread: deleting _out there
        # as it ends takes its sink and feed with it, not whichever thread
        # happens to collect them later.
        self._thread.finished.connect(self._out.deleteLater)
        self._thread.start(QThread.Priority.TimeCriticalPriority)
        self._toDevice.emit(device)
        app = QCoreApplication.instance()
        if app is not None:
            app.aboutToQuit.connect(self._shutdown)

    def _shutdown(self):
        """End the audio thread (which deletes the stream) and stop any decoder still running.
        Safe to call twice (a test, then the app quitting)."""
        self._closed = True
        self._thread.quit()
        self._thread.wait(1000)
        with self._lock:
            self._stop_decoder()

    # ---- the stream ---------------------------------------------------------
    def set_device(self, device):
        self._toDevice.emit(device)

    def set_volume(self, v):
        self._toVolume.emit(float(v))

    def _joined(self, index, gen, epoch, ms):
        """Say song `index` is playing once the audio queued ahead of it has
        been heard, unless play_from has started something else by then:
        the index would be into a list that's gone. `epoch` is as it was when
        the index was read: a rebase can land before this gets to the main thread."""
        if DEBUG:
            print(f"audio: song {index} joins in {ms} ms", flush=True)

        def heard():
            if gen != self._gen:
                return
            if epoch != self._epoch:        # renumbered since: that song's number now
                index_now = self._joined_now(gen)
                if index_now is not None:
                    self.trackStarted.emit(index_now)
            else:
                self.trackStarted.emit(index)
        QTimer.singleShot(ms, heard)

    def _joined_now(self, gen):
        """The number of the song that joined (the first in line, or the one a
        seek is switching to) after a rebase, or None."""
        with self._lock:
            if self._pending is not None:
                return self._pending[0]
            if self._songs and self._songs[0].gen == gen:
                return self._songs[0].index
        return None

    def _next(self, index):
        nxt = self._after(index, index in self._bad)
        # After a song that won't decode, one that already failed means a loop
        # of failures (a one-song queue, or nothing readable): stop instead.
        return None if index in self._bad and nxt in self._bad else nxt

    def _ran_out(self, gen, ms):
        """The list ended: once its last song has been heard, stop, paused."""
        QTimer.singleShot(ms, lambda: gen == self._gen and self._end())

    def _end(self):
        with self._lock:
            self._want_play = False
            if self._pending is None:
                self._target = 0.0
        self.ended.emit()

    def refresh_next(self):
        """The order changed (shuffle, repeat): forget the song already lined
        up after the current one and line up the right one."""
        with self._lock:
            if self._pending is not None:
                return
            while len(self._songs) > 1:
                self._songs.pop()
        self._decode_more()

    def rebase(self, remap, apply=None):
        """The list was rebuilt around the song playing: renumber the songs
        in flight (`remap`: old index -> new) and line up the one after again.
        `apply` swaps in the new list; it runs under the lock, so the audio
        thread never sees the old list with the new numbers."""
        with self._lock:
            if apply:
                apply()
            self._epoch += 1
            if self._pending is not None:
                index, skip = self._pending
                self._pending = (remap(index), skip)
            while len(self._songs) > 1:
                self._songs.pop()
            if self._songs:
                self._songs[0].index = remap(self._songs[0].index)
            self._bad.clear()
        self._decode_more()

    # ---- decoding (main thread) ---------------------------------------------
    def _decode_more(self):
        """Decode the first song not yet decoded, as far as its limit allows;
        once the current song is decoded, line up the next one too."""
        with self._lock:
            if self._closed:
                return
            if self._decoding is not None and self._decoding not in self._songs:
                self._stop_decoder()            # its song was skipped
            dec, song = self._decoder, self._decoding
            if song is None:
                if self._songs and self._songs[-1].done and len(self._songs) < 2:
                    last = self._songs[-1]
                    nxt = self._next(last.index)
                    if nxt is not None:
                        self._songs.append(_Song(nxt, last.gen))
                song = next((s for s in self._songs if not s.done), None)
            if song is None or song.held:       # held: until the feed has played some
                return
        if dec is not None:
            self._decoded(dec, song)            # it's been waiting on us
            return
        dec = QAudioDecoder(self)
        dec.setAudioFormat(audio_format())
        dec.setSource(QUrl.fromLocalFile(self._path_of(song.index)))
        dec.bufferReady.connect(lambda: self._decoded(dec, song))
        dec.finished.connect(lambda: self._decode_done(dec, song))
        dec.error.connect(lambda _e: self._decode_failed(dec, song))
        self._decoder, self._decoding = dec, song
        dec.start()

    def _limit(self, song):
        current = self._songs and song is self._songs[0]
        return (AHEAD_S if current else NEXT_S) * BYTES_PER_S

    def _decoded(self, dec, song, drain=False):
        """Take what the decoder has, up to the song's limit. Leaving a buffer
        unread is what makes it wait. `drain`: it's finished, take the lot."""
        while dec.bufferAvailable():
            with self._lock:
                if not drain and (song.held or song.end - song.played >= self._limit(song)):
                    if song.held:
                        song.strays += 1
                        if song.strays > STRAYS:        # it won't wait: stop it, and
                            song.strays = 0             # start over when it's needed
                            song.skip, song.end = song.end, 0
                            self._stop_decoder()
                    song.held = True
                    return
            buf = dec.read()
            size = buf.byteCount()
            song.end += size
            if size <= song.skip:                       # quick: no copy of what's left out
                song.skip -= size
            elif size:
                data = buf.constData().asstring(size)
                song.chunks.append(data[song.skip:] if song.skip else data)
                song.skip = 0

    def _decode_done(self, dec, song):
        self._decoded(dec, song, drain=True)
        if song.end:                             # gave us sound: the run of bad songs is over
            with self._lock:
                self._bad.clear()
        else:                                    # no sound and no error: as bad as one that failed
            print(f"Music: {self._path_of(song.index)} decoded to nothing")
            self._bad.add(song.index)            # before done: what follows it can't be itself
        song.held = False
        song.done = True
        self._drop_decoder(dec)
        self._decode_more()

    def _decode_failed(self, dec, song):
        print(f"Music: couldn't decode {self._path_of(song.index)} ({dec.errorString()})")
        self._bad.add(song.index)                # before done: what follows it can't be itself
        song.done = True                         # skipped: it plays as nothing
        self._drop_decoder(dec)
        self._decode_more()

    def _drop_decoder(self, dec):
        if dec is self._decoder:
            self._decoder = self._decoding = None
        dec.deleteLater()

    def _stop_decoder(self):
        if self._decoder is not None:
            dec = self._decoder
            self._decoder = self._decoding = None
            for sig in (dec.bufferReady, dec.finished, dec.error):
                sig.disconnect()
            dec.stop()
            dec.deleteLater()

    # ---- controls -----------------------------------------------------------
    def play_from(self, index, play=True, at=0):
        """Start song `index` now, `at` seconds in, fading out whatever is
        playing first. With play False it waits there, paused."""
        with self._lock:
            self._bad.clear()
            self._want_play = play
            self._gen += 1
            now = self._switch(index, at)
        if now:
            self._decode_more()

    def seek(self, seconds):
        """Jump within the song being heard, playing or paused as it is. The
        song hasn't changed, so unlike play_from the generation stays: a
        trackStarted on its way still counts."""
        with self._lock:
            if self._pending is not None:
                index = self._pending[0]
            elif self._songs:
                index = self._songs[0].index
            else:
                return
            now = self._switch(index, seconds)
        if now:
            self._decode_more()

    def _switch(self, index, at):
        """Under the lock: restart from `at` seconds into song `index`. True
        if that's done and needs decoding; if not, the feed does it once faded out."""
        skip = int(max(0, at) * RATE) * FRAME
        if self._gain > 0.0:
            self._pending = (index, skip)
            self._target = 0.0
            return False
        self._pending = None
        self._songs.clear()
        self._songs.append(_Song(index, self._gen, skip))
        self._target = 1.0 if self._want_play else 0.0
        return True

    def set_playing(self, on):
        with self._lock:
            self._want_play = on
            if self._pending is None:
                self._target = 1.0 if on else 0.0

    @property
    def playing(self):
        return self._want_play

    def position(self):
        """Seconds into the song being heard."""
        with self._lock:
            if self._pending is not None:
                return self._pending[1] // BYTES_PER_S    # a seek shows where it's going
            if not self._songs:
                return 0
            # Paused, what's queued in the stream is silence: counting it
            # would put a restored song (and each save of it) a bit earlier.
            held = self._latency if self._want_play else 0
            return max(0, self._songs[0].played - held) // BYTES_PER_S
