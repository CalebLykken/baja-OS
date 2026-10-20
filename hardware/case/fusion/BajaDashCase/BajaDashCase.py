"""Baja OS dash case for the 2005 Subaru Baja, built with Fusion's API.

Run it from Utilities > Add-Ins > Scripts and Add-Ins.

- First run: makes a new design, adds every size below as a Fusion user
  parameter (Modify > Change Parameters), builds the parts, and writes the
  print files (hardware/case/print/), a STEP and a Fusion archive.
- Later runs, with that design open: reads the parameters back and rebuilds
  the parts from them. To change a size, edit it in Change Parameters and run
  the script again. Any other design is left alone (a new one is made).

Each parameter's comment says how sure we are of it: MEASURED (Caleb),
VERIFIED (a document), ESTIMATED (worked out, not confirmed), UNKNOWN
(placeholder until measured) or DESIGN (a choice; change freely).

Layout, as seen from the driver's seat: X to the right, Y up, Z out of the
dash toward you. The origin is the bottom-left corner of the factory bezel's
opening, on the back face of the dash panel. Lengths are millimetres.
"""

import math
import os
import time
import traceback

import adsk.core
import adsk.fusion

VERSION = 6

# (name, default, unit, comment). Units: 'mm', 'deg', or '' (a plain number).
PARAMETERS = [
    # Factory bezel opening: the radio slot on top, the climate controls below
    ('OpeningWidth', 171.45, 'mm', 'MEASURED (Caleb): bezel opening width, 6 3/4 in'),
    ('OpeningHeight', 222.25, 'mm', 'MEASURED (Caleb): bezel opening height, 8 3/4 in'),
    ('CornerRadiusTopLeft', 15.0, 'mm', 'MEASURED (Caleb, re-measured after the first test print)'),
    ('CornerRadiusTopRight', 3.0, 'mm', 'MEASURED (Caleb, re-measured after the first test print)'),
    ('CornerClearance', 0.5, 'mm', "DESIGN: the panel's top corners are this much rounder than the opening's, so they never bind"),
    ('ClimateGap', 82.55, 'mm', 'MEASURED (Caleb): the climate controls fill the bottom 3 1/4 in of the opening (6 3/4 in wide)'),
    ('BezelReturnDepth', 20.0, 'mm', 'UNKNOWN: how far the bezel walls reach behind the panel; the adapters step out behind them'),
    # Factory radio brackets 66201AE17A (left) and 66201AE18A (right)
    ('BracketSeparation', 180.0, 'mm', 'ESTIMATED: inside face to inside face of the factory brackets (radio width); 180 is a common DIN width, not verified for the Baja'),
    ('FactoryBracketUpperY', 185.0, 'mm', 'UNKNOWN: middle of the upper adapter screws, above the bottom of the opening'),
    ('FactoryBracketLowerY', 120.0, 'mm', 'UNKNOWN: middle of the lower adapter screws, above the bottom of the opening'),
    ('FactoryBracketHoleSpacing', 25.0, 'mm', 'UNKNOWN: up-and-down spacing of the two screws each adapter takes'),
    ('FactoryHoleDiameter', 5.5, 'mm', 'ESTIMATED: M5 clearance; Subaru screw 045005160 reads as M5 x 16 by its part-number pattern'),
    ('FactoryBracketThickness', 1.6, 'mm', 'UNKNOWN: steel thickness of the factory bracket (reference model only)'),
    # Printed parts
    ('PanelThickness', 12.7, 'mm', 'DESIGN (Caleb): 1/2 in'),
    ('FitGap', 0.0, 'mm', 'DESIGN: 0 = exactly the measured opening; add 0.2-0.4 per side if the test print is tight'),
    ('PanelBottomRadius', 0.0, 'mm', "MEASURED (Caleb): the opening's bottom corners are square"),
    ('FrameEdgeDepth', 10.0, 'mm', "MEASURED (Caleb): the silver frame is 10 mm thick at the opening's edge; the panel's front part is this deep"),
    ('LipSide', 3.0, 'mm', 'MEASURED (Caleb): behind the frame the panel is this much wider on the left and right, so the frame holds it'),
    ('LipTop', 3.0, 'mm', 'MEASURED (Caleb): the same 3 mm lip along the top edge'),
    ('LipRadiusTopLeft', 0.0, 'mm', "DESIGN (Caleb): the lip's top-left corner is square; the top-right follows the rounded corner"),
    ('AdapterPlateThickness', 4.0, 'mm', 'DESIGN: adapter plate wall (ASA, carries the M5 screws)'),
    ('AdapterHeight', 50.0, 'mm', 'DESIGN: height of each of the four adapter plates'),
    ('AdapterSideLength', 40.0, 'mm', 'DESIGN: front-to-back length of the slotted side wall'),
    ('AdapterSlotLength', 24.0, 'mm', 'DESIGN: front-to-back adjustment in the side slots'),
    # Screen, fixed on four posts
    ('ScreenWidth', 194.0, 'mm', 'VERIFIED: Waveshare 8DP-CAPLCD drawing; Caleb\'s caliper check of the holes matches it'),
    ('ScreenHeight', 119.0, 'mm', 'VERIFIED: Waveshare 8DP-CAPLCD drawing'),
    ('ScreenDepth', 4.8, 'mm', 'VERIFIED: glass + LCD, Waveshare drawing'),
    ('ScreenBackDepth', 11.39, 'mm', 'VERIFIED: glass front to the back of the mounting nuts, Waveshare drawing'),
    ('ScreenMountHoleSpacing', 58.0, 'mm', 'VERIFIED: Raspberry Pi hole pattern, side to side (Waveshare drawing)'),
    ('ScreenMountHoleSpacingV', 49.0, 'mm', 'VERIFIED: Raspberry Pi hole pattern, up and down'),
    ('ScreenMountOffsetX', -12.21, 'mm', 'VERIFIED: hole pattern centre is 12.2 mm left of the glass centre, seen from the front (Waveshare drawing; Caleb measured 12.8)'),
    ('ScreenMountOffsetY', -3.21, 'mm', 'VERIFIED: 3.2 mm below the glass centre (Waveshare drawing; Caleb measured 3.9)'),
    ('ScreenOverhangTop', 5.5, 'mm', 'DESIGN (Caleb): top of the screen stands this far above the opening'),
    ('ScreenStandoffHeight', 6.0, 'mm', 'DESIGN (Caleb): posts from the panel face to the back of the screen, 6 at most'),
    ('ScreenPostDiameter', 6.5, 'mm', 'DESIGN'),
    ('ScreenScrewLength', 16.0, 'mm', 'DESIGN: M2.5 screws from the back of the panel into the screen; the counterbore depth follows'),
    ('DisplayTiltAngle', 0.0, 'deg', 'DESIGN: + leans the screen back by shortening the top posts; keep it small (0 to 4)'),
    ('CableClearance', 6.0, 'mm', 'DESIGN: room around the plugs in the panel notch'),
    ('PlugAreaLeft', -40.0, 'mm', 'VERIFIED: left end of the USB-C/HDMI/USB sockets from the glass centre, seen from the front (Waveshare drawing)'),
    ('PlugAreaRight', 14.0, 'mm', 'VERIFIED: right end of the sockets from the glass centre (Waveshare drawing)'),
    ('PlugAreaBottom', 33.0, 'mm', "VERIFIED: the board's top edge, where the plugs go in, above the glass centre (Waveshare drawing; HDMI faces up, Caleb)"),
    # Volume knob (EC11 encoder)
    ('KnobX', 25.0, 'mm', 'DESIGN (Caleb): driver side'),
    ('KnobY', 93.3, 'mm', 'DESIGN: centred between the climate controls and the bottom of the screen'),
    ('KnobDiameter', 19.0, 'mm', 'DESIGN: 3/4 in; the strip between the climate controls and the screen is about 24.5 mm tall'),
    ('KnobHeight', 18.0, 'mm', 'DESIGN: fits a 15 or 20 mm encoder shaft'),
    ('EncoderWall', 2.5, 'mm', 'DESIGN: panel left in front of the encoder so its nut reaches'),
    ('EncoderCollarHole', 7.4, 'mm', 'ESTIMATED: EC11 threaded collar is M7'),
    ('EncoderPocket', 15.0, 'mm', 'MEASURED (Caleb): square pocket for the encoder body, 15 x 15'),
    ('ShaftDiameter', 6.1, 'mm', 'MEASURED (Caleb): 6 mm shaft'),
    ('ShaftFlat', 4.6, 'mm', 'ESTIMATED: D shaft, 4.5 mm across the flat'),
    # Raspberry Pi 5
    ('PiX', 43.2, 'mm', 'DESIGN: left edge of the Pi board'),
    ('PiY', 110.0, 'mm', 'DESIGN: bottom edge of the Pi board'),
    ('PiStandoffHeight', 6.0, 'mm', 'DESIGN'),
    ('PiCaseWall', 2.0, 'mm', 'DESIGN: wall of the Pi case'),
    ('PiCaseHeight', 25.0, 'mm', 'DESIGN: wall height from the case floor; the top stays open for the DAC HAT and airflow'),
    ('PiStackHeight', 34.0, 'mm', 'ESTIMATED: Pi + active cooler + DAC HAT, for the clearance check'),
    ('AmpBoardWidth', 118.0, 'mm', 'MEASURED (Caleb): the amp board (Taidacent XH-M180), long side'),
    ('AmpBoardHeight', 76.0, 'mm', 'MEASURED (Caleb): the amp board, short side'),
    ('AmpHoleSpacingX', 111.0, 'mm', "ESTIMATED: the amp board's mounting holes, centre to centre along the long side "
                                     '(3.5 mm in from each end); measure'),
    ('AmpHoleSpacingY', 69.0, 'mm', "ESTIMATED: the amp board's mounting holes, centre to centre along the short side; "
                                    'measure'),
    ('AmpTotalHeight', 29.0, 'mm', "ESTIMATED: the amp's height with its heatsink, from the seller's listing"),
    ('AmpStandoffHeight', 8.0, 'mm', 'DESIGN: gap under the amp board, for its solder joints and the plate screws'),
    ('AmpPlateThickness', 3.0, 'mm', 'DESIGN'),
    ('AmpClearance', 5.0, 'mm', 'DESIGN: air gap between the top of the Pi stack (DAC HAT) and the amp plate'),
    ('AmpPostSize', 8.0, 'mm', 'DESIGN: the four square posts on the Pi case that hold the amp plate'),
]

# Parameters earlier versions made that are no longer used; a rebuild removes them.
OBSOLETE = ['HingeAxisBelowScreenTop', 'HingeKnuckleRadius', 'HingeKnuckleWidth', 'HingeKnuckleGap',
            'HingeLeftX', 'HingeRightX', 'HingePinHole', 'ScreenPlateThickness', 'RearClearance',
            'FactoryBracketCenterY', 'LipRadiusTopRight']

M3_INSERT = 4.0          # hole for an M3 heat-set insert
M3_INSERT_DEPTH = 6.5
M25_INSERT = 3.6         # hole for an M2.5 heat-set insert
M2_INSERT = 3.2          # hole for an M2 heat-set insert (the amp's holes are about 2.5 mm)
M2_INSERT_DEPTH = 4.5
M25_HOLE, M25_HEAD = 3.2, 5.5    # a little loose, to forgive small errors
PI_HOLES = [(3.5, 3.5), (61.5, 3.5), (3.5, 52.5), (61.5, 52.5)]
PI_W, PI_H = 85.0, 56.0
# Raspberry Pi 5 ports, from Raspberry Pi's mechanical drawing (approximate).
# The board sits components-out, GPIO header along the bottom, USB/Ethernet to
# the right: x from the board's left edge, y from its bottom (GPIO) edge.
PI_PORTS_RIGHT = [(9.0, 15.0), (26.9, 15.0), (45.8, 17.5)]   # USB 3, USB 2, Ethernet: (y centre, opening width)
PI_PORTS_TOP = (4.2, 46.2)                                     # USB-C power and both micro-HDMI: x range
PI_PORTS_LEFT = (19.0, 46.0)                                   # PCIe ribbon and power button: y range
PI_CASE_GAP = (3.0, 4.0, 3.0, 4.0)                              # board to wall: bottom, right, top, left
ADAPTER_BASE = 16.0
# The screen's driver board, from Waveshare's drawing (reference model only):
# x0, x1, y0, y1 from the glass centre, seen from the front.
SCREEN_BOARD = (-53.96, 54.04, -39.21, 32.79)

HERE = os.path.dirname(os.path.abspath(__file__))
CASE_DIR = os.path.normpath(os.path.join(HERE, '..', '..'))

FeatureOps = adsk.fusion.FeatureOperations
OPS = {'new': FeatureOps.NewBodyFeatureOperation,
       'join': FeatureOps.JoinFeatureOperation,
       'cut': FeatureOps.CutFeatureOperation}


class Params(dict):
    __getattr__ = dict.__getitem__
    __setattr__ = dict.__setitem__


def cm(mm):
    return mm / 10.0


def val(mm):
    return adsk.core.ValueInput.createByReal(cm(mm))


# ------------------------------------------------------------ 2D shapes
# Each shape is a list of segments in a sketch plane's (u, v) coordinates:
# ('L', p0, p1) is a line, ('A', p0, pmid, p1) a three-point arc.

def _arc(cu, cv, r, a0):
    pts = [(cu + r * math.cos(math.radians(a)), cv + r * math.sin(math.radians(a)))
           for a in (a0, a0 + 45, a0 + 90)]
    return ('A', pts[0], pts[1], pts[2])


def rrect(u0, v0, u1, v1, r=0.0):
    """Rectangle with rounded corners; r is one radius or (bl, br, tr, tl)."""
    bl, br, tr, tl = r if isinstance(r, (tuple, list)) else (r, r, r, r)
    s = [('L', (u0 + bl, v0), (u1 - br, v0))]
    if br > 0:
        s.append(_arc(u1 - br, v0 + br, br, -90))
    s.append(('L', (u1, v0 + br), (u1, v1 - tr)))
    if tr > 0:
        s.append(_arc(u1 - tr, v1 - tr, tr, 0))
    s.append(('L', (u1 - tr, v1), (u0 + tl, v1)))
    if tl > 0:
        s.append(_arc(u0 + tl, v1 - tl, tl, 90))
    s.append(('L', (u0, v1 - tl), (u0, v0 + bl)))
    if bl > 0:
        s.append(_arc(u0 + bl, v0 + bl, bl, 180))
    return s


def centred_rect(cu, cv, w, h, r=0.0):
    return rrect(cu - w / 2, cv - h / 2, cu + w / 2, cv + h / 2, r)


def slot(u0, v0, u1, v1, w):
    """Stadium between end centres (u0, v0) and (u1, v1), lying along u or v."""
    h = w / 2
    if abs(u1 - u0) < 1e-9:      # along v
        lo, hi = min(v0, v1), max(v0, v1)
        return [('L', (u0 - h, lo), (u0 - h, hi)), ('A', (u0 - h, hi), (u0, hi + h), (u0 + h, hi)),
                ('L', (u0 + h, hi), (u0 + h, lo)), ('A', (u0 + h, lo), (u0, lo - h), (u0 - h, lo))]
    lo, hi = min(u0, u1), max(u0, u1)
    return [('L', (lo, v0 - h), (hi, v0 - h)), ('A', (hi, v0 - h), (hi + h, v0), (hi, v0 + h)),
            ('L', (hi, v0 + h), (lo, v0 + h)), ('A', (lo, v0 + h), (lo - h, v0), (lo, v0 - h))]


def d_shape(cu, cv, d, flat):
    """D-shaft bore: a circle with a flat `flat` mm from the round side."""
    r = d / 2
    f = flat - r
    w = math.sqrt(r * r - f * f)
    return [('L', (cu - w, cv + f), (cu + w, cv + f)),
            ('A', (cu + w, cv + f), (cu, cv - r), (cu - w, cv + f))]


def polygon(pts):
    return [('L', pts[i], pts[(i + 1) % len(pts)]) for i in range(len(pts))]


# ------------------------------------------------------------- building

class Sketch:
    """A sketch on a plane across `axis` at `at` mm, drawn in model coordinates."""

    def __init__(self, sketch, axis, at):
        self.sk = sketch
        self.axis = axis
        self.at = at

    def p(self, u, v):
        if self.axis == 'z':
            x, y, z = u, v, self.at
        elif self.axis == 'x':
            x, y, z = self.at, u, v
        else:
            x, y, z = u, self.at, v
        return self.sk.modelToSketchSpace(adsk.core.Point3D.create(cm(x), cm(y), cm(z)))

    def draw(self, segs):
        lines = self.sk.sketchCurves.sketchLines
        arcs = self.sk.sketchCurves.sketchArcs
        for s in segs:
            if s[0] == 'L':
                lines.addByTwoPoints(self.p(*s[1]), self.p(*s[2]))
            else:
                arcs.addByThreePoints(self.p(*s[1]), self.p(*s[2]), self.p(*s[3]))

    def circle(self, u, v, d):
        self.sk.sketchCurves.sketchCircles.addByCenterRadius(self.p(u, v), cm(d / 2))


class Part:
    """One component, built from extrusions across planes in model space."""

    def __init__(self, design, name):
        self.occ = design.rootComponent.occurrences.addNewComponent(adsk.core.Matrix3D.create())
        self.comp = self.occ.component
        self.comp.name = name
        self.name = name
        self.body = None
        self.bodies = []

    def _plane(self, axis, at):
        c = self.comp
        base = {'x': c.yZConstructionPlane, 'y': c.xZConstructionPlane, 'z': c.xYConstructionPlane}[axis]
        if abs(at) < 1e-9:
            return base
        planes = c.constructionPlanes
        for sign in (1.0, -1.0):          # a plane's normal may point either way
            inp = planes.createInput()
            inp.setByOffset(base, val(sign * at))
            plane = planes.add(inp)
            o = plane.geometry.origin
            got = {'x': o.x, 'y': o.y, 'z': o.z}[axis] * 10.0
            if abs(got - at) < 1e-3:
                plane.isLightBulbOn = False
                return plane
            plane.deleteMe()
        raise RuntimeError('could not place a sketch plane at %s = %.2f' % (axis, at))

    def sketch(self, axis, at):
        return Sketch(self.comp.sketches.add(self._plane(axis, at)), axis, at)

    def prism(self, axis, lo, hi, draw, op='join', name=None):
        """Extrude what `draw(sketch)` draws, from lo to hi along `axis`."""
        lo, hi = min(lo, hi), max(lo, hi)
        sk = self.sketch(axis, (lo + hi) / 2.0)
        draw(sk)
        profiles = adsk.core.ObjectCollection.create()
        for prof in sk.sk.profiles:
            profiles.add(prof)
        if profiles.count == 0:
            raise RuntimeError('%s: nothing closed to extrude (%s)' % (self.name, name))
        if op == 'join' and self.body is None:
            op = 'new'
        extrudes = self.comp.features.extrudeFeatures
        inp = extrudes.createInput(profiles, OPS[op])
        inp.setSymmetricExtent(val(hi - lo), True)
        if op != 'new':
            inp.participantBodies = [self.body]
        feature = extrudes.add(inp)
        if name:
            feature.name = name
        sk.sk.isVisible = False
        if feature.bodies.count > 0:
            self.body = feature.bodies.item(0)
            if op == 'new':
                self.bodies.append(self.body)
        return feature

    def name_body(self, name):
        if self.body:
            self.body.name = name


# ------------------------------------------------------- the layout

def derive(p):
    """Positions every part works from."""
    d = Params()
    d.cx = p.OpeningWidth / 2                          # centre line of the opening and the screen
    d.face = p.PanelThickness                          # panel front face (Z)
    d.glass_top = p.OpeningHeight + p.ScreenOverhangTop
    d.scy = d.glass_top - p.ScreenHeight / 2           # screen centre (Y)
    d.glass_bottom = d.glass_top - p.ScreenHeight
    d.mx = d.cx + p.ScreenMountOffsetX                 # centre of the screen's hole pattern
    d.my = d.scy + p.ScreenMountOffsetY
    h = p.ScreenStandoffHeight
    h_top = h - p.ScreenMountHoleSpacingV * math.tan(math.radians(p.DisplayTiltAngle))
    if h_top < 1.0:
        raise RuntimeError('DisplayTiltAngle is too big for ScreenStandoffHeight')
    sx, sy = p.ScreenMountHoleSpacing / 2, p.ScreenMountHoleSpacingV / 2
    d.posts = [(d.mx - sx, d.my - sy, h), (d.mx + sx, d.my - sy, h),
               (d.mx - sx, d.my + sy, h_top), (d.mx + sx, d.my + sy, h_top)]
    d.z_glass = d.face + h + p.ScreenBackDepth         # front of the glass (bottom posts)
    # Notch for the plugs (90-degree plugs turn back into it), from just below
    # where they go in up to the top; it starts above the top posts.
    post_top = d.my + sy + p.ScreenPostDiameter / 2
    d.notch = (d.cx + p.PlugAreaLeft - p.CableClearance, d.cx + p.PlugAreaRight + p.CableClearance,
               max(d.scy + p.PlugAreaBottom - p.CableClearance, post_top + 2.0))
    d.adapter_ys = [p.FactoryBracketLowerY, p.FactoryBracketUpperY]
    # The amp rides behind the Pi, on a plate held by four posts on the Pi case.
    d.pi_top = -3 - p.PiStandoffHeight - p.PiStackHeight     # back of the DAC HAT (Z)
    d.amp_z = d.pi_top - p.AmpClearance                      # the amp plate's front face
    return d


def adapter_geometry(p, side):
    """Panel edge, factory bracket face and inward direction for one side."""
    cx = p.OpeningWidth / 2
    if side == 'left':
        return p.FitGap, cx - p.BracketSeparation / 2, 1.0
    return p.OpeningWidth - p.FitGap, cx + p.BracketSeparation / 2, -1.0


def adapter_base_holes(p, d):
    holes = []
    for side in ('left', 'right'):
        edge, _, inward = adapter_geometry(p, side)
        for yc in d.adapter_ys:
            y0 = yc - p.AdapterHeight / 2
            for y in (y0 + 8, y0 + p.AdapterHeight - 8):
                holes.append((edge + inward * ADAPTER_BASE / 2, y))
    return holes


def pi_case_box(p):
    """Inside of the Pi case walls: x0, y0, x1, y1."""
    gb, gr, gt, gl = PI_CASE_GAP
    return p.PiX - gl, p.PiY - gb, p.PiX + PI_W + gr, p.PiY + PI_H + gt


def pi_plate_holes(p):
    """Screws through the case's side ears into the panel's inserts."""
    x0, y0, x1, y1 = pi_case_box(p)
    xl = x0 - p.PiCaseWall - 5
    xr = x1 + p.PiCaseWall + 5
    return [(xl, p.PiY + 10), (xl, p.PiY + PI_H - 10), (xr, p.PiY + 10), (xr, p.PiY + PI_H - 10)]


def amp_posts(p):
    """Centres of the square posts that hold the amp plate: above and below the
    Pi case's ends, clear of its port openings."""
    x0, y0, x1, y1 = pi_case_box(p)
    w, s = p.PiCaseWall, p.AmpPostSize
    return [(x, y) for y in (y0 - w - s / 2, y1 + w + s / 2) for x in (x0 - w + s / 2, x1 + w - s / 2)]


def amp_layout(p):
    """Centre of the amp (over the Pi case) and its plate's outline: (cx, cy), (x0, y0, x1, y1)."""
    x0, y0, x1, y1 = pi_case_box(p)
    w, s = p.PiCaseWall, p.AmpPostSize
    cx, cy = (x0 + x1) / 2, (y0 + y1) / 2
    margin = 3.0
    return (cx, cy), (min(cx - p.AmpBoardWidth / 2 - margin, x0 - w),
                      min(cy - p.AmpBoardHeight / 2 - margin, y0 - w - s),
                      max(cx + p.AmpBoardWidth / 2 + margin, x1 + w),
                      max(cy + p.AmpBoardHeight / 2 + margin, y1 + w + s))


def amp_holes(p):
    (cx, cy), _ = amp_layout(p)
    hx, hy = p.AmpHoleSpacingX / 2, p.AmpHoleSpacingY / 2
    return [(cx + sx * hx, cy + sy * hy) for sy in (-1, 1) for sx in (-1, 1)]


def tie_slots(p, d):
    x0, x1, y0 = d.notch
    return [(x, y0 + dy) for x in (x0 - 6, x1 + 6) for dy in (6.0, 18.0)]


# ------------------------------------------------------------ the parts

def build_panel(design, p, d):
    part = Part(design, 'Dash panel')
    x0, x1 = p.FitGap, p.OpeningWidth - p.FitGap
    y0, y1 = p.ClimateGap, p.OpeningHeight - p.FitGap
    radii = (p.PanelBottomRadius, p.PanelBottomRadius,
             max(p.CornerRadiusTopRight + p.CornerClearance - p.FitGap, 0.0),
             max(p.CornerRadiusTopLeft + p.CornerClearance - p.FitGap, 0.0))
    part.prism('z', 0, d.face, lambda s: s.draw(rrect(x0, y0, x1, y1, radii)), 'new', 'Panel')
    part.name_body('Dash panel')

    # Lip: behind the silver frame's edge the panel is wider, like the factory
    # radio and climate control, so the frame holds it in.
    # At the top right the lip follows the rounded corner, the same distance
    # out all the way round; at the top left it is square (LipRadiusTopLeft).
    lip_t = d.face - p.FrameEdgeDepth
    if lip_t > 0.5 and (p.LipSide > 0 or p.LipTop > 0):
        lip_radii = (radii[0], radii[1], radii[2] + min(p.LipSide, p.LipTop), p.LipRadiusTopLeft)
        part.prism('z', 0, lip_t, lambda s: s.draw(
            rrect(x0 - p.LipSide, y0, x1 + p.LipSide, y1 + p.LipTop, lip_radii)), 'join', 'Lip')

    # Screen posts on the front, screwed from the back into the screen's nuts.
    for x, y, h in d.posts:
        part.prism('z', d.face - 0.5, d.face + h, lambda s: s.circle(x, y, p.ScreenPostDiameter),
                   'join', 'Screen post')
    part.prism('z', -1, d.face + max(h for _, _, h in d.posts) + 1,
               lambda s: [s.circle(x, y, M25_HOLE) for x, y, _ in d.posts], 'cut', 'Screen screw holes')
    for x, y, h in d.posts:
        floor = d.face + h + 3.0 - p.ScreenScrewLength     # leaves 3 mm of thread in the screen's nut
        if floor > 0.5:
            part.prism('z', -1, floor, lambda s: s.circle(x, y, M25_HEAD), 'cut', 'Screw counterbore')

    # Notch in the top edge where the screen's plugs and cables go back into the dash.
    nx0, nx1, ny0 = d.notch
    part.prism('z', -1, d.face + 1, lambda s: s.draw(
        rrect(nx0, ny0, nx1, p.OpeningHeight + p.LipTop + 5, (4, 4, 0, 0))), 'cut', 'Cable notch')

    # Encoder: pocket from behind, hole for its threaded collar.
    part.prism('z', -1, d.face - p.EncoderWall, lambda s: s.draw(
        centred_rect(p.KnobX, p.KnobY, p.EncoderPocket, p.EncoderPocket, 1.0)), 'cut', 'Encoder pocket')
    part.prism('z', -1, d.face + 1, lambda s: s.circle(p.KnobX, p.KnobY, p.EncoderCollarHole),
               'cut', 'Encoder collar hole')

    # M3 heat-set inserts for the adapter plates and the Pi plate.
    holes = adapter_base_holes(p, d) + pi_plate_holes(p)
    part.prism('z', -1, M3_INSERT_DEPTH, lambda s: [s.circle(x, y, M3_INSERT) for x, y in holes],
               'cut', 'Heat-set insert holes')

    # Zip-tie slots beside the notch (strain relief for the screen cables).
    part.prism('z', -1, d.face + 1, lambda s: [
        s.draw(centred_rect(x, y, 2.4, 5.5, 0.5)) for x, y in tie_slots(p, d)], 'cut', 'Zip-tie slots')
    return part


def build_knob(design, p, d):
    part = Part(design, 'Volume knob')
    z0 = d.face + 1.0
    z1 = z0 + p.KnobHeight
    part.prism('z', z0, z1, lambda s: s.circle(p.KnobX, p.KnobY, p.KnobDiameter), 'new', 'Knob')
    part.name_body('Volume knob')
    r = p.KnobDiameter / 2
    n = 20
    part.prism('z', z0 - 1, z1 + 1, lambda s: [
        s.circle(p.KnobX + r * math.cos(2 * math.pi * i / n), p.KnobY + r * math.sin(2 * math.pi * i / n), 1.6)
        for i in range(n)], 'cut', 'Grip')
    part.prism('z', z0 - 1, z0 + 3, lambda s: s.circle(p.KnobX, p.KnobY, 12.5), 'cut', 'Nut recess')
    d_top = z1 - 1.0                   # closed top
    d_bottom = d_top - 10.0
    part.prism('z', z0 - 1, d_bottom + 0.01, lambda s: s.circle(p.KnobX, p.KnobY, 7.5), 'cut', 'Shaft clearance')
    part.prism('z', d_bottom, d_top, lambda s: s.draw(
        d_shape(p.KnobX, p.KnobY, p.ShaftDiameter, p.ShaftFlat)), 'cut', 'D bore')
    return part


def build_adapter(design, p, d, side, level, yc):
    part = Part(design, 'Adapter plate %s %s' % (level, side))
    edge, wall, inward = adapter_geometry(p, side)
    t, depth, length = p.AdapterPlateThickness, p.BezelReturnDepth, p.AdapterSideLength
    out = (wall - edge) * inward           # wall face from the panel edge; negative is outside the panel
    if out >= 0:
        raise RuntimeError('BracketSeparation puts the factory brackets inside the panel edge; '
                           'the adapter needs a different shape')
    y0 = yc - p.AdapterHeight / 2
    y1 = y0 + p.AdapterHeight

    def X(w):
        return edge + inward * w
    outline = [(ADAPTER_BASE, 0), (0, 0), (0, -depth + t), (out, -depth + t), (out, -depth - length),
               (out + t, -depth - length), (out + t, -depth), (t, -depth), (t, -t), (ADAPTER_BASE, -t)]
    part.prism('y', y0, y1, lambda s: s.draw(polygon([(X(w), z) for w, z in outline])), 'new', 'Adapter')
    part.name_body('Adapter plate %s %s' % (level, side))

    # Screws into the panel's heat-set inserts.
    part.prism('z', -t - 1, 1, lambda s: [
        s.circle(X(ADAPTER_BASE / 2), y, 3.4) for y in (y0 + 8, y1 - 8)], 'cut', 'Panel screw holes')
    # Slots that line up with the factory bracket's screws (M5), front to back.
    zs0 = -depth - 8
    zs1 = zs0 - p.AdapterSlotLength
    for dy in (-p.FactoryBracketHoleSpacing / 2, p.FactoryBracketHoleSpacing / 2):
        y = yc + dy
        part.prism('x', X(out + t / 2) - t, X(out + t / 2) + t, lambda s: s.draw(
            slot(y, zs0, y, zs1, p.FactoryHoleDiameter)), 'cut', 'Bracket slot')
    return part


def build_pi_case(design, p, d):
    part = Part(design, 'Pi case')
    x0, y0, x1, y1 = pi_case_box(p)
    w = p.PiCaseWall
    px, py = p.PiX, p.PiY
    part.prism('z', -3, 0, lambda s: s.draw(rrect(x0 - w, y0 - w, x1 + w, y1 + w, 3.0)), 'new', 'Floor')
    part.name_body('Pi case')
    # Ears with the screws into the panel.
    part.prism('z', -3, 0, lambda s: (s.draw(rrect(x0 - w - 10, py + 2, x0 - w + 1, py + PI_H - 2, 3.0)),
                                      s.draw(rrect(x1 + w - 1, py + 2, x1 + w + 10, py + PI_H - 2, 3.0))),
               'join', 'Ears')
    part.prism('z', -4, 1, lambda s: [s.circle(x, y, 3.4) for x, y in pi_plate_holes(p)], 'cut', 'Panel screw holes')
    # Walls, open at the back for the DAC HAT and airflow.
    zt = -3 - p.PiCaseHeight
    part.prism('z', zt, -2.5, lambda s: (s.draw(rrect(x0 - w, y0 - w, x1 + w, y1 + w, 3.0)),
                                         s.draw(rrect(x0, y0, x1, y1, 1.0))), 'join', 'Walls')
    part.prism('z', -3, zt - 1, lambda s: s.draw(rrect(x0, y0, x1, y1, 1.0)), 'cut', 'Inside')
    # Standoffs and their M2.5 inserts.
    h = p.PiStandoffHeight
    part.prism('z', -3 - h, -2.5, lambda s: [s.circle(px + hx, py + hy, 7.0) for hx, hy in PI_HOLES],
               'join', 'Standoffs')
    part.prism('z', -3 - h - 1, -3 - h + 5.5, lambda s: [
        s.circle(px + hx, py + hy, M25_INSERT) for hx, hy in PI_HOLES], 'cut', 'Insert holes')
    # Floor: a vent, and access to the screen screws behind it.
    part.prism('z', -4, 1, lambda s: s.draw(rrect(px + 10, py + 10, px + 55, py + PI_H - 10, 3.0)), 'cut', 'Vent')
    access = [(x, y) for x, y, _ in d.posts if x0 < x < x1 and y0 < y < y1]
    if access:
        part.prism('z', -4, 1, lambda s: [s.circle(x, y, 7.0) for x, y in access], 'cut', 'Screen screw access')
    # Port openings, from just below the board to the open back.
    z_port = -3 - h + 0.6
    part.prism('x', x1 - 1, x1 + w + 1, lambda s: [
        s.draw(rrect(py + yc - wd / 2, zt - 2, py + yc + wd / 2, z_port, 1.0)) for yc, wd in PI_PORTS_RIGHT],
        'cut', 'USB and Ethernet')
    part.prism('y', y1 - 1, y1 + w + 1, lambda s: s.draw(
        rrect(px + PI_PORTS_TOP[0], zt - 2, px + PI_PORTS_TOP[1], z_port, 1.0)), 'cut', 'Power and HDMI')
    part.prism('x', x0 - w - 1, x0 + 1, lambda s: s.draw(
        rrect(py + PI_PORTS_LEFT[0], -3 - h - 1.6 - 7, py + PI_PORTS_LEFT[1], z_port, 1.0)),
        'cut', 'PCIe and power button')
    # Posts for the amp plate, from the panel to just behind the Pi stack. Each
    # reaches into the case wall beside it, to join it.
    a = p.AmpPostSize / 2

    def post(x, y):
        if y < y0:
            return rrect(x - a, y - a, x + a, y0)
        return rrect(x - a, y1, x + a, y + a)
    part.prism('z', d.amp_z, 0, lambda s: [s.draw(post(x, y)) for x, y in amp_posts(p)], 'join', 'Amp posts')
    part.prism('z', d.amp_z - 1, d.amp_z + M3_INSERT_DEPTH, lambda s: [
        s.circle(x, y, M3_INSERT) for x, y in amp_posts(p)], 'cut', 'Amp post inserts')
    return part


def build_amp_plate(design, p, d):
    part = Part(design, 'Amp plate')
    _, (x0, y0, x1, y1) = amp_layout(p)
    t, h = p.AmpPlateThickness, p.AmpStandoffHeight
    zf = d.amp_z                       # front face, on the Pi case's posts
    zb = zf - t                        # back face; the amp sits on posts here, its parts facing into the dash
    part.prism('z', zb, zf, lambda s: s.draw(rrect(x0, y0, x1, y1, 4.0)), 'new', 'Plate')
    part.name_body('Amp plate')
    part.prism('z', zb - h, zb + 0.5, lambda s: [s.circle(x, y, 7.0) for x, y in amp_holes(p)],
               'join', 'Amp standoffs')
    part.prism('z', zb - h - 1, zb - h + M2_INSERT_DEPTH, lambda s: [
        s.circle(x, y, M2_INSERT) for x, y in amp_holes(p)], 'cut', 'Amp insert holes')
    part.prism('z', zb - 1, zf + 1, lambda s: [s.circle(x, y, 3.4) for x, y in amp_posts(p)],
               'cut', 'Post screw holes')
    # Vents, so the air behind the Pi isn't closed in.
    (cx, _), _ = amp_layout(p)
    part.prism('z', zb - 1, zf + 1, lambda s: [
        s.draw(slot(cx + 15 * k, y0 + 14, cx + 15 * k, y1 - 14, 6.0)) for k in (-2, -1, 0, 1, 2)], 'cut', 'Vents')
    return part


def build_references(design, p, d):
    """Bodies to check fit against; not printed."""
    s = Part(design, 'Screen (reference)')
    s.prism('z', d.z_glass - p.ScreenDepth, d.z_glass, lambda k: k.draw(
        centred_rect(d.cx, d.scy, p.ScreenWidth, p.ScreenHeight, 2.0)), 'new')
    h = p.ScreenStandoffHeight
    bx0, bx1, by0, by1 = SCREEN_BOARD
    s.prism('z', d.face + h, d.z_glass - p.ScreenDepth, lambda k: k.draw(
        rrect(d.cx + bx0, d.scy + by0, d.cx + bx1, d.scy + by1)), 'new')

    pi = Part(design, 'Raspberry Pi 5 + DAC (reference)')
    z = -3 - p.PiStandoffHeight
    pi.prism('z', z - 1.6, z, lambda k: k.draw(rrect(p.PiX, p.PiY, p.PiX + PI_W, p.PiY + PI_H, 3.0)), 'new')
    pi.prism('z', z - p.PiStackHeight, z - 1.6, lambda k: k.draw(
        rrect(p.PiX, p.PiY, p.PiX + PI_W, p.PiY + PI_H, 3.0)), 'new')

    (acx, acy), _ = amp_layout(p)
    amp = Part(design, 'Amp (reference)')
    zb = d.amp_z - p.AmpPlateThickness - p.AmpStandoffHeight      # underside of the amp board
    amp.prism('z', zb - 1.6, zb, lambda k: k.draw(
        centred_rect(acx, acy, p.AmpBoardWidth, p.AmpBoardHeight, 2.0)), 'new')
    amp.prism('z', zb - p.AmpTotalHeight, zb - 1.6, lambda k: k.draw(
        centred_rect(acx, acy, p.AmpBoardWidth, p.AmpBoardHeight, 2.0)), 'new')

    cl = None
    if p.ClimateGap > 0:
        cl = Part(design, 'Climate controls (space)')
        cl.prism('z', 0, d.face - 4, lambda k: k.draw(rrect(0, 0, p.OpeningWidth, p.ClimateGap - 1)), 'new')

    fb = Part(design, 'Factory radio brackets (placeholder)')
    t = p.FactoryBracketThickness
    zb0, zb1 = -p.BezelReturnDepth - p.AdapterSideLength - 10, -p.BezelReturnDepth + 2
    yb0 = min(d.adapter_ys) - p.AdapterHeight / 2 - 10
    yb1 = max(d.adapter_ys) + p.AdapterHeight / 2 + 10
    for side in ('left', 'right'):
        _, wall, inward = adapter_geometry(p, side)
        xa, xb = sorted((wall, wall - inward * t))
        fb.prism('x', xa, xb, lambda k: k.draw(rrect(yb0, zb0, yb1, zb1, 2.0)), 'new')
        fb.prism('x', xa - 1, xb + 1, lambda k: [k.draw(slot(
            yc + dy, -p.BezelReturnDepth - 14, yc + dy, -p.BezelReturnDepth - 22, p.FactoryHoleDiameter))
            for yc in d.adapter_ys
            for dy in (-p.FactoryBracketHoleSpacing / 2, p.FactoryBracketHoleSpacing / 2)], 'cut')

    for part in [x for x in (s, pi, amp, cl, fb) if x]:
        for body in part.bodies:
            try:
                body.opacity = 0.35
            except Exception:
                pass


# ------------------------------------------------------------- running

def open_design(app, log):
    """The open Baja dash case design (cleared for a rebuild), or a new one."""
    design = adsk.fusion.Design.cast(app.activeProduct)
    if design and design.userParameters.itemByName('BajaCaseVersion'):
        root = design.rootComponent
        for i in range(root.occurrences.count - 1, -1, -1):
            root.occurrences.item(i).deleteMe()
        log.append('rebuilding the open Baja dash case design from its parameters')
        return design
    app.documents.add(adsk.core.DocumentTypes.FusionDesignDocumentType)
    design = adsk.fusion.Design.cast(app.activeProduct)
    design.designType = adsk.fusion.DesignTypes.ParametricDesignType
    try:
        design.fusionUnitsManager.distanceDisplayUnits = adsk.fusion.DistanceUnits.MillimeterDistanceUnits
    except Exception:
        pass
    design.userParameters.add('BajaCaseVersion', adsk.core.ValueInput.createByString(str(VERSION)), '',
                              'Marks this design as the Baja dash case; the script rebuilds it in place')
    log.append('made a new design')
    return design


def read_parameters(design, log):
    ups = design.userParameters
    for name in OBSOLETE:
        param = ups.itemByName(name)
        if param:
            try:
                param.deleteMe()
                log.append('removed unused parameter ' + name)
            except Exception:
                pass
    p = Params()
    for name, default, unit, note in PARAMETERS:
        param = ups.itemByName(name)
        if param is None:
            expr = '%g %s' % (default, unit) if unit else '%g' % default
            param = ups.add(name, adsk.core.ValueInput.createByString(expr), unit, note)
        v = param.value
        p[name] = math.degrees(v) if unit == 'deg' else (v * 10.0 if unit == 'mm' else v)
    return p


def export(design, parts, log):
    em = design.exportManager
    stl_dir = os.path.join(CASE_DIR, 'build')
    os.makedirs(stl_dir, exist_ok=True)
    for part, filename in parts:
        opts = em.createSTLExportOptions(part.body, os.path.join(stl_dir, filename))
        opts.meshRefinement = adsk.fusion.MeshRefinementSettings.MeshRefinementHigh
        opts.isBinaryFormat = True
        try:
            opts.sendToPrintUtility = False
        except Exception:
            pass
        em.execute(opts)
        log.append('wrote build/' + filename)
    em.execute(em.createSTEPExportOptions(os.path.join(CASE_DIR, 'baja-dash-case.step'), design.rootComponent))
    em.execute(em.createFusionArchiveExportOptions(os.path.join(CASE_DIR, 'baja-dash-case.f3d'),
                                                   design.rootComponent))
    log.append('wrote baja-dash-case.step and baja-dash-case.f3d')
    # Print-ready copies of the parts, each turned onto its best side.
    tool = os.path.join(CASE_DIR, 'make_print_files.py')
    g = {'__name__': 'make_print_files', '__file__': tool}
    exec(compile(open(tool).read(), tool, 'exec'), g)
    log.extend(g['make_all']())


def build(log):
    app = adsk.core.Application.get()
    design = open_design(app, log)
    p = read_parameters(design, log)
    d = derive(p)

    steps = [('panel', lambda: build_panel(design, p, d)),
             ('knob', lambda: build_knob(design, p, d))]
    for side in ('left', 'right'):
        for level, yc in zip(('lower', 'upper'), d.adapter_ys):
            steps.append(('adapter %s %s' % (level, side),
                          lambda side=side, level=level, yc=yc: build_adapter(design, p, d, side, level, yc)))
    steps += [('pi case', lambda: build_pi_case(design, p, d)),
              ('amp plate', lambda: build_amp_plate(design, p, d)),
              ('references', lambda: build_references(design, p, d))]
    built = {}
    failed = []
    for label, fn in steps:
        t = time.time()
        try:
            built[label] = fn()
            log.append('built %s (%.1f s)' % (label, time.time() - t))
        except Exception:
            failed.append(label)
            log.append('FAILED %s:\n%s' % (label, traceback.format_exc()))

    if not failed:
        try:
            export(design, [(built['panel'], 'dash-panel.stl'),
                            (built['knob'], 'volume-knob.stl'),
                            (built['adapter upper left'], 'adapter-plate-left.stl'),
                            (built['adapter upper right'], 'adapter-plate-right.stl'),
                            (built['pi case'], 'pi-case.stl'),
                            (built['amp plate'], 'amp-plate.stl')], log)
        except Exception:
            failed.append('export')
            log.append('FAILED export:\n' + traceback.format_exc())
    try:
        app.activeViewport.fit()
    except Exception:
        pass
    return failed


def run(context):
    log = []
    failed = build(log)
    print('\n'.join(log))
    print('Built the dash case' if not failed else 'Problems: ' + ', '.join(failed))
