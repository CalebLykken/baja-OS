"""Baja OS backends."""


def safe_emit(obj, signal, *args):
    """Emit obj's signal (by name) from a worker thread. While the app shuts
    down Qt may already have deleted obj, and then even looking the signal
    up fails; there's nobody to tell by then, so skip it."""
    try:
        getattr(obj, signal).emit(*args)
    except RuntimeError:
        pass
