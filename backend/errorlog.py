"""The log for uncaught errors (main.log_exception), rate-limited.

An error in something that runs constantly (the 5 Hz vehicle update, a
property QML re-reads on every change) would otherwise write several
tracebacks a second to the journal on the SD card. Errors are told apart by
type, place and label. The place is the innermost frame plus, when that is
inside the standard library, the innermost frame of our own code, so two bugs
raised in the same library call stay apart. The first few of each are logged in
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
PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def _in_project(filename):
    try:
        path = os.path.abspath(filename)
        return os.path.commonpath([PROJECT_ROOT, path]) == PROJECT_ROOT
    except Exception:       # another drive, or odd names like <string>
        return False


def _describe(tb):
    code = tb.tb_frame.f_code
    return f"{os.path.basename(code.co_filename)}:{tb.tb_lineno} in {code.co_name}"


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
        """(error type, file:line in function) of the innermost frame. If that
        frame is outside the project (the standard library), the innermost
        project frame comes first: 'gps.py:393 in _run > decoder.py:361 in
        raw_decode'."""
        where = "?"
        try:
            project = None
            while tb is not None and tb.tb_next is not None:
                if _in_project(tb.tb_frame.f_code.co_filename):
                    project = tb
                tb = tb.tb_next
            if tb is not None:
                where = _describe(tb)
                if project is not None and not _in_project(tb.tb_frame.f_code.co_filename):
                    where = f"{_describe(project)} > {where}"
        except Exception:
            pass
        return getattr(exc_type, "__name__", str(exc_type)), where

    def report(self, exc_type, exc, tb, label=None):
        """Count an error; log it in full if it's one of the first few of its
        kind, else leave it for the summary. Never raises."""
        try:
            key = (*self.key(exc_type, tb), label)
            with self._lock:
                self._count += 1
                if key not in self._kinds and len(self._kinds) >= MAX_KINDS:
                    key = ("other errors", "", None)
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
                for (kind, where, label), entry in self._kinds.items():
                    if entry[1]:
                        at = f" at {where}" if where else ""
                        by = f" ({label.rstrip(':')})" if label else ""
                        print(f"Same error {entry[1]:,} more times in the last "
                              f"{self._every}s: {kind}{at}{by}", file=out)
                        entry[1] = 0
                out.flush()
        except Exception:
            pass


class QtMessages:
    """The same limiter for Qt's own messages (QML 'Cannot read property',
    'Binding loop detected', a Component warning), installed with
    qInstallMessageHandler. A bad binding on a 5 Hz property would otherwise
    write hundreds of journal lines a minute. Messages are told apart by mode
    and text; the first few of each go to stderr as given (so file:line stays),
    then they're only counted, with one summary line a minute. Fatal messages
    are always printed. Never raises."""

    def __init__(self, out=None, clock=time.monotonic, full=FULL_EACH,
                 every=SUMMARY_EVERY_S, timer=threading.Timer):
        self._out = out
        self._clock = clock
        self._full = full
        self._every = every
        self._timer_class = timer
        self._lock = threading.Lock()
        self._kinds = {}                # (mode, text) -> [seen, suppressed since the last summary]
        self._timer = None

    def handle(self, mode, context, message):
        try:
            fatal = getattr(mode, "name", str(mode)) == "QtFatalMsg"
            key = (str(mode), str(message))
            with self._lock:
                if key not in self._kinds and len(self._kinds) >= MAX_KINDS:
                    key = ("other", "")
                entry = self._kinds.setdefault(key, [0, 0])
                entry[0] += 1
                if fatal or entry[0] <= self._full:
                    out = self._out or sys.stderr
                    print(message, file=out)
                    if entry[0] == self._full and not fatal:
                        print(f"(more of this message are counted, not logged: "
                              f"a summary follows every {self._every}s)", file=out)
                    out.flush()
                else:
                    entry[1] += 1
                    self._arm()
        except Exception:
            pass

    def _arm(self):
        if self._timer is None:
            try:
                self._timer = self._timer_class(self._every, self.flush)
                self._timer.daemon = True
                self._timer.start()
            except Exception:
                self._timer = None

    def flush(self):
        """Write a summary line for each message with suppressed repeats."""
        try:
            with self._lock:
                self._timer = None
                out = self._out or sys.stderr
                for (mode, text), entry in self._kinds.items():
                    if entry[1]:
                        first = text.splitlines()[0][:160] if text else "other messages"
                        print(f"Same message {entry[1]:,} more times in the last "
                              f"{self._every}s: {first}", file=out)
                        entry[1] = 0
                out.flush()
        except Exception:
            pass


log = ErrorLog()
qt_messages = QtMessages()
