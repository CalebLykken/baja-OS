"""Rank the dashboard's startup import cost and say who pulled each heavy
package in.

Reads CPython's `-X importtime` output (stderr lines such as
`import time:      4288 |      33963 |       http.client`), prints the total, the
costliest backend.* modules, and every heavy non-backend package with the
backend module that imported it first. A lazy import only pays off when EVERY
importer defers it, so each heavy package also lists all backend modules that
import it at the top of the file. Developer tool only: nothing in the app
imports it, so it costs nothing at runtime. Stdlib only, so it runs on the
Mac and on the Pi alike.

Usage:
    python3 tools/import_report.py
    python3 tools/import_report.py --top 20 --min-ms 5
    ssh baja.local 'cd ~/baja-OS && python3 -X importtime -c "import main"' 2> imports.txt; python3 tools/import_report.py --file imports.txt
    python3 tools/import_report.py --file -   # read a saved log from stdin
"""

import argparse
import os
import re
import subprocess
import sys

_LINE = re.compile(r"^import time:\s+(\d+)\s*\|\s*(\d+)\s*\|( *)(\S.*?)\s*$")
_ROOT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..")


def parse(text):
    """(name, self_us, cumulative_us, depth) per importtime line, in order.

    The header and any line that doesn't match are skipped, never raised on."""
    records = []
    for line in text.splitlines():
        m = _LINE.match(line)
        if not m:
            continue
        # CPython indents the name two spaces per nesting level.
        records.append((m.group(4), int(m.group(1)), int(m.group(2)),
                        len(m.group(3)) // 2))
    return records


def build_parents(records):
    """Each record's parent module name (None at top level).

    CPython prints children before their parent, so the parent is the next
    record after it with a smaller depth."""
    parents = [None] * len(records)
    pending = []  # indexes still waiting for a parent
    for i, rec in enumerate(records):
        while pending and records[pending[-1]][3] > rec[3]:
            parents[pending.pop()] = rec[0]
        pending.append(i)
    return parents


def _is_backend(name, prefix):
    # the bare package record ("backend") is the backend too, not a heavy package
    return (name.startswith(prefix) or name == prefix.rstrip(".")
            or name == "main")


def attribute(records, prefix="backend."):
    """{index: importer}: the nearest ancestor under prefix (else 'main') for
    every record that is not itself under prefix and not main."""
    parents = build_parents(records)
    by_name = {rec[0]: i for i, rec in enumerate(records)}
    out = {}
    for i, rec in enumerate(records):
        if _is_backend(rec[0], prefix):
            continue
        who = parents[i]
        while who is not None and not who.startswith(prefix):
            who = parents[by_name[who]] if who in by_name else None
        out[i] = who or "main"
    return out


def _ms(us):
    return "%.1f" % (us / 1000.0)


def heavy_packages(records, min_ms=2.0, prefix="backend."):
    """Indexes of the outermost non-backend records at or over min_ms."""
    parents = build_parents(records)
    by_name = {rec[0]: i for i, rec in enumerate(records)}
    heavy = []
    for i, rec in enumerate(records):
        if _is_backend(rec[0], prefix) or rec[2] / 1000.0 < min_ms:
            continue
        # skip when an ancestor outside the backend is itself heavy
        who, nested = parents[i], False
        while who is not None and not _is_backend(who, prefix):
            j = by_name.get(who)
            if j is None:
                break
            if records[j][2] / 1000.0 >= min_ms:
                nested = True
                break
            who = parents[j]
        if not nested:
            heavy.append(i)
    return heavy


def report(records, top=15, min_ms=2.0, importers=None):
    """Report lines. importers optionally maps a heavy module's full name to
    the backend modules that import it at the top of their file."""
    lines = []
    outer = sum(r[2] for r in records if r[3] == 0)
    lines.append("Total (outermost imports): %s ms" % _ms(outer))
    lines.append("")
    backend = sorted((r for r in records if r[0].startswith("backend.")),
                     key=lambda r: -r[2])[:top]
    lines.append("Top %d backend modules by cumulative ms:" % top)
    for name, self_us, cum, _ in backend:
        lines.append("  %8s ms  (self %s)  %s" % (_ms(cum), _ms(self_us), name))
    lines.append("")
    lines.append("Heavy packages (>= %.1f ms) and the backend module that "
                 "first imported them:" % min_ms)
    who = attribute(records)
    for i in sorted(heavy_packages(records, min_ms), key=lambda i: -records[i][2]):
        name, _, cum, _ = records[i]
        lines.append("  %8s ms  %s  <- %s" % (_ms(cum), name, who.get(i, "main")))
        if importers:
            found = importers.get(name)
            if found:
                lines.append("               also imported by: " + ", ".join(found))
    return lines


_IMPORT = re.compile(r"^import\s+([^#\n]+)", re.M)
_FROM = re.compile(r"^from\s+([A-Za-z_][\w.]*)\s+import\s+([^#\n]+)", re.M)


def _imported_modules(text):
    """Every dotted module name a top-of-line import statement in text loads.

    `import a.b, c` -> a.b, c. `from a import b` -> a and a.b (b may be a
    submodule)."""
    mods = set()
    for m in _IMPORT.finditer(text):
        for part in m.group(1).split(","):
            words = part.split()
            if words and re.match(r"[A-Za-z_][\w.]*$", words[0]):
                mods.add(words[0])
    for m in _FROM.finditer(text):
        mods.add(m.group(1))
        for part in m.group(2).strip("() \\").split(","):
            words = part.split()
            if words and re.match(r"\w+$", words[0]):
                mods.add(m.group(1) + "." + words[0])
    return mods


def scan_importers(directory, names):
    """{heavy module name: sorted backend.<module> names} for every top-of-line
    import in directory/*.py that loads that exact module (`import a.b.c`
    counts for a.b, but `import a.b` does not count for a.c)."""
    out = {}
    try:
        files = sorted(f for f in os.listdir(directory) if f.endswith(".py"))
    except OSError:
        return out
    for fname in files:
        try:
            with open(os.path.join(directory, fname), encoding="utf-8") as f:
                text = f.read()
        except (OSError, UnicodeDecodeError):
            continue
        mod = "backend." + fname[:-3]
        mods = _imported_modules(text)
        for h in names:
            if any(m == h or m.startswith(h + ".") for m in mods):
                if mod not in out.setdefault(h, []):
                    out[h].append(mod)
    return {k: sorted(v) for k, v in out.items() if v}


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--file", help="saved importtime log ('-' for stdin)")
    ap.add_argument("--top", type=int, default=15)
    ap.add_argument("--min-ms", type=float, default=2.0)
    args = ap.parse_args(argv)

    if args.file:
        try:
            if args.file == "-":
                text = sys.stdin.read()
            else:
                with open(args.file, encoding="utf-8", errors="replace") as f:
                    text = f.read()
        except OSError as e:
            print("Can't read %s: %s" % (args.file, e))
            return 2
    else:
        env = dict(os.environ, QT_QPA_PLATFORM="offscreen")
        try:
            p = subprocess.run(
                [sys.executable, "-X", "importtime", "-c", "import main"],
                cwd=_ROOT, env=env, capture_output=True, text=True, timeout=120)
        except (OSError, subprocess.SubprocessError) as e:
            print("Import run failed: %s" % e)
            return 2
        if p.returncode != 0:
            print("Import run failed (exit %d):" % p.returncode)
            print("\n".join(p.stderr.splitlines()[-10:]))
            return 2
        text = p.stderr

    records = parse(text)
    if not records:
        print("No importtime lines found.")
        return 1
    heavy = {records[i][0] for i in heavy_packages(records, args.min_ms)}
    importers = scan_importers(os.path.join(_ROOT, "backend"), heavy)
    print("\n".join(report(records, args.top, args.min_ms, importers)))
    return 0


if __name__ == "__main__":
    sys.exit(main())
