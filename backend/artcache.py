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
import tempfile
import threading
import time
from pathlib import Path

MAX_BYTES = 100 * 1024 * 1024
STALE_TMP_S = 3600          # a temp file this old was left by a crash
_TMP = ".tmp-"
_prune_lock = threading.Lock()


def cache_root():
    """~/.cache/baja-os (not created): the library's tag cache lives here too."""
    return Path(os.environ.get("XDG_CACHE_HOME") or "~/.cache").expanduser() / "baja-os"


def cache_dir():
    d = cache_root() / "art"
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
    hit = path.is_file()
    if hit:
        touch(path)
    return path, hit


@contextlib.contextmanager
def writing(path):
    """Yield a temporary path next to `path`; on a clean exit it replaces
    `path`, otherwise it's removed. The suffix is kept so image writers can
    tell the format from it."""
    fd, tmp = tempfile.mkstemp(dir=path.parent, prefix=_TMP, suffix=path.suffix)
    os.close(fd)
    try:
        yield Path(tmp)
        os.replace(tmp, path)
    except BaseException:
        with contextlib.suppress(OSError):
            os.unlink(tmp)
        raise
    prune(keep=path)


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


def prune(keep=None, limit=None):
    """Delete least recently used files until the folder fits the cap
    (never `keep`), and temp files left by a crash."""
    limit = MAX_BYTES if limit is None else limit
    with _prune_lock:
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
