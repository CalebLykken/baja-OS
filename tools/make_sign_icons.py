"""Make the map's traffic light, stop and yield icons (web/map/icons/*.png)
from the real artwork in tools/sign-icons (see its README): sized for the
map at twice screen resolution, the dark traffic light with a thin white
edge so it shows on the night map, and all with a soft shadow.

    python3 tools/make_sign_icons.py        (needs PyQt6 and Pillow)
"""
import sys
from pathlib import Path

from PIL import Image, ImageFilter
from PyQt6.QtCore import QRectF
from PyQt6.QtGui import QGuiApplication, QImage, QPainter
from PyQt6.QtSvg import QSvgRenderer

ROOT = Path(__file__).resolve().parent.parent
SRC, OUT = ROOT / "tools/sign-icons", ROOT / "web/map/icons"
PAD = 6                       # room for the edge and shadow


def from_svg(path, w, h):
    img = QImage(w, h, QImage.Format.Format_RGBA8888)
    img.fill(0)
    p = QPainter(img)
    QSvgRenderer(str(path)).render(p, QRectF(0, 0, w, h))
    p.end()
    return Image.frombuffer("RGBA", (w, h), bytes(img.constBits().asarray(w * h * 4)), "raw", "RGBA", 0, 1)


def finish(im, edge=0):
    """Pad, optionally ring with white, and drop a soft shadow under it."""
    w, h = im.size
    out = Image.new("RGBA", (w + 2 * PAD, h + 2 * PAD), (0, 0, 0, 0))
    a = Image.new("L", out.size, 0)
    a.paste(im.getchannel("A"), (PAD, PAD))
    shadow = a.filter(ImageFilter.GaussianBlur(2.5)).point(lambda v: v * 0.45)
    shade = Image.new("RGBA", out.size, (0, 0, 0, 0))
    shade.putalpha(shadow)
    out.alpha_composite(shade, (0, 2))
    if edge:
        ring = a.filter(ImageFilter.MaxFilter(2 * edge + 1))
        white = Image.new("RGBA", out.size, (255, 255, 255, 0))
        white.putalpha(ring)
        out.alpha_composite(white)
    out.alpha_composite(im, (PAD, PAD))
    return out


app = QGuiApplication(sys.argv[:1] + ["-platform", "offscreen"])
OUT.mkdir(parents=True, exist_ok=True)
finish(from_svg(SRC / "stop-R1-1.svg", 60, 60)).save(OUT / "stop.png", optimize=True)
finish(from_svg(SRC / "yield-R1-2.svg", 62, 54)).save(OUT / "yield.png", optimize=True)
light = Image.open(SRC / "traffic-light-noto.png").convert("RGBA")
light = light.resize((round(72 * light.width / light.height), 72), Image.LANCZOS)
finish(light, edge=2).save(OUT / "signal.png", optimize=True)
for name in ("stop", "yield", "signal"):
    print(name, Image.open(OUT / f"{name}.png").size)
