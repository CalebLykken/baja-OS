"""The dash knob: an EC11 rotary encoder with a push switch, wired straight
to the Pi's pin header and read with libgpiod (on a Mac it does nothing).

Wiring, at the USB end of the header, clear of the sound board's pins:
  pins 32 (GPIO12) and 36 (GPIO16): the knob's two outer legs
  pin 34 (ground): its middle leg
  pin 37 (GPIO26) and pin 39 (ground): the push switch

The pins are only ever read, with the Pi's own pull-ups, so a loose or
misplaced wire can't harm anything. Turning reports clicks (`turned`, +1
or -1); a press reports `pressed` and its end `released`. `Gestures`
turns those into a single, double or long press. main.py decides what
they do.
"""

import itertools
import threading
import time
from datetime import timedelta

from PyQt6.QtCore import QObject, QTimer, pyqtSignal

from backend import errorlog, safe_emit

try:
    import gpiod
    from gpiod.line import Bias, Direction, Edge, Value
except ImportError:          # not a Pi
    gpiod = None

CHIP = "/dev/gpiochip0"
KNOB_A, KNOB_B, BUTTON = 12, 16, 26      # GPIO numbers: pins 32, 36, 37
FLIP = True                              # as wired it counts backwards; flipped so clockwise is up

# Each click of these knobs runs both switches through a full cycle and
# rests with both open (high). Steps between neighbouring states count +1
# or -1; a jump over a state (too fast, or contact bounce) counts nothing.
STEPS = {(0, 1): 1, (1, 3): 1, (3, 2): 1, (2, 0): 1,
         (0, 2): -1, (2, 3): -1, (3, 1): -1, (1, 0): -1}
REST = 3
PRESS_GAP_S = 0.05                       # ignore switch bounce shorter than this
LONG_PRESS_MS = 700                      # held this long: a long press (fires while still held)
DOUBLE_PRESS_MS = 300                    # a second press within this of the first release: a double


class Gestures(QObject):
    """Single, double and long presses from a switch going down and up.

    A long press fires once the switch has been held LONG_PRESS_MS, without
    waiting for the release. A single press has to wait DOUBLE_PRESS_MS after
    the release in case a second press follows, so it fires that much late;
    the double fires on the second press going down."""
    single = pyqtSignal()
    double = pyqtSignal()
    long = pyqtSignal()

    IDLE, DOWN, WAITING, SPENT = range(4)    # SPENT: down, but already a double or long press

    def __init__(self, parent=None):
        super().__init__(parent)
        self._state = self.IDLE
        self._hold = QTimer(self, singleShot=True, interval=LONG_PRESS_MS, timeout=self._held)
        self._wait = QTimer(self, singleShot=True, interval=DOUBLE_PRESS_MS, timeout=self._waited)

    def down(self):
        if self._state == self.IDLE:
            self._state = self.DOWN
            self._hold.start()
        elif self._state == self.WAITING:
            self._wait.stop()
            self._state = self.SPENT
            self.double.emit()
        # Already down (a missed release): nothing new.

    def up(self):
        if self._state == self.DOWN:
            self._hold.stop()
            self._state = self.WAITING
            self._wait.start()
        elif self._state == self.SPENT:
            self._state = self.IDLE

    def _held(self):
        if self._state == self.DOWN:
            self._state = self.SPENT
            self.long.emit()

    def _waited(self):
        if self._state == self.WAITING:
            self._state = self.IDLE
            self.single.emit()


def double_press(routing, media):
    """What a double press does: while navigating, say the last direction
    again; otherwise the next song."""
    if routing.active:
        routing.repeatLast()
    else:
        media.next()


class Knob(QObject):
    turned = pyqtSignal(int)             # +1 per click clockwise, -1 the other way
    pressed = pyqtSignal()               # the switch went down
    released = pyqtSignal()              # and came back up

    def start(self):
        if gpiod is not None:
            threading.Thread(target=self._run, name="knob", daemon=True).start()

    def _request(self):
        lines = (KNOB_A, KNOB_B, BUTTON)
        error = None
        for debounce in (timedelta(milliseconds=1), None):
            kwargs = {"debounce_period": debounce} if debounce else {}
            try:
                req = gpiod.request_lines(CHIP, consumer="baja-knob", config={
                    lines: gpiod.LineSettings(direction=Direction.INPUT, bias=Bias.PULL_UP,
                                              edge_detection=Edge.BOTH, **kwargs)})
            except Exception as e:       # any libgpiod error, not just OSError: no debounce support, or a half-torn-down chip
                error = e
                continue                 # try without debounce, or give up below
            self._last_request_error = None
            return req
        # Each retry from _reopen fails the same way: name the error once, not every time.
        text = f"{type(error).__name__}: {error}"
        if text != getattr(self, "_last_request_error", None):
            self._last_request_error = text
            print(f"Knob: couldn't request the pins: {text}", flush=True)
        return None

    def _reopen(self):
        """Request the pins again after a fault: at once, then with a growing
        pause, until they come back. The knob only gives up at start."""
        req = self._request()
        if req is not None:
            return req
        print("Knob: its pins aren't available, retrying")
        for pause in itertools.chain((1, 2, 5), itertools.repeat(10)):
            time.sleep(pause)
            req = self._request()
            if req is not None:
                print("Knob: working again")
                return req

    def _run(self):
        req = self._request()
        if req is None:
            print("Knob: its pins aren't available")
            return

        def state():
            a, b = req.get_values([KNOB_A, KNOB_B])
            return (a == Value.ACTIVE) << 1 | (b == Value.ACTIVE)

        try:
            last = state()
        except Exception as e:           # a GPIO hiccup just as the lines are read
            errorlog.log.report(type(e), e, e.__traceback__, label="Knob: read error, assuming at rest:")
            last = REST
        steps = 0
        down, changed_at, settling = False, float("-inf"), False
        while True:
            try:
                wait = 1.0
                if settling:             # a change was ignored as bounce: look again once the gap is over
                    wait = max(changed_at + PRESS_GAP_S - time.monotonic(), 0.001)
                if req.wait_edge_events(timedelta(seconds=wait)):
                    req.read_edge_events()
                elif not settling:
                    continue
                now = time.monotonic()

                s = state()
                if s != last:
                    steps += STEPS.get((last, s), 0)
                    last = s
                    if s == REST:            # a click finished: which way did it go?
                        if abs(steps) >= 2:
                            click = 1 if steps > 0 else -1
                            safe_emit(self, "turned", -click if FLIP else click)
                        steps = 0

                # Bounce on make or break: a change this soon after the last
                # one is ignored, and the level is read again once the gap is
                # over, so only the settled level counts.
                is_down = req.get_value(BUTTON) == Value.INACTIVE
                settling = is_down != down and now - changed_at <= PRESS_GAP_S
                if is_down != down and not settling:
                    down, changed_at = is_down, now
                    safe_emit(self, "pressed" if is_down else "released")
            except Exception as e:       # a GPIO hiccup must not end the knob for good
                errorlog.log.report(type(e), e, e.__traceback__, label="Knob: read error, retrying:")
                time.sleep(1.0)
                try:
                    req.release()
                except Exception:
                    pass
                req = self._reopen()
                steps = 0
                if down:                 # the press can't be followed any more: end it, so gestures aren't left down
                    down = False
                    safe_emit(self, "released")
                try:
                    last = state()
                except Exception:
                    pass      # the next pass fails again and comes back here, a second apart
