"""Plays real audio files from a music folder.

`LibraryPlayer` has the same properties and slots as the demo `MediaPlayer`,
so the QML doesn't care which one it gets. Tags and cover art (embedded, or
a cover.jpg beside the files) are read with mutagen. Playback is gapless
(backend/gapless.py), so songs that run into each other on an album do
here too. Songs are grouped into albums by their tags, and playing an
album makes it the queue; "all songs" plays everything in folder order.
After a restart it picks up the album, song and place in it that the hub
saved (backend/hub.py), and it never starts playing by itself otherwise.
Reading every file's tags is slow, so the folder is read off the UI thread
by a `LibraryScanner`, and the tags are kept in a cache file: a start-up
uses the cache at once, and `set_tracks` swaps in what the scan found
without interrupting the song playing.
With no songs (an empty folder, or the card not there yet) it's an honest
empty player: nothing playing, every key does nothing, and the resume point
it was given is kept for the next run that has music.
"""

import functools
import json
import os
import random
import re
import stat
import tempfile
import threading
from pathlib import Path

import mutagen
from PyQt6.QtCore import QObject, QTimer, QUrl, pyqtProperty, pyqtSignal, pyqtSlot
from PyQt6.QtMultimedia import QMediaDevices

from backend import artcache
from backend.gapless import GaplessEngine

EQ_SINK = "baja_eq"           # the equalizer's input (deploy/audio/baja-eq.conf)
AUDIO_EXTENSIONS = {".mp3", ".m4a", ".aac", ".flac", ".ogg", ".opus", ".wav"}
REPEATS = ("all", "one", "off")      # the order the key cycles; "all" is how it always played
NO_SONG = {"title": "", "artist": "", "art": "", "duration": 0}
NO_STATE = {"album": None, "path": "", "index": 0, "position": 0}   # state() with nothing to resume


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


def _folder_art(folder):
    """A cover picture saved in a song's folder (cover.jpg and the like), or ''."""
    for f in sorted(folder.iterdir()):
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
    out = artcache.store(artcache.digest(data) + ".img", data)    # the album's tracks share one
    return QUrl.fromLocalFile(str(out)).toString()


CACHE_VERSION = 1
TRACK_STRINGS = ("path", "title", "artist", "art", "album", "albumArtist")
TRACK_INTS = ("duration", "disc", "track")
TRACK_KEYS = set(TRACK_STRINGS + TRACK_INTS)


def cache_file():
    return artcache.cache_root() / "library.json"


def _load_cache(root):
    """{path: {"stamp": [mtime_ns, size], "embedded": bool, "track": dict or None}}
    from the last scan of `root`; empty if there's none, it's for another
    folder, or the file is damaged."""
    try:
        data = json.loads(cache_file().read_text())
        if data["version"] != CACHE_VERSION or data["folder"] != str(root):
            return {}
        files = data["files"]
        return files if isinstance(files, dict) else {}
    except (OSError, ValueError, KeyError, TypeError):
        return {}


def _save_cache(root, files):
    """Written whole under a temporary name and moved into place, so a crash
    never leaves half a file (only a temporary one, cleared up here later)."""
    path = cache_file()
    tmp = None
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        artcache.drop_stale_temp(path.parent)
        with tempfile.NamedTemporaryFile("w", dir=path.parent, prefix=".tmp-", delete=False) as f:
            tmp = f.name
            json.dump({"version": CACHE_VERSION, "folder": str(root), "files": files}, f)
        os.replace(tmp, path)
    except OSError as e:
        print(f"Music: couldn't save the library cache ({e!r})")
        if tmp:
            Path(tmp).unlink(missing_ok=True)


def _valid_track(track):
    """A cached track with every field the right kind (a hand-edited or
    damaged cache must not reach the player)."""
    return (isinstance(track, dict) and TRACK_KEYS <= track.keys()
            and all(isinstance(track[k], str) for k in TRACK_STRINGS)
            and all(type(track[k]) is int for k in TRACK_INTS))


def cached_tracks(folder):
    """The tracks the last scan found, straight from the cache: for an
    instant start. Empty if there's no usable cache, or the folder isn't
    there (or has no songs now), so the player stays honestly empty and its
    resume point is kept."""
    root = Path(folder).expanduser()
    tracks = []
    for entry in _load_cache(root).values():
        track = entry.get("track") if isinstance(entry, dict) else None
        if _valid_track(track):
            tracks.append(track)
    return tracks if tracks and has_audio_files(root) else []


def has_audio_files(folder):
    """Is there any audio file under folder? By name only, no tags."""
    return any(p.suffix.lower() in AUDIO_EXTENSIONS
               for p in Path(folder).expanduser().rglob("*"))


def _walk(root):
    """(path, stat) for every audio file and cover picture under root, sorted."""
    for path in sorted(root.rglob("*")):
        suffix = path.suffix.lower()
        if suffix not in AUDIO_EXTENSIONS and suffix not in COVER_TYPES:
            continue
        try:
            st = path.stat()
        except OSError:
            continue
        if stat.S_ISREG(st.st_mode):
            yield path, st


def signature(folder):
    """{path: (mtime_ns, size)} of the folder's audio files and covers, from
    stat alone: if it hasn't changed, neither has anything a scan would find."""
    return {str(p): (st.st_mtime_ns, st.st_size) for p, st in _walk(Path(folder).expanduser())}


def _read_track(path, folder_art):
    """(track dict, whether its art came from the file itself) for one file,
    or (None, False) if it can't be read."""
    try:
        audio = mutagen.File(path)
    except Exception:
        audio = None
    if audio is None:
        return None, False
    tags = audio.tags or {}
    try:
        embedded = _extract_art(path, audio)
        return {
            "path": str(path),
            "title": _first_tag(tags, "TIT2", "\xa9nam", "title") or path.stem,
            "artist": _first_tag(tags, "TPE1", "\xa9ART", "artist") or "Unknown artist",
            "duration": int(audio.info.length),
            "art": embedded or folder_art(path.parent),
            "album": _first_tag(tags, "TALB", "\xa9alb", "album") or path.parent.name,
            "albumArtist": _first_tag(tags, "TPE2", "aART", "albumartist", "album artist"),
            "disc": _number(tags, "TPOS", "disk", "discnumber"),
            "track": _number(tags, "TRCK", "trkn", "tracknumber"),
        }, bool(embedded)
    except Exception as e:  # one odd file mustn't stop the dashboard starting
        print(f"Music: skipped {path.name} ({e!r})")
        return None, False


def _reuse(entry, stamp, path, folder_art):
    """The cached entry for a file that hasn't changed (a copy: the old
    cache stays as it was to compare against), or None to read it again. A
    file that couldn't be read is always read again: the fault may have been
    the moment's (a full disk, a read error), not the file's."""
    try:
        if entry["stamp"] != stamp or type(entry["embedded"]) is not bool:
            return None
        track = entry["track"]
        if not _valid_track(track):
            return None
        track = dict(track)
        if entry["embedded"]:               # its picture is in the art cache: still there?
            if not os.path.isfile(QUrl(track["art"]).toLocalFile()):
                return None
        else:                               # a cover.jpg beside it may have come or gone
            track["art"] = folder_art(path.parent)
        return {**entry, "track": track}
    except (KeyError, TypeError, AttributeError):
        return None


def scan(folder):
    """Return a sorted list of track dicts for every audio file under folder.
    A file whose time and size are as last time keeps the tags read then (so
    a scan reads only what changed), and the result is saved."""
    root = Path(folder).expanduser()
    old = _load_cache(root)
    files, tracks = {}, []
    # Once per folder: listing the folder for every song made a big one O(n²).
    folder_art = functools.cache(_folder_art)
    for path, st in _walk(root):
        if path.suffix.lower() not in AUDIO_EXTENSIONS:
            continue
        key, stamp = str(path), [st.st_mtime_ns, st.st_size]
        entry = _reuse(old.get(key), stamp, path, folder_art)
        if entry is None:
            track, embedded = _read_track(path, folder_art)
            entry = {"stamp": stamp, "embedded": embedded, "track": track}
        files[key] = entry
        if entry["track"] is not None:
            tracks.append(entry["track"])
    # An empty result over a cache that had songs (a card that's gone) isn't saved over it.
    if files != old and (files or not old):
        _save_cache(root, files)
    return tracks


class LibraryScanner(QObject):
    """Reads the music folder on a worker thread: once as soon as it's
    started, then whenever the files' times or sizes differ from the last
    pass (looked at every `interval` seconds).
    `found(tracks)` is delivered on the thread this object lives in (the
    UI's). The worker touches no Qt objects but the signal."""
    found = pyqtSignal(list)

    def __init__(self, folder, interval=60, parent=None):
        super().__init__(parent)
        self._folder = folder
        self._interval = interval
        self._stop = threading.Event()
        self._thread = None

    def start(self):
        if self._thread is None:
            self._thread = threading.Thread(target=self._run, name="library-scan", daemon=True)
            self._thread.start()

    def stop(self):
        """End the worker. A pass in the middle of a big folder is left to
        finish on its own (it's a daemon thread) and delivers nothing."""
        self._stop.set()
        if self._thread is not None:
            self._thread.join(2)

    def _run(self):
        last = None
        while not self._stop.is_set():
            try:
                now = signature(self._folder)
                if now != last:
                    tracks = scan(self._folder)
                    last = now
                    if not self._stop.is_set():
                        self.found.emit(tracks)
            except Exception as e:           # never fatal: try again next time
                print(f"Music: scan failed ({e!r})")
            self._stop.wait(self._interval)


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


def resume_point(albums, tracks, state):
    """Where to pick up from a saved state: (album index or -1 for all
    songs, song index in that queue, seconds in). The album is found by
    name and the song by its file, so songs added since don't shift them;
    a song that's gone falls back to its place in the queue, then to the
    first song."""
    if not tracks:
        return -1, 0, 0
    state = state if isinstance(state, dict) else {}
    album, same_queue = -1, True
    want = state.get("album")
    if isinstance(want, list) and len(want) == 2:
        key = [str(v).casefold() for v in want]
        album = next((i for i, a in enumerate(albums)
                      if [a["artist"].casefold(), a["title"].casefold()] == key), -1)
        same_queue = album >= 0
    queue = albums[album]["tracks"] if album >= 0 else range(len(tracks))
    paths = [tracks[i]["path"] for i in queue]
    index = state.get("index")
    if state.get("path") in paths:
        index = paths.index(state["path"])
    elif not (same_queue and isinstance(index, int) and 0 <= index < len(paths)):
        index = 0
    position = state.get("position")
    if paths[index] != state.get("path") or not isinstance(position, (int, float)):
        position = 0                         # not the same song: from its start
    return album, index, max(0, int(position))


def play_order(count, first, shuffle):
    """Queue positions in the order they play: folder order, or (shuffle)
    every song once, `first` leading."""
    order = list(range(count))
    if shuffle and count:
        first = first if 0 <= first < count else 0
        order.remove(first)
        random.shuffle(order)
        order.insert(0, first)
    return order


def step(order, index, delta, wrap):
    """The position `delta` songs from `index` in `order`; at either end it
    goes round if `wrap`, else None. A position that isn't in the order (the
    queue changed under it) gives the first."""
    if not order:
        return None
    if index not in order:
        return order[0]
    at = order.index(index) + delta
    if 0 <= at < len(order):
        return order[at]
    return order[at % len(order)] if wrap else None


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
    modesChanged = pyqtSignal()         # shuffle or repeat
    libraryChanged = pyqtSignal()       # the albums (a scan found other songs)
    scanningChanged = pyqtSignal()

    def __init__(self, tracks, parent=None, scanning=False):
        super().__init__(parent)
        self._scanning = scanning       # the first scan hasn't reported yet
        self._all = tracks
        self._albums = group_albums(tracks)
        self._queue = list(tracks)      # what's playing through: an album, or all songs
        self._album = -1                # index into _albums, or -1 for all songs
        self._index = 0
        self._start_at = 0              # seconds into the first song (from restore())
        self._start_playing = False
        self._saved = None              # what restore() was given, kept while there are no songs
        self._volume = 40
        self._shuffle = False
        self._repeat = "all"
        self._order = list(range(len(self._queue)))   # queue positions, in play order

        self._engine = GaplessEngine(lambda i: self._queue[i]["path"], lambda: len(self._queue),
                                     preferred_output(), self, after=self._after)
        self._engine.trackStarted.connect(self._heard)
        self._engine.ended.connect(self._ended)
        # The equalizer may start after the dashboard: move to it when it does.
        self._devices = QMediaDevices(self)
        self._devices.audioOutputsChanged.connect(self._pick_output)
        self._tick = QTimer(self, interval=500,
                            timeout=lambda: self._engine.playing and self.positionChanged.emit())
        self._tick.start()
        self._apply_volume()

    def restore(self, state, play=False):
        """Pick up where the last run left off (what state() saved): its
        album, song and place in the song, playing only if `play`. Call it
        before start()."""
        self._saved = dict(state) if isinstance(state, dict) else None
        self._start_playing = play
        if not self._queue:
            return                      # no songs: state() hands it back as it was
        album, self._index, self._start_at = resume_point(self._albums, self._all, state)
        if album >= 0:
            self._queue = [self._all[i] for i in self._albums[album]["tracks"]]
        self._album = album
        self._reorder()

    def set_tracks(self, tracks):
        """A scan found these songs (call on the UI thread). Swaps them in
        without interrupting the song playing; with nothing in the player yet
        it starts as a normal boot would, from the state restore() was given."""
        if self._scanning:
            self._scanning = False
            self.scanningChanged.emit()
        if tracks == self._all or (self._all and not tracks):
            return                      # same songs; or the card went, which isn't "all deleted"
        if not self._queue:
            self._all = tracks
            self._albums = group_albums(tracks)
            self._queue, self._album, self._index, self._start_at = list(tracks), -1, 0, 0
            self.restore(self._saved, self._start_playing)
            self.libraryChanged.emit()
            self.queueChanged.emit()
            self.start()
            return
        old_queue, old_index = self._queue, self._index
        was = old_queue[old_index]
        playing = was["path"]
        album = self._albums[self._album] if self._album >= 0 else None
        self._all, self._albums = tracks, group_albums(tracks)
        by_path = {t["path"]: i for i, t in enumerate(tracks)}
        if album is not None:
            key = (album["artist"].casefold(), album["title"].casefold())
            self._album = next((i for i, a in enumerate(self._albums)
                                if (a["artist"].casefold(), a["title"].casefold()) == key), -1)
        if playing not in by_path:
            self.libraryChanged.emit()  # the song playing is gone: let it finish, queue as it was
            self.queueChanged.emit()
            return
        if self._album >= 0:
            queue = [tracks[i] for i in self._albums[self._album]["tracks"]]
        elif album is None:
            queue = list(tracks)
        else:                           # its album was retagged away: keep what's left of the queue
            queue = [tracks[by_path[t["path"]]] for t in old_queue if t["path"] in by_path]
        if playing not in [t["path"] for t in queue]:
            queue = [tracks[by_path[t["path"]]] for t in old_queue if t["path"] in by_path]
            self._album = -1
        index = next(i for i, t in enumerate(queue) if t["path"] == playing)

        def swap():
            self._queue, self._index = queue, index
            self._reorder()

        if [t["path"] for t in queue] != [t["path"] for t in old_queue]:
            position = {t["path"]: i for i, t in enumerate(queue)}
            self._engine.rebase(lambda i: position.get(old_queue[i]["path"], index)
                                if 0 <= i < len(old_queue) else index, apply=swap)
        else:
            self._queue = queue
        self.libraryChanged.emit()
        self.queueChanged.emit()
        if index != old_index or queue[index] != was:    # moved, or retagged / a new cover
            self.trackChanged.emit()

    def cancel_autoplay(self):
        """Another source has taken over: songs found later must not start
        playing over it (they wait, paused)."""
        self._start_playing = False

    def set_modes(self, shuffle, repeat):
        """Shuffle and repeat from the last run (before restore())."""
        self._shuffle = bool(shuffle)
        self._repeat = repeat if repeat in REPEATS else "all"
        self._reorder()

    def _reorder(self):
        """The play order for the queue as it is, the current song first."""
        self._order = play_order(len(self._queue), self._index if self._queue else 0, self._shuffle)

    def _after(self, index, failed=False):
        """The song that follows `index` by itself (also called on the audio
        thread, so it only reads): the same one on repeat one (unless it
        won't play: then the next, round), the next in order, and at the end
        the first again on repeat all, else None. `failed`: song `index` won't
        play, so never itself; the engine stops (None) once the song after it
        is a bad one too."""
        if self._repeat == "one" and 0 <= index < len(self._queue):
            return step(self._order, index, 1, True) if failed else index
        return step(self._order, index, 1, self._repeat == "all")

    def state(self):
        """Where local music is up to, to save between runs. With no songs,
        what restore() was given, so a run where the music is missing
        doesn't overwrite the resume point."""
        if not self._queue:
            return dict(NO_STATE if self._saved is None else self._saved)
        album = self._albums[self._album] if self._album >= 0 else None
        return {"album": [album["artist"], album["title"]] if album else None,
                "path": self._queue[self._index]["path"], "index": self._index,
                "position": self._engine.position()}

    def start(self):
        # Paused unless restore() says it was playing: a fresh boot never
        # starts the first song of everything by itself.
        if not self._queue:
            return                      # nothing to play: leave the audio stream alone
        self._engine.play_from(self._index, play=self._start_playing, at=self._start_at)
        self.trackChanged.emit()
        self.positionChanged.emit()
        self.playingChanged.emit()

    def _pick_output(self):
        self._engine.set_device(preferred_output())

    def _ended(self):
        """Repeat is off and the last song is over: back to the first, paused."""
        if not self._queue:
            return
        # A shuffle starts again from any song, not the one that just finished.
        first = random.randrange(len(self._queue)) if self._shuffle else 0
        self._order = play_order(len(self._queue), first, self._shuffle)
        self._index = first
        self._engine.play_from(self._index, play=False)
        self.trackChanged.emit()
        self.positionChanged.emit()
        self.playingChanged.emit()

    def _go(self, index, reorder=False):
        """Play song `index` of the queue now. `reorder`: a song picked on
        purpose, so a shuffle starts over from it."""
        if not self._queue:
            return
        self._index = index % len(self._queue)
        if reorder:
            self._reorder()
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
    def _song(self):
        return self._queue[self._index] if self._queue else NO_SONG

    @pyqtProperty(str, notify=trackChanged)
    def title(self):
        return self._song()["title"]

    @pyqtProperty(str, notify=trackChanged)
    def artist(self):
        return self._song()["artist"]

    @pyqtProperty(str, notify=trackChanged)
    def art(self):
        return self._song()["art"]

    @pyqtProperty(int, notify=trackChanged)
    def duration(self):
        return self._song()["duration"]

    @pyqtProperty(int, notify=trackChanged)
    def index(self):
        return self._index if self._queue else -1

    @pyqtProperty("QVariantList", notify=queueChanged)
    def queue(self):
        return [{"title": t["title"], "artist": t["artist"]} for t in self._queue]

    @pyqtProperty("QVariantList", notify=libraryChanged)
    def albums(self):
        return [{"title": a["title"], "artist": a["artist"], "art": a["art"],
                 "count": len(a["tracks"]),
                 "duration": sum(self._all[i]["duration"] for i in a["tracks"])}
                for a in self._albums]

    @pyqtProperty(bool, notify=scanningChanged)
    def scanning(self):
        """The first read of the music folder is still going."""
        return self._scanning

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

    @pyqtProperty(bool, constant=True)
    def hasModes(self):
        """Shuffle and repeat work on this source."""
        return True

    @pyqtProperty(bool, constant=True)
    def canSeek(self):
        return True

    @pyqtSlot(int)
    def seek(self, seconds):
        """Jump within the song. A long file re-decodes from its start, so a
        deep seek is silent for a moment."""
        if not self._queue:
            return
        dur = self.duration
        # Not quite the end: the song would end before it was heard.
        seconds = max(0, min(int(seconds), dur - 1 if dur > 1 else 0))
        self._engine.seek(seconds)
        self.positionChanged.emit()

    @pyqtProperty(bool, notify=modesChanged)
    def shuffle(self):
        return self._shuffle

    @pyqtProperty(str, notify=modesChanged)
    def repeat(self):
        """'all' (round to the first, as it always has), 'one' or 'off' (stop after the last)."""
        return self._repeat

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
        if not self._queue:
            return                      # nothing to play: stay paused
        self._engine.set_playing(not self._engine.playing)
        self.playingChanged.emit()

    @pyqtSlot()
    def next(self):
        # The key always moves on (round at the end), even on repeat one or off.
        self._go(step(self._order, self._index, 1, True) or 0)

    @pyqtSlot()
    def previous(self):
        # Like a head unit: back to the start of the song, unless just begun.
        if self._engine.position() > 3:
            self._go(self._index)
        else:
            self._go(step(self._order, self._index, -1, True) or 0)

    @pyqtSlot(int)
    def playIndex(self, index):
        self._go(index, reorder=True)

    @pyqtSlot()
    def toggleShuffle(self):
        self._shuffle = not self._shuffle
        self._reorder()                 # from the song playing
        self._engine.refresh_next()
        self.modesChanged.emit()

    @pyqtSlot()
    def cycleRepeat(self):
        self._repeat = REPEATS[(REPEATS.index(self._repeat) + 1) % len(REPEATS)]
        self._engine.refresh_next()
        self.modesChanged.emit()

    @pyqtSlot(int, int)
    def playAlbum(self, album, start=0):
        """Play an album from one of its songs; it becomes the queue. A negative
        `start` is the album's own Play key: song 1, or any song when shuffling."""
        if not 0 <= album < len(self._albums):
            return
        self._queue = [self._all[i] for i in self._albums[album]["tracks"]]
        self._album = album
        self._reorder()
        self.queueChanged.emit()
        if start < 0:
            start = random.randrange(len(self._queue)) if self._shuffle else 0
        self.playIndex(start)

    @pyqtSlot()
    def playAll(self):
        """Back to every song, in folder order, from the first."""
        if not self._all:
            return
        self._queue = list(self._all)
        self._album = -1
        self._reorder()
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
