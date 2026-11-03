"""Settings that survive a restart (style, volume, units).

Stored with QSettings in ~/.config/baja-os/baja-os.conf. Values come back
as strings from that file, so callers convert what they read.

Qt rewrites the whole file, with an fsync, on every sync. On the Pi's SD card
that can take a good while, and the file holds big blobs (the Spotify
library) while the music position saves every 5 s and the knob and sliders
save in bursts. So the UI thread never touches the file after start-up:

- At start-up every saved value is read into memory once. get() answers from
  that copy, which set() keeps up to date, so a read never waits on the disk
  (or on a write going on at the same moment).
- Changes wait a moment (FLUSH_AFTER_MS after the last one, MAX_WAIT_MS at
  most after the first, so a key that never stops changing is still saved)
  and are then handed to a writer thread. It owns its own QSettings for the
  file (QSettings is reentrant: one object per thread, never shared) and does
  the setValue and the sync there. Batches handed over while it's busy are
  merged into one write.
- Keys in IMMEDIATE (a power cut a second later would hurt) are handed over
  at once.
- flush(wait=True) hands over what's waiting and blocks until it is on disk:
  the app calls it on the way out, on SIGTERM and before it powers the Pi off
  or reboots it.
"""

import threading
import time

from PyQt6.QtCore import QCoreApplication, QEvent, QObject, QSettings, QTimer, pyqtSlot

FLUSH_AFTER_MS = 1500       # quiet this long after a change, then write
MAX_WAIT_MS = 10000         # but never sit on a change longer than this
FLUSH_TIMEOUT_S = 3.0       # how long a waiting flush blocks (systemd allows 5 s)
# The route is what the truck picks up again after a power cut mid-drive.
IMMEDIATE = frozenset({"route"})


def _open_conf():
    return QSettings("baja-os", "baja-os")


class _Writer:
    """Writes batches of changes to the file on a thread of its own. hand()
    and wait() are called from the UI thread; the store is only ever touched
    on the writer thread."""

    def __init__(self, open_store):
        self._open_store = open_store
        self._cond = threading.Condition()
        self._outbox = {}       # handed over, not written yet
        self._retry = {}        # a write that failed: tried again with the next one
        self._handed = 0        # batches handed over so far
        self._done = 0          # of those, how many have been tried
        self._closing = False
        self._thread = None

    def hand(self, changes):
        """Queue changes for writing; returns a ticket for wait()."""
        with self._cond:
            if self._retry:
                changes = {**self._retry, **changes}
                self._retry = {}
            self._outbox.update(changes)
            self._handed += 1
            ticket = self._handed
            if self._thread is None or not self._thread.is_alive():
                self._closing = False
                self._thread = threading.Thread(target=self._run, name="settings-writer",
                                                daemon=True)
                self._thread.start()
            self._cond.notify_all()
        return ticket

    def last_ticket(self):
        with self._cond:
            return self._handed

    def wait(self, ticket, timeout):
        """True once everything handed over up to ticket has been written."""
        with self._cond:
            return self._cond.wait_for(lambda: self._done >= ticket, timeout)

    def close(self, timeout):
        with self._cond:
            self._closing = True
            self._cond.notify_all()
            thread = self._thread
        if thread is not None:
            thread.join(timeout)

    def _run(self):
        store = None
        while True:
            with self._cond:
                self._cond.wait_for(lambda: self._outbox or self._closing)
                if not self._outbox:
                    return                  # closing, with nothing left
                batch, self._outbox = self._outbox, {}
                upto = self._handed
            try:
                if store is None:
                    store = self._open_store()
                for key, value in batch.items():
                    store.setValue(key, value)
                store.sync()
                if isinstance(store, QObject):
                    # setValue posted a write request to this thread, which
                    # has no event loop to run it: sync() already did it.
                    QCoreApplication.removePostedEvents(store, QEvent.Type.UpdateRequest)
                status = store.status() if hasattr(store, "status") else QSettings.Status.NoError
                if status != QSettings.Status.NoError:
                    raise OSError(f"QSettings status {status}")
                failed = None
            except Exception as e:
                print(f"Settings: couldn't write {sorted(batch)}: {type(e).__name__}: {e}",
                      flush=True)
                failed = batch
                store = None        # its error status sticks: start afresh next time
            with self._cond:
                if failed:
                    for key, value in failed.items():
                        if key not in self._outbox:     # a newer value wins
                            self._retry.setdefault(key, value)
                self._done = max(self._done, upto)
                self._cond.notify_all()


class Settings(QObject):
    def __init__(self, parent=None, open_store=_open_conf,
                 flush_after_ms=FLUSH_AFTER_MS, max_wait_ms=MAX_WAIT_MS):
        super().__init__(parent)
        # Read everything once; this QSettings is dropped straight after and
        # never writes.
        store = open_store()
        self._values = {key: store.value(key) for key in store.allKeys()}
        del store
        self._writer = _Writer(open_store)
        self._pending = {}                  # changed, not handed to the writer yet
        self._first_pending = None          # time.monotonic() of the oldest of them
        self._flush_after_ms = flush_after_ms
        self._max_wait_ms = max_wait_ms
        self._flush_timer = QTimer(self, singleShot=True, timeout=self._timed_flush)

    @pyqtSlot(str, "QVariant", result="QVariant")
    def get(self, key, default=None):
        return self._values.get(key, default)

    @pyqtSlot(str, "QVariant")
    def set(self, key, value):
        if self._values.get(key) == value:
            return
        self._values[key] = value
        self._pending[key] = value
        if key in IMMEDIATE:
            self.flush()
            return
        now = time.monotonic()
        if self._first_pending is None:
            self._first_pending = now
        left_ms = self._max_wait_ms - (now - self._first_pending) * 1000
        # Restarts on every change, one write after a burst, but the oldest
        # change never waits past the max.
        self._flush_timer.start(int(max(0, min(self._flush_after_ms, left_ms))))

    @pyqtSlot()
    def _timed_flush(self):
        self.flush()

    def flush(self, wait=False, timeout=FLUSH_TIMEOUT_S):
        """Hand what's waiting to the writer. With wait, block until it's on
        disk (or timeout runs out); returns False if it ran out."""
        self._flush_timer.stop()
        self._first_pending = None
        if self._pending:
            pending, self._pending = self._pending, {}
            ticket = self._writer.hand(pending)
        else:
            ticket = self._writer.last_ticket()   # anything still being written
        if not wait:
            return True
        return self._writer.wait(ticket, timeout)

    @pyqtSlot()
    def flush_and_wait(self):
        """For the way out: everything on disk before this returns."""
        if not self.flush(wait=True):
            print("Settings: the last write didn't finish in time", flush=True)

    def close(self, timeout=FLUSH_TIMEOUT_S):
        """Write everything and stop the writer thread."""
        self.flush_and_wait()
        self._writer.close(timeout)

    def get_int(self, key, default):
        try:
            return int(self.get(key, default))
        except (TypeError, ValueError):
            return default
