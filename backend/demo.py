"""Whether this run may make things up: the simulated drive, the demo
playlist, the Seattle demo loop.

On the Mac everything is simulated so the UI can be worked on. In the truck
the dashboard must only show what's real. Each backend decides for itself
when it's allowed to fall back to its demo (see their docstrings); --demo
and --no-demo on the command line force the choice for all of them.
"""

from pathlib import Path

MODEL = Path("/proc/device-tree/model")


def on_pi():
    """True on a Raspberry Pi (the truck or a bench Pi)."""
    try:
        return "Raspberry Pi" in MODEL.read_text(errors="ignore")
    except OSError:
        return False


def allowed(flag, default):
    """flag is True for --demo, False for --no-demo, None for neither;
    default is what the backend picks when it isn't forced."""
    return default if flag is None else flag
