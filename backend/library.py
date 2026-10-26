"""Plays real audio files from a music folder.

`LibraryPlayer` has the same properties and slots as the demo `MediaPlayer`,
so the QML doesn't care which one it gets. Tags and cover art (embedded, or
a cover.jpg beside the files) are read with mutagen. Playback is gapless
(backend/gapless.py), so songs that run into each other on an album do
here too. Songs are grouped into albums by their tags, and playing an
album makes it the queue; "all songs" plays everything in folder order.
"""

import hashlib
import re
import tempfile
from pathlib import Path

import mutagen
from PyQt6.QtCore import QObject, QTimer, QUrl, pyqtProperty, pyqtSignal, pyqtSlot
from PyQt6.QtMultimedia import QMediaDevices

from backend.gapless import GaplessEngine

EQ_SINK = "baja_eq"           # the equalizer's input (deploy/audio/baja-eq.conf)
AUDIO_EXTENSIONS = {".mp3", ".m4a", ".aac", ".flac", ".ogg", ".opus", ".wav"}
ART_CACHE = Path(tempfile.gettempdir()) / "baja-art"


COVER_NAMES = ("cover", "folder", "front", "album")
COVER_TYPES = (".jpg", ".jpeg", ".png")


def _first_tag(tags, *keys):
    for key in keys:
        try:
            value = tags.get(key)
        except ValueError:     # FLAC/Ogg tags reject names they can't hold (e.g. "\xa9nam")
            continue
        if value:
            text = value[0] if isinstance(value, list) else getattr(value, "text", [value])[0]
            return str(text)
    return ""


def _number(tags, *keys):
    """A track or disc number ("3/12", (3, 12) or "03") as an int, or 0."""
    for key in keys:
        try:
            value = tags.get(key)
        except ValueError:
            continue
        if not value:
            continue
        v = value[0] if isinstance(value, list) else getattr(value, "text", [value])[0]
        if isinstance(v, tuple):          # MP4 "trkn": [(3, 12)]
            v = v[0]
        m = re.match(r"\s*(\d+)", str(v))
        if m:
            return int(m[1])
    return 0


def _folder_art(path):
    """A cover picture saved beside the song (cover.jpg and the like), or ''."""
    for f in sorted(path.parent.iterdir()):
        if f.suffix.lower() in COVER_TYPES and f.stem.lower() in COVER_NAMES:
            return QUrl.fromLocalFile(str(f)).toString()
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
        try:
            tracks.append({
                "path": str(path),
                "title": _first_tag(tags, "TIT2", "\xa9nam", "title") or path.stem,
                "artist": _first_tag(tags, "TPE1", "\xa9ART", "artist") or "Unknown artist",
                "duration": int(audio.info.length),
                "art": _extract_art(path, audio) or _folder_art(path),
                "album": _first_tag(tags, "TALB", "\xa9alb", "album") or path.parent.name,
                "albumArtist": _first_tag(tags, "TPE2", "aART", "albumartist", "album artist"),
                "disc": _number(tags, "TPOS", "disk", "discnumber"),
                "track": _number(tags, "TRCK", "trkn", "tracknumber"),
            })
        except Exception as e:  # one odd file mustn't stop the dashboard starting
            print(f"Music: skipped {path.name} ({e!r})")
    return tracks


def group_albums(tracks):
    """Albums from the songs' tags: [{title, artist, art, tracks: [indexes]}],
    sorted by artist then title, each album's songs in disc and track order."""
    albums = {}
    for i, t in enumerate(tracks):
        artist = t.get("albumArtist") or t["artist"]
        key = (artist.casefold(), t["album"].casefold())
        a = albums.setdefault(key, {"title": t["album"], "artist": artist, "art": "", "tracks": []})
        a["tracks"].append(i)
        a["art"] = a["art"] or t["art"]
    for a in albums.values():
        # Disc and track numbers when they're usable; some releases restart
        # the numbers partway (a deluxe edition's bonus tracks, with no disc
        # number), and then the file names' order is the one to trust.
        numbers = [(tracks[i]["disc"], tracks[i]["track"]) for i in a["tracks"]]
        if all(n[1] for n in numbers) and len(set(numbers)) == len(numbers):
            a["tracks"].sort(key=lambda i: (tracks[i]["disc"], tracks[i]["track"], tracks[i]["path"]))
        else:
            a["tracks"].sort(key=lambda i: tracks[i]["path"])
    return [albums[k] for k in sorted(albums, key=lambda k: (k[0], k[1]))]


def preferred_output():
    """The equalizer when it's running, so music goes through it and on to
    whichever output is the default (the sound board); else the default.
    Qt keeps the output it's given, so handing it the default would pin
    music to whatever that was at start-up."""
    for device in QMediaDevices.audioOutputs():
        if bytes(device.id()).decode(errors="ignore") == EQ_SINK:
            return device
    return QMediaDevices.defaultAudioOutput()


class LibraryPlayer(QObject):
    trackChanged = pyqtSignal()
    positionChanged = pyqtSignal()
    playingChanged = pyqtSignal()
    volumeChanged = pyqtSignal()
    queueChanged = pyqtSignal()

    def __init__(self, tracks, parent=None):
        super().__init__(parent)
        self._all = tracks
        self._albums = group_albums(tracks)
        self._queue = list(tracks)      # what's playing through: an album, or all songs
        self._album = -1                # index into _albums, or -1 for all songs
        self._index = 0
        self._volume = 40

        self._engine = GaplessEngine(lambda i: self._queue[i]["path"], lambda: len(self._queue),
                                     preferred_output(), self)
        self._engine.trackStarted.connect(self._heard)
        # The equalizer may start after the dashboard: move to it when it does.
        self._devices = QMediaDevices(self)
        self._devices.audioOutputsChanged.connect(self._pick_output)
        self._tick = QTimer(self, interval=500,
                            timeout=lambda: self._engine.playing and self.positionChanged.emit())
        self._tick.start()
        self._apply_volume()

    def start(self):
        self._go(self._index)

    def _pick_output(self):
        self._engine.set_device(preferred_output())

    def _go(self, index):
        """Play song `index` of the queue now."""
        self._index = index % len(self._queue)
        self._engine.play_from(self._index)
        self.trackChanged.emit()
        self.positionChanged.emit()
        self.playingChanged.emit()

    def _heard(self, index):
        """The next song started by itself (no gap): show it."""
        if 0 <= index < len(self._queue) and index != self._index:
            self._index = index
            self.trackChanged.emit()
            self.positionChanged.emit()

    def _apply_volume(self):
        # Squared so the low end of the bar isn't all "loud"; ears hear
        # volume roughly logarithmically.
        self._engine.set_volume((self._volume / 100) ** 2)

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

    @pyqtProperty("QVariantList", notify=queueChanged)
    def queue(self):
        return [{"title": t["title"], "artist": t["artist"]} for t in self._queue]

    @pyqtProperty("QVariantList", constant=True)
    def albums(self):
        return [{"title": a["title"], "artist": a["artist"], "art": a["art"],
                 "count": len(a["tracks"]),
                 "duration": sum(self._all[i]["duration"] for i in a["tracks"])}
                for a in self._albums]

    @pyqtProperty(int, notify=queueChanged)
    def album(self):
        """The album playing, as an index into `albums`, or -1 for all songs."""
        return self._album

    @pyqtSlot(int, result="QVariantList")
    def albumTracks(self, album):
        if not 0 <= album < len(self._albums):
            return []
        return [{"title": self._all[i]["title"], "artist": self._all[i]["artist"],
                 "duration": self._all[i]["duration"]} for i in self._albums[album]["tracks"]]

    @pyqtProperty(int, notify=positionChanged)
    def position(self):
        return self._engine.position()

    @pyqtProperty(bool, notify=playingChanged)
    def playing(self):
        return self._engine.playing

    @pyqtProperty(int, notify=volumeChanged)
    def volume(self):
        return self._volume

    # ---- controls ---------------------------------------------------------
    @pyqtSlot()
    def togglePlay(self):
        self._engine.set_playing(not self._engine.playing)
        self.playingChanged.emit()

    @pyqtSlot()
    def next(self):
        self._go(self._index + 1)

    @pyqtSlot()
    def previous(self):
        # Like a head unit: back to the start of the song, unless just begun.
        self._go(self._index if self._engine.position() > 3 else self._index - 1)

    @pyqtSlot(int)
    def playIndex(self, index):
        self._go(index)

    @pyqtSlot(int, int)
    def playAlbum(self, album, start=0):
        """Play an album from one of its songs; it becomes the queue."""
        if not 0 <= album < len(self._albums):
            return
        self._queue = [self._all[i] for i in self._albums[album]["tracks"]]
        self._album = album
        self.queueChanged.emit()
        self.playIndex(start)

    @pyqtSlot()
    def playAll(self):
        """Back to every song, in folder order, from the first."""
        self._queue = list(self._all)
        self._album = -1
        self.queueChanged.emit()
        self.playIndex(0)

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
