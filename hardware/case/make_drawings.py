"""Dimensioned drawings of the printed dash case parts, for checking a test
print with a ruler and calipers.

    python3 hardware/case/make_drawings.py

Needs matplotlib (pip3 install matplotlib). Writes drawings/*.png and
drawings/baja-dash-case-drawings.pdf. Every size comes from the Fusion
script (fusion/BajaDashCase): this tool runs the script's own layout and
build code with a stand-in for Fusion and records every feature it makes, so
the drawings follow the PARAMETERS defaults. It also checks them against the
print files in print/ and warns if those were made from other sizes.
"""

import math
import os
import re
import sys
import types

HERE = os.path.dirname(os.path.abspath(__file__))
SCRIPT = os.path.join(HERE, 'fusion', 'BajaDashCase', 'BajaDashCase.py')
OUT = os.path.join(HERE, 'drawings')


# ------------------------------------------------------- reading the model
# A Num is a length that carries how it changes with each parameter it was
# worked out from, so each dimension can say how sure we are of it. A size
# that doesn't move when a parameter changes (a slot's width, say, though its
# position follows the opening) isn't tagged with that parameter.

class Num(float):
    def __new__(cls, value, slope=None):
        n = float.__new__(cls, value)
        n.slope = {k: s for k, s in (slope or {}).items() if abs(s) > 1e-9}
        return n

    @property
    def src(self):
        return frozenset(self.slope)


def _slope(x):
    return getattr(x, 'slope', {})


def _combine(a, ka, b, kb):
    """ka * slope(a) + kb * slope(b)."""
    out = {}
    for x, k in ((a, ka), (b, kb)):
        for name, s in _slope(x).items():
            out[name] = out.get(name, 0.0) + k * s
    return out


def _add(a, b):
    return Num(float(a) + float(b), _combine(a, 1.0, b, 1.0))


def _sub(a, b):
    return Num(float(a) - float(b), _combine(a, 1.0, b, -1.0))


def _mul(a, b):
    return Num(float(a) * float(b), _combine(a, float(b), b, float(a)))


def _div(a, b):
    return Num(float(a) / float(b), _combine(a, 1.0 / float(b), b, -float(a) / float(b) ** 2))


def _ok(f):
    def g(a, b):
        return f(a, b) if isinstance(b, (int, float)) else NotImplemented
    return g


Num.__add__, Num.__radd__ = _ok(_add), _ok(lambda a, b: _add(b, a))
Num.__sub__, Num.__rsub__ = _ok(_sub), _ok(lambda a, b: _sub(b, a))
Num.__mul__, Num.__rmul__ = _ok(_mul), _ok(lambda a, b: _mul(b, a))
Num.__truediv__, Num.__rtruediv__ = _ok(_div), _ok(lambda a, b: _div(b, a))
Num.__neg__ = lambda a: Num(-float(a), {k: -s for k, s in a.slope.items()})
Num.__pos__ = lambda a: a
Num.__abs__ = lambda a: a if float(a) >= 0 else -a


def _src(x):
    return getattr(x, 'src', frozenset())

# How sure we are, weakest first. A size worked out from several parameters
# takes its least sure source.
SURENESS = ['UNKNOWN', 'ESTIMATED', 'MEASURED', 'DESIGN']
TAGS = {'UNKNOWN': 'U', 'ESTIMATED': 'E', 'MEASURED': 'M', 'DESIGN': 'D'}

# The script's fixed tables that aren't parameters: (names, sureness).
CONSTANTS = {'PI_HOLES': 'MEASURED', 'PI_W': 'MEASURED', 'PI_H': 'MEASURED',       # Raspberry Pi drawing
             'PI_PORTS_RIGHT': 'ESTIMATED', 'PI_PORTS_TOP': 'ESTIMATED',            # "approximate"
             'PI_PORTS_LEFT': 'ESTIMATED'}


class Shape:
    """One closed outline drawn in a sketch, in model coordinates (u, v)."""

    def __init__(self, kind, data):
        self.kind = kind          # 'circle': (u, v, d); 'path': list of segments
        self.data = data


class Prism:
    def __init__(self, axis, lo, hi, op, name, shapes):
        self.axis, self.lo, self.hi, self.op, self.name, self.shapes = axis, lo, hi, op, name, shapes

    def circles(self):
        return [s.data for s in self.shapes if s.kind == 'circle']

    def paths(self):
        return [s.data for s in self.shapes if s.kind == 'path']


class _Sketch:
    def __init__(self):
        self.shapes = []

    def draw(self, segs):
        self.shapes.append(Shape('path', list(segs)))

    def circle(self, u, v, d):
        self.shapes.append(Shape('circle', (u, v, d)))


class _Body:
    pass


class RecordedPart:
    """Stands in for the script's Part: keeps each extrusion instead of making it."""

    def __init__(self, design, name):
        self.name = name
        self.prisms = []
        self.body = None
        self.bodies = []

    def prism(self, axis, lo, hi, draw, op='join', name=None):
        lo, hi = min(lo, hi), max(lo, hi)
        sk = _Sketch()
        draw(sk)
        if op == 'join' and self.body is None:
            op = 'new'
        if op == 'new':
            self.body = _Body()
            self.bodies.append(self.body)
        self.prisms.append(Prism(axis, lo, hi, op, name, sk.shapes))

    def name_body(self, name):
        pass

    def get(self, name):
        found = [p for p in self.prisms if p.name == name]
        if not found:
            raise KeyError('%s has no feature named %r' % (self.name, name))
        return found

    def one(self, name):
        return self.get(name)[0]


class _Anything(types.ModuleType):
    """Fusion's adsk modules: any attribute is another stand-in."""

    def __getattr__(self, name):
        if name.startswith('__'):
            raise AttributeError(name)
        return _Anything(name)

    def __call__(self, *a, **k):
        return _Anything('call')


def load_model():
    adsk = _Anything('adsk')
    adsk.core = _Anything('adsk.core')
    adsk.fusion = _Anything('adsk.fusion')
    saved = {k: sys.modules.get(k) for k in ('adsk', 'adsk.core', 'adsk.fusion')}
    sys.modules.update({'adsk': adsk, 'adsk.core': adsk.core, 'adsk.fusion': adsk.fusion})
    try:
        mod = types.ModuleType('BajaDashCase')
        mod.__file__ = SCRIPT
        exec(compile(open(SCRIPT).read(), SCRIPT, 'exec'), mod.__dict__)
    finally:
        for k, v in saved.items():
            if v is None:
                sys.modules.pop(k, None)
            else:
                sys.modules[k] = v

    sureness = {}
    p = mod.Params()
    for name, default, unit, note in mod.PARAMETERS:
        word = note.split(':')[0].split('(')[0].split()[0].strip().upper()
        sureness[name] = 'MEASURED' if word == 'VERIFIED' else word
        if sureness[name] not in SURENESS:
            raise ValueError('%s: cannot tell how sure %r is' % (name, note))
        p[name] = Num(default, {name: 1.0})

    def tracked(value, name, how):
        if isinstance(value, (tuple, list)):
            return type(value)(tracked(v, '%s[%d]' % (name, i), how) for i, v in enumerate(value))
        sureness[name] = how
        return Num(value, {name: 1.0})
    for name, how in CONSTANTS.items():
        setattr(mod, name, tracked(getattr(mod, name), name, how))

    made = []

    def record(design, name):
        made.append(RecordedPart(design, name))
        return made[-1]
    mod.Part = record
    d = mod.derive(p)
    parts = {'panel': mod.build_panel(None, p, d), 'knob': mod.build_knob(None, p, d),
             'pi case': mod.build_pi_case(None, p, d), 'amp plate': mod.build_amp_plate(None, p, d)}
    for side in ('left', 'right'):
        for level, yc in zip(('lower', 'upper'), d.adapter_ys):
            parts['adapter %s %s' % (level, side)] = mod.build_adapter(None, p, d, side, level, yc)
    n = len(made)
    mod.build_references(None, p, d)                 # the screen, the Pi, the climate controls, the brackets
    parts.update({r.name: r for r in made[n:]})
    return types.SimpleNamespace(mod=mod, p=p, d=d, parts=parts, sureness=sureness)


def sureness_of(model, value):
    """The least sure source of a size; a plain number is a design choice."""
    found = [model.sureness[s] for s in _src(value)] or ['DESIGN']
    return min(found, key=SURENESS.index)


# ------------------------------------------------------------ geometry

def arc_points(p0, pm, p1):
    """Points along a three-point arc, from p0 up to (not including) p1."""
    (x1, y1), (x2, y2), (x3, y3) = [(float(a), float(b)) for a, b in (p0, pm, p1)]
    d = 2 * (x1 * (y2 - y3) + x2 * (y3 - y1) + x3 * (y1 - y2))
    s1, s2, s3 = x1 * x1 + y1 * y1, x2 * x2 + y2 * y2, x3 * x3 + y3 * y3
    cx = (s1 * (y2 - y3) + s2 * (y3 - y1) + s3 * (y1 - y2)) / d
    cy = (s1 * (x3 - x2) + s2 * (x1 - x3) + s3 * (x2 - x1)) / d
    r = math.hypot(x1 - cx, y1 - cy)
    a0, am, a1 = [math.atan2(y - cy, x - cx) for x, y in ((x1, y1), (x2, y2), (x3, y3))]
    sweep = (a1 - a0) % (2 * math.pi)
    if (am - a0) % (2 * math.pi) > sweep:
        sweep -= 2 * math.pi
    n = max(4, int(abs(sweep) / math.radians(5)) + 1)
    return [(cx + r * math.cos(a0 + sweep * i / n), cy + r * math.sin(a0 + sweep * i / n)) for i in range(n)]


def seg_points(seg):
    return [seg[1]] if seg[0] == 'L' else arc_points(seg[1], seg[2], seg[3])


def path_points(segs):
    pts = []
    for seg in segs:
        pts += seg_points(seg)
    return pts


class Box:
    """Sides and corner radii of a rounded rectangle the script drew with rrect()."""

    def __init__(self, segs):
        lines = [s for s in segs if s[0] == 'L']
        flat = [s for s in lines if abs(s[1][1] - s[2][1]) < 1e-9]
        upright = [s for s in lines if abs(s[1][0] - s[2][0]) < 1e-9]
        self.v0 = min((s[1][1] for s in flat), key=float)
        self.v1 = max((s[1][1] for s in flat), key=float)
        self.u0 = min((s[1][0] for s in upright), key=float)
        self.u1 = max((s[1][0] for s in upright), key=float)
        self.r = {}
        cu, cv = (self.u0 + self.u1) / 2, (self.v0 + self.v1) / 2
        for s in segs:
            if s[0] == 'A':
                a, b = s[1], s[3]
                r = max(abs(a[0] - b[0]), abs(a[1] - b[1]), key=float)
                key = ('t' if s[2][1] > cv else 'b') + ('r' if s[2][0] > cu else 'l')
                self.r[key] = (r, s[2])
        self.segs = segs

    @property
    def w(self):
        return self.u1 - self.u0

    @property
    def h(self):
        return self.v1 - self.v0

    @property
    def cu(self):
        return (self.u0 + self.u1) / 2

    @property
    def cv(self):
        return (self.v0 + self.v1) / 2


def bounds(segs):
    """Sides of any closed outline (a slot, say), for sizes: an object like Box without corner radii."""
    pts = [q for seg in segs for q in seg[1:]]        # ends, and each arc's middle (a slot's far point)
    us, vs = [q[0] for q in pts], [q[1] for q in pts]
    u0, u1, v0, v1 = min(us, key=float), max(us, key=float), min(vs, key=float), max(vs, key=float)
    return types.SimpleNamespace(u0=u0, u1=u1, v0=v0, v1=v1, w=u1 - u0, h=v1 - v0, cu=(u0 + u1) / 2,
                                 cv=(v0 + v1) / 2, segs=segs)


def notched_top(outline, notch):
    """A rounded-rectangle outline with a notch cut down into its top edge."""
    box, cut = Box(outline), Box(notch)
    pts = []
    for seg in outline:
        if seg[0] == 'L' and abs(seg[1][1] - box.v1) < 1e-9 and abs(seg[2][1] - box.v1) < 1e-9:
            bottom = []
            for s in notch:                       # the notch's bottom corners and edge, left to right
                pts_s = seg_points(s)
                if all(float(q[1]) < float(box.v1) for q in pts_s) and s[0] == 'A' or (
                        s[0] == 'L' and abs(s[1][1] - cut.v0) < 1e-9 and abs(s[2][1] - cut.v0) < 1e-9):
                    bottom.append(s)
            inner = []
            for s in bottom:
                inner += seg_points(s)
            inner.sort(key=lambda q: float(q[0]))
            pts += [seg[1], (cut.u1, box.v1)] + [(cut.u1, cut.v0 + cut.r['br'][0])] + \
                list(reversed(inner)) + [(cut.u0, cut.v0 + cut.r['bl'][0]), (cut.u0, box.v1)]
        else:
            pts += seg_points(seg)
    return pts


def fluted_circle(r, flutes, flute_r, n=1440):
    """Outline of a round knob with grooves cut around its edge (polar samples)."""
    pts = []
    for i in range(n):
        t = 2 * math.pi * i / n
        rr = r
        for k in range(flutes):
            dt = t - 2 * math.pi * k / flutes
            disc = flute_r ** 2 - (r * math.sin(dt)) ** 2
            if disc >= 0 and math.cos(dt) > 0:
                rr = min(rr, r * math.cos(dt) - math.sqrt(disc))
        pts.append((rr * math.cos(t), rr * math.sin(t)))
    return pts


# ------------------------------------------------------------- the paper

PAGE_W, PAGE_H = 279.4, 215.9           # US Letter, landscape (mm)
MARGIN = 6.0
STRIP_TOP = MARGIN + 21.0               # top of the title strip
PT = 25.4 / 72                          # mm in a point

INK = '#161616'
SOFT = '#4a4a4a'
FAINT = '#a3a3a3'
GHOST = '#6f8fb0'
PART = '#f1f0ec'                        # the part's face
BLIND = '#d9d7d0'                       # pockets and blind holes
TAG_COLOUR = {'M': INK, 'D': INK, 'E': '#c25400', 'U': '#c8102e'}
THICK, MID, THIN, HAIR = 1.1, 0.75, 0.45, 0.35       # line widths, points
DIM_PT, NOTE_PT = 6.5, 6.8
ARROW = 2.0                             # arrowhead length, mm
HIDDEN = (3.0, 1.6)                     # dash pattern, points
CENTRE = (9.0, 2.0, 2.0, 2.0)


def num(v):
    r = math.floor(abs(float(v)) * 100 + 0.5 + 1e-6) / 100
    s = ('%.2f' % r).rstrip('0').rstrip('.')
    return '-' + s if float(v) < 0 and r else s


def inches(v):
    """'6 3/4 in' when a size is a whole number of sixteenths of an inch, else ''."""
    n16 = float(v) / 25.4 * 16
    n = int(round(n16))
    if n <= 0 or abs(n16 - n) > 0.02:
        return ''
    whole, frac = divmod(n, 16)
    den = 16
    while frac and frac % 2 == 0:
        frac, den = frac // 2, den // 2
    return ' '.join(([str(whole)] if whole else []) + (['%d/%d' % (frac, den)] if frac else [])) + ' in'


def text_width(s, size):
    """Rough width (mm) of a label in DejaVu Sans."""
    plain = re.sub(r'\$\^\{\\rm (\w)\}\$', 'x', s)
    return max(len(line) for line in plain.split('\n')) * 0.6 * size * PT


def spread(xs, gap):
    """Move sorted positions apart to at least `gap`, keeping each crowd centred."""
    groups = [[x] for x in xs]

    def place(g):
        start = sum(g) / len(g) - gap * (len(g) - 1) / 2
        return [start + i * gap for i in range(len(g))]
    merged = True
    while merged:
        merged = False
        for i in range(len(groups) - 1):
            if place(groups[i + 1])[0] - place(groups[i])[-1] < gap - 1e-9:
                groups[i:i + 2] = [groups[i] + groups[i + 1]]
                merged = True
                break
    return [x for g in groups for x in place(g)]


class Sheet:
    """One page: a US Letter sheet in millimetres, with the title strip."""

    def __init__(self, model, number, total, title, about, scale):
        self.m = model
        self.fig = plt.figure(figsize=(PAGE_W / 25.4, PAGE_H / 25.4))
        self.ax = self.fig.add_axes([0, 0, 1, 1])
        self.ax.set_xlim(0, PAGE_W)
        self.ax.set_ylim(0, PAGE_H)
        self.ax.axis('off')
        self.title = title
        self.frame(number, total, title, about, scale)

    # labels -------------------------------------------------------------
    def val(self, v, prefix='', suffix='', inch=False):
        tag = TAGS[sureness_of(self.m, v)]
        extra = ' (%s)' % inches(v) if inch and inches(v) else ''
        return '%s%s%s$^{\\rm %s}$%s' % (prefix, num(v), suffix, tag, extra), tag

    def fmt(self, template, *values, inch=False):
        """Fill each {} with a size and its letter; the colour is the least sure one's."""
        pieces = template.split('{}')
        if len(pieces) != len(values) + 1:
            raise ValueError('%r needs %d sizes' % (template, len(pieces) - 1))
        out, tags = [pieces[0]], ['D']
        for v, piece in zip(values, pieces[1:]):
            s, tag = self.val(v, inch=inch)
            out += [s, piece]
            tags.append(tag)
        return ''.join(out), TAG_COLOUR[min(tags, key='UEMD'.index)]

    # drawing ------------------------------------------------------------
    def line(self, pts, lw=THIN, color=INK, dash=None, z=3):
        (ln,) = self.ax.plot([float(p[0]) for p in pts], [float(p[1]) for p in pts], color=color, lw=lw,
                             zorder=z, solid_capstyle='butt', dash_capstyle='butt', solid_joinstyle='round')
        if dash:
            ln.set_dashes(dash)

    def shape(self, pts, lw=THICK, color=INK, fill=None, dash=None, hatch=None, z=3):
        patch = Polygon([(float(x), float(y)) for x, y in pts], closed=True, facecolor=fill or 'none',
                        edgecolor=color, lw=lw, hatch=hatch, zorder=z, joinstyle='round')
        if dash:
            patch.set_linestyle((0, dash))
        self.ax.add_patch(patch)

    def circle(self, c, r, lw=MID, color=INK, fill=None, dash=None, z=3):
        patch = Circle((float(c[0]), float(c[1])), float(r), facecolor=fill or 'none', edgecolor=color,
                       lw=lw, zorder=z)
        if dash:
            patch.set_linestyle((0, dash))
        self.ax.add_patch(patch)

    def text(self, xy, s, size=NOTE_PT, color=INK, ha='center', va='center', rot=0, weight='normal',
             bg=False, z=7):
        kw = {'bbox': dict(facecolor='white', edgecolor='none', pad=0.4, alpha=0.92)} if bg else {}
        self.ax.text(float(xy[0]), float(xy[1]), s, fontsize=size, color=color, ha=ha, va=va, rotation=rot,
                     fontweight=weight, zorder=z, linespacing=1.3, rotation_mode='anchor' if rot else 'default',
                     **kw)

    def arrowhead(self, tip, back, color=INK, z=6):
        """A filled arrowhead with its point at `tip`, its tail toward the unit vector `back`."""
        bx, by = back
        nx, ny = -by, bx
        w = 0.33 * ARROW
        tx, ty = float(tip[0]), float(tip[1])
        self.ax.add_patch(Polygon([(tx, ty), (tx + bx * ARROW + nx * w, ty + by * ARROW + ny * w),
                                   (tx + bx * ARROW - nx * w, ty + by * ARROW - ny * w)],
                                  closed=True, facecolor=color, edgecolor='none', zorder=z))

    def ext(self, p, q, color=SOFT):
        """Extension line from a feature at p out past the dimension line at q."""
        px, py, qx, qy = float(p[0]), float(p[1]), float(q[0]), float(q[1])
        L = math.hypot(qx - px, qy - py)
        if L < 1e-6:
            return
        ux, uy = (qx - px) / L, (qy - py) / L
        gap = min(0.8, L / 3)
        self.line([(px + ux * gap, py + uy * gap), (qx + ux * 1.5, qy + uy * 1.5)], lw=HAIR, color=color)

    def dim(self, a, b, label, color=INK, side=1, shift=0.0, out=None):
        """Dimension line between paper points a and b with its label beside the middle.

        side=1 writes the label above a horizontal line (left of an upright one), -1 below (right).
        shift slides the label along the line; out=+1/-1 puts it past b/a when it won't fit."""
        ax_, ay, bx_, by = float(a[0]), float(a[1]), float(b[0]), float(b[1])
        L = math.hypot(bx_ - ax_, by - ay)
        ux, uy = (bx_ - ax_) / L, (by - ay) / L
        upright = abs(ux) < 0.5
        tw = text_width(label, DIM_PT)
        if L >= 2 * ARROW + 0.6:
            self.line([(ax_, ay), (bx_, by)], lw=HAIR, color=color)
            self.arrowhead((ax_, ay), (ux, uy), color)
            self.arrowhead((bx_, by), (-ux, -uy), color)
        else:
            k = ARROW + 2.5
            self.line([(ax_ - ux * k, ay - uy * k), (bx_ + ux * k, by + uy * k)], lw=HAIR, color=color)
            self.arrowhead((ax_, ay), (-ux, -uy), color)
            self.arrowhead((bx_, by), (ux, uy), color)
        if out is None and L < tw + 2 * ARROW + 1.5 and not shift:
            out = 1
        mx, my = (ax_ + bx_) / 2 + ux * shift, (ay + by) / 2 + uy * shift
        if out:
            end = (bx_, by) if out > 0 else (ax_, ay)
            reach = tw / 2 + ARROW + 3.0
            mx, my = end[0] + out * ux * reach, end[1] + out * uy * reach
            k = out * (ARROW + 2.5)
            self.line([end, (end[0] + ux * k, end[1] + uy * k)], lw=HAIR, color=color)
        if upright:
            self.text((mx - side * 1.1, my), label, DIM_PT, color, ha='center',
                      va='bottom' if side > 0 else 'top', rot=90, bg=True)
        else:
            self.text((mx, my + side * 1.0), label, DIM_PT, color, ha='center',
                      va='bottom' if side > 0 else 'top', bg=True)

    def leader(self, target, at, text, color=INK, ha='left', va='center', size=NOTE_PT):
        """A note at `at` with a line and arrowhead to `target` (paper points)."""
        self.text(at, text, size, color, ha=ha, va=va, bg=True)
        sx = float(at[0]) + {'left': -0.8, 'right': 0.8, 'center': 0.0}[ha]
        sy = float(at[1])
        tx, ty = float(target[0]), float(target[1])
        if ha == 'center':           # leave from the edge of the text nearest the target
            hw = text_width(text, size) / 2
            hh = (text.count('\n') + 1) * size * PT * 1.3 / 2
            if abs(tx - sx) > hw + 1.0 and abs(ty - sy) < hh + 4.0:
                sx += (hw + 0.8) * (1 if tx > sx else -1)
            else:
                sy += (hh + 0.6) * (1 if ty > sy else -1)
        L = math.hypot(tx - sx, ty - sy)
        if L < 1e-6:
            return
        ux, uy = (tx - sx) / L, (ty - sy) / L
        self.line([(sx, sy), (tx, ty)], lw=HAIR, color=color, z=6)
        self.arrowhead((tx, ty), (-ux, -uy), color)

    def view_title(self, xy, title, sub='', ha='left'):
        self.text(xy, title, 8.2, INK, ha=ha, va='bottom', weight='bold')
        if sub:
            self.text((xy[0], xy[1] - 0.8), sub, 6.4, SOFT, ha=ha, va='top')

    # frame --------------------------------------------------------------
    def frame(self, number, total, title, about, scale):
        x0, y0, x1, y1 = MARGIN, MARGIN, PAGE_W - MARGIN, PAGE_H - MARGIN
        self.shape([(x0, y0), (x1, y0), (x1, y1), (x0, y1)], lw=MID, z=1)
        c1, c2 = 122.0, 213.0
        self.line([(x0, STRIP_TOP), (x1, STRIP_TOP)], lw=MID, z=1)
        self.line([(c1, y0), (c1, STRIP_TOP)], lw=THIN, z=1)
        self.line([(c2, y0), (c2, STRIP_TOP)], lw=THIN, z=1)
        self.text((x0 + 3, STRIP_TOP - 3.0), '%d   %s' % (number, title), 12.5, INK, ha='left', va='top',
                  weight='bold')
        self.text((x0 + 3, STRIP_TOP - 10.5), about, 6.6, SOFT, ha='left', va='top')
        legend = [('The letter after each size says how sure it is:', INK),
                  ('M  measured by Caleb, or from a datasheet          D  a design choice', INK),
                  ('E  estimated: the print should match, but check it against the real part', TAG_COLOUR['E']),
                  ('U  unknown: a placeholder until it is measured in the truck', TAG_COLOUR['U']),
                  ('A size worked out from several others takes the least sure one.', SOFT)]
        for i, (line, colour) in enumerate(legend):
            self.text((c1 + 2.5, STRIP_TOP - 2.6 - i * 3.45), line, 5.9, colour, ha='left', va='top')
        self.text((c2 + 2.5, STRIP_TOP - 2.6), 'Sizes in mm.  A print within about 0.3 mm is fine.',
                  5.9, INK, ha='left', va='top')
        self.text((c2 + 2.5, STRIP_TOP - 6.1), 'Scale %s on US Letter printed at 100 %%' % scale, 5.9, INK,
                  ha='left', va='top')
        bx, by = c2 + 4.0, STRIP_TOP - 13.2
        self.line([(bx, by), (bx + 50, by)], lw=THIN)
        for i in range(6):
            self.line([(bx + 10 * i, by), (bx + 10 * i, by + (1.6 if i % 5 == 0 else 1.0))], lw=THIN)
        self.text((bx + 25, by - 0.8), 'this bar is 50 mm when printed at 100 %', 5.2, SOFT, va='top')
        self.text((x1 - 2.5, y0 + 1.6), 'from fusion/BajaDashCase v%s  ·  sheet %d of %d'
                  % (self.m.mod.VERSION, number, total), 5.2, SOFT, ha='right', va='bottom')


class View:
    """Places a flat view of the model on the sheet: model (u, v) in mm to paper."""

    def __init__(self, sheet, at, ref, scale=1.0, flip_u=False, flip_v=False):
        self.s = sheet
        self.at = (float(at[0]), float(at[1]))
        self.ref = (float(ref[0]), float(ref[1]))
        self.k = scale
        self.fu = -1.0 if flip_u else 1.0
        self.fv = -1.0 if flip_v else 1.0

    def P(self, u, v):
        return (self.at[0] + self.k * self.fu * (float(u) - self.ref[0]),
                self.at[1] + self.k * self.fv * (float(v) - self.ref[1]))

    def X(self, u):
        return self.P(u, self.ref[1])[0]

    def Y(self, v):
        return self.P(self.ref[0], v)[1]

    def shape(self, pts, **kw):
        self.s.shape([self.P(*q) for q in pts], **kw)

    def line(self, pts, **kw):
        self.s.line([self.P(*q) for q in pts], **kw)

    def circle(self, u, v, d, **kw):
        self.s.circle(self.P(u, v), self.k * float(d) / 2, **kw)

    def centre(self, u, v, d, both=True):
        """Centre lines across a hole."""
        x, y = self.P(u, v)
        h = self.k * float(d) / 2 + 1.2
        self.s.line([(x - h, y), (x + h, y)], lw=HAIR, color=SOFT, z=4)
        if both:
            self.s.line([(x, y - h), (x, y + h)], lw=HAIR, color=SOFT, z=4)

    def edge(self, u, v, d, toward):
        """The paper point on a circle's edge facing the paper point `toward`."""
        x, y = self.P(u, v)
        tx, ty = float(toward[0]), float(toward[1])
        L = math.hypot(tx - x, ty - y) or 1.0
        r = self.k * float(d) / 2
        return (x + (tx - x) / L * r, y + (ty - y) / L * r)

    # sizes --------------------------------------------------------------
    def hdim(self, a, b, y, value=None, template='{}', side=1, inch=False, **kw):
        """Horizontal size between model points a and b, its line at paper height y."""
        pa, pb = self.P(*a), self.P(*b)
        self.s.ext(pa, (pa[0], y))
        self.s.ext(pb, (pb[0], y))
        value = abs(b[0] - a[0]) if value is None else value
        label, colour = self.s.fmt(template, value, inch=inch)
        lo, hi = sorted([pa[0], pb[0]])
        self.s.dim((lo, y), (hi, y), label, colour, side=side, **kw)

    def vdim(self, a, b, x, value=None, template='{}', side=1, inch=False, **kw):
        """Upright size between model points a and b, its line at paper x."""
        pa, pb = self.P(*a), self.P(*b)
        self.s.ext(pa, (x, pa[1]))
        self.s.ext(pb, (x, pb[1]))
        value = abs(b[1] - a[1]) if value is None else value
        label, colour = self.s.fmt(template, value, inch=inch)
        lo, hi = sorted([pa[1], pb[1]])
        self.s.dim((x, lo), (x, hi), label, colour, side=side, **kw)

    def ord_x(self, zero, items, y, gap=3.3, below=True, absolute=False):
        """Distances along u from `zero`, written along paper height y.

        items: model points (u, v) where each extension line starts."""
        rows = sorted([(self.X(u), self.Y(v), abs(u - zero) if absolute else self.fu * (u - zero))
                       for u, v in items] + [(self.X(zero), None, None)], key=lambda r: r[0])
        sgn = -1 if below else 1
        xs = spread([r[0] for r in rows], gap)
        for (px, py, value), tx in zip(rows, xs):
            if py is not None:
                self.s.line([(px, py + sgn * 0.8), (px, y)], lw=HAIR, color=FAINT, z=2)
            self.s.line([(px, y), (px, y + sgn * 1.0), (tx, y + sgn * 2.6), (tx, y + sgn * 3.4)],
                        lw=HAIR, color=SOFT)
            label, colour = ('0', INK) if value is None else self.s.fmt('{}', value)
            self.s.text((tx, y + sgn * 3.8), label, DIM_PT, colour, ha='right' if below else 'left',
                        va='center', rot=90)

    def ord_y(self, zero, items, x, gap=3.3, left=True):
        rows = sorted([(self.Y(v), self.X(u), self.fv * (v - zero)) for u, v in items] +
                      [(self.Y(zero), None, None)], key=lambda r: r[0])
        sgn = -1 if left else 1
        ys = spread([r[0] for r in rows], gap)
        for (py, px, value), ty in zip(rows, ys):
            if px is not None:
                self.s.line([(px + sgn * 0.8, py), (x, py)], lw=HAIR, color=FAINT, z=2)
            self.s.line([(x, py), (x + sgn * 1.0, py), (x + sgn * 2.6, ty), (x + sgn * 3.4, ty)],
                        lw=HAIR, color=SOFT)
            label, colour = ('0', INK) if value is None else self.s.fmt('{}', value)
            self.s.text((x + sgn * 3.8, ty), label, DIM_PT, colour, ha='right' if left else 'left', va='center')

    def note(self, target, at, template, *values, ha='left', va='center'):
        """A note at paper point `at` pointing to model point `target`; target may be a paper point
        if given as ('paper', x, y)."""
        text, colour = self.s.fmt(template, *values)
        tgt = target[1:] if target[0] == 'paper' else self.P(*target)
        self.s.leader(tgt, at, text, colour, ha=ha, va=va)

    def label(self, at, template, *values, ha='left', va='center', size=NOTE_PT):
        text, colour = self.s.fmt(template, *values)
        self.s.text(at, text, size, colour, ha=ha, va=va, bg=True)


# ------------------------------------------------------------- the sheets

FRONT_SHEET, LIP_SHEET, BACK_SHEET = 1, 2, 3
PI_SHEET, AMP_SHEET = 5, 6


def lip_box(m):
    """The lip at the back of the panel, behind the silver frame: (Box, prism), or (None, None)."""
    try:
        pr = m.parts['panel'].one('Lip')
    except KeyError:
        return None, None
    return Box(pr.paths()[0]), pr


def lip_corner_lines(p, lip, box):
    """Two lines on how the top lip turns each top corner."""
    if p.LipTop <= 0 or not lip:
        return ['', '']
    name = {'tl': 'top-left', 'tr': 'top-right'}
    rounded = [k for k in ('tl', 'tr') if k in lip.r]
    square = [name[k] for k in ('tl', 'tr') if k not in lip.r]
    if len(rounded) != 1:
        return ['rounded at both top corners.' if rounded else 'square at both top corners.', '']
    k = rounded[0]
    return ['rounded %s corner (R%s, from the same centre as' % (name[k], num(lip.r[k][0])),
            "the front part's R%s) and is square at the %s." % (num(box.r[k][0]), square[0].replace('-', ' '))]


def panel_parts(m):
    pan = m.parts['panel']
    outline = pan.one('Panel').paths()[0]
    return pan, Box(outline), notched_top(outline, pan.one('Cable notch').paths()[0])


def sheet_panel_front(m, number, total):
    p = m.p
    pan, box, outline = panel_parts(m)
    s = Sheet(m, number, total, 'Dash panel: front',
              'Print 1, back face down. This is the face toward you;\nthe screen bolts onto the four posts.', '1:1')
    v = View(s, at=(36, 54), ref=(box.u0, box.v0))
    v.shape(outline, fill=PART)
    lip, lip_pr = lip_box(m)
    if lip:                                   # the wider back part shows past the sides
        v.shape(notched_top(lip_pr.paths()[0], pan.one('Cable notch').paths()[0]), fill=BLIND, lw=MID, z=2)
    posts = [c for pr in pan.get('Screen post') for c in pr.circles()]
    holes = pan.one('Screen screw holes').circles()
    collar = pan.one('Encoder collar hole').circles()[0]
    slots = [Box(path) for path in pan.one('Zip-tie slots').paths()]
    notch = Box(pan.one('Cable notch').paths()[0])
    for x, y, dia in posts:
        v.circle(x, y, dia, lw=THICK, fill=PART, z=4)
    for x, y, dia in holes + [collar]:
        v.circle(x, y, dia, fill='white', z=4)
        v.centre(x, y, dia)
    for sl in slots:
        v.shape(path_points(sl.segs), lw=MID, fill='white', z=4)

    # where things are, from the bottom-left corner
    lower = [c for c in posts if float(c[1]) < float(box.cv)]
    v.ord_x(box.u0, [(collar[0], collar[1] - collar[2] / 2)] +
            [(sl.cu, sl.v0) for sl in slots if float(sl.cv) < float(notch.v0) + 10] +
            [(x, y - dia / 2) for x, y, dia in lower] +
            [(notch.u0, notch.v0), (notch.u1, notch.v0)], y=50)
    left_slots = [sl for sl in slots if float(sl.cu) < float(box.cu)]
    left_posts = [c for c in posts if float(c[0]) < float(box.cu)]
    v.ord_y(box.v0, [(collar[0] - collar[2] / 2, collar[1]), (notch.u0, notch.v0)] +
            [(sl.u0, sl.cv) for sl in left_slots] +
            [(x - dia / 2, y) for x, y, dia in left_posts], x=32)
    v.hdim((box.u0, box.v0), (box.u1, box.v0), 35.0, inch=True)
    v.vdim((box.u0 + box.r['tl'][0], box.v1), (box.u0, box.v0), 15.0, inch=True)
    v.hdim((notch.u0, box.v1), (notch.u1, box.v1), 199.0)
    v.vdim((notch.cu, notch.v0), (notch.cu, box.v1), v.X(notch.cu) + 0.0, side=-1)

    # what things are
    post = sorted(lower, key=lambda c: float(c[0]))[0]
    hole = [h for h in holes if abs(float(h[0]) - float(post[0])) < 1e-6][0]
    spacing = (p.ScreenMountHoleSpacing, p.ScreenMountHoleSpacingV)
    v.note(('paper',) + v.edge(post[0], post[1], post[2], v.P(post[0] + 8, post[1] - 14)),
           v.P(post[0] + 8, post[1] - 14),
           '4 screen posts Ø{}, {} tall,\nØ{} hole through each.\nCentres {} × {} apart (Raspberry Pi pattern)',
           post[2], p.ScreenStandoffHeight, hole[2], spacing[0], spacing[1])
    v.note(('paper',) + v.edge(collar[0], collar[1], collar[2], v.P(collar[0] + 14, collar[1])),
           v.P(collar[0] + 14, collar[1]), 'Knob hole Ø{} for the encoder\'s threaded collar', collar[2])
    right_slot = sorted(slots, key=lambda b: (-float(b.cu), float(b.cv)))[0]
    v.note((right_slot.cu, right_slot.v0), v.P(right_slot.u1 + 6, right_slot.v0 - 12),
           '4 zip-tie slots\n{} × {}, through', right_slot.w, right_slot.h)
    r_br, mid = notch.r['br']
    v.note(mid, v.P(notch.cu, notch.v0 - 9), 'Cable notch, R{} corners', r_br, ha='center')
    for key, at, ha in (('tl', (box.u0 + 16, box.v1 - 16), 'left'), ('tr', (box.u1 - 14, box.v1 - 12), 'right')):
        r, mid = box.r[key]
        v.note(mid, v.P(*at), 'R{}', r, ha=ha)
    if lip:
        v.note((lip.u0 + (box.u0 - lip.u0) / 2, box.cv - 20), v.P(box.u0 + 10, box.cv - 32),
               ('lip at the back, {} out\non the sides%s\n(grey; see sheet %d)'
                % (' and top' if float(lip.v1) > float(box.v1) + 1e-6 else '', LIP_SHEET)), box.u0 - lip.u0)
    s.view_title((36, 205.5), 'FRONT', '(from the driver\'s seat)')

    # side view from the passenger side: Z to the left
    face = pan.one('Panel').hi
    sv = View(s, at=(240, 54), ref=(0, box.v0), flip_u=True)
    if lip and float(lip.v1) > float(box.v1) + 1e-6:      # the top lip steps up at the back
        lip_t = lip_pr.hi
        sv.shape([(0, box.v0), (face, box.v0), (face, box.v1), (lip_t, box.v1), (lip_t, lip.v1), (0, lip.v1)],
                 fill=PART)
        sv.note((lip_t / 2, lip.v1), (246, sv.Y(lip.v1) + 8), 'top lip, {} up', lip.v1 - box.v1)
    else:
        sv.shape([(0, box.v0), (face, box.v0), (face, box.v1), (0, box.v1)], fill=PART)
    tops = {}
    for pr in pan.get('Screen post'):
        x, y, dia = pr.circles()[0]
        tops[float(y)] = (y, dia, pr.hi)
    for y, dia, top in tops.values():
        sv.shape([(face, y - dia / 2), (top, y - dia / 2), (top, y + dia / 2), (face, y + dia / 2)], fill=PART)
    cb = pan.get('Screw counterbore')[0]
    cb_d = cb.circles()[0][2]
    for y, dia, top in tops.values():
        for dy in (-hole[2] / 2, hole[2] / 2):
            sv.line([(cb.hi, y + dy), (top, y + dy)], lw=THIN, color=SOFT, dash=HIDDEN)
        sv.shape([(0, y - cb_d / 2), (cb.hi, y - cb_d / 2), (cb.hi, y + cb_d / 2), (0, y + cb_d / 2)],
                 lw=THIN, color=SOFT, dash=HIDDEN)
        sv.line([(top + 1.2, y), (-1.2, y)], lw=HAIR, color=SOFT, dash=CENTRE)
    sv.line([(0, notch.v0), (face, notch.v0)], lw=THIN, color=SOFT, dash=HIDDEN)
    top_post = max(tops.values(), key=lambda t: float(t[0]))
    sv.hdim((0, box.v0), (face, box.v0), 46.0)
    sv.hdim((face, top_post[0] - top_post[1] / 2), (top_post[2], top_post[0] - top_post[1] / 2), 46.0, out=-1)
    sv.hdim((0, box.v0), (top_post[2], top_post[0] - top_post[1] / 2), 39.0)
    # The two labels share one column: keep them in the order of what they
    # point at, and push the upper one clear of the lower.
    label_y = {'notch': sv.Y(notch.v0) + 9, 'cb': sv.Y(top_post[0]) + 14}
    lower, upper = sorted(label_y, key=lambda k: float(notch.v0) if k == 'notch' else float(top_post[0]))
    label_y[upper] = max(label_y[upper], label_y[lower] + 14.0)
    sv.note((face / 2, notch.v0), (246, label_y['notch']), 'bottom of\nthe notch')
    sv.note((cb.hi / 2, top_post[0] + cb_d / 2), (246, label_y['cb']),
            'counterbores\n(see sheet %d)' % BACK_SHEET)
    s.view_title((sv.X(face / 2), 205.5), 'SIDE', '(from the\npassenger side)', ha='center')
    return s


def sheet_panel_lip(m, number, total):
    """Looking down on the panel's top edge, and a close-up of the step the silver frame sits on."""
    p = m.p
    pan, box, outline = panel_parts(m)
    lip, lip_pr = lip_box(m)
    face = pan.one('Panel').hi
    lip_t = lip_pr.hi if lip else 0.0
    l0, l1 = (lip.u0, lip.u1) if lip else (box.u0, box.u1)
    s = Sheet(m, number, total, 'Dash panel: top and the lip',
              "The front %s mm fits inside the silver frame's opening. Behind it the panel is wider,\n"
              'so the frame holds it in, like the factory radio and climate control.' % num(p.FrameEdgeDepth),
              '1:1, detail 4:1')
    stepped = [(l0, 0), (l1, 0), (l1, lip_t), (box.u1, lip_t), (box.u1, face), (box.u0, face),
               (box.u0, lip_t), (l0, lip_t)]
    posts = {}
    for pr in pan.get('Screen post'):
        x, y, dia = pr.circles()[0]
        posts[round(float(x), 3)] = (x, dia, pr.hi)
    notch = Box(pan.one('Cable notch').paths()[0])

    # top view: back of the panel at the top, the front toward the bottom
    v = View(s, at=(40, 188), ref=(l0, 0), flip_v=True)
    v.shape(stepped, fill=PART)
    for x, dia, top in posts.values():
        v.shape([(x - dia / 2, face), (x + dia / 2, face), (x + dia / 2, top), (x - dia / 2, top)], fill=PART)
    for u in (notch.u0, notch.u1):
        v.line([(u, 0), (u, face)], lw=THIN, color=SOFT, dash=HIDDEN)
    v.label(v.P(notch.cu, face / 2), 'cable notch', ha='center', size=6.0)
    for side in (-1, 1):
        edge = box.u0 if side < 0 else box.u1
        v.shape([(edge, lip_t), (edge + side * 10, lip_t), (edge + side * 10, face), (edge, face)],
                lw=THIN, color=GHOST, dash=(5, 2.5), hatch='////', z=2)
    v.hdim((l0, 0), (l1, 0), v.Y(0) + 9, inch=False)
    v.hdim((box.u0, face), (box.u1, face), v.Y(max(t for _, _, t in posts.values())) - 7, inch=True, side=-1)
    v.vdim((l1, 0), (l1, face), v.X(l1) + 16)
    v.vdim((box.u1, lip_t), (box.u1, face), v.X(l1) + 7, side=-1)
    v.label(v.P(l0, -2.5), 'back (inside the dash)', ha='left', va='bottom', size=6.0)
    v.label(v.P(l0 - 1, face + 1), 'front, toward you', ha='right', va='top', size=6.0)
    v.note((box.u0 - 5, (lip_t + face) / 2), v.P(box.u0 + 22, face + 9), 'silver frame (dashed blue)', ha='left')
    s.view_title((40, 205.5), 'TOP', '(looking down on the top edge)')

    # detail of the left edge, 4 times size
    k = 4.0
    d = View(s, at=(64, 136), ref=(l0, 0), scale=k, flip_v=True)
    reach = 16.0
    d.shape([(l0, 0), (box.u0 + reach, 0), (box.u0 + reach, face), (box.u0, face), (box.u0, lip_t), (l0, lip_t)],
            fill=PART)
    d.line([(box.u0 + reach, -1), (box.u0 + reach, face + 1)], lw=THIN, color=SOFT, dash=(2, 2), z=5)
    d.shape([(box.u0, lip_t), (box.u0 - 9, lip_t), (box.u0 - 9, face), (box.u0, face)],
            lw=THIN, color=GHOST, dash=(5, 2.5), hatch='////', z=2)
    d.label(d.P(box.u0 - 4.5, (lip_t + face) / 2 + 3), 'silver frame\nedge', ha='center', size=6.0)
    if lip:
        d.hdim((l0, 0), (box.u0, 0), d.Y(0) + 8)
    d.vdim((l0, 0), (l0, lip_t), d.X(box.u0 - 9) - 6, out=-1)
    d.vdim((l0, 0), (box.u0, face), d.X(box.u0 - 9) - 15)
    d.vdim((box.u0 + reach, lip_t), (box.u0 + reach, face), d.X(box.u0 + reach) + 7, side=-1)
    d.label(d.P(l0 + (box.u0 - l0) / 2, lip_t / 2), 'lip', ha='center', size=6.0)
    d.label(d.P(box.u0 + reach / 2, (lip_t + face) / 2), 'front part', ha='center', size=6.0)
    s.view_title((d.X(box.u0 - 9) - 15, 155), 'DETAIL: LEFT EDGE', '(4 times size; the right edge%s the same)' % (' and the top are' if p.LipTop > 0 else ' is'))

    # what changed
    lines = ['What changed',
             '',
             'The back %s mm of the panel reaches %s mm past the front part' % (num(lip_t), num(p.LipSide)),
             'on the left, the right%s:' % (' and the top' if p.LipTop > 0 else ''),
             '%s × %s mm instead of %s × %s mm.' % (
                 num(l1 - l0), num(lip.v1 - lip.v0 if lip else box.h), num(box.u1 - box.u0), num(box.h)),
             '',
             'The front %s mm is still exactly the opening\'s size,' % num(p.FrameEdgeDepth),
             "so it slides into the silver frame's %s mm-thick edge," % num(p.FrameEdgeDepth),
             'and the frame overlaps the lip behind it.',
             '',
             ('The top edge has the same %s mm lip: it follows the' % num(p.LipTop)
              if p.LipTop > 0 else 'The top edge has no lip (LipTop = 0).'),
             *lip_corner_lines(p, lip, box),
             'The bottom edge has none (the climate control is there).',
             'The panel prints back face down, so the lip sits flat on the bed.']
    for i, line in enumerate(lines):
        s.text((160, 136 - i * 4.6), line, 6.8 if i else 8.2, INK, ha='left', va='top',
               weight='bold' if i == 0 else 'normal')
    return s


def adapter_footprints(m):
    """Where each adapter plate's base sits on the panel's back: (x0, x1, y0, y1)."""
    out = []
    for key, part in m.parts.items():
        if key.startswith('adapter'):
            pr = part.one('Adapter')
            base = [pt for seg in pr.paths()[0] for pt in seg_points(seg) if abs(float(pt[1])) < 1e-9]
            xs = sorted((pt[0] for pt in base), key=float)
            out.append((xs[0], xs[-1], pr.lo, pr.hi))
    return out


def sheet_panel_back(m, number, total):
    pan, box, outline = panel_parts(m)
    s = Sheet(m, number, total, 'Dash panel: back',
              'The face that goes into the dash, seen from behind: a mirror image\nof sheet %d. '
              'Press the heat-set inserts into the 12 holes.' % FRONT_SHEET, '1:1')
    v = View(s, at=(36, 54), ref=(box.u1, box.v0), flip_u=True)
    lip, lip_pr = lip_box(m)
    if lip:
        v.shape(notched_top(lip_pr.paths()[0], pan.one('Cable notch').paths()[0]), fill=PART)
        v.shape(outline, lw=THIN, color=SOFT, dash=HIDDEN, z=3.2)
    else:
        v.shape(outline, fill=PART)
    pocket = Box(pan.one('Encoder pocket').paths()[0])
    pocket_pr = pan.one('Encoder pocket')
    collar = pan.one('Encoder collar hole').circles()[0]
    inserts = pan.one('Heat-set insert holes').circles()
    insert_pr = pan.one('Heat-set insert holes')
    cbs = [pr.circles()[0] for pr in pan.get('Screw counterbore')]
    cb_pr = pan.get('Screw counterbore')[0]
    holes = pan.one('Screen screw holes').circles()
    slots = [Box(path) for path in pan.one('Zip-tie slots').paths()]

    # where the Pi case and the adapter plates sit
    case = m.parts['pi case']
    for path in case.one('Floor').paths() + case.one('Ears').paths() + case.one('Amp posts').paths():
        v.shape(path_points(path), lw=THIN, color=GHOST, dash=(5, 2.5), z=3.5)
    feet = adapter_footprints(m)
    for x0, x1, y0, y1 in feet:
        v.shape([(x0, y0), (x1, y0), (x1, y1), (x0, y1)], lw=THIN, color=GHOST, dash=(5, 2.5), z=3.5)

    v.shape(path_points(pocket.segs), lw=MID, fill=BLIND, z=4)
    v.circle(collar[0], collar[1], collar[2], fill='white', z=5)
    v.centre(collar[0], collar[1], pocket.w)
    for x, y, dia in inserts:
        v.circle(x, y, dia, fill=BLIND, z=4)
        v.centre(x, y, dia)
    for x, y, dia in cbs:
        v.circle(x, y, dia, fill=BLIND, z=4)
        v.centre(x, y, dia)
    for x, y, dia in holes:
        v.circle(x, y, dia, fill='white', lw=THIN, z=5)
    for sl in slots:
        v.shape(path_points(sl.segs), lw=MID, fill='white', z=4)

    # where things are, from this view's bottom-left corner
    lowest = {}
    for x, y, dia in inserts + cbs:
        if float(x) not in lowest or float(y) < float(lowest[float(x)][1]):
            lowest[float(x)] = (x, y - dia / 2)
    v.ord_x(box.u1, list(lowest.values()) + [(pocket.cu, pocket.v0)], y=50)
    nearest = {}
    for x, y, dia in inserts + cbs:
        key = round(float(y), 3)
        if key not in nearest or float(x) > float(nearest[key][0]):
            nearest[key] = (x + dia / 2, y)
    v.ord_y(box.v0, list(nearest.values()) + [(pocket.u1, pocket.cv)], x=32)
    v.hdim((box.u1, box.v0), (box.u0, box.v0), 35.0, inch=True)
    v.vdim((box.u0 + box.r['tl'][0], box.v1), (box.u1, box.v0), 15.0, inch=True)

    # what things are
    adapter_hole = max((c for c in inserts if float(c[0]) > float(box.cu)), key=lambda c: float(c[1]))
    v.note(('paper',) + v.edge(adapter_hole[0], adapter_hole[1], adapter_hole[2],
                               v.P(adapter_hole[0] - 22, adapter_hole[1] + 3)),
           v.P(adapter_hole[0] - 22, adapter_hole[1] + 3),
           '12 holes Ø{}, {} deep, for M3 heat-set inserts:\n8 for the adapter plates, 4 for the Pi case',
           adapter_hole[2], insert_pr.hi)
    tab_xs = [float(h[0]) for h in case.one('Panel screw holes').circles()]
    pi_hole = max((c for c in inserts if any(abs(float(c[0]) - x) < 1e-6 for x in tab_xs)),
                  key=lambda c: (float(c[1]), float(c[0])))
    v.note(('paper',) + v.edge(pi_hole[0], pi_hole[1], pi_hole[2], v.P(pi_hole[0] + 6, pi_hole[1] + 14)),
           v.P(pi_hole[0] + 6, pi_hole[1] + 14), 'insert hole\n(Pi case)', ha='right')
    cb = max(cbs, key=lambda c: (float(c[1]), float(c[0])))
    notch = Box(pan.one('Cable notch').paths()[0])
    at = (v.X(notch.cu), v.Y(notch.v0) - 9)
    v.note(('paper',) + v.edge(cb[0], cb[1], cb[2], at), at,
           '4 counterbores Ø{}, {} deep,\nØ{} through (screen screws)', cb[2], cb_pr.hi, holes[0][2], ha='center')
    at = (v.X(pocket.u1) - 5, v.Y(pocket.cv) + 1)
    v.note(('paper',) + v.P(pocket.u1, pocket.cv + 1), at,
           'Encoder pocket {} × {}, {} deep\n(leaves {} in front), Ø{} hole through', pocket.w, pocket.h,
           pocket_pr.hi, pan.one('Panel').hi - pocket_pr.hi, collar[2], ha='right')
    x0, x1, y0, y1 = feet[0]
    v.label(v.P((x0 + x1) / 2, y1 + 3), 'adapter plate', ha='center', va='bottom', size=6.0)
    floor = Box(case.one('Floor').paths()[0])
    v.label(v.P(floor.cu, floor.v0 + 3), 'Pi case', ha='center', va='bottom', size=6.0)
    s.text((36, 205.5), 'BACK', 8.2, INK, ha='left', va='bottom', weight='bold')
    s.text((36, 204.7), '(from behind, inside the dash)', 6.4, SOFT, ha='left', va='top')
    s.text((36, 200.6), 'White: through.  Grey: blind, as deep as given.  Dashed blue: where the Pi case '
           'and the adapter plates sit.', 6.4, SOFT, ha='left', va='top')

    # section through the knob: Z to the right, front face on the right
    face = pan.one('Panel').hi
    a_x = v.X(collar[0])
    for y in (box.v0 - 4, box.v1 + 4):
        s.line([(a_x, v.Y(y) - 2.5 if y > box.v1 else v.Y(y) + 2.5), (a_x, v.Y(y))], lw=MID, color=INK)
    s.line([(a_x, v.Y(box.v0) - 2), (a_x, v.Y(box.v1) + 2)], lw=HAIR, color=SOFT, dash=CENTRE, z=6)
    for y, va in ((box.v0, 'top'), (box.v1, 'bottom')):
        yy = v.Y(y) + (-4.5 if va == 'top' else 4.5)
        s.line([(a_x, yy), (a_x - 5, yy)], lw=MID)
        s.arrowhead((a_x - 5, yy), (1, 0))
        s.text((a_x + 1.5, yy), 'A', 8, INK, ha='left', va='center', weight='bold')
    sv = View(s, at=(226, 54), ref=(0, box.v0))
    wall = face - pocket_pr.hi
    lower = [(0, box.v0), (face, box.v0), (face, collar[1] - collar[2] / 2), (pocket_pr.hi, collar[1] - collar[2] / 2),
             (pocket_pr.hi, pocket.v0), (0, pocket.v0)]
    upper = [(0, pocket.v1), (pocket_pr.hi, pocket.v1), (pocket_pr.hi, collar[1] + collar[2] / 2),
             (face, collar[1] + collar[2] / 2), (face, box.v1), (0, box.v1)]
    for pts in (lower, upper):
        sv.shape(pts, fill=PART, hatch='////', lw=MID, color=SOFT, z=3)
        sv.shape(pts, lw=THICK, z=4)
    sv.line([(-1.5, collar[1]), (face + 1.5, collar[1])], lw=HAIR, color=SOFT, dash=CENTRE)
    sv.hdim((0, pocket.v0), (pocket_pr.hi, pocket.v0), 46.0, out=-1)
    sv.hdim((pocket_pr.hi, pocket.v0), (face, pocket.v0), 46.0, value=wall, out=1)
    sv.hdim((0, box.v0), (face, box.v0), 39.0)
    sv.vdim((0, pocket.v0), (0, pocket.v1), sv.X(0) - 5)
    sv.vdim((face, collar[1] - collar[2] / 2), (face, collar[1] + collar[2] / 2), sv.X(face) + 5,
            template='Ø{}', side=-1)
    s.view_title((sv.X(face / 2), 205.5), 'SECTION A–A', '(through the knob;\nfront face on the right)', ha='center')
    return s


def sheet_adapter(m, number, total):
    part = m.parts['adapter upper left']
    pr = part.one('Adapter')
    # build_adapter() draws the Z shape as ten corners, (in from the panel edge, Z):
    # base end, web at the panel, step front (web), step front (outside), wall back (outside),
    # wall back (inside), step back (wall), step back (web), base underside (web), base underside (end)
    V = [seg[1] for seg in pr.paths()[0]]
    base_end, web, _, wall_front, wall_back, wall_back_in, _, step_back, _, _ = V
    pts = path_points(pr.paths()[0])
    t = wall_back_in[0] - wall_back[0]
    y_lo, y_hi = pr.lo, pr.hi
    k = 2.0
    s = Sheet(m, number, total, 'Adapter plate',
              'Print 4, each standing on its Z-shaped end. The same part fits both sides:\n'
              'turn it upside down for the right side.', '2:1')

    # end view: the Z shape, in from the panel edge to the right, depth downward
    ev = View(s, at=(146, 190), ref=(wall_front[0], 0), scale=k)
    ev.shape(pts, fill=PART)
    ev.hdim(wall_front, web, 195.5, value=web[0] - wall_front[0])
    ev.hdim(web, base_end, 195.5)
    ev.hdim(wall_front, base_end, 202.0, value=base_end[0] - wall_front[0])
    right = ev.X(base_end[0]) + 6
    ev.vdim(base_end, step_back, right, value=web[1] - step_back[1], side=-1)
    ev.vdim(step_back, wall_back_in, right, value=step_back[1] - wall_back[1], side=-1)
    ev.vdim(base_end, wall_back_in, right + 8, value=web[1] - wall_back[1], side=-1)
    under = (web[0] + t + base_end[0]) / 2
    ev.note((under, -t), (ev.X(under), ev.Y(-t) - 11), 'base: screws\nto the panel', ha='center')
    mid = (wall_front[1] + wall_back[1]) / 2
    ev.note((wall_back_in[0], mid), (ev.X(wall_back_in[0]) + 4, ev.Y(mid)),
            'side wall:\nbolts to the\nfactory\nbracket')
    ev.label((ev.X(wall_back_in[0]) + 4, ev.Y(wall_back[1]) + 8), 'every wall\n{} thick', t)
    s.view_title((ev.X((wall_front[0] + base_end[0]) / 2), ev.Y(wall_back[1]) - 4), 'END VIEW',
                 '(the Z shape;\npanel face at the top)', ha='center')
    s.text((ev.X(base_end[0]) - 1, ev.Y(0) + 1.0), 'panel side', 6.0, SOFT, ha='right', va='bottom')

    # the slotted side wall, seen from outside: height across, depth downward (lines up with the end view)
    sv = View(s, at=(28, 190), ref=(y_lo, 0), scale=k)
    sv.shape([(y_lo, web[1]), (y_hi, web[1]), (y_hi, wall_back[1]), (y_lo, wall_back[1])], fill=PART)
    sv.line([(y_lo, wall_front[1]), (y_hi, wall_front[1])], lw=MID)
    slots = []
    for sp in part.get('Bracket slot'):
        path = sp.paths()[0]
        sv.shape(path_points(path), lw=MID, fill='white', z=4)
        # slot() is a stadium: a side line from end centre to end centre, then the round end
        side, cap = path[0], path[1]
        ends = sorted((side[1][1], side[2][1]), key=float)
        slots.append((cap[2][0], ends[1], ends[0], cap[3][0] - cap[1][0]))   # y, near Z, far Z, width
    slots.sort(key=lambda sl: float(sl[0]))
    yc, z_near, z_far, width = slots[0]
    for y, _, _, _ in slots:
        sv.line([(y, z_near + 4.5), (y, z_far - 4.5)], lw=HAIR, color=SOFT, dash=CENTRE)
    for z in (z_near, z_far):
        sv.line([(slots[0][0] - 5, z), (slots[-1][0] + 5, z)], lw=HAIR, color=SOFT, dash=CENTRE)
    sv.hdim((y_lo, wall_back[1]), (yc, z_far), 63.0, value=yc - y_lo, side=-1)
    sv.hdim((yc, z_far), (slots[1][0], z_far), 63.0, side=-1)
    sv.hdim((y_lo, wall_back[1]), (y_hi, wall_back[1]), 55.0, side=-1)
    left = sv.X(y_lo) - 6
    sv.vdim((y_lo, web[1]), (yc - 4, z_near), left, value=web[1] - z_near)
    sv.vdim((yc - 4, z_near), (yc - 4, z_far), left, value=z_near - z_far)
    sv.vdim((y_lo, web[1]), (y_lo, wall_front[1]), left - 8, value=web[1] - wall_front[1])
    sv.note((slots[-1][0] + width / 2, (z_near + z_far) / 2), (sv.X(y_hi) - 3, sv.Y(z_near) + 9),
            '2 slots {} wide\n(M5 clearance),\n{} of travel', width, z_near - z_far)
    s.view_title((sv.X((y_lo + y_hi) / 2), 199.0), 'SIDE WALL', '(seen from outside; the slots line up with the '
                 'factory bracket\'s screw holes)', ha='center')

    # the base, seen from the panel side: in from the panel edge across, height up
    bv = View(s, at=(213, 62), ref=(wall_front[0], y_lo), scale=k)
    bv.shape([(wall_front[0], y_lo), (base_end[0], y_lo), (base_end[0], y_hi), (wall_front[0], y_hi)], fill=PART)
    bv.line([(web[0], y_lo), (web[0], y_hi)], lw=MID)
    holes = sorted(part.one('Panel screw holes').circles(), key=lambda c: float(c[1]))
    for x, y, dia in holes:
        bv.circle(x, y, dia, fill='white', z=4)
        bv.centre(x, y, dia)
    top_hole, low_hole = holes[-1], holes[0]
    bv.hdim((web[0], y_hi), top_hole[:2], bv.Y(y_hi) + 6, value=top_hole[0] - web[0])
    bv.vdim((base_end[0], y_lo), low_hole[:2], bv.X(base_end[0]) + 5, value=low_hole[1] - y_lo, side=-1)
    bv.vdim(low_hole[:2], top_hole[:2], bv.X(base_end[0]) + 5, side=-1)
    bv.vdim((base_end[0], y_lo), (base_end[0], y_hi), bv.X(base_end[0]) + 13, value=y_hi - y_lo, side=-1)
    at = bv.P(low_hole[0] - 6, low_hole[1] - 14)
    bv.note(('paper',) + bv.edge(low_hole[0], low_hole[1], low_hole[2], at), at,
            '2 holes Ø{}\n(M3 × 8 screws)', low_hole[2], ha='center')
    s.view_title((bv.X((wall_front[0] + base_end[0]) / 2), bv.Y(y_hi) + 13), 'BASE', '(from the panel side)',
                 ha='center')
    return s

def cut_into_top(path, top):
    """The run of a closed outline that lies below the wall top `top` (z), from its u1 side to its u0 side,
    closed off at the top: an opening notched into the top of a wall."""
    pts = path_points(path)
    inside = [float(q[1]) > float(top) + 1e-9 for q in pts]
    n = len(pts)
    start = [i for i in range(n) if inside[i] and not inside[i - 1]][0]
    run = []
    i = start
    while inside[i % n]:
        run.append(pts[i % n])
        i += 1
    return [(run[0][0], top)] + run + [(run[-1][0], top)]


def wall_elevation(sheet, view, u_lo, u_hi, top, notches, windows, ears, zero_u, ord_y, title, sub,
                   heights=True):
    """One wall of the Pi case seen from outside, floor down: its outline, openings and their sizes."""
    pts = [(u_lo, 0), (u_hi, 0), (u_hi, top)]
    for run in sorted((cut_into_top(path, top) for path in notches), key=lambda r: -float(r[0][0])):
        pts += run
    pts.append((u_lo, top))
    for e0, e1, eh in ears:                      # the side tab, standing out toward you at the bottom
        view.shape([(e0, 0), (e1, 0), (e1, eh), (e0, eh)], lw=THIN, fill=PART, z=2)
    view.shape(pts, fill=PART)
    for e0, e1, eh in ears:
        view.line([(e0, eh), (e1, eh)], lw=THIN, z=4)
    items = []
    for path in windows:
        view.shape(path_points(path), lw=MID, fill='white', z=4)
    for path in notches + windows:
        b = Box(path)
        items += [(b.u0, b.v1), (b.u1, b.v1)]
    far = u_hi if abs(float(u_lo) - float(zero_u)) < 1e-9 else u_lo
    view.ord_x(zero_u, items + [(far, 0)], y=ord_y, absolute=True)
    x_right = max(view.X(u_lo), view.X(u_hi))
    ref = max((u_lo, u_hi), key=lambda u: view.X(u))
    if heights:
        bottoms = {round(float(Box(q).v1), 6): Box(q).v1 for q in notches + windows}
        tops = {round(float(Box(q).v0), 6): Box(q).v0 for q in windows}
        for h in bottoms.values():
            view.vdim((ref, 0), (ref, h), x_right + 5, value=0 - h, side=-1)
        for h in tops.values():
            view.vdim((ref, 0), (ref, h), x_right + 11.5, value=0 - h, side=-1)
        view.vdim((ref, 0), (ref, top), x_right + (18 if tops else 11.5), value=0 - top, side=-1)
    x_left = min(view.X(u_lo), view.X(u_hi))
    sheet.text((x_left, view.Y(top) + 3.4), title, 8.2, INK, ha='left', va='bottom', weight='bold')
    sheet.text((x_left + 5, view.Y(top) + 3.4), sub, 6.4, SOFT, ha='left', va='bottom')


def sheet_pi_case(m, number, total):
    p = m.p
    case = m.parts['pi case']
    ears = sorted((Box(path) for path in case.one('Ears').paths()), key=lambda b: float(b.cu))
    outer, inner = sorted((Box(path) for path in case.one('Walls').paths()), key=lambda b: -float(b.w))
    top = case.one('Walls').lo                       # the open side (Z); the floor's outside is at Z = 0
    floor_in = case.one('Inside').hi                 # the floor's inside face
    stand_pr = case.one('Standoffs')
    stands = stand_pr.circles()
    ins_pr = case.one('Insert holes')
    ins_d = ins_pr.circles()[0][2]
    ear_holes = case.one('Panel screw holes').circles()
    vent = Box(case.one('Vent').paths()[0])

    def in_vent(c):
        x, y, dd = [float(q) for q in c]
        return (float(vent.u0) <= x - dd / 2 and x + dd / 2 <= float(vent.u1) and
                float(vent.v0) <= y - dd / 2 and y + dd / 2 <= float(vent.v1))
    reach = case.one('Screen screw access').circles()
    access = [c for c in reach if not in_vent(c)]    # one falls inside the vent and leaves no edge
    usb = case.one('USB and Ethernet').paths()
    hdmi = case.one('Power and HDMI').paths()
    pcie = case.one('PCIe and power button').paths()
    amp_posts = case.one('Amp posts')
    amp_ins = case.one('Amp post inserts')
    s = Sheet(m, number, total, 'Pi case',
              'Print 1, floor down, open side up. It screws to the panel through its two side tabs. The Pi\n'
              'sits on the four short posts inside; the four tall posts outside hold the amp plate.', '1:1')

    # inside, looking into the open side as it sits on the bed (seen from behind the dash)
    v = View(s, at=(42, 112), ref=(outer.u1, outer.v0), flip_u=True)
    for path in amp_posts.paths():
        v.shape(path_points(path), fill=PART, z=2.5)
    for x, y, dd in amp_ins.circles():
        v.circle(x, y, dd, fill=BLIND, z=5)
        v.centre(x, y, dd)
    top_post = max((Box(q) for q in amp_posts.paths()), key=lambda b: (float(b.v1), -float(b.u0)))
    v.label((v.X(top_post.cu), v.Y(top_post.v1) + 1.5), 'amp posts', ha='center', va='bottom', size=5.8)
    for e in ears:
        v.shape(path_points(e.segs), fill=PART, z=2)
    v.shape(path_points(outer.segs), fill=PART, z=3)
    v.shape(path_points(inner.segs), lw=MID, fill=PART, z=4)
    v.shape(path_points(vent.segs), lw=MID, fill='white', z=5)
    for x, y, dd in access + ear_holes:
        v.circle(x, y, dd, fill='white', z=5)
        v.centre(x, y, dd)
    for x, y, dd in stands:
        v.circle(x, y, dd, lw=THICK, fill=PART, z=5)
        v.circle(x, y, ins_d, fill=BLIND, z=6)
        v.centre(x, y, dd)
    for path in usb:                                 # the openings break the top of the wall
        for u in (Box(path).u0, Box(path).u1):
            v.line([(inner.u1, u), (outer.u1, u)], lw=MID, z=5)
    for path in hdmi:
        for u in (Box(path).u0, Box(path).u1):
            v.line([(u, inner.v1), (u, outer.v1)], lw=MID, z=5)
    bw, bh = m.mod.PI_W, m.mod.PI_H
    v.shape([(p.PiX, p.PiY), (p.PiX + bw, p.PiY), (p.PiX + bw, p.PiY + bh), (p.PiX, p.PiY + bh)],
            lw=THIN, color=GHOST, dash=(5, 2.5), z=6)
    v.label((v.X(p.PiX + bw) + 1.2, v.Y(p.PiY + bh) - 1.2), 'Pi board', ha='left', va='top', size=5.8)
    s.text((v.X(outer.cu), v.Y(outer.v1) + 1.2), 'C: power + HDMI wall', 6.0, SOFT, va='bottom')
    s.text((v.X(inner.u1) + 2.4, v.Y(inner.cv)), 'B: USB + Ethernet', 5.8, SOFT, rot=90, va='center')
    s.text((v.X(inner.u0) - 2.4, v.Y(inner.cv)), 'D: PCIe + button', 5.8, SOFT, rot=90, va='center')

    # where things are, from the outside of the USB wall and of the plain wall
    low = sorted((c for c in stands if float(c[1]) < float(inner.cv)), key=lambda c: -float(c[0]))
    v.ord_x(outer.u1, [(inner.u1, inner.v0)] + [(x, y - dd / 2) for x, y, dd in access + low] +
            [(vent.u0, vent.v0), (vent.u1, vent.v0), (outer.u0, outer.v0)], y=100)
    near = [c for c in stands if abs(float(c[0]) - float(low[0][0])) < 1e-6]
    usb_ear = ears[-1]
    v.ord_y(outer.v0, [(x + dd / 2, y) for x, y, dd in near] + [(vent.u1, vent.v0), (vent.u1, vent.v1)] +
            [(x + dd / 2, y) for x, y, dd in access] +
            [(usb_ear.u1, usb_ear.v0), (usb_ear.u1, usb_ear.v1), (outer.u1, outer.v1)], x=26)
    v.hdim((ears[-1].u1, ears[-1].cv), (ears[0].u0, ears[0].cv), 198.5, value=ears[-1].u1 - ears[0].u0)
    hx = sorted(ear_holes, key=lambda c: (float(c[1]), float(c[0])))
    v.hdim((hx[-1][0], hx[-1][1]), (hx[-2][0], hx[-2][1]), 192.0, value=abs(hx[-1][0] - hx[-2][0]))

    # notes, written in the vent
    v.label((v.X(vent.cu), v.Y(vent.v1) - 2.5), 'vent {} × {}, R{} corners', vent.w, vent.h, vent.r['tr'][0],
            ha='center', va='top', size=6.2)
    if access:
        acc = access[0]
        at = (v.X(vent.cu), v.Y(vent.cv) + 5)
        v.note(('paper',) + v.edge(acc[0], acc[1], acc[2], at), at,
               'Ø{} hole to reach a screen screw;\nthe other one is reached\nthrough the vent', acc[2],
               ha='center')
    st = low[0]
    at = (v.X(vent.cu), v.Y(vent.v0) + 7)
    v.note(('paper',) + v.edge(st[0], st[1], st[2], at), at,
           '4 posts Ø{}, {} tall,\nØ{} holes {} deep\nfor M2.5 inserts', st[2], floor_in - stand_pr.lo, ins_d,
           ins_pr.hi - stand_pr.lo, ha='center')
    s.text((8, 205.5), 'INSIDE', 8.2, INK, ha='left', va='bottom', weight='bold')
    s.text((8, 204.7), '(looking into the open side;\nthe floor is underneath)', 6.4, SOFT, ha='left', va='top')

    # section through the lower posts, floor down, lined up with the view above
    y_cut = low[0][1]
    ax_ = v.X(ears[0].u0) + 2
    s.line([(ax_, v.Y(y_cut)), (ax_ + 6, v.Y(y_cut))], lw=HAIR, color=SOFT, dash=CENTRE)
    s.line([(ax_ + 6, v.Y(y_cut)), (ax_ + 6, v.Y(y_cut) + 4)], lw=MID)
    s.arrowhead((ax_ + 6, v.Y(y_cut) + 4), (0, -1))
    s.text((ax_ + 7.2, v.Y(y_cut) + 2), 'A', 8, INK, ha='left', weight='bold')
    sv = View(s, at=(42, 50), ref=(outer.u1, 0), flip_u=True, flip_v=True)
    wall_top = {}
    for side, paths in (('usb', usb), ('pcie', pcie)):
        h = top
        for path in paths:
            b = Box(path)
            if float(b.u0) < float(y_cut) < float(b.u1) and float(b.v0) <= float(top):
                h = b.v1                             # cut through an opening that reaches the top
        wall_top[side] = h
    lo_x, hi_x = ears[0].u0, ears[-1].u1
    sec = [(lo_x, 0), (hi_x, 0), (hi_x, floor_in), (outer.u1, floor_in), (outer.u1, wall_top['usb']),
           (inner.u1, wall_top['usb']), (inner.u1, floor_in)]
    for x, y, dd in low:
        r, ri = dd / 2, ins_d / 2
        sec += [(x + r, floor_in), (x + r, stand_pr.lo), (x + ri, stand_pr.lo), (x + ri, ins_pr.hi),
                (x - ri, ins_pr.hi), (x - ri, stand_pr.lo), (x - r, stand_pr.lo), (x - r, floor_in)]
    sec += [(inner.u0, floor_in), (inner.u0, wall_top['pcie']), (outer.u0, wall_top['pcie']),
            (outer.u0, floor_in), (lo_x, floor_in)]
    sv.shape(sec, fill=PART, hatch='////', lw=MID, color=SOFT, z=3)
    sv.shape(sec, z=4)
    for x, y, dd in low:
        sv.line([(x, 1.5), (x, stand_pr.lo - 1.5)], lw=HAIR, color=SOFT, dash=CENTRE)
    left_x, right_x = sv.X(hi_x), sv.X(lo_x)
    sv.vdim((hi_x, 0), (hi_x, floor_in), left_x - 4, value=0 - floor_in, out=1)
    sv.vdim((outer.u1, 0), (outer.u1, wall_top['usb']), left_x - 11, value=0 - wall_top['usb'])
    sv.vdim((lo_x, 0), (outer.u0, top), right_x + 5, value=0 - top, side=-1)
    st = low[-1]
    sv.vdim((st[0] + st[2] / 2, floor_in), (st[0] + st[2] / 2, stand_pr.lo), sv.X(st[0] + st[2] / 2) - 3,
            value=floor_in - stand_pr.lo)
    sv.vdim((st[0] + ins_d / 2, ins_pr.hi), (st[0] + ins_d / 2, stand_pr.lo), sv.X(st[0] + st[2] / 2) - 9,
            value=ins_pr.hi - stand_pr.lo)
    sv.label((sv.X(inner.cu), sv.Y(top * 0.55)), 'walls {} thick, floor {} thick', outer.u1 - inner.u1,
             0 - floor_in, ha='center', size=6.2)
    s.text((left_x - 1, sv.Y(wall_top['usb']) + 2.5), 'cut through\nthe USB opening', 5.6, SOFT, ha='left',
           va='bottom')
    s.text((8, sv.Y(top) + 7.5), 'SECTION A–A', 8.2, INK, ha='left', va='bottom', weight='bold')
    s.text((8, sv.Y(top) + 6.7), '(through the lower posts, floor down)', 6.4, SOFT, ha='left', va='top')
    tab = hx[0]
    s.text((8, 43), s.fmt('Side tabs: 4 holes Ø{} for the M3 × 8 screws into the panel\'s inserts.', tab[2])[0],
           6.4, INK, ha='left', va='top')
    s.text((8, 38.5), 'The fourth wall (bottom of the inside view) is plain.', 6.4, INK, ha='left', va='top')
    pb = [Box(q) for q in amp_posts.paths()]
    xs = sorted({round(float(x), 6): x for x, _, _ in amp_ins.circles()}.values(), key=float)
    ys = sorted({round(float(y), 6): y for _, y, _ in amp_ins.circles()}.values(), key=float)
    line, colour = s.fmt('Amp posts: 4 posts {} × {}, {} tall from the floor\'s outside, centres {} × {} apart,\n'
                         'Ø{} holes {} deep for M3 inserts (the amp plate, sheet %d). B, C and D leave them out.'
                         % AMP_SHEET, pb[0].w, pb[0].w, 0 - amp_posts.lo, xs[-1] - xs[0], ys[-1] - ys[0],
                         amp_ins.circles()[0][2], amp_ins.hi - amp_posts.lo)
    s.text((8, 34), line, 6.4, colour, ha='left', va='top')

    # the walls with openings, each seen from outside, floor down
    col = 168.0
    vb = View(s, at=(col, 168), ref=(outer.v1, 0), flip_u=True, flip_v=True)
    wall_elevation(s, vb, outer.v0, outer.v1, top, usb, [], [(usb_ear.v0, usb_ear.v1, floor_in)], outer.v1, 164,
                   'B', 'USB + Ethernet wall, from outside')
    vc = View(s, at=(col, 112), ref=(outer.u0, 0), flip_v=True)
    wall_elevation(s, vc, outer.u0, outer.u1, top, hdmi, [], [], outer.u0, 108, 'C',
                   'power + HDMI wall, from outside (heights as B)', heights=False)
    vd = View(s, at=(col, 56), ref=(outer.v0, 0), flip_v=True)
    wall_elevation(s, vd, outer.v0, outer.v1, top, [], pcie, [(ears[0].v0, ears[0].v1, floor_in)], outer.v0, 52,
                   'D', 'PCIe + button wall, from outside')
    return s


def sheet_amp_plate(m, number, total):
    p = m.p
    part = m.parts['amp plate']
    plate_pr = part.one('Plate')
    pl = Box(plate_pr.paths()[0])
    zf, zb = plate_pr.hi, plate_pr.lo
    st_pr = part.one('Amp standoffs')
    stands = st_pr.circles()
    st_d = stands[0][2]
    ins_pr = part.one('Amp insert holes')
    ins_d = ins_pr.circles()[0][2]
    screws = part.one('Post screw holes').circles()
    vents = sorted((bounds(q) for q in part.one('Vents').paths()), key=lambda b: float(b.cu))
    board = Box(m.parts['Amp (reference)'].prisms[0].paths()[0])
    s = Sheet(m, number, total, 'Amp plate',
              'Print 1, flat, the posts up. The amp screws onto its four posts; the plate screws onto\n'
              "the four tall posts on the Pi case (sheet %d), behind the Pi." % PI_SHEET, '1:1')

    # the side the amp sits on, seen from behind the dash
    v = View(s, at=(40, 98), ref=(pl.u1, pl.v0), flip_u=True)
    v.shape(path_points(pl.segs), fill=PART)
    for b in vents:
        v.shape(path_points(b.segs), lw=MID, fill='white', z=4)
    for x, y, dd in screws:
        v.circle(x, y, dd, fill='white', z=4)
        v.centre(x, y, dd)
    for x, y, dd in stands:
        v.circle(x, y, dd, lw=THICK, fill=PART, z=4)
        v.circle(x, y, ins_d, fill=BLIND, z=5)
        v.centre(x, y, dd)
    v.shape(path_points(board.segs), lw=THIN, color=GHOST, dash=(5, 2.5), z=6)

    def pair(holes, key):
        lo = min(holes, key=lambda c: (float(c[1]), -float(c[0])))
        return lo, [c for c in holes if abs(float(c[key]) - float(lo[key])) < 1e-6 and c is not lo][0]
    top = max(float(c[1]) for c in stands)
    st_top = [c for c in stands if abs(float(c[1]) - top) < 1e-6]
    sc_top = [c for c in screws if float(c[1]) > float(pl.cv)]
    v.hdim(st_top[0][:2], st_top[1][:2], v.Y(pl.v1) + 8)
    v.hdim(sc_top[0][:2], sc_top[1][:2], v.Y(pl.v1) + 14.5)
    v.hdim((pl.u0, pl.v1), (pl.u1, pl.v1), v.Y(pl.v1) + 21)
    right = v.X(pl.u0)
    st_side = [c for c in stands if float(c[0]) < float(pl.cu)]
    sc_side = [c for c in screws if float(c[0]) < float(pl.cu)]
    v.vdim(st_side[0][:2], st_side[1][:2], right + 6, side=-1)
    v.vdim(sc_side[0][:2], sc_side[1][:2], right + 13, side=-1)
    v.vdim((pl.u0, pl.v0), (pl.u0, pl.v1), right + 20, side=-1)
    v.label((v.X(board.cu), v.Y(board.v1) - 4.5), 'amp board {} × {} (dashed)', board.w, board.h,
            ha='center', size=6.0)

    # what things are
    st = max(stands, key=lambda c: (-float(c[1]), float(c[0])))       # lower, on the paper's left
    at = (52, 84)
    v.note(('paper',) + v.edge(st[0], st[1], st[2], at), at,
           '4 posts Ø{}, {} tall,\nØ{} holes {} deep for M2\nheat-set inserts (the amp\'s\nholes are about 2.5)',
           st_d, zb - st_pr.lo, ins_d, ins_pr.hi - st_pr.lo)
    sc = min(sc_side, key=lambda c: float(c[1]))
    at = (164, 84)
    v.note(('paper',) + v.edge(sc[0], sc[1], sc[2], at), at,
           "4 holes Ø{} for M3 × 8 screws\ninto the Pi case's posts", sc[2], ha='right')
    mid = vents[len(vents) // 2]
    at = (v.X(mid.cu), 66)
    v.note(('paper',) + v.P(mid.cu, mid.v0), at, '%d vents {} × {}, {} apart' % len(vents), mid.w, mid.h,
           vents[1].cu - vents[0].cu, ha='center')
    s.text((v.X(pl.u1), 206.5), 'BACK', 8.2, INK, ha='left', va='bottom', weight='bold')
    s.text((v.X(pl.u1) + 13, 206.5), '(the side the amp sits on, seen from behind the dash); everything is centred',
           6.4, SOFT, ha='left', va='bottom')

    # section through two of the posts
    cut = min(stands, key=lambda c: float(c[0]))       # the paper's right-hand pair, beside the section
    a_x = v.X(cut[0])
    for y, va in ((pl.v0, 'top'), (pl.v1, 'bottom')):
        yy = v.Y(y) + (-4.0 if va == 'top' else 3.0)
        s.line([(a_x, v.Y(y)), (a_x, yy)], lw=HAIR, color=SOFT, dash=CENTRE)
        s.line([(a_x, yy), (a_x - 5, yy)], lw=MID)
        s.arrowhead((a_x - 5, yy), (1, 0))
        s.text((a_x + 1.5, yy), 'A', 8, INK, ha='left', va='center', weight='bold')
    sv = View(s, at=(222, 98), ref=(zf, pl.v0), flip_u=True)
    zt, zi = st_pr.lo, ins_pr.hi
    r, ri = st_d / 2, ins_d / 2
    sec = [(zf, pl.v0), (zb, pl.v0)]
    for ys in sorted((c[1] for c in stands if abs(float(c[0]) - float(cut[0])) < 1e-6), key=float):
        sec += [(zb, ys - r), (zt, ys - r), (zt, ys - ri), (zi, ys - ri), (zi, ys + ri), (zt, ys + ri),
                (zt, ys + r), (zb, ys + r)]
    sec += [(zb, pl.v1), (zf, pl.v1)]
    sv.shape(sec, fill=PART, hatch='////', lw=MID, color=SOFT, z=3)
    sv.shape(sec, z=4)
    low = min(float(c[1]) for c in stands)
    sv.hdim((zf, pl.v0), (zb, pl.v0), sv.Y(pl.v0) - 6, out=-1, side=-1)
    sv.hdim((zb, low - r), (zt, low - r), sv.Y(pl.v0) - 6, side=-1)
    sv.hdim((zf, pl.v0), (zt, low - r), sv.Y(pl.v0) - 14, side=-1)
    hi_y = max(float(c[1]) for c in stands)
    sv.hdim((zt, hi_y + ri), (zi, hi_y + ri), sv.Y(pl.v1) + 6, out=1)
    sv.vdim((zt, hi_y - ri), (zt, hi_y + ri), sv.X(zt) + 6, template='Ø{}', side=-1)
    s.view_title((sv.X((zf + zt) / 2), 196), 'SECTION A–A', '(through two posts)', ha='center')
    s.text((sv.X(zf) - 2, sv.Y(pl.cv)), 'faces the Pi', 6.0, SOFT, ha='right', rot=90, va='bottom')
    s.text((sv.X(zt) + 2, sv.Y(pl.cv)), 'the amp goes here', 6.0, SOFT, ha='left', rot=90, va='top')

    lines = [('Put it together:', INK),
             ("1. Press M2 inserts into this plate's four posts, and M3 inserts into the Pi case's tall posts.", INK),
             ("2. Screw the plate onto the Pi case's posts (M3 × 8), this side facing away from the Pi.", INK),
             ("3. Screw the amp onto the posts (M2 × 6), its parts facing away from the Pi.", INK),
             ("The amp's hole spacing is a guess (E): measure it, centre to centre, before printing.",
              TAG_COLOUR['E'])]
    for i, (line, colour) in enumerate(lines):
        s.text((8, 52 - i * 4.6), line, 6.6, colour, ha='left', va='top', weight='bold' if i == 0 else 'normal')
    return s


def sheet_knob(m, number, total):
    p = m.p
    knob = m.parts['knob']
    body = knob.one('Knob')
    cx, cy, dia = body.circles()[0]
    grip = knob.one('Grip').circles()
    recess, clear, bore = knob.one('Nut recess'), knob.one('Shaft clearance'), knob.one('D bore')
    z0, z1 = body.lo, body.hi
    r = dia / 2
    k = 3.0
    s = Sheet(m, number, total, 'Volume knob',
              'Print 1, top down. It presses onto the EC11 encoder\'s 6 mm D shaft;\n'
              'the recess clears the encoder\'s nut.', '3:1')
    flute_d = grip[0][2]
    outline = [(cx + u, cy + w) for u, w in fluted_circle(float(r), len(grip), float(flute_d) / 2)]

    # the end you turn
    tv = View(s, at=(62, 120), ref=(cx, cy), scale=k)
    tv.shape(outline, fill=PART)
    tv.centre(cx, cy, dia)
    tv.hdim((cx - r, cy), (cx + r, cy), tv.Y(cy - r) - 8, value=dia, template='Ø{}', side=-1)
    g = min(grip, key=lambda c: float(c[1]))
    tv.note(('paper',) + tv.P(g[0], g[1] - flute_d / 2), (tv.X(cx) + 12, tv.Y(cy - r) - 20),
            '%d grooves Ø{} around the edge' % len(grip), flute_d, ha='center')
    s.view_title((tv.X(cx), tv.Y(cy + r) + 22), 'TOP', '(the end you turn)', ha='center')

    # section through the middle, top up
    sv = View(s, at=(140, 120), ref=(cx, (z0 + z1) / 2), scale=k)
    rr, rc, rb = recess.circles()[0][2] / 2, clear.circles()[0][2] / 2, p.ShaftDiameter / 2
    h_rec, h_clr, h_bore = recess.hi, bore.lo, bore.hi
    steps = [(rr, z0), (rr, h_rec), (rc, h_rec), (rc, h_clr), (rb, h_clr), (rb, h_bore)]
    sec = [(cx - r, z0)] + [(cx - u, z) for u, z in steps] + [(cx + u, z) for u, z in reversed(steps)] + \
          [(cx + r, z0), (cx + r, z1), (cx - r, z1)]
    sv.shape(sec, fill=PART, hatch='////', lw=MID, color=SOFT, z=3)
    sv.shape(sec, z=4)
    sv.line([(cx, z0 - 1.5), (cx, z1 + 1.5)], lw=HAIR, color=SOFT, dash=CENTRE)
    right = sv.X(cx + r)
    sv.vdim((cx + rr, z0), (cx + rr, h_rec), right + 5, value=h_rec - z0, side=-1)
    sv.vdim((cx + rc, z0), (cx + rc, h_clr), right + 11.5, value=h_clr - z0, side=-1)
    sv.vdim((cx + r, z0), (cx + r, z1), right + 18, value=z1 - z0, side=-1)
    sv.vdim((cx - rb, z0), (cx - rb, h_bore), sv.X(cx - r) - 5, value=h_bore - z0)
    sv.vdim((cx - rb, h_bore), (cx - r, z1), sv.X(cx - r) - 12, value=z1 - h_bore, out=1)
    sv.hdim((cx - rr, z0), (cx + rr, z0), sv.Y(z0) - 7, value=rr * 2, template='Ø{}', side=-1)
    sv.hdim((cx - rc, h_clr), (cx + rc, h_clr), sv.Y(z0) - 14, value=rc * 2, template='Ø{}', side=-1)
    sv.hdim((cx - rb, h_bore), (cx + rb, h_bore), sv.Y(z1) + 6, value=rb * 2, template='Ø{}')
    sv.hdim((cx - r, z1), (cx + r, z1), sv.Y(z1) + 14, value=dia, template='Ø{}')
    s.view_title((sv.X(cx), sv.Y(z1) + 22), 'SECTION', '(through the middle, top up; grooves left out)',
                 ha='center')
    s.text((sv.X(cx), sv.Y(z0) - 21), 'open end: onto the shaft', 6.2, SOFT, va='top')

    # the end that goes onto the shaft: mirror image of the top
    bv = View(s, at=(222, 120), ref=(cx, cy), scale=k, flip_u=True)
    bv.shape(outline, fill=PART)
    bv.circle(cx, cy, rr * 2, fill=BLIND, z=4)
    bv.circle(cx, cy, rc * 2, fill='#c9c6bd', z=5)
    dpath = bore.paths()[0]
    bv.shape(path_points(dpath), lw=MID, fill='#b5b2a8', z=6)
    bv.centre(cx, cy, dia)
    flat_y = dpath[0][1][1]                         # d_shape() starts with the flat
    across = flat_y - (cy - rb)
    bv.vdim((cx, cy - rb), (cx, flat_y), bv.X(cx - r) + 6, value=across, side=-1)
    bv.note(('paper',) + bv.P(cx + rb * 0.7, cy - rb * 0.72), (bv.X(cx), bv.Y(cy - r) - 14),
            'D bore Ø{}, {} across the flat,\n{} deep from the open end', rb * 2, across, h_bore - z0, ha='center')
    s.view_title((bv.X(cx), bv.Y(cy + r) + 22), 'BOTTOM', '(the open end, looking in)', ha='center')
    return s


def sheet_assembly(m, number, total):
    p = m.p
    pan, box, outline = panel_parts(m)
    face = pan.one('Panel').hi
    s = Sheet(m, number, total, 'Assembly: side view',
              'Everything in place, seen from the driver\'s door. Blue: screen. Green: Pi + DAC HAT.\n'
              'Orange: amp. Pink: climate controls. Red: factory bracket (placeholder; shape unknown).', '1:1')
    v = View(s, at=(150, 56), ref=(0, box.v0))           # across: Z (toward you); up: Y
    BLUE, GREEN, PINK, RED = '#cfe0f3', '#d8ecc8', '#f3d6dc', '#f4cccc'
    HID = (4.0, 2.0)

    clim = m.parts['Climate controls (space)'].prisms[0]
    cl = Box(clim.paths()[0])
    lo = box.v0 - 6
    v.shape([(clim.lo, lo), (clim.hi, lo), (clim.hi, cl.v1), (clim.lo, cl.v1)], lw=THIN, color='#b07c88',
            fill=PINK, z=2)
    v.label((v.X(clim.hi) + 2, v.Y(lo + 3)), 'climate controls', ha='left', size=6.0)

    # the Pi case and the Pi, behind the adapter plates from this side
    case = m.parts['pi case']
    walls = Box(sorted(case.one('Walls').paths(), key=lambda q: -float(Box(q).w))[0])
    ctop = case.one('Walls').lo
    pi = m.parts['Raspberry Pi 5 + DAC (reference)']
    board = Box(pi.prisms[0].paths()[0])
    zlo = min((pr.lo for pr in pi.prisms), key=float)
    zhi = max((pr.hi for pr in pi.prisms), key=float)
    case_pts = [(0, walls.v0), (ctop, walls.v0), (ctop, walls.v1), (0, walls.v1)]
    pi_pts = [(zhi, board.v0), (zlo, board.v0), (zlo, board.v1), (zhi, board.v1)]
    v.shape(pi_pts, lw=0, fill=GREEN, z=1.8)
    v.shape(case_pts, lw=0, fill=PART, z=2)

    # the amp, on its plate on the Pi case's tall posts
    ORANGE = '#f6dfc2'
    tall = case.one('Amp posts')
    plate = m.parts['amp plate']
    ppr, spr = plate.one('Plate'), plate.one('Amp standoffs')
    pbox = Box(ppr.paths()[0])
    amp = m.parts['Amp (reference)']
    abox = Box(amp.prisms[0].paths()[0])
    amp_lo = min((pr.lo for pr in amp.prisms), key=float)
    amp_hi = max((pr.hi for pr in amp.prisms), key=float)
    behind = []
    for b in {(round(float(b.v0), 6)): b for b in (Box(q) for q in tall.paths())}.values():
        behind.append([(tall.lo, b.v0), (0, b.v0), (0, b.v1), (tall.lo, b.v1)])
    behind.append([(ppr.lo, pbox.v0), (ppr.hi, pbox.v0), (ppr.hi, pbox.v1), (ppr.lo, pbox.v1)])
    for y in {round(float(c[1]), 6): c[1] for c in spr.circles()}.values():
        r = spr.circles()[0][2] / 2
        behind.append([(spr.lo, y - r), (ppr.lo, y - r), (ppr.lo, y + r), (spr.lo, y + r)])
    for pts in behind:
        v.shape(pts, lw=0, fill=PART, z=2)
    amp_pts = [(amp_lo, abox.v0), (amp_hi, abox.v0), (amp_hi, abox.v1), (amp_lo, abox.v1)]
    v.shape(amp_pts, lw=0, fill=ORANGE, z=1.8)

    adapters = [m.parts[key].one('Adapter') for key in ('adapter lower left', 'adapter upper left')]
    for key, pr in zip(('adapter lower left', 'adapter upper left'), adapters):
        pts = path_points(pr.paths()[0])
        zmin = min((q[1] for q in pts), key=float)
        z_wall = max((q[1] for q in pts if abs(float(q[0]) - min(float(a[0]) for a in pts)) < 1e-9), key=float)
        v.shape([(0, pr.lo), (zmin, pr.lo), (zmin, pr.hi), (0, pr.hi)], fill=PART, z=3)
        v.line([(z_wall, pr.lo), (z_wall, pr.hi)], lw=MID, z=3.2)
        for sp in m.parts[key].get('Bracket slot'):
            v.shape([(z, y) for y, z in path_points(sp.paths()[0])], lw=MID, fill='white', z=3.2)
    v.shape(case_pts, lw=MID, dash=HID, z=3.5)
    v.shape(pi_pts, lw=THIN, color='#4f7a35', dash=HID, z=3.5)
    for pts in behind:
        v.shape(pts, lw=MID, dash=HID, z=3.5)
    v.shape(amp_pts, lw=THIN, color='#b07a3a', dash=HID, z=3.5)

    fb = m.parts['Factory radio brackets (placeholder)']
    fbb = Box([pr for pr in fb.prisms if pr.op == 'new'][0].paths()[0])      # (y, z)
    v.shape([(fbb.v0, fbb.u0), (fbb.v1, fbb.u0), (fbb.v1, fbb.u1), (fbb.v0, fbb.u1)], lw=THIN,
            color='#c08080', fill=RED + '66', dash=(5, 2.5), z=3.8)
    v.label((v.X(fbb.v0) + 1.5, v.Y(fbb.u1) - 1.5), 'factory bracket\n(shape unknown)', ha='left', va='top',
            size=6.0)

    v.shape([(0, box.v0), (face, box.v0), (face, box.v1), (0, box.v1)], fill=PART, z=6)
    posts = {}
    for pr in pan.get('Screen post'):
        x, y, dd = pr.circles()[0]
        posts[float(y)] = (y, dd, pr.hi)
    for y, dd, ptop in posts.values():
        v.shape([(face, y - dd / 2), (ptop, y - dd / 2), (ptop, y + dd / 2), (face, y + dd / 2)], fill=PART, z=6)
    scr = m.parts['Screen (reference)'].prisms
    glass = max(scr, key=lambda pr: float(pr.hi))
    module = min(scr, key=lambda pr: float(pr.hi))
    gb, mb = Box(glass.paths()[0]), Box(module.paths()[0])
    v.shape([(module.lo, mb.v0), (module.hi, mb.v0), (module.hi, mb.v1), (module.lo, mb.v1)], lw=THIN,
            color='#5b85b0', fill=BLUE, z=6)
    v.shape([(glass.lo, gb.v0), (glass.hi, gb.v0), (glass.hi, gb.v1), (glass.lo, gb.v1)], lw=MID,
            color='#3f6d9c', fill=BLUE, z=6)
    knob = m.parts['knob'].one('Knob')
    kx, ky, kd = knob.circles()[0]
    v.shape([(knob.lo, ky - kd / 2), (knob.hi, ky - kd / 2), (knob.hi, ky + kd / 2), (knob.lo, ky + kd / 2)],
            fill=PART, z=6)
    v.label((v.X(knob.hi) + 2, v.Y(ky)), 'knob', ha='left', size=6.0)
    v.label((v.X(glass.hi) + 2, v.Y(gb.cv) - 20), 'screen', ha='left', size=6.0)
    s.text((v.X(face / 2), v.Y(box.v1) + 1.2), 'panel', 6.0, SOFT, va='bottom')

    # labels for what's behind
    gap_lo, gap_hi = adapters[0].hi, adapters[1].lo
    left = v.X(min(fbb.v0, zlo, amp_lo, key=float)) - 4
    mid = (gap_lo + gap_hi) / 2
    v.note((ctop * 0.35, gap_lo + 2), (left, v.Y(mid) - 12), 'Pi case', ha='right')
    v.note((zlo + 4, mid), (left, v.Y(mid) + 3), 'Pi + cooler\n+ DAC HAT', ha='right')
    v.note(((ppr.lo + ppr.hi) / 2, gap_hi - 3), (left, v.Y(mid) + 18), 'amp plate', ha='right')
    v.note(((amp_lo + amp_hi) / 2, mid + 6), (left, v.Y(mid) + 30), 'amp (its height is\nfrom the listing)',
           ha='right')
    s.text((14, 199.5), 'Dashed: hidden behind the adapter plates.', 6.4, SOFT, ha='left', va='top')

    # front to back (Z), from the back face of the panel
    lowest = [(face, box.v0), (max(t[2] for t in posts.values()), min(t[0] - t[1] / 2 for t in posts.values())),
              (glass.hi, gb.v0), (knob.hi, ky - kd / 2), (ctop, walls.v0), (zlo, board.v0)]
    zmin = min((q[1] for q in path_points(adapters[0].paths()[0])), key=float)
    lowest.append((zmin, adapters[0].lo))
    lowest += [(ppr.hi, pbox.v0), (amp_lo, abox.v0)]
    v.ord_x(0, lowest, y=v.Y(lo) - 2.5, absolute=True)
    s.text((14, v.Y(lo) - 4), 'Front to back, from the back\nface of the panel:\n'
           '← behind it      in front of it →', 6.2, INK, ha='left', va='top')
    v.hdim((0, adapters[0].lo), (-p.BezelReturnDepth, adapters[0].lo), v.Y(adapters[0].lo) - 4,
           value=p.BezelReturnDepth, side=-1)
    v.label((v.X(-p.BezelReturnDepth / 2), v.Y(adapters[0].lo) - 10), 'bezel walls\nbehind the panel',
            ha='center', va='top', size=5.8)

    # up and down
    right = v.X(knob.hi) + 22
    v.vdim((glass.hi, gb.v1), (face, box.v1), right, value=gb.v1 - box.v1, out=-1)
    v.vdim((knob.hi, ky + kd / 2), (glass.lo, gb.v0), right, value=gb.v0 - (ky + kd / 2), side=-1, out=-1)
    v.vdim((knob.hi, ky - kd / 2), (face, box.v0), right, value=ky - kd / 2 - box.v0, side=-1, out=-1)
    s.text((right + 4, v.Y(box.v1) + 3), 'screen stands\nabove the opening', 6.0, SOFT, ha='left', va='center')
    s.text((right + 4, v.Y((ky + kd / 2 + gb.v0) / 2)), 'knob to screen', 6.0, SOFT, ha='left', va='center')
    s.text((right + 4, v.Y(box.v0 - 2)), 'knob above the\nclimate controls', 6.0, SOFT, ha='left', va='center')
    top_post = max(posts.values(), key=lambda t: float(t[0]))
    v.note((face + (top_post[2] - face) / 2, top_post[0] - top_post[1] / 2),
           (v.X(glass.hi) + 14, v.Y(top_post[0]) - 20), 'screen posts:\n{} gap behind\nthe screen',
           top_post[2] - face)
    s.text((14, 205.5), 'SIDE', 8.2, INK, ha='left', va='bottom', weight='bold')
    s.text((14, 204.7), '(from the driver\'s door; toward you is to the right)', 6.4, SOFT, ha='left', va='top')
    return s

def check_print_files(m):
    """Warn when print/ was made from other sizes than the script's defaults (say, changed in Fusion)."""
    sys.path.insert(0, HERE)
    from make_print_files import read_stl
    parts = {'dash-panel.stl': ['panel'], 'pi-case.stl': ['pi case'], 'volume-knob.stl': ['knob'],
             'adapter-plate.stl': ['adapter upper left'], 'amp-plate.stl': ['amp plate']}
    warnings = []
    for name, keys in parts.items():
        path = os.path.join(HERE, 'print', name)
        if not os.path.exists(path):
            continue
        tris = read_stl(path)
        got = sorted(max(q[i] for t in tris for q in t) - min(q[i] for t in tris for q in t) for i in range(3))
        want = sorted(model_size(m.parts[keys[0]]))
        if any(abs(a - b) > 0.2 for a, b in zip(got, want)):
            warnings.append('print/%s is %s mm but the script gives %s mm' % (
                name, ' x '.join('%.1f' % g for g in got), ' x '.join('%.1f' % w for w in want)))
    return warnings


def model_size(part):
    """Overall size of a recorded part: the solids it adds, not the cuts."""
    lo, hi = [math.inf] * 3, [-math.inf] * 3
    axes = {'x': (1, 2, 0), 'y': (0, 2, 1), 'z': (0, 1, 2)}       # sketch u, sketch v, extrude
    for pr in part.prisms:
        if pr.op == 'cut':
            continue
        iu, iv, iw = axes[pr.axis]
        for shape in pr.shapes:
            if shape.kind == 'circle':
                u, v, dd = [float(q) for q in shape.data]
                pts = [(u - dd / 2, v - dd / 2), (u + dd / 2, v + dd / 2)]
            else:
                pts = [(float(a), float(b)) for a, b in path_points(shape.data)]
            for u, v in pts:
                for i, val in ((iu, u), (iv, v)):
                    lo[i], hi[i] = min(lo[i], val), max(hi[i], val)
        lo[iw], hi[iw] = min(lo[iw], float(pr.lo)), max(hi[iw], float(pr.hi))
    return [b - a for a, b in zip(lo, hi)]


def render(sheets):
    os.makedirs(OUT, exist_ok=True)
    pdf_path = os.path.join(OUT, 'baja-dash-case-drawings.pdf')
    with PdfPages(pdf_path, metadata={'Title': 'Baja OS dash case: drawings', 'Creator': 'make_drawings.py',
                                      'CreationDate': None}) as pdf:
        for name, s in sheets:
            s.fig.savefig(os.path.join(OUT, name + '.png'), dpi=200, facecolor='white',
                          metadata={'Software': None})
            pdf.savefig(s.fig, facecolor='white')
            plt.close(s.fig)
            print('wrote drawings/%s.png' % name)
    print('wrote drawings/%s' % os.path.basename(pdf_path))


def main():
    global plt, Polygon, Circle, PdfPages
    try:
        import matplotlib
    except ImportError:
        sys.exit('This needs matplotlib: pip3 install matplotlib')
    matplotlib.use('Agg')
    matplotlib.rcParams.update({'pdf.fonttype': 42, 'font.family': 'DejaVu Sans',
                                'mathtext.fontset': 'dejavusans', 'hatch.linewidth': 0.4})
    from matplotlib import pyplot as plt
    from matplotlib.backends.backend_pdf import PdfPages
    from matplotlib.patches import Circle, Polygon
    m = load_model()
    for warning in check_print_files(m):
        print('warning: ' + warning + '; the drawings follow the script')
    total = 8
    sheets = [('1-dash-panel-front', sheet_panel_front(m, FRONT_SHEET, total)),
              ('2-dash-panel-top-and-lip', sheet_panel_lip(m, LIP_SHEET, total)),
              ('3-dash-panel-back', sheet_panel_back(m, BACK_SHEET, total)),
              ('4-adapter-plate', sheet_adapter(m, 4, total)),
              ('5-pi-case', sheet_pi_case(m, PI_SHEET, total)),
              ('6-amp-plate', sheet_amp_plate(m, AMP_SHEET, total)),
              ('7-volume-knob', sheet_knob(m, 7, total)),
              ('8-assembly-side', sheet_assembly(m, 8, total))]
    render(sheets)


if __name__ == '__main__':
    main()
