"""Where cover art is kept: ~/.cache/baja-os/art (under $XDG_CACHE_HOME if set).

It lives in the user's cache rather than /tmp (a RAM-backed tmpfs on the Pi,
emptied at every boot), so Spotify's covers are still there after a reboot
with no hotspot yet.

- File names are hashes: of the image bytes for embedded art, so every track
  of an album shares one file; of the URL for downloads. Never raw titles or
  paths.
- Files are written under a temporary name in the same folder and moved into
  place with os.replace, so a crash or a second thread never leaves (or
  reads) a half-written image.
- The folder is kept under MAX_BYTES: after a write, the least recently used
  files go first. A hit refreshes the file's time, so what's on screen or was
  shown lately stays. 100 MB is a few hundred covers (a 600 px card is
  ~0.5 MB, a Spotify cover ~50 KB), far more than a drive needs, and small
  next to the SD card.
"""

import contextlib
import hashlib
import os
import stat
import tempfile
import threading
import time
from pathlib import Path

MAX_BYTES = 100 * 1024 * 1024
STALE_TMP_S = 3600          # a temp file this old was left by a crash
_TMP = ".tmp-"
_prune_lock = threading.Lock()
_total = None               # running estimate of the folder's bytes; None until a walk
_made = None                # the art folder cache_dir() last created (as a string)


def cache_root():
    """~/.cache/baja-os (not created): the library's tag cache lives here too."""
    return Path(os.environ.get("XDG_CACHE_HOME") or "~/.cache").expanduser() / "baja-os"


def cache_dir():
    global _made
    d = cache_root() / "art"
    if _made != str(d):     # mkdir only the first time per path, not on every lookup
        d.mkdir(parents=True, exist_ok=True)
        _made = str(d)
    return d


def pinned_dir():
    """Where the library's embedded covers live: not subject to the LRU cap."""
    d = cache_root() / "library-art"
    d.mkdir(parents=True, exist_ok=True)
    return d


def digest(data):
    """A file-name-safe hash of bytes or a string."""
    if isinstance(data, str):
        data = data.encode()
    return hashlib.sha256(data).hexdigest()[:32]


def touch(path):
    """Mark a cached file as just used."""
    with contextlib.suppress(OSError):
        os.utime(path)


def lookup(name):
    """(path, True) if `name` is cached (and counts as used now), else (path, False)."""
    path = cache_dir() / name
    hit = _usable(path)
    if hit:
        touch(path)
    return path, hit


def _usable(path):
    """True for a non-empty regular file. A zero-byte one (a power cut after
    the rename, before the data reached the disk) is deleted and counts as a
    miss, so it's written again instead of being a hit for ever. One stat."""
    try:
        st = os.stat(path)
    except OSError:
        return False
    if not stat.S_ISREG(st.st_mode):
        return False
    if st.st_size > 0:
        return True
    with contextlib.suppress(OSError):
        os.unlink(path)
    return False


@contextlib.contextmanager
def writing(path, lru=True):
    """Yield a temporary path next to `path`; on a clean exit it replaces
    `path`, otherwise it's removed. The suffix is kept so image writers can
    tell the format from it. With lru=False (pinned_dir() files) the write
    isn't counted against the LRU folder's budget and doesn't prune it."""
    try:
        fd, tmp = tempfile.mkstemp(dir=path.parent, prefix=_TMP, suffix=path.suffix)
    except FileNotFoundError:   # the folder was deleted since cache_dir() made it
        path.parent.mkdir(parents=True, exist_ok=True)
        fd, tmp = tempfile.mkstemp(dir=path.parent, prefix=_TMP, suffix=path.suffix)
    os.close(fd)
    try:
        yield Path(tmp)
        # Flush the data before the rename: on ext4 a power cut soon after
        # os.replace can otherwise leave the final name as a zero-length file.
        with contextlib.suppress(OSError):
            fd = os.open(tmp, os.O_RDONLY)
            try:
                os.fsync(fd)
            finally:
                os.close(fd)
        os.replace(tmp, path)
    except BaseException:
        with contextlib.suppress(OSError):
            os.unlink(tmp)
        raise
    if lru:
        _after_write(path)


def _after_write(path):
    """Count the new file against the folder's size and only walk the folder
    (prune) on the first write of a run or once the estimate passes the cap.
    A name that was already there is counted twice: that only means an
    earlier real prune, which then records the true total."""
    global _total
    with _prune_lock:
        if _total is not None:
            try:
                _total += path.stat().st_size
            except OSError:
                pass
        if _total is None or _total > MAX_BYTES:
            _prune_locked(path, MAX_BYTES)


def drop_stale_temp(folder):
    """Delete temp files a crash left in `folder` (the art cache's own go in prune)."""
    for f in folder.glob(_TMP + "*"):
        with contextlib.suppress(OSError):
            if time.time() - f.stat().st_mtime > STALE_TMP_S:
                f.unlink()


def store(name, data):
    """Cache bytes under `name` unless it's there already; returns the path."""
    path, hit = lookup(name)
    if not hit:
        with writing(path) as tmp:
            tmp.write_bytes(data)
    return path


def store_pinned(name, data):
    """Like store(), but in pinned_dir(): only prune_pinned() removes it."""
    path = pinned_dir() / name
    if not _usable(path):
        with writing(path, lru=False) as tmp:
            tmp.write_bytes(data)
    return path


def prune_pinned(used):
    """Delete the files in pinned_dir() that aren't in `used` (paths), and
    temp files left by a crash."""
    folder = pinned_dir()
    drop_stale_temp(folder)
    keep = {str(p) for p in used}
    for f in folder.iterdir():
        if not f.name.startswith(_TMP) and str(f) not in keep:
            with contextlib.suppress(OSError):
                f.unlink()


def prune(keep=None, limit=None):
    """Delete least recently used files until the folder fits the cap
    (never `keep`), and temp files left by a crash."""
    with _prune_lock:
        _prune_locked(keep, MAX_BYTES if limit is None else limit)


def _prune_locked(keep, limit):
    """The folder walk behind prune(); the caller holds _prune_lock."""
    global _total
    files = []
    now = time.time()
    for f in cache_dir().iterdir():
        try:
            st = f.stat()
        except OSError:
            continue
        if f.name.startswith(_TMP):
            if now - st.st_mtime > STALE_TMP_S:
                with contextlib.suppress(OSError):
                    f.unlink()
            continue
        files.append((st.st_mtime, f, st.st_size))
    total = sum(size for _, _, size in files)
    for _, f, size in sorted(files, key=lambda t: t[0]):
        if total <= limit:
            break
        if keep is not None and f == keep:
            continue
        with contextlib.suppress(OSError):
            f.unlink()
            total -= size
    _total = total
