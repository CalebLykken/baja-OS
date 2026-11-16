"""Render side-profile and hero stills (baja-side.png, baja-hero.png) from the
portfolio's baja.glb with Blender. The boot screen and splash now use
tools/render_boot.py's Atlantic Blue three-quarter render instead.

    blender -b --python tools/render_stills.py -- path/to/baja.glb OUTDIR

Prints the headlight position in the side view (0..1), which Splash.qml
uses to place the glow.
"""
import bpy, sys, math, json
from mathutils import Vector
from bpy_extras.object_utils import world_to_camera_view

src, out = sys.argv[-2], sys.argv[-1]
bpy.ops.wm.read_factory_settings(use_empty=True)
bpy.ops.import_scene.gltf(filepath=src)
sc = bpy.context.scene
sc.render.engine = 'BLENDER_EEVEE'
sc.render.film_transparent = True
sc.render.image_settings.file_format = 'PNG'
sc.render.image_settings.color_mode = 'RGBA'
try: sc.eevee.taa_render_samples = 64
except Exception: pass
sc.view_settings.view_transform = 'AgX'

# Eevee renders the model's transmissive glass as white blotches, so make
# every see-through material a dark glossy tint instead.
for m in bpy.data.materials:
    if not m.use_nodes:
        continue
    for n in m.node_tree.nodes:
        if n.type == 'BSDF_PRINCIPLED':
            t = n.inputs.get("Transmission Weight")
            if t is not None and t.default_value > 0.01:
                print("GLASS", m.name)
                t.default_value = 0.0
                tint = {"lens_red": (0.45, 0.02, 0.02), "lens_brake": (0.45, 0.02, 0.02),
                        "lens_amber": (0.75, 0.32, 0.03), "lens_clear": (0.55, 0.57, 0.6)}
                rgb = next((v for k, v in tint.items() if m.name.startswith(k)), (0.01, 0.012, 0.015))
                n.inputs["Base Color"].default_value = (*rgb, 1)
                n.inputs["Roughness"].default_value = 0.04
                n.inputs["Metallic"].default_value = 0.0
                if n.inputs.get("Coat Weight") is not None:
                    n.inputs["Coat Weight"].default_value = 0.0

w = bpy.data.worlds.new("w"); sc.world = w; w.use_nodes = True
w.node_tree.nodes["Background"].inputs[0].default_value = (0.05, 0.055, 0.06, 1)
w.node_tree.nodes["Background"].inputs[1].default_value = 0.6

def area(name, loc, rot, size, energy, color=(1, 1, 1)):
    d = bpy.data.lights.new(name, 'AREA'); d.size = size; d.energy = energy; d.color = color
    o = bpy.data.objects.new(name, d); o.location = loc; o.rotation_euler = rot
    sc.collection.objects.link(o)
area("key",  (0, 0, 6),     (0, 0, 0),                     7, 2500)
area("fill", (6, -2, 1.5),  (math.radians(80), 0, math.radians(70)), 5, 900)
area("rim",  (-4, 5, 3),    (math.radians(-60), 0, math.radians(-140)), 5, 700, (1, 0.85, 0.7))

cam_d = bpy.data.cameras.new("cam"); cam = bpy.data.objects.new("cam", cam_d)
sc.collection.objects.link(cam); sc.camera = cam

def look(loc, target):
    cam.location = loc
    cam.rotation_euler = (Vector(target) - Vector(loc)).to_track_quat('-Z', 'Y').to_euler()

def headlight_px():
    o = bpy.data.objects["Refl_head"]
    pts = [o.matrix_world @ Vector(c) for c in o.bound_box]
    # The nearer (driver-side, +X) half of the reflector is what's visible from the side.
    near = [p for p in pts if p.x > 0] or pts
    c = sum(near, Vector()) / len(near)
    v = world_to_camera_view(sc, cam, c)
    return [round(v.x, 4), round(1 - v.y, 4)]   # 0..1, origin top-left

meta = {}

# 1) Three-quarter front, driver side: the Home hero.
sc.render.resolution_x, sc.render.resolution_y = 1400, 860
cam_d.type = 'PERSP'; cam_d.lens = 50
look((5.6, -6.4, 2.0), (0, -0.15, 0.78))
sc.render.filepath = out + "/baja-hero.png"; bpy.ops.render.render(write_still=True)

# 2) Side profile, front facing left, headlights off then on: the splash.
sc.render.resolution_x, sc.render.resolution_y = 1600, 640
cam_d.type = 'ORTHO'; cam_d.ortho_scale = 5.5
look((9, -0.05, 0.86), (0, -0.05, 0.86))
sc.render.filepath = out + "/baja-side.png"; bpy.ops.render.render(write_still=True)
meta["side_headlight"] = headlight_px()

json.dump(meta, open(out + "/baja-meta.json", "w"))
print("META", meta)
