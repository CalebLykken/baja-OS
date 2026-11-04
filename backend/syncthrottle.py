"""Decides when a settings file sync may run (no Qt, so it tests anywhere).

The first change after a quiet spell syncs at once. Changes that follow
within the window are folded into one trailing sync.
"""

import time


class SyncThrottle:
    def __init__(self, window_s=0.25, now=time.monotonic):
        self._window = window_s
        self._now = now
        self._last = None  # when the last sync ran
        self._pending = False

    @property
    def pending(self):
        return self._pending

    def changed(self):
        """'now' to sync immediately, 'later' to sync at due_in() seconds."""
        if self._last is None or self._now() - self._last >= self._window:
            return "now"
        self._pending = True
        return "later"

    def synced(self):
        """Record that a sync just ran."""
        self._last = self._now()
        self._pending = False

    def due_in(self):
        """Seconds until the trailing sync may run, never negative."""
        if self._last is None:
            return 0.0
        return max(0.0, self._last + self._window - self._now())
