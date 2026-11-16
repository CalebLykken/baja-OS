"""Make qml/assets/truck/BajaModel.qml from Qt's balsam output for the Baja.

The Truck page used to parse baja-3d.glb at run time (RuntimeLoader), which
also left its materials out of reach. balsam converts it once to Qt's own
mesh files; this then fixes up the QML it writes:

- colours: glTF stores them linear, but balsam writes them where Qt expects
  ordinary screen colours, so the paint came out orange and the grey
  cladding black. They're converted back here.
- materials: glossy Atlantic Blue paint, matte cladding in the same blue,
  dark tinted glass (no see-through muddle or jagged reflections), headlight
  covers you can see the chrome through, satin wheels.
- the model's own "HUMSTER3D" plates are hidden; it draws plate.png, a
  BAJA plate, for TruckPage to put on instead.
- the cab interior is hidden (nothing shows through the tinted glass).

    balsam qml/assets/baja-3d.glb -o OUT        (from Qt 6 / PySide6)
    python3 tools/convert_truck.py OUT/Baja_3d.qml qml/assets/truck
    cp OUT/meshes/*.mesh qml/assets/truck/meshes/
"""
import re
import sys
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

ROOT = Path(__file__).resolve().parent.parent

# objectName prefix -> properties to set (replacing balsam's).
MATERIALS = {
    # Glossy solid paint in the truck's own colour, Atlantic Blue Pearl
    # (Subaru 33A, #2A4C7A on the portfolio site); the 2005-06 Baja wore it
    # monotone, so the cladding is the same blue, matte. The Truck page's
    # studio light and filmic tone map lift paint a lot: #2A4C7A came out a
    # light sky blue there, so the base is deeper (#1D3557) to look like the
    # boot screen's render of the real colour. (Metallic paint mirrors the
    # dark studio and goes brown; Qt's clear coat darkens this model's paint
    # the same way.)
    "carpaint.": {"baseColor": '"#1d3557"', "metalness": "0", "roughness": "0.24"},
    "carpaint_second": {"baseColor": '"#1d3557"', "metalness": "0", "roughness": "0.75"},
    "clearglass": {"baseColor": '"#0d1013"', "roughness": "0.8", "metalness": "0", "specularAmount": "0.08",
                   "cullMode": "PrincipledMaterial.BackFaceCulling", "alphaMode": "PrincipledMaterial.Opaque"},
    "windowglass": {"baseColor": '"#0d1013"', "roughness": "0.8", "metalness": "0", "specularAmount": "0.08",
                    "cullMode": "PrincipledMaterial.BackFaceCulling", "alphaMode": "PrincipledMaterial.Opaque"},
    "darkglass": {"baseColor": '"#0a0b0d"', "roughness": "0.8", "metalness": "0", "specularAmount": "0.08",
                  "cullMode": "PrincipledMaterial.BackFaceCulling", "alphaMode": "PrincipledMaterial.Opaque"},
    # The thin glass shells draw only their outer face (the inner one mirrored
    # the studio panels a second time and z-fought), with a rough, dim lobe so
    # the bright panels blur into a soft grade instead of jagged white streaks.
    # The small bright metal parts are roughened a touch for the same reason.
    "mirror.": {"roughness": "0.08"},
    "chrome.": {"roughness": "0.1"},
    "lens_clear": {"baseColor": '"#ffffff"', "opacity": "0.22", "roughness": "0.03",
                   "alphaMode": "PrincipledMaterial.Blend"},
    "rim.": {"roughness": "0.35"},
    "tire.": {"roughness": "0.9"},
    "brakedisk.": {"roughness": "0.5"},
}
HIDDEN = {"body", "body_010", "body_011", "body_012", "body_013"}   # plates, interior


def to_srgb(c):
    return 12.92 * c if c <= 0.0031308 else 1.055 * c ** (1 / 2.4) - 0.055


def fix_colour(m):
    a, rgb = m[1][:2], m[1][2:]
    lin = [int(rgb[i:i + 2], 16) / 255 for i in (0, 2, 4)]
    return 'baseColor: "#%s%s"' % (a, "".join("%02x" % round(to_srgb(c) * 255) for c in lin))


def fix_material(block):
    name = re.search(r'objectName: "([^"]+)"', block)
    block = re.sub(r'baseColor: "#([0-9a-f]{8})"', fix_colour, block)
    for prefix, props in MATERIALS.items():
        if name and name[1].startswith(prefix):
            for key, value in props.items():
                if re.search(rf"\n\s*{key}: ", block):
                    block = re.sub(rf"(\n\s*){key}: [^\n]*", rf"\g<1>{key}: {value}", block)
                else:
                    block = block.replace("\n    }", f"\n        {key}: {value}\n    }}")
    return block


src, out = Path(sys.argv[1]), Path(sys.argv[2])
qml = src.read_text()
qml = re.sub(r"    PrincipledMaterial \{.*?\n    \}", lambda m: fix_material(m[0]), qml, flags=re.S)
for node in HIDDEN:
    qml = qml.replace(f"            id: {node}\n", f"            id: {node}\n            visible: false\n")
header = ("// The Baja, converted from baja-3d.glb by Qt's balsam and fixed up by\n"
          "// tools/convert_truck.py (colours, materials, plates). Generated: edit\n"
          "// that script rather than this file.\n")
out.mkdir(parents=True, exist_ok=True)
(out / "BajaModel.qml").write_text(header + qml)
print("wrote", out / "BajaModel.qml")

# The plate: the model's plate size (520 x 110 mm), white with BAJA on it.
W, H = 1040, 220
plate = Image.new("RGB", (W, H), "#f2f2ee")
draw = ImageDraw.Draw(plate)
draw.rounded_rectangle((4, 4, W - 5, H - 5), 18, outline="#2a2a2a", width=8)
font = ImageFont.truetype(str(ROOT / "qml/assets/fonts/Overpass-Bold.ttf"), 168)
text = "B A J A"
box = draw.textbbox((0, 0), text, font=font)
draw.text(((W - (box[2] - box[0])) / 2 - box[0], (H - (box[3] - box[1])) / 2 - box[1]), text,
          font=font, fill="#1b2a4e")
plate.save(out / "plate.png", optimize=True)
print("wrote", out / "plate.png")

# The floor under the truck on the Truck page: a soft oval of light (for a
# dark page) or shade (for a light one); pictures, as the Pi's Qt has no
# blur effect.
glow = Image.new("L", (512, 128), 0)
px = glow.load()
for y in range(128):
    for x in range(512):
        d = ((x - 255.5) / 256) ** 2 + ((y - 63.5) / 64) ** 2
        px[x, y] = round(255 * max(0.0, 1 - d) ** 1.6)
for name, rgb in (("floor.png", (255, 255, 255)), ("floor-shade.png", (0, 0, 0))):
    floor = Image.new("RGBA", glow.size, rgb + (0,))
    floor.putalpha(glow)
    floor.save(out / name, optimize=True)
    print("wrote", out / name)
