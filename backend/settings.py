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
- A write that fails (SD card full) stays queued; the writer retries it by
  itself with a growing pause, and flush(wait=True) reports False while any
  key is still unwritten.
- The way out flushes more than once (SIGTERM, aboutToQuit, close()). Those
  share one deadline, FLUSH_TIMEOUT_S from the first of them, so a store that
  keeps failing can't stack 3 s waits past systemd's 5 s stop timeout. The
  flush before a poweroff or reboot gets its own full wait.
"""

import threading
import time

from PyQt6.QtCore import QCoreApplication, QEvent, QObject, QSettings, QTimer, pyqtSlot

FLUSH_AFTER_MS = 1500       # quiet this long after a change, then write
MAX_WAIT_MS = 10000         # but never sit on a change longer than this
FLUSH_TIMEOUT_S = 3.0       # how long a waiting flush blocks, and the whole way out
                            # (systemd allows 5 s)
RETRY_FIRST_S = 2.0         # a failed write is tried again after this,
RETRY_MAX_S = 30.0          # doubling up to this
RETRY_WAITING_S = 0.25      # ...or this often while a flush is waiting on it
# The route is what the truck picks up again after a power cut mid-drive.
IMMEDIATE = frozenset({"route"})


def _open_conf():
    return QSettings("baja-os", "baja-os")


class _Writer:
    """Writes batches of changes to the file on a thread of its own. hand()
    and wait() are called from the UI thread; the store is only ever touched
    on the writer thread. A batch that fails to write stays in the outbox and
    the writer tries it again itself, with a growing pause, until it is on
    disk; wait() only says True once nothing is left unwritten."""

    def __init__(self, open_store):
        self._open_store = open_store
        self._cond = threading.Condition()
        self._outbox = {}       # handed over, not on disk yet (failed ones too)
        self._writing = False   # a batch is being written right now
        self._retry_at = 0.0    # time.monotonic() before which no retry is made
        self._backoff = RETRY_FIRST_S
        self._waiters = 0       # wait() callers: retry quickly for them
        self._closing = False
        self._thread = None

    def hand(self, changes):
        """Queue changes for writing."""
        with self._cond:
            self._outbox.update(changes)
            if self._thread is None or not self._thread.is_alive():
                self._closing = False
                self._thread = threading.Thread(target=self._run, name="settings-writer",
                                                daemon=True)
                self._thread.start()
            self._cond.notify_all()

    def wait(self, timeout):
        """True once everything handed over has been written. False if the
        timeout ran out first, or if a write is failing and keys are still
        unwritten."""
        with self._cond:
            self._waiters += 1
            self._retry_at = 0.0            # someone is waiting: try now
            self._cond.notify_all()
            try:
                return self._cond.wait_for(lambda: not self._outbox and not self._writing,
                                           timeout)
            finally:
                self._waiters -= 1

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
                while True:
                    if not self._outbox:
                        if self._closing:
                            return                  # closing, with nothing left
                        self._cond.wait()
                        continue
                    left = self._retry_at - time.monotonic()
                    if left <= 0 or self._closing:
                        break
                    self._cond.wait(left)           # a failed write, pausing
                batch, self._outbox = self._outbox, {}
                self._writing = True
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
                self._writing = False
                if failed:
                    for key, value in failed.items():
                        self._outbox.setdefault(key, value)     # a newer value wins
                    pause = RETRY_WAITING_S if self._waiters else self._backoff
                    self._backoff = min(self._backoff * 2, RETRY_MAX_S)
                    self._retry_at = time.monotonic() + pause
                    if self._closing:
                        return                      # shutting down: one try was all we get
                else:
                    self._backoff = RETRY_FIRST_S
                    self._retry_at = 0.0
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
        self._exit_deadline = None          # time.monotonic() the way out must end by

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
        disk (or timeout runs out); returns False if it ran out or if a write is
        failing, so something is still unwritten."""
        self._flush_timer.stop()
        self._first_pending = None
        if self._pending:
            pending, self._pending = self._pending, {}
            self._writer.hand(pending)
        if not wait:
            return True
        return self._writer.wait(timeout)       # also what failed earlier

    def _exit_left(self, cap=FLUSH_TIMEOUT_S):
        """What's left of the way out's one time budget; the first call starts it."""
        now = time.monotonic()
        if self._exit_deadline is None:
            self._exit_deadline = now + FLUSH_TIMEOUT_S
        return max(0.0, min(cap, self._exit_deadline - now))

    @pyqtSlot()
    def flush_and_wait(self):
        """For the way out: everything on disk before this returns. Every
        call on the way out (and close()) shares one FLUSH_TIMEOUT_S budget,
        so a store that keeps failing doesn't make each of them wait in full."""
        if not self.flush(wait=True, timeout=self._exit_left()):
            print("Settings: the last write didn't finish (not saved)", flush=True)

    @pyqtSlot()
    def flush_before_power(self):
        """Before a poweroff or reboot: everything on disk, with a full wait of
        its own (systemd's stop timeout hasn't started yet)."""
        if not self.flush(wait=True):
            print("Settings: the last write didn't finish (not saved)", flush=True)

    def close(self, timeout=FLUSH_TIMEOUT_S):
        """Write everything and stop the writer thread, within what's left of
        the way out's budget (and never longer than timeout)."""
        self.flush_and_wait()
        self._writer.close(self._exit_left(timeout))

    def get_int(self, key, default):
        try:
            return int(self.get(key, default))
        except (TypeError, ValueError):
            return default
