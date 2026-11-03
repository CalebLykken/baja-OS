"""How long the dashboard takes to start, for the journal: a clock that notes
the time at each startup phase, and one summary line to print once the first
frame is on screen. Pure Python (no PyQt), so it can be tested off the Pi."""

import time


def since_boot(path="/proc/uptime"):
    """Seconds since the system booted, from /proc/uptime; None where that
    file can't be read (a Mac)."""
    try:
        with open(path) as f:
            return float(f.read().split()[0])
    except (OSError, ValueError, IndexError):
        return None


class StartupClock:
    """Marks named phases with the milliseconds since the clock was made.
    A name marked again keeps its first time."""

    def __init__(self, now=time.monotonic, uptime=since_boot):
        self._now = now
        self._uptime = uptime
        self._start = now()
        self._marks = []
        self._names = set()

    def mark(self, name):
        if name in self._names:
            return
        self._names.add(name)
        self._marks.append((name, round((self._now() - self._start) * 1000)))

    def summary(self):
        """One line, e.g. 'Startup: imports 412 ms, qml 1840 ms (system up 14.2 s)'."""
        line = "Startup: " + ", ".join(f"{name} {ms} ms" for name, ms in self._marks)
        up = self._uptime()
        if up is not None:
            line += f" (system up {up:.1f} s)"
        return line
