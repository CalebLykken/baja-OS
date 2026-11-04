"""Summarise the dashboard's startup timings across boots.

Reads the journal lines that backend/startup.py prints once per start, e.g.

    Startup: imports 412 ms, backends 900 ms, qml 1840 ms (system up 14.2 s)

and prints per-phase statistics (count, median, min, max, latest), so a
boot-speed change can be shown with a before and after number. Stdlib only,
so it runs on the Mac and on the Pi alike.

Usage:
    journalctl -u baja-os -o cat | python3 tools/startup_report.py
    python3 tools/startup_report.py journal.txt --last 10
    ssh baja.local journalctl -u baja-os -o cat | python3 tools/startup_report.py
"""

import argparse
import re
import statistics
import sys

STARTUP = "Startup: "
_SYSTEM_UP = re.compile(r"\(system up ([0-9.]+) s\)")
_PHASE = re.compile(r"(.+?) (\d+) ms")


def parse(line):
    """(phases, system_up) for a line holding a Startup: summary, else None.

    phases maps each phase name to its milliseconds; system_up is the uptime
    in seconds, or None when the line has no '(system up X s)' part. Pieces
    that don't read as '<name> <int> ms' are skipped, never raised on."""
    at = line.find(STARTUP)
    if at < 0:
        return None
    body = line[at + len(STARTUP):]
    system_up = None
    m = _SYSTEM_UP.search(body)
    if m:
        try:
            system_up = float(m.group(1))
        except ValueError:
            system_up = None
        body = body[:m.start()] + body[m.end():]
    phases = {}
    for piece in body.split(","):
        m = _PHASE.fullmatch(piece.strip())
        if m:
            phases[m.group(1)] = int(m.group(2))
    return phases, system_up


def select_last(records, n):
    """The newest n records, in their original order."""
    return records[-n:]


def _stats(values):
    return {
        "n": len(values),
        "median": statistics.median(values),
        "min": min(values),
        "max": max(values),
        "latest": values[-1],
    }


def summarise(records):
    """Rows of (name, stats) in first-seen phase order, with a final
    'system up (s)' row when any record has an uptime."""
    order = []
    values = {}
    for phases, _ in records:
        for name, ms in phases.items():
            if name not in values:
                order.append(name)
                values[name] = []
            values[name].append(ms)
    rows = [(name, _stats(values[name])) for name in order]
    ups = [up for _, up in records if up is not None]
    if ups:
        rows.append(("system up (s)", _stats(ups)))
    return rows


def _num(v):
    return f"{v:g}"


def render(rows):
    """Lines of an aligned table: the phase name left, the numbers right."""
    head = ["phase", "n", "median", "min", "max", "latest"]
    body = [
        [name, str(s["n"]), _num(s["median"]), _num(s["min"]),
         _num(s["max"]), _num(s["latest"])]
        for name, s in rows
    ]
    widths = [max(len(r[i]) for r in [head] + body) for i in range(len(head))]

    def line(cells):
        out = [cells[0].ljust(widths[0])]
        out += [c.rjust(w) for c, w in zip(cells[1:], widths[1:])]
        return "  ".join(out).rstrip()

    return [line(head)] + [line(r) for r in body]


def main(argv=None):
    p = argparse.ArgumentParser(
        description="Summarise Baja OS startup timings from journal output.")
    p.add_argument("file", nargs="?",
                   help="journal output to read (default: stdin)")
    p.add_argument("--last", type=int, metavar="N",
                   help="only the most recent N starts")
    args = p.parse_args(argv)
    if args.last is not None and args.last < 1:
        p.error("--last must be at least 1")

    if args.file in (None, "-"):
        text = sys.stdin.read()
    else:
        try:
            with open(args.file, encoding="utf-8", errors="replace") as f:
                text = f.read()
        except OSError as e:
            print(f"startup_report: {e}", file=sys.stderr)
            return 2

    records = [r for r in (parse(line) for line in text.splitlines())
               if r is not None]
    if args.last is not None:
        records = select_last(records, args.last)
    if not records:
        print("no Startup: lines found")
        return 1

    print(f"{len(records)} starts")
    for line in render(summarise(records)):
        print(line)
    return 0


if __name__ == "__main__":
    sys.exit(main())
