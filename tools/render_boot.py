"""Render the boot-screen truck: the Baja three-quarters from the front, in
Atlantic Blue Pearl (Subaru 33A, monotone on the 2005-06 Baja), on the
screens' near-black (#050506) with a soft ground shadow.

    /Applications/Blender.app/Contents/MacOS/Blender -b --python tools/render_boot.py -- \
        256 qml/assets/baja-3d.glb OUTDIR       # samples, model, output folder

Writes OUTDIR/baja-boot.png and OUTDIR/baja-boot.json, which has both
headlights' positions in the image (0..1, origin top-left); Splash.qml uses
them to place the headlight glow. The paint values come from the portfolio
site's paintData.js / BajaScene.js (#2A4C7A, its "pearl" finish; cladding the
same colour, far rougher), so the truck looks the same in both places.
"""
import bpy, sys, math, json
from mathutils import Vector
from bpy_extras.object_utils import world_to_camera_view

src, out = sys.argv[-2], sys.argv[-1]
BODY_HEX = "#2A4C7A"
PEARL = dict(metallic=0.46, roughness=0.21, coat_roughness=0.026)


def linear(hex_):
    def ch(c):
        c = int(c, 16) / 255
        return c / 12.92 if c <= 0.04045 else ((c + 0.055) / 1.055) ** 2.4
    h = hex_.lstrip("#")
    return (ch(h[0:2]), ch(h[2:4]), ch(h[4:6]), 1.0)


bpy.ops.wm.read_factory_settings(use_empty=True)
bpy.ops.import_scene.gltf(filepath=src)
sc = bpy.context.scene

sc.render.engine = 'CYCLES'
sc.cycles.samples = int(sys.argv[-3]) if sys.argv[-3].isdigit() else 192
sc.cycles.use_denoising = True
try:
    prefs = bpy.context.preferences.addons["cycles"].preferences
    prefs.compute_device_type = "METAL"
    prefs.get_devices()
    for d in prefs.devices:
        d.use = True
    sc.cycles.device = "GPU"
except Exception as e:
    print("GPU unavailable, CPU render:", e)
sc.render.film_transparent = True
sc.render.image_settings.file_format = 'PNG'
sc.render.image_settings.color_mode = 'RGBA'
sc.view_settings.view_transform = 'AgX'
sc.view_settings.look = 'AgX - Punchy'
sc.view_settings.exposure = -0.9         # keep the blue deep; the boot screen is near-black

body = linear(BODY_HEX)
for m in bpy.data.materials:
    if not m.use_nodes:
        continue
    for n in m.node_tree.nodes:
        if n.type != 'BSDF_PRINCIPLED':
            continue
        name = m.name
        if name.startswith("carpaint_second"):          # cladding: same pigment, textured
            n.inputs["Base Color"].default_value = body
            n.inputs["Metallic"].default_value = PEARL["metallic"] * 0.3
            n.inputs["Roughness"].default_value = 0.56
            n.inputs["Coat Weight"].default_value = 0.0
        elif name.startswith("carpaint"):               # body panels: pearl under clear
            n.inputs["Base Color"].default_value = body
            n.inputs["Metallic"].default_value = PEARL["metallic"]
            n.inputs["Roughness"].default_value = PEARL["roughness"]
            n.inputs["Coat Weight"].default_value = 1.0
            n.inputs["Coat Roughness"].default_value = PEARL["coat_roughness"]
        elif name.startswith("rim"):                    # the model's rims are matte; give them some sheen
            n.inputs["Roughness"].default_value = 0.3
        elif name.startswith(("clearglass", "windowglass", "darkglass")):
            # Dark tinted glass, as in the app (tools/convert_truck.py): the
            # model's glass is faceted, so a sharp reflection of the sky came
            # out as jagged white shapes. Rougher, with a weaker reflection.
            n.inputs["Transmission Weight"].default_value = 0.0
            n.inputs["Base Color"].default_value = (0.006, 0.007, 0.009, 1)
            n.inputs["Metallic"].default_value = 0.0
            n.inputs["Roughness"].default_value = 0.45
            n.inputs["Specular IOR Level"].default_value = 0.2
            n.inputs["Alpha"].default_value = 1.0

# The model maker's "HUMSTER3D" plates come off (the app hides them too):
# a clean bumper rather than a blank plate with the maker's flag on it.
for o in bpy.data.objects:
    if o.type == 'MESH' and any(s.material and s.material.name.startswith("LicPlate")
                                for s in o.material_slots):
        o.hide_render = True
    if o.name == "Body.010":                     # the cab interior: nothing shows through tinted glass
        o.hide_render = True

# A smooth sky for reflections, dark at the horizon and light overhead: the
# studio HDR's softboxes showed up as white blotches in the windscreen. Kept
# out of the background itself (the film is transparent).
w = bpy.data.worlds.new("w"); sc.world = w; w.use_nodes = True
nt = w.node_tree
bg = nt.nodes["Background"]
coord = nt.nodes.new("ShaderNodeTexCoord")
sep = nt.nodes.new("ShaderNodeSeparateXYZ")
ramp = nt.nodes.new("ShaderNodeValToRGB")
nt.links.new(coord.outputs["Generated"], sep.inputs[0])
nt.links.new(sep.outputs["Z"], ramp.inputs["Fac"])
nt.links.new(ramp.outputs["Color"], bg.inputs["Color"])
cr = ramp.color_ramp
cr.elements[0].position, cr.elements[0].color = 0.45, (0.004, 0.005, 0.007, 1)
cr.elements[1].position, cr.elements[1].color = 0.95, (0.55, 0.6, 0.68, 1)
bg.inputs["Strength"].default_value = 0.8


def area(name, loc, target, size, energy, color=(1, 1, 1)):
    d = bpy.data.lights.new(name, 'AREA'); d.size = size; d.energy = energy; d.color = color
    o = bpy.data.objects.new(name, d); o.location = loc
    o.rotation_euler = (Vector(target) - Vector(loc)).to_track_quat('-Z', 'Y').to_euler()
    sc.collection.objects.link(o)

# Key overhead and a touch forward, a cool fill from the camera side, and two
# rims behind: dark blue on a near-black screen needs its outline lit.
area("key",   (0.5, -1.0, 6.5),  (0, 0, 0.6), 6, 1800)
area("fill",  (6.5, -5.0, 1.6),  (0, 0, 0.7), 4, 450, (0.85, 0.9, 1.0))
area("rimL",  (-5.5, 3.5, 2.6),  (0, 0, 0.8), 4, 1300, (0.75, 0.85, 1.0))
area("rimR",  (4.5, 5.5, 2.4),   (0, 0, 0.8), 4, 900, (1.0, 0.92, 0.85))
area("front", (-2.5, -7.0, 1.2), (0, -1, 0.6), 3, 250)

# Ground that only catches the shadow.
bpy.ops.mesh.primitive_plane_add(size=30, location=(0, 0, 0))
ground = bpy.context.active_object
ground.is_shadow_catcher = True

cam_d = bpy.data.cameras.new("cam"); cam = bpy.data.objects.new("cam", cam_d)
sc.collection.objects.link(cam); sc.camera = cam
cam_d.type = 'PERSP'; cam_d.lens = 58


def look(loc, target):
    cam.location = loc
    cam.rotation_euler = (Vector(target) - Vector(loc)).to_track_quat('-Z', 'Y').to_euler()


def lens_centre(obj_name, side):
    o = bpy.data.objects[obj_name]
    pts = [o.matrix_world @ Vector(c) for c in o.bound_box]
    half = [p for p in pts if (p.x > 0) == (side > 0)] or pts
    c = sum(half, Vector()) / len(half)
    v = world_to_camera_view(sc, cam, c)
    return [round(v.x, 4), round(1 - v.y, 4)]


sc.render.resolution_x, sc.render.resolution_y = 1800, 1000
look((6.2, -7.4, 2.15), (0.0, -0.35, 0.72))
sc.render.filepath = out + "/baja-boot-full.png"
bpy.ops.render.render(write_still=True)
heads = {"near_headlight": lens_centre("Refl_head", +1),
         "far_headlight": lens_centre("Refl_head", -1)}

# Crop to what's drawn (the shadow's faint edge doesn't count), plus a margin,
# and move the headlight positions into the cropped frame.
import numpy as np
W, H = sc.render.resolution_x, sc.render.resolution_y
img = bpy.data.images.load(out + "/baja-boot-full.png")
px = np.array(img.pixels[:], dtype=np.float32).reshape(H, W, 4)   # bottom row first
# The truck is what's opaque and lit; the shadow is opaque but black. Keep a
# little of the shadow under the wheels (rows are bottom-first, so it's y0).
truck = (px[:, :, 3] > 0.25) & (px[:, :, :3].max(axis=2) > 0.03)
ys, xs = np.nonzero(truck)
pad, shadow = 12, 36
x0, x1 = max(0, xs.min() - pad), min(W, xs.max() + pad + 1)
y0, y1 = max(0, ys.min() - shadow), min(H, ys.max() + pad + 1)
crop = px[y0:y1, x0:x1].copy()
cw, ch = x1 - x0, y1 - y0
# Flatten onto the screens' own background (#050506, Splash.qml and the
# Plymouth theme): the shadow catcher darkens the whole ground plane, so left
# transparent the picture's edges showed as a faint box on the screen. The
# pixels are the PNG's stored (sRGB) values, straight alpha.
bg = np.array([5, 5, 6], dtype=np.float32) / 255
# The ground catches a little shadow everywhere (sky and area lights), so fade
# the shadow out towards the picture's edges; the truck itself is untouched.
ramp = 90.0
yy, xx = np.mgrid[0:ch, 0:cw].astype(np.float32)
edge = np.minimum.reduce([xx, cw - 1 - xx, yy, ch - 1 - yy]) / ramp
fade = np.clip(edge, 0, 1) ** 1.5
shade = ~truck[y0:y1, x0:x1]
crop[:, :, 3] = np.where(shade, crop[:, :, 3] * fade, crop[:, :, 3])
a = crop[:, :, 3:4]
crop[:, :, :3] = crop[:, :, :3] * a + bg * (1 - a)
crop[:, :, 3] = 1.0
out_img = bpy.data.images.new("crop", cw, ch, alpha=True)
out_img.pixels[:] = crop.ravel()
out_img.filepath_raw = out + "/baja-boot.png"
out_img.file_format = 'PNG'
out_img.save()
top = H - y1                                    # crop's top edge, from the image top
meta = {k: [round((v[0] * W - x0) / cw, 4), round((v[1] * H - top) / ch, 4)]
        for k, v in heads.items()}
meta["size"] = [int(cw), int(ch)]
json.dump(meta, open(out + "/baja-boot.json", "w"))
print("META", meta)
