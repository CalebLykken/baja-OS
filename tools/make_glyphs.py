"""Make MapLibre glyph files (signed-distance-field PBFs) from a font, so the
map's labels can use the dashboard's map font instead of the stock one.

    pip install freetype-py numpy scipy
    python3 tools/make_glyphs.py Overpass-Regular.ttf "Overpass Regular" web/map/fonts

Writes OUT/<name>/<start>-<end>.pbf for the Latin ranges the map needs;
anything else falls back to the stock Noto glyphs (backend/maps.py).

The format matches what MapLibre expects (and what Mapbox's fontnik and
TinySDF produce): glyphs drawn at 24 px with a 3 px border, distances
mapped with radius 8 and cutoff 0.25 (so the outline sits at 192/255),
and each glyph's top measured from the font's ascender.
"""

import math
import sys
from pathlib import Path

import freetype
import numpy as np
from scipy.ndimage import distance_transform_edt

SIZE, BUFFER, RADIUS, CUTOFF = 24, 3, 8, 0.25
OVERSAMPLE = 8
RANGES = [0, 256, 512, 7680, 8192, 8448]        # Latin, Latin Extended, punctuation, symbols


def _varint(n):
    out = bytearray()
    while True:
        b = n & 0x7F
        n >>= 7
        if n:
            out.append(b | 0x80)
        else:
            out.append(b)
            return bytes(out)


def _field(num, wire, payload):
    key = _varint((num << 3) | wire)
    if wire == 0:
        return key + _varint(payload)
    return key + _varint(len(payload)) + payload


def _zigzag(n):
    return (n << 1) ^ (n >> 31)


class GlyphMaker:
    def __init__(self, path):
        self.face = freetype.Face(str(path))
        self.face.set_pixel_sizes(0, SIZE)
        # Glyph tops are measured from the ascender (as fontnik does).
        self.ascender = math.floor(self.face.ascender * SIZE / self.face.units_per_EM)

    def glyph(self, cp):
        face = self.face
        if face.get_char_index(cp) == 0:
            return None
        face.set_pixel_sizes(0, SIZE)
        face.load_char(cp, freetype.FT_LOAD_NO_BITMAP | freetype.FT_LOAD_NO_HINTING)
        advance = face.glyph.advance.x // 64           # truncated, as fontnik does
        box = face.glyph.outline.get_bbox()
        if box.xMax <= box.xMin or box.yMax <= box.yMin:
            return {"id": cp, "w": 0, "h": 0, "left": 0, "top": -self.ascender, "adv": advance, "bitmap": b""}
        xmin, xmax = round(box.xMin / 64), round(box.xMax / 64)
        ymin, ymax = round(box.yMin / 64), round(box.yMax / 64)
        w, h = xmax - xmin, ymax - ymin

        # Draw it OVERSAMPLE times larger, placed on a canvas that covers the
        # glyph plus its border, so distances can be measured finely.
        face.set_pixel_sizes(0, SIZE * OVERSAMPLE)
        face.load_char(cp, freetype.FT_LOAD_RENDER | freetype.FT_LOAD_NO_HINTING)
        bm = face.glyph.bitmap
        gray = np.array(bm.buffer, dtype=np.uint8).reshape(bm.rows, bm.pitch)[:, :bm.width] if bm.rows else np.zeros((0, 0), np.uint8)
        cw, ch = (w + 2 * BUFFER) * OVERSAMPLE, (h + 2 * BUFFER) * OVERSAMPLE
        canvas = np.zeros((ch, cw), dtype=bool)
        # Canvas origin (top-left) is at (xmin - BUFFER, ymax + BUFFER) in 24 px units.
        ox = face.glyph.bitmap_left - (xmin - BUFFER) * OVERSAMPLE
        oy = (ymax + BUFFER) * OVERSAMPLE - face.glyph.bitmap_top
        y0, x0 = max(0, oy), max(0, ox)
        y1, x1 = min(ch, oy + gray.shape[0]), min(cw, ox + gray.shape[1])
        if y1 > y0 and x1 > x0:
            canvas[y0:y1, x0:x1] = gray[y0 - oy:y1 - oy, x0 - ox:x1 - ox] >= 128

        # Signed distance in 24 px units: positive outside, negative inside.
        outside = distance_transform_edt(~canvas)
        inside = distance_transform_edt(canvas)
        signed = (outside - inside) / OVERSAMPLE
        # Sample at the centre of each 24 px pixel.
        c = OVERSAMPLE // 2
        d = signed[c::OVERSAMPLE, c::OVERSAMPLE][:h + 2 * BUFFER, :w + 2 * BUFFER]
        alpha = np.clip(np.round(255 - 255 * (d / RADIUS + CUTOFF)), 0, 255).astype(np.uint8)
        return {"id": cp, "w": w, "h": h, "left": xmin, "top": ymax - self.ascender, "adv": advance,
                "bitmap": alpha.tobytes()}


def encode_range(maker, name, start):
    end = start + 255
    glyphs = b""
    for cp in range(start, end + 1):
        g = maker.glyph(cp)
        if not g:
            continue
        body = _field(1, 0, g["id"])
        if g["bitmap"]:
            body += _field(2, 2, g["bitmap"])
        body += (_field(3, 0, g["w"]) + _field(4, 0, g["h"]) + _field(5, 0, _zigzag(g["left"]))
                 + _field(6, 0, _zigzag(g["top"])) + _field(7, 0, g["adv"]))
        glyphs += _field(3, 2, body)
    stack = _field(1, 2, name.encode()) + _field(2, 2, f"{start}-{end}".encode()) + glyphs
    return _field(1, 2, stack)


def main():
    font, name, out = sys.argv[1], sys.argv[2], Path(sys.argv[3])
    maker = GlyphMaker(font)
    folder = out / name
    folder.mkdir(parents=True, exist_ok=True)
    for start in RANGES:
        (folder / f"{start}-{start + 255}.pbf").write_bytes(encode_range(maker, name, start))
    print(f"{name}: {len(RANGES)} ranges in {folder}")


if __name__ == "__main__":
    main()
