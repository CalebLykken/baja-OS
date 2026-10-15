"""Turn the parts Fusion exports (each in its place on the dash) into
print-ready STL files: every part turned onto its best side for printing and
set on the bed at the origin. Plain Python, no extra packages.

    python3 hardware/case/make_print_files.py

The Fusion script (fusion/BajaDashCase) runs this after every build, so
print/ always matches the model.
"""

import math
import os
import struct

HERE = os.path.dirname(os.path.abspath(__file__))
SRC = os.path.join(HERE, 'build')
DST = os.path.join(HERE, 'print')
BED = 256.0      # a common bed size (Bambu, Prusa MK4/XL is bigger); just a warning

# (exported file, print file, copies, turns as (axis, degrees), how it sits)
PARTS = [
    ('dash-panel.stl', 'dash-panel.stl', 1, [], 'back face down, screen posts up'),
    ('pi-case.stl', 'pi-case.stl', 1, [('x', 180)], 'floor down, open back up'),
    ('volume-knob.stl', 'volume-knob.stl', 1, [('x', 180)], 'top down, shaft hole up'),
    ('adapter-plate-left.stl', 'adapter-plate.stl', 4, [('x', 90)],
     'standing on its Z-shaped end; the same part fits left and right'),
]


def read_stl(path):
    """Triangles as lists of three (x, y, z) tuples. Binary or ASCII STL."""
    data = open(path, 'rb').read()
    if len(data) >= 84:
        count = struct.unpack('<I', data[80:84])[0]
        if 84 + count * 50 == len(data):
            tris = []
            for i in range(count):
                v = struct.unpack('<12f', data[84 + i * 50:84 + i * 50 + 48])
                tris.append([v[3:6], v[6:9], v[9:12]])
            return tris
    tris, cur = [], []
    for line in data.decode('ascii', 'replace').splitlines():
        parts = line.split()
        if parts and parts[0] == 'vertex':
            cur.append(tuple(float(x) for x in parts[1:4]))
            if len(cur) == 3:
                tris.append(cur)
                cur = []
    return tris


def write_stl(path, tris, name):
    out = [name.encode('ascii', 'replace')[:80].ljust(80, b' '), struct.pack('<I', len(tris))]
    for a, b, c in tris:
        ux, uy, uz = b[0] - a[0], b[1] - a[1], b[2] - a[2]
        vx, vy, vz = c[0] - a[0], c[1] - a[1], c[2] - a[2]
        n = (uy * vz - uz * vy, uz * vx - ux * vz, ux * vy - uy * vx)
        ln = math.sqrt(n[0] ** 2 + n[1] ** 2 + n[2] ** 2) or 1.0
        out.append(struct.pack('<12fH', n[0] / ln, n[1] / ln, n[2] / ln, *a, *b, *c, 0))
    with open(path, 'wb') as fh:
        fh.write(b''.join(out))


def turn(tris, axis, degrees):
    c, s = round(math.cos(math.radians(degrees)), 12), round(math.sin(math.radians(degrees)), 12)

    def r(p):
        x, y, z = p
        if axis == 'x':
            return (x, y * c - z * s, y * s + z * c)
        if axis == 'y':
            return (x * c + z * s, y, -x * s + z * c)
        return (x * c - y * s, x * s + y * c, z)
    return [[r(p) for p in t] for t in tris]


def place_on_bed(tris):
    xs = [p[0] for t in tris for p in t]
    ys = [p[1] for t in tris for p in t]
    zs = [p[2] for t in tris for p in t]
    dx, dy, dz = -(min(xs) + max(xs)) / 2, -(min(ys) + max(ys)) / 2, -min(zs)
    moved = [[(p[0] + dx, p[1] + dy, p[2] + dz) for p in t] for t in tris]
    return moved, (max(xs) - min(xs), max(ys) - min(ys), max(zs) - min(zs))


def bed_contact(tris):
    """Area (mm^2) of downward faces lying on the bed."""
    area = 0.0
    for a, b, c in tris:
        if max(a[2], b[2], c[2]) < 0.01:
            area += abs((b[0] - a[0]) * (c[1] - a[1]) - (c[0] - a[0]) * (b[1] - a[1])) / 2
    return area


def make_all():
    os.makedirs(DST, exist_ok=True)
    lines = []
    for src, dst, copies, turns, how in PARTS:
        path = os.path.join(SRC, src)
        if not os.path.exists(path):
            lines.append('missing build/%s (run the Fusion script first)' % src)
            continue
        tris = read_stl(path)
        for axis, degrees in turns:
            tris = turn(tris, axis, degrees)
        tris, size = place_on_bed(tris)
        write_stl(os.path.join(DST, dst), tris, 'Baja OS dash case: ' + dst)
        warn = '  (bigger than a %d mm bed)' % BED if max(size[0], size[1]) > BED or size[2] > BED else ''
        lines.append('print/%s x%d: %.1f x %.1f x %.1f mm, %.0f mm2 on the bed, %s%s' % (
            dst, copies, size[0], size[1], size[2], bed_contact(tris), how, warn))
    return lines


if __name__ == '__main__':
    print('\n'.join(make_all()))
