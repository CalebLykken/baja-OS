"""Media playback exposed to the UI.

`MediaPlayer` fakes a playlist so the music screens have something to show.
Later this becomes a real player (MPD, a Bluetooth/AirPlay sink, or Spotify
audio metadata), and `volumeUp`/`volumeDown` get wired to the dash knob.
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


class MediaPlayer(QObject):
    trackChanged = pyqtSignal()
    positionChanged = pyqtSignal()
    playingChanged = pyqtSignal()
    volumeChanged = pyqtSignal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self._queue = list(DEMO_QUEUE)
        self._index = 0
        self._position = 37
        self._playing = True
        self._volume = 40
        self._timer = QTimer(self)
        self._timer.setInterval(1000)
        self._timer.timeout.connect(self._tick)

    def start(self):
        self._timer.start()

    def _tick(self):
        if not self._playing:
            return
        self._position += 1
        if self._position >= self.duration:
            self.next()
        else:
            self.positionChanged.emit()

    def _set_index(self, index):
        self._index = index % len(self._queue)
        self._position = 0
        self.trackChanged.emit()
        self.positionChanged.emit()

    # ---- properties -------------------------------------------------------
    @pyqtProperty(str, notify=trackChanged)
    def title(self):
        return self._queue[self._index]["title"]

    @pyqtProperty(str, notify=trackChanged)
    def artist(self):
        return self._queue[self._index]["artist"]

    @pyqtProperty(str, notify=trackChanged)
    def art(self):
        return ""  # demo tracks have no cover art

    @pyqtProperty(int, notify=trackChanged)
    def duration(self):
        return self._queue[self._index]["duration"]

    @pyqtProperty(int, notify=trackChanged)
    def index(self):
        return self._index

    @pyqtProperty("QVariantList", constant=True)
    def queue(self):
        return self._queue

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
