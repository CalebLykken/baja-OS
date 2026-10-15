"""Gapless playback for the Pi's own music.

Qt's media player closes its audio stream at the end of every song and
opens a new one for the next, which leaves a short gap and a click: wrong
for albums whose songs run into each other. Here there's one audio stream
that never closes. Songs are decoded to plain 48 kHz stereo samples
(QAudioDecoder, far faster than they play), the next one while the current
one plays, and fed into the stream back to back, so one ends on exactly
the sample the next begins.

Pausing and skipping fade over 30 ms instead of cutting mid-wave, and
while paused the stream plays silence rather than stopping, so nothing
clicks. A decoded song is held in memory until it has played (about 10 MB
a minute), at most the current one and the next.
"""

from array import array
from collections import deque

from PyQt6.QtCore import QIODevice, QObject, QTimer, QUrl, pyqtSignal
from PyQt6.QtMultimedia import QAudio, QAudioDecoder, QAudioFormat, QAudioSink

RATE, CHANNELS, SAMPLE_BYTES = 48000, 2, 2
FRAME = CHANNELS * SAMPLE_BYTES
BYTES_PER_S = RATE * FRAME
BUFFER_S = 0.3              # what the audio system holds: room for a busy screen
RAMP_FRAMES = RATE * 30 // 1000


def audio_format():
    fmt = QAudioFormat()
    fmt.setSampleRate(RATE)
    fmt.setChannelCount(CHANNELS)
    fmt.setSampleFormat(QAudioFormat.SampleFormat.Int16)
    return fmt


class _Song:
    """One song's samples on their way to the speakers."""

    def __init__(self, index):
        self.index = index
        self.chunks = deque()
        self.done = False           # decoding finished (or failed)
        self.played = 0             # bytes handed to the stream so far


class _Feed(QIODevice):
    """What the audio stream reads from: always as much as it asks for."""

    def __init__(self, engine):
        super().__init__(engine)
        self._engine = engine

    def readData(self, maxlen):
        return self._engine._pull(maxlen)

    def writeData(self, data):
        return 0

    def isSequential(self):
        return True

    def bytesAvailable(self):
        return BYTES_PER_S + super().bytesAvailable()


class GaplessEngine(QObject):
    """Plays songs from a list, one after another, without gaps.

    `path_of(i)` and `count()` describe the list (it can change: call
    `play_from` after). `trackStarted(i)` says song i is now being heard."""
    trackStarted = pyqtSignal(int)

    def __init__(self, path_of, count, device, parent=None):
        super().__init__(parent)
        self._path_of, self._count = path_of, count
        self._songs = deque()
        self._decoder = None
        self._decoding = None       # the _Song being decoded
        self._want_play = False
        self._gain, self._target = 0.0, 0.0
        self._pending = None        # a song to switch to once faded out
        self._volume = 1.0
        self._feed = _Feed(self)
        self._feed.open(QIODevice.OpenModeFlag.ReadOnly)
        self._sink = None
        self._make_sink(device)

    # ---- the stream ---------------------------------------------------------
    def _make_sink(self, device):
        if self._sink is not None:
            self._sink.stop()
            self._sink.deleteLater()
        self._sink = QAudioSink(device, audio_format(), self)
        self._sink.setBufferSize(int(BYTES_PER_S * BUFFER_S) // FRAME * FRAME)
        self._sink.setVolume(self._volume)
        self._sink.stateChanged.connect(self._sink_state)
        self._sink.start(self._feed)

    def _sink_state(self, state):
        if state == QAudio.State.StoppedState and self._sink.error() != QAudio.Error.NoError:
            QTimer.singleShot(1000, lambda: self._make_sink(self._sink.device()))

    def set_device(self, device):
        if device != self._sink.device():
            self._make_sink(device)

    def set_volume(self, v):
        self._volume = v
        self._sink.setVolume(v)

    def _latency_bytes(self):
        return max(0, self._sink.bufferSize() - self._sink.bytesFree())

    def _pull(self, maxlen):
        maxlen -= maxlen % FRAME
        if maxlen <= 0:
            return b""
        if self._gain == 0.0 and self._target == 0.0:
            if self._pending is not None:       # faded out: now switch songs
                index, self._pending = self._pending, None
                self._start_song(index)
                if self._want_play:
                    self._target = 1.0
            if self._target == 0.0:
                return bytes(maxlen)            # paused: silence, stream stays open

        out = bytearray()
        while len(out) < maxlen and self._songs:
            song = self._songs[0]
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
            elif song.done:                     # its end: straight into the next
                self._songs.popleft()
                if not self._songs:
                    self._queue_next(after=song.index)
                if self._songs:
                    self._announce(self._songs[0].index)
                self._decode_more()
            else:
                break                           # decoding hasn't caught up
        out += bytes(maxlen - len(out))
        if self._gain != 1.0 or self._target != 1.0:
            out = self._ramp(out)
        return bytes(out)

    def _ramp(self, data):
        samples = array("h")
        samples.frombytes(bytes(data))
        g, target, step = self._gain, self._target, 1.0 / RAMP_FRAMES
        for f in range(0, len(samples), CHANNELS):
            if g != target:
                g = min(target, g + step) if target > g else max(target, g - step)
            for c in range(CHANNELS):
                samples[f + c] = int(samples[f + c] * g)
        self._gain = g
        return samples.tobytes()

    # ---- songs --------------------------------------------------------------
    def _announce(self, index):
        """Say song `index` is playing once the audio already queued ahead of
        it has been heard."""
        ms = int(self._latency_bytes() * 1000 / BYTES_PER_S)
        QTimer.singleShot(ms, lambda: self.trackStarted.emit(index))

    def _start_song(self, index):
        self._stop_decoder()
        self._songs.clear()
        self._songs.append(_Song(index))
        self._decode_more()

    def _queue_next(self, after):
        n = self._count()
        if n:
            self._songs.append(_Song((after + 1) % n))

    def _decode_more(self):
        """Decode the first song not yet decoded; once the current song is
        decoded, line up the next one too."""
        if self._decoding is not None:
            return
        if self._songs and self._songs[-1].done and len(self._songs) < 2:
            self._queue_next(after=self._songs[-1].index)
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
                song.chunks.append(buf.constData().asstring(buf.byteCount()))

    def _decode_done(self, dec, song):
        self._decoded(dec, song)
        song.done = True
        self._drop_decoder(dec)
        self._decode_more()

    def _decode_failed(self, dec, song):
        print(f"Music: couldn't decode {self._path_of(song.index)} ({dec.errorString()})")
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
    def play_from(self, index, play=True):
        """Start song `index` now, fading out whatever is playing first."""
        self._want_play = play
        if self._gain > 0.0:
            self._pending = index
            self._target = 0.0
        else:
            self._start_song(index)
            self._pending = None
            self._target = 1.0 if play else 0.0

    def set_playing(self, on):
        self._want_play = on
        if self._pending is None:
            self._target = 1.0 if on else 0.0

    @property
    def playing(self):
        return self._want_play

    def position(self):
        """Seconds into the song being heard."""
        if not self._songs or self._pending is not None:
            return 0
        return max(0, self._songs[0].played - self._latency_bytes()) // BYTES_PER_S
