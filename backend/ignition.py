"""Shuts the Pi down cleanly when the key is turned off.

In the truck the Pi is powered through a 12 V off-delay relay: it switches
on with the key and stays on for about a minute after the key goes off.
That minute is for this. A PC817 optocoupler module on the accessory wire
(harness red) tells a GPIO pin whether the key is on, and once the key has
stayed off for OFF_DELAY_S this runs a normal `systemctl poweroff`, well
before the relay cuts the power.

Starting the engine drops the accessory feed for a second or two, so short
drops are ignored: the key has to stay off for the whole delay. Nothing
happens until the key has been seen on once, so a Pi on the bench with
nothing wired (or the module the wrong way round) never shuts itself down.

Wiring, next to the knob's pins at the USB end of the header:
  pin 29 (GPIO5): the opto module's output
  pin 30 (ground): the module's output ground
  pin 17 (3.3 V): the module's output VCC, if it has one. Never 5 V.

It runs as its own service (deploy/power/baja-ignition.service), not in the
dashboard, so a crashed dashboard can't stop it. To check the wiring, stop
the service (it holds the pin) and watch the key:

    sudo systemctl stop baja-ignition
    python3 -m backend.ignition --dry-run     # turn the key; Ctrl-C to quit
    sudo systemctl start baja-ignition
"""

import argparse
import subprocess
import sys
import time
from datetime import timedelta

try:
    import gpiod
    from gpiod.line import Bias, Direction, Edge, Value
except ImportError:          # not a Pi
    gpiod = None

# The settings. After changing them: sudo systemctl restart baja-ignition
CHIP = "/dev/gpiochip0"
PIN = 5                      # GPIO number: pin 29
KEY_ON_HIGH = True           # the module's output is high with the key on; False if it's low
OFF_DELAY_S = 5.0            # the key must stay off this long. Keep it plus ~20 s for the
                             # shutdown itself well inside the relay's hold time (60 s)

POLL_S = 1.0                 # look at the pin at least this often, edge or not


class KeyPin:
    """The opto module's output on the pin header, read with libgpiod."""

    def __init__(self, chip=CHIP, pin=PIN, key_on_high=KEY_ON_HIGH):
        self.pin = pin
        self.on = Value.ACTIVE if key_on_high else Value.INACTIVE
        # Pulled up, like the knob, so with nothing connected it reads high.
        self.req = gpiod.request_lines(chip, consumer="baja-ignition", config={
            pin: gpiod.LineSettings(direction=Direction.INPUT, bias=Bias.PULL_UP,
                                    edge_detection=Edge.BOTH)})

    def key_on(self):
        return self.req.get_value(self.pin) == self.on

    def wait(self, seconds):
        """Return after `seconds`, or sooner if the pin changes."""
        if self.req.wait_edge_events(timedelta(seconds=seconds)):
            self.req.read_edge_events()


def watch(pin, on_key_off, delay_s=OFF_DELAY_S, clock=time.monotonic, log=print):
    """Follow the key, and call on_key_off() once it has stayed off for
    delay_s. Returns when on_key_off() returns True (shutting down); if it
    returns False (a dry run) it waits for the next key-off.

    `pin` needs key_on() and wait(seconds); tests pass a fake one, with a
    fake clock.
    """
    seen_on = False          # nothing happens until the key has been on once
    off_at = None            # when the key went off, while it's off
    acted = False            # on_key_off() already called for this key-off
    if not pin.key_on():
        log("Key off: waiting to see it on before doing anything")
    while True:
        now = clock()
        if pin.key_on():
            if off_at is not None and not acted:
                log(f"Key back on after {now - off_at:.1f} s: not shutting down")
            elif not seen_on or acted:
                log("Key on")
            seen_on, off_at, acted = True, None, False
        elif seen_on and off_at is None:
            off_at = now
            log(f"Key off: shutting down in {delay_s:g} s unless it comes back on")

        wait = POLL_S
        if off_at is not None and not acted:
            deadline = off_at + delay_s
            if now >= deadline:
                log(f"Key off for {delay_s:g} s: shutting down")
                if on_key_off():
                    return
                acted = True
            else:
                wait = min(wait, deadline - now)
        pin.wait(wait)


def power_off():
    # systemd stops the dashboard and everything else properly, then the Pi
    # halts. If that fails, exit with an error: the service starts this
    # again, and with the key still off it tries again.
    code = subprocess.run(["systemctl", "poweroff"]).returncode
    if code:
        sys.exit(f"systemctl poweroff failed (exit {code})")
    return True


def dry_run():
    print("Dry run: would power off now")
    return False


def main():
    parser = argparse.ArgumentParser(description="Shut the Pi down cleanly when the key is turned off")
    parser.add_argument("--dry-run", action="store_true",
                        help="only say what it sees and would do; never power off")
    args = parser.parse_args()

    if gpiod is None:
        sys.exit("No libgpiod here; this runs on the Pi (python3-libgpiod)")
    try:
        pin = KeyPin()
    except (OSError, ValueError) as e:
        sys.exit(f"Can't read GPIO{PIN}: {e}. Is the baja-ignition service holding it?")
    print(f"Watching the key on GPIO{PIN} ({'high' if KEY_ON_HIGH else 'low'} = on), "
          f"shutting down {OFF_DELAY_S:g} s after key-off" + (" (dry run)" if args.dry_run else ""))
    try:
        watch(pin, dry_run if args.dry_run else power_off)
    except KeyboardInterrupt:
        pass


if __name__ == "__main__":
    main()
