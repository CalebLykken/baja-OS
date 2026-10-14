"""Write qml/assets/studio.hdr: a small equirectangular studio environment
(soft overhead box, two side strips, a warm rim) that lights the Truck page.

    python3 tools/make_studio_hdr.py qml/assets/studio.hdr

Then pre-filter it into the cubemap the page actually loads, with Qt's
balsam from the same Qt version as the Pi (pip install PySide6==6.8.2
ships it as PySide6/balsam):

    balsam -o qml/assets qml/assets/studio.hdr      # writes studio.ktx

Loading the .hdr directly makes Qt filter it on the Pi's CPU, which froze
the Truck page for 7 s the first time it opened.
"""
import math
import sys

W, H = 256, 128   # small: it is blurred for lighting anyway, and prefilters fast


def env(u, v):
    lon = (u - 0.5) * 2 * math.pi
    lat = (0.5 - v) * math.pi
    # Room: mid-grey walls, brighter overhead, darker floor.
    base = 0.22 + 0.25 * max(0.0, math.sin(lat)) - 0.12 * max(0.0, -math.sin(lat))
    rgb = [base, base, base]

    def box(lon0, lat0, wlon, wlat, power, tint=(1, 1, 1)):
        dl = math.atan2(math.sin(lon - lon0), math.cos(lon - lon0))
        x, y = dl / wlon, (lat - lat0) / wlat
        if abs(x) < 1 and abs(y) < 1:
            soft = (1 - x ** 8) * (1 - y ** 8)
            for i in range(3):
                rgb[i] += power * tint[i] * soft

    box(0.0, math.radians(75), math.radians(60), math.radians(12), 14.0)                  # overhead
    box(math.radians(70), math.radians(20), math.radians(10), math.radians(25), 6.0)      # side strip
    box(math.radians(-70), math.radians(20), math.radians(10), math.radians(25), 5.0)     # side strip
    box(math.radians(180), math.radians(15), math.radians(30), math.radians(10), 4.0, (1.0, 0.82, 0.62))  # rim
    return rgb


def rgbe(r, g, b):
    m = max(r, g, b)
    if m < 1e-32:
        return bytes((0, 0, 0, 0))
    e = math.frexp(m)[1]
    s = 256.0 / (2.0 ** e)
    return bytes((int(r * s), int(g * s), int(b * s), e + 128))


with open(sys.argv[1], "wb") as f:
    f.write(b"#?RADIANCE\nFORMAT=32-bit_rle_rgbe\n\n")
    f.write(f"-Y {H} +X {W}\n".encode())
    for y in range(H):
        f.write(b"".join(rgbe(*env((x + 0.5) / W, (y + 0.5) / H)) for x in range(W)))
print("wrote", sys.argv[1])
