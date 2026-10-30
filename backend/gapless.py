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
clicks. A decoded song is held in memory until it has played (about 10 MB
a minute), at most the current one and the next.
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
    joined = pyqtSignal(int, int, int)  # a song took over: its index, generation, ms until heard
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
        if state == QAudio.State.StoppedState and self.sink.error() != QAudio.Error.NoError:
            QTimer.singleShot(1000, lambda: self.make_sink(self.sink.device()))

    @pyqtSlot(float)
    def set_volume(self, v):
        self.volume = v
        if self.sink is not None:
            self.sink.setVolume(v)

    @pyqtSlot()
    def stop(self):
        if self.sink is not None:
            self.sink.stop()

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
                        self.joined.emit(nxt.index, nxt.gen, int(ahead * 1000 / BYTES_PER_S))
                    self.wantDecode.emit()
                else:
                    break                       # decoding hasn't caught up
            starved = len(out) < maxlen and e._gain == 1.0 and e._target == 1.0
        if DEBUG and starved:
            print(f"audio: starved, {(maxlen - len(out)) * 1000 // BYTES_PER_S} ms of silence", flush=True)
        out += bytes(maxlen - len(out))
        if e._gain != 1.0 or e._target != 1.0:
            out = self._ramp(out)
        return bytes(out)

    def _ramp(self, data):
        e = self.e
        samples = array("h")
        samples.frombytes(bytes(data))
        g, target, step = e._gain, e._target, 1.0 / RAMP_FRAMES
        for f in range(0, len(samples), CHANNELS):
            if g != target:
                g = min(target, g + step) if target > g else max(target, g - step)
            for c in range(CHANNELS):
                samples[f + c] = int(samples[f + c] * g)
        e._gain = g
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
    _toStop = pyqtSignal()

    def __init__(self, path_of, count, device, parent=None, after=None):
        """`after(i, failed)` is the song to play after song i, or None to stop
        (it runs on the audio thread, so it must only read); `failed`: song i
        couldn't be decoded, so it must not be followed by itself. By default
        the next one, round to the first at the end."""
        super().__init__(parent)
        self._path_of, self._count = path_of, count
        self._after = after or (lambda i, failed=False: (i + 1) % count() if count() else None)
        self._bad = set()           # songs that wouldn't decode since the last play_from
        self._lock = threading.Lock()
        self._songs = deque()
        self._want_play = False
        self._gain, self._target = 0.0, 0.0
        self._pending = None        # (song, bytes in) to switch to once faded out
        self._gen = 0               # counts play_from calls (the list may have changed)
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
        self._toStop.connect(self._out.stop)
        self._thread.start(QThread.Priority.TimeCriticalPriority)
        self._toDevice.emit(device)
        app = QCoreApplication.instance()
        if app is not None:
            app.aboutToQuit.connect(self._shutdown)

    def _shutdown(self):
        self._toStop.emit()
        self._thread.quit()
        self._thread.wait(1000)

    # ---- the stream ---------------------------------------------------------
    def set_device(self, device):
        self._toDevice.emit(device)

    def set_volume(self, v):
        self._toVolume.emit(float(v))

    def _joined(self, index, gen, ms):
        """Say song `index` is playing once the audio queued ahead of it has
        been heard, unless play_from has started something else by then:
        the index would be into a list that's gone."""
        if DEBUG:
            print(f"audio: song {index} joins in {ms} ms", flush=True)
        QTimer.singleShot(ms, lambda: gen == self._gen and self.trackStarted.emit(index))

    def _next(self, index):
        return self._after(index, index in self._bad)

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

    # ---- decoding (main thread) ---------------------------------------------
    def _decode_more(self):
        """Decode the first song not yet decoded; once the current song is
        decoded, line up the next one too."""
        with self._lock:
            if self._decoding is not None and self._decoding not in self._songs:
                self._stop_decoder()            # its song was skipped
            if self._decoding is not None:
                return
            if self._songs and self._songs[-1].done and len(self._songs) < 2:
                last = self._songs[-1]
                nxt = self._next(last.index)
                if nxt is not None:
                    self._songs.append(_Song(nxt, last.gen))
            song = next((s for s in self._songs if not s.done), None)
        if song is None:
            return
        dec = QAudioDecoder(self)
        dec.setAudioFormat(audio_format())
        dec.setSource(QUrl.fromLocalFile(self._path_of(song.index)))
        dec.bufferReady.connect(lambda: self._decoded(dec, song))
        dec.finished.connect(lambda: self._decode_done(dec, song))
        dec.error.connect(lambda _e: self._decode_failed(dec, song))
        self._decoder, self._decoding = dec, song
        dec.start()

    def _decoded(self, dec, song):
        while dec.bufferAvailable():
            buf = dec.read()
            if buf.byteCount():
                data = buf.constData().asstring(buf.byteCount())
                if song.skip:
                    cut = min(song.skip, len(data))
                    song.skip -= cut
                    data = data[cut:]
                if data:
                    song.chunks.append(data)

    def _decode_done(self, dec, song):
        self._decoded(dec, song)
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
        skip = int(max(0, at) * RATE) * FRAME
        with self._lock:
            self._bad.clear()
            self._want_play = play
            self._gen += 1
            if self._gain > 0.0:
                self._pending = (index, skip)
                self._target = 0.0
                return                           # the feed switches once faded out
            self._pending = None
            self._songs.clear()
            self._songs.append(_Song(index, self._gen, skip))
            self._target = 1.0 if play else 0.0
        self._decode_more()

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
            if not self._songs or self._pending is not None:
                return 0
            # Paused, what's queued in the stream is silence: counting it
            # would put a restored song (and each save of it) a bit earlier.
            held = self._latency if self._want_play else 0
            return max(0, self._songs[0].played - held) // BYTES_PER_S
