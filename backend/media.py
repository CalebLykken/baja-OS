"""Media playback exposed to the UI.

`MediaPlayer` fakes a playlist so the music screens have something to show
(on a Mac; the truck only shows what's real). Given an empty queue it's an
empty player instead: nothing playing, and every key does nothing.
The real players are backend/library.py (local files), bluetooth.py (phone)
and spotify.py; this is the stand-in the UI shows when none is wired.
`volumeUp`/`volumeDown` are what the dash knob drives.
"""

from PyQt6.QtCore import QObject, QTimer, pyqtProperty, pyqtSignal, pyqtSlot

DEMO_QUEUE = [
    {"title": "Gravel Road Overture", "artist": "The Flat-Four Choir", "duration": 214},
    {"title": "Intercooler Blues", "artist": "Boxer Rebellion", "duration": 187},
    {"title": "Cascade Pass", "artist": "Northbound Static", "duration": 241},
    {"title": "Maple Leaf Night Drive", "artist": "Lo-Fi Odometer", "duration": 198},
    {"title": "Head Gasket Heartbreak", "artist": "The Timing Belts", "duration": 176},
    {"title": "Ferry Line Daydream", "artist": "Sound & Puget", "duration": 222},
]
NO_SONG = {"title": "", "artist": "", "duration": 0}
NO_STATE = {"album": None, "path": "", "index": 0, "position": 0}   # state() with nothing to resume


class MediaPlayer(QObject):
    trackChanged = pyqtSignal()
    positionChanged = pyqtSignal()
    playingChanged = pyqtSignal()
    volumeChanged = pyqtSignal()
    queueChanged = pyqtSignal()             # never: the demo has no albums
    modesChanged = pyqtSignal()             # never: the demo plays in order

    def __init__(self, queue=None, parent=None):
        """The demo playlist, or `queue` (a list of {title, artist, duration};
        [] for none)."""
        super().__init__(parent)
        self._queue = list(DEMO_QUEUE if queue is None else queue)
        self._index = 0 if self._queue else -1
        self._position = 37 if self._queue else 0
        self._playing = bool(self._queue)
        self._saved = None              # what restore() was given, kept while the queue is empty
        self._volume = 40
        self._timer = QTimer(self)
        self._timer.setInterval(1000)
        self._timer.timeout.connect(self._tick)

    def restore(self, state, play=False):
        """Pick up the song and place in it from the last run (as
        LibraryPlayer does), playing only if `play`. With nothing saved
        the demo plays from where it always has."""
        if not self._queue:
            self._saved = dict(state) if isinstance(state, dict) else None   # state() hands it back
            return
        state = state if isinstance(state, dict) else {}
        if isinstance(state.get("index"), int):
            self._index = state["index"] % len(self._queue)
        if isinstance(state.get("position"), int):
            self._position = max(0, min(state["position"], self.duration - 1))
        self._playing = play

    def state(self):
        """Where the demo is up to, in LibraryPlayer's shape (with an empty
        queue, what restore() was given)."""
        if not self._queue:
            return dict(NO_STATE if self._saved is None else self._saved)
        return {"album": None, "path": "", "index": self._index, "position": self._position}

    def start(self):
        if self._queue:
            self._timer.start()

    def _tick(self):
        if not self._playing:
            return
        self._position += 1
        if self._position >= self.duration:
            self.next()
        else:
            self.positionChanged.emit()

    def _song(self):
        return self._queue[self._index] if self._queue else NO_SONG

    def _set_index(self, index):
        if not self._queue:
            return
        self._index = index % len(self._queue)
        self._position = 0
        self.trackChanged.emit()
        self.positionChanged.emit()

    # ---- properties -------------------------------------------------------
    @pyqtProperty(str, notify=trackChanged)
    def title(self):
        return self._song()["title"]

    @pyqtProperty(str, notify=trackChanged)
    def artist(self):
        return self._song()["artist"]

    @pyqtProperty(str, notify=trackChanged)
    def art(self):
        return ""  # demo tracks have no cover art

    @pyqtProperty(int, notify=trackChanged)
    def duration(self):
        return self._song()["duration"]

    @pyqtProperty(int, notify=trackChanged)
    def index(self):
        return self._index

    @pyqtProperty("QVariantList", constant=True)
    def queue(self):
        return self._queue

    @pyqtProperty(bool, constant=True)
    def hasModes(self):
        return False

    @pyqtProperty(bool, constant=True)
    def canSeek(self):
        """AVRCP has no seek: the bar stays inert."""
        return False

    @pyqtProperty(bool, constant=True)
    def shuffle(self):
        return False

    @pyqtProperty(str, constant=True)
    def repeat(self):
        return "all"

    def set_modes(self, shuffle, repeat):
        pass

    @pyqtSlot()
    def toggleShuffle(self):
        pass

    @pyqtSlot()
    def cycleRepeat(self):
        pass

    @pyqtProperty("QVariantList", constant=True)
    def albums(self):
        return []

    @pyqtProperty(int, constant=True)
    def album(self):
        return -1

    @pyqtSlot(int, result="QVariantList")
    def albumTracks(self, album):
        return []

    @pyqtSlot(int, int)
    def playAlbum(self, album, start=0):
        pass

    @pyqtSlot()
    def playAll(self):
        self.playIndex(0)

    @pyqtProperty(int, notify=positionChanged)
    def position(self):
        return self._position

    @pyqtProperty(bool, notify=playingChanged)
    def playing(self):
        return self._playing

    @pyqtProperty(int, notify=volumeChanged)
    def volume(self):
        return self._volume

    # ---- controls ---------------------------------------------------------
    @pyqtSlot()
    def togglePlay(self):
        if not self._queue:
            return
        self._playing = not self._playing
        self.playingChanged.emit()

    @pyqtSlot()
    def next(self):
        self._set_index(self._index + 1)

    @pyqtSlot()
    def previous(self):
        # Like a real head unit: restart the song unless we're near the start.
        if self._position > 3:
            self._position = 0
            self.positionChanged.emit()
        else:
            self._set_index(self._index - 1)

    @pyqtSlot(int)
    def playIndex(self, index):
        if not self._queue:
            return
        self._set_index(index)
        if not self._playing:
            self.togglePlay()

    @pyqtSlot(int)
    def setVolume(self, value):
        value = max(0, min(100, int(value)))
        if value != self._volume:
            self._volume = value
            self.volumeChanged.emit()

    @pyqtSlot()
    def volumeUp(self):
        self.setVolume(self._volume + 2)

    @pyqtSlot()
    def volumeDown(self):
        self.setVolume(self._volume - 2)
