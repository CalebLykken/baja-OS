"""The dash knob: an EC11 rotary encoder with a push switch, wired straight
to the Pi's pin header and read with libgpiod (on a Mac it does nothing).

Wiring, at the USB end of the header, clear of the sound board's pins:
  pins 32 (GPIO12) and 36 (GPIO16): the knob's two outer legs
  pin 34 (ground): its middle leg
  pin 37 (GPIO26) and pin 39 (ground): the push switch

The pins are only ever read, with the Pi's own pull-ups, so a loose or
misplaced wire can't harm anything. Turning reports clicks (`turned`, +1
or -1); a press reports `pressed`. main.py decides what they do.
"""

import threading
import time
from datetime import timedelta

from PyQt6.QtCore import QObject, pyqtSignal

from backend import safe_emit

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


class Knob(QObject):
    turned = pyqtSignal(int)             # +1 per click clockwise, -1 the other way
    pressed = pyqtSignal()

    def start(self):
        if gpiod is not None:
            threading.Thread(target=self._run, name="knob", daemon=True).start()

    def _request(self):
        lines = (KNOB_A, KNOB_B, BUTTON)
        for debounce in (timedelta(milliseconds=1), None):
            kwargs = {"debounce_period": debounce} if debounce else {}
            try:
                return gpiod.request_lines(CHIP, consumer="baja-knob", config={
                    lines: gpiod.LineSettings(direction=Direction.INPUT, bias=Bias.PULL_UP,
                                              edge_detection=Edge.BOTH, **kwargs)})
            except (OSError, ValueError):
                continue                 # no debounce support: try without
        return None

    def _run(self):
        req = self._request()
        if req is None:
            print("Knob: its pins aren't available")
            return

        def state():
            a, b = req.get_values([KNOB_A, KNOB_B])
            return (a == Value.ACTIVE) << 1 | (b == Value.ACTIVE)

        last, steps = state(), 0
        down, released_at = False, 0.0
        while True:
            if not req.wait_edge_events(timedelta(seconds=1)):
                continue
            req.read_edge_events()
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

            is_down = req.get_value(BUTTON) == Value.INACTIVE
            if is_down and not down and now - released_at > PRESS_GAP_S:
                down = True
                safe_emit(self, "pressed")
            elif not is_down and down:
                down, released_at = False, now
