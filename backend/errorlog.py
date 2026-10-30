"""The log for uncaught errors (main.log_exception), rate-limited.

An error in something that runs constantly (the 5 Hz vehicle update, a
property QML re-reads on every change) would otherwise write several
tracebacks a second to the journal on the SD card. Errors are told apart by
type and place (the innermost frame). The first few of each are logged in
full; after that they're only counted, and one line a minute says how many
more there were. Every error still counts toward `count()`, which Settings
shows. Logging never raises: a broken stderr must not be a second crash.
"""

import os
import sys
import threading
import time
import traceback

FULL_EACH = 3          # tracebacks logged in full per distinct error
SUMMARY_EVERY_S = 60
MAX_KINDS = 200        # distinct errors remembered; the rest share one entry


class ErrorLog:
    def __init__(self, out=None, clock=time.monotonic, full=FULL_EACH,
                 every=SUMMARY_EVERY_S, timer=threading.Timer):
        self._out = out                 # None: whatever sys.stderr is at the time
        self._clock = clock
        self._full = full
        self._every = every
        self._timer_class = timer
        self._lock = threading.Lock()
        self._count = 0
        self._kinds = {}                # key -> [seen, suppressed since the last summary]
        self._timer = None

    def count(self):
        """Every uncaught error since start, logged or not."""
        return self._count

    @staticmethod
    def key(exc_type, tb):
        """(error type, file:line in function) of the innermost frame."""
        where = "?"
        try:
            while tb is not None and tb.tb_next is not None:
                tb = tb.tb_next
            if tb is not None:
                code = tb.tb_frame.f_code
                where = f"{os.path.basename(code.co_filename)}:{tb.tb_lineno} in {code.co_name}"
        except Exception:
            pass
        return getattr(exc_type, "__name__", str(exc_type)), where

    def report(self, exc_type, exc, tb, label=None):
        """Count an error; log it in full if it's one of the first few of its
        kind, else leave it for the summary. Never raises."""
        try:
            key = self.key(exc_type, tb)
            with self._lock:
                self._count += 1
                if key not in self._kinds and len(self._kinds) >= MAX_KINDS:
                    key = ("other errors", "")
                entry = self._kinds.setdefault(key, [0, 0])
                entry[0] += 1
                full = entry[0] <= self._full
                if not full:
                    entry[1] += 1
                    self._arm()
                if full:
                    out = self._out or sys.stderr
                    print(label or f"Uncaught error #{self._count}:", file=out)
                    traceback.print_exception(exc_type, exc, tb, file=out)
                    if entry[0] == self._full:
                        print(f"(more of this error are counted, not logged: "
                              f"a summary follows every {self._every}s)", file=out)
                    out.flush()
        except Exception:
            pass

    def _arm(self):
        """Make sure a summary is written even if the errors then stop."""
        if self._timer is None:
            try:
                self._timer = self._timer_class(self._every, self.flush)
                self._timer.daemon = True
                self._timer.start()
            except Exception:
                self._timer = None

    def flush(self):
        """Write the summary line for each error with suppressed repeats."""
        try:
            with self._lock:
                self._timer = None
                out = self._out or sys.stderr
                for (kind, where), entry in self._kinds.items():
                    if entry[1]:
                        at = f" at {where}" if where else ""
                        print(f"Same error {entry[1]:,} more times in the last "
                              f"{self._every}s: {kind}{at}", file=out)
                        entry[1] = 0
                out.flush()
        except Exception:
            pass


log = ErrorLog()
