"""Plays real audio files from a music folder.

`LibraryPlayer` has the same properties and slots as the demo `MediaPlayer`,
so the QML doesn't care which one it gets. Tags and embedded cover art are
read with mutagen; playback goes through Qt Multimedia.
"""

import hashlib
import tempfile
from pathlib import Path

import mutagen
from PyQt6.QtCore import QObject, QUrl, pyqtProperty, pyqtSignal, pyqtSlot
from PyQt6.QtMultimedia import QAudioOutput, QMediaPlayer

AUDIO_EXTENSIONS = {".mp3", ".m4a", ".aac", ".flac", ".ogg", ".opus", ".wav"}
ART_CACHE = Path(tempfile.gettempdir()) / "baja-art"


def _first_tag(tags, *keys):
    for key in keys:
        value = tags.get(key)
        if value:
            text = value[0] if isinstance(value, list) else getattr(value, "text", [value])[0]
            return str(text)
    return ""


def _extract_art(path, audio):
    """Save embedded cover art to the cache and return its file URL, or ''."""
    data = None
    tags = audio.tags or {}
    for key in tags.keys():
        if key.startswith("APIC"):  # ID3 (mp3)
            data = tags[key].data
            break
    if data is None and "covr" in tags:  # MP4 (m4a)
        data = bytes(tags["covr"][0])
    if data is None and getattr(audio, "pictures", None):  # FLAC
        data = audio.pictures[0].data
    if not data:
        return ""
    ART_CACHE.mkdir(exist_ok=True)
    out = ART_CACHE / (hashlib.sha1(str(path).encode()).hexdigest() + ".img")
    if not out.exists():
        out.write_bytes(data)
    return QUrl.fromLocalFile(str(out)).toString()


def scan(folder):
    """Return a sorted list of track dicts for every audio file under folder."""
    tracks = []
    for path in sorted(Path(folder).expanduser().rglob("*")):
        if path.suffix.lower() not in AUDIO_EXTENSIONS or not path.is_file():
            continue
        try:
            audio = mutagen.File(path)
        except Exception:
            audio = None
        if audio is None:
            continue
        tags = audio.tags or {}
        tracks.append({
            "path": str(path),
            "title": _first_tag(tags, "TIT2", "\xa9nam", "title") or path.stem,
            "artist": _first_tag(tags, "TPE1", "\xa9ART", "artist") or "Unknown artist",
            "duration": int(audio.info.length),
            "art": _extract_art(path, audio),
        })
    return tracks


class LibraryPlayer(QObject):
    trackChanged = pyqtSignal()
    positionChanged = pyqtSignal()
    playingChanged = pyqtSignal()
    volumeChanged = pyqtSignal()

    def __init__(self, tracks, parent=None):
        super().__init__(parent)
        self._queue = tracks
        self._index = 0
        self._volume = 40

        self._output = QAudioOutput(self)
        self._player = QMediaPlayer(self)
        self._player.setAudioOutput(self._output)
        self._player.positionChanged.connect(lambda _: self.positionChanged.emit())
        self._player.playbackStateChanged.connect(lambda _: self.playingChanged.emit())
        self._player.mediaStatusChanged.connect(self._on_status)
        self._player.errorOccurred.connect(
            lambda _err, msg: print(f"Playback error: {msg}"))
        self._apply_volume()
        self._load(0)

    def start(self):
        self._player.play()

    def _load(self, index):
        self._index = index % len(self._queue)
        self._player.setSource(QUrl.fromLocalFile(self._queue[self._index]["path"]))
        self.trackChanged.emit()
        self.positionChanged.emit()

    def _on_status(self, status):
        if status == QMediaPlayer.MediaStatus.EndOfMedia:
            self.next()

    def _apply_volume(self):
        # Squared so the low end of the bar isn't all "loud"; ears hear
        # volume roughly logarithmically.
        self._output.setVolume((self._volume / 100) ** 2)

    # ---- properties -------------------------------------------------------
    @pyqtProperty(str, notify=trackChanged)
    def title(self):
        return self._queue[self._index]["title"]

    @pyqtProperty(str, notify=trackChanged)
    def artist(self):
        return self._queue[self._index]["artist"]

    @pyqtProperty(str, notify=trackChanged)
    def art(self):
        return self._queue[self._index]["art"]

    @pyqtProperty(int, notify=trackChanged)
    def duration(self):
        return self._queue[self._index]["duration"]

    @pyqtProperty(int, notify=trackChanged)
    def index(self):
        return self._index

    @pyqtProperty("QVariantList", constant=True)
    def queue(self):
        return [{"title": t["title"], "artist": t["artist"]} for t in self._queue]

    @pyqtProperty(int, notify=positionChanged)
    def position(self):
        return self._player.position() // 1000

    @pyqtProperty(bool, notify=playingChanged)
    def playing(self):
        return self._player.playbackState() == QMediaPlayer.PlaybackState.PlayingState

    @pyqtProperty(int, notify=volumeChanged)
    def volume(self):
        return self._volume

    # ---- controls ---------------------------------------------------------
    @pyqtSlot()
    def togglePlay(self):
        if self.playing:
            self._player.pause()
        else:
            self._player.play()

    @pyqtSlot()
    def next(self):
        self._load(self._index + 1)
        self._player.play()

    @pyqtSlot()
    def previous(self):
        if self._player.position() > 3000:
            self._player.setPosition(0)
        else:
            self._load(self._index - 1)
            self._player.play()

    @pyqtSlot(int)
    def playIndex(self, index):
        self._load(index)
        self._player.play()

    @pyqtSlot(int)
    def setVolume(self, value):
        value = max(0, min(100, int(value)))
        if value != self._volume:
            self._volume = value
            self._apply_volume()
            self.volumeChanged.emit()

    @pyqtSlot()
    def volumeUp(self):
        self.setVolume(self._volume + 2)

    @pyqtSlot()
    def volumeDown(self):
        self.setVolume(self._volume - 2)
