"""Draw qml/assets/shadow.png: the soft shadow under the map's floating
panels, as a nine-patch for BorderImage (the Pi's Qt has no shadow effect,
and a picture costs nothing to draw anyway).

    python3 tools/make_shadow.py qml/assets/shadow.png
"""
import sys

from PIL import Image, ImageDraw, ImageFilter

SIZE, MARGIN, RADIUS, BLUR, ALPHA = 144, 36, 24, 10, 70

mask = Image.new("L", (SIZE, SIZE), 0)
ImageDraw.Draw(mask).rounded_rectangle((MARGIN, MARGIN, SIZE - MARGIN, SIZE - MARGIN), RADIUS, fill=ALPHA)
mask = mask.filter(ImageFilter.GaussianBlur(BLUR))
shadow = Image.new("RGBA", (SIZE, SIZE), (0, 0, 0, 0))
shadow.putalpha(mask)
shadow.save(sys.argv[1], optimize=True)
