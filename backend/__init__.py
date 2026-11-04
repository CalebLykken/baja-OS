"""Baja OS backends."""

import traceback


class FailureLog:
    """Logs a failing check once while the same error repeats, and once when it works again."""

    def __init__(self, failed, recovered):
        self._failed, self._recovered, self._error = failed, recovered, ""

    def __call__(self, error=None):
        """Call with the error a check crashed with, or with nothing when it worked."""
        err = "" if error is None else f"{type(error).__name__}: {error}"
        if err and err != self._error:
            trace = "".join(traceback.format_exception(type(error), error, error.__traceback__)).rstrip()
            print(f"{self._failed}: {err}\n{trace}", flush=True)
        elif not err and self._error:
            print(self._recovered, flush=True)
        self._error = err

    @property
    def error(self):
        """The error the last check died of, while it keeps happening, or ''."""
        return self._error


def safe_emit(obj, signal, *args):
    """Emit obj's signal (by name) from a worker thread. While the app shuts
    down Qt may already have deleted obj, and then even looking the signal
    up fails; there's nobody to tell by then, so skip it."""
    try:
        getattr(obj, signal).emit(*args)
    except RuntimeError:
        pass
