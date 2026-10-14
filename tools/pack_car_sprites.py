"""Pack the frames from tools/render_car_sprites.py into one picture for the
map: web/map/car.webp (one row-major grid: tilt by tilt, heading by heading)
and web/map/car.json (how to find a frame in it).

    python3 tools/pack_car_sprites.py FRAMES_DIR web/map
"""
import json
import os
import sys

from PIL import Image, ImageFilter

COLS = 16
HAZE = 14            # alpha below this, away from the truck, is ground haze


def clean(im):
    """Keep the truck and its shadow; drop the faint haze the shadow-catching
    ground leaves across the whole frame (it shows as a box on a light map)."""
    a = im.getchannel("A")
    near = a.point(lambda v: 255 if v >= 250 else 0).filter(ImageFilter.MaxFilter(5))
    shadow = a.point(lambda v: 0 if v < HAZE else round((v - HAZE) * 255 / (255 - HAZE)))
    out = Image.new("RGBA", im.size, (0, 0, 0, 0))
    out.putalpha(shadow)
    return Image.composite(im, out, near)


src, out = sys.argv[1], sys.argv[2]
meta = json.load(open(os.path.join(src, "frames.json")))
size, headings = meta["frame"], meta["headings"]
count = headings * len(meta["tilts"])
rows = -(-count // COLS)
sheet = Image.new("RGBA", (COLS * size, rows * size), (0, 0, 0, 0))
for t, tilt in enumerate(meta["tilts"]):
    for h in range(headings):
        i = t * headings + h
        im = clean(Image.open(os.path.join(src, f"t{tilt['elevation']}_h{h:02d}.png")).convert("RGBA"))
        sheet.paste(im, ((i % COLS) * size, (i // COLS) * size))
# WebP: a third the size of PNG and no visible difference at this size.
sheet.save(os.path.join(out, "car.webp"), "WEBP", quality=92, method=6, alpha_quality=95)
json.dump({"frame": size, "headings": headings, "cols": COLS, "rows": rows, "tilts": meta["tilts"]},
          open(os.path.join(out, "car.json"), "w"), indent=1)
print(f"car.webp {sheet.size[0]}x{sheet.size[1]}, {count} frames,",
      f"{os.path.getsize(os.path.join(out, 'car.webp')) / 1e6:.1f} MB")
