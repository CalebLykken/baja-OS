"""Render the map's 3D truck: the Baja from 64 directions at three camera
tilts, each a small picture on a transparent background with its own soft
shadow. The map shows the frame that matches which way the truck points on
screen (and how far the map is tilted), so it looks like a real 3D car,
like the car icons in Google Maps, for the cost of drawing one picture.

    blender -b --python tools/render_car_sprites.py -- path/to/baja.glb OUT_DIR

writes OUT_DIR/t<tilt>_h<heading>.png and OUT_DIR/frames.json; then
tools/pack_car_sprites.py packs them into web/map/car.webp and car.json.
"""
import bpy, sys, math, json, os
from mathutils import Vector

src, out = sys.argv[-2], sys.argv[-1]
os.makedirs(out, exist_ok=True)

FRAME = 160                  # pixels per frame (shown at ~76 CSS px, x1.7 on the Pi)
HEADINGS = int(os.environ.get("HEADINGS", 64))   # 5.625 degrees apart; the map turns the rest
# Camera height above the horizon for each tilt set, and the smallest map
# pitch it's used from. Even a flat map gets a slightly raised view, so the
# truck always reads as a solid 3D car.
TILTS = [(68, 0), (54, 25), (42, 45)]
VIEW = 5.6                   # metres across a frame

bpy.ops.wm.read_factory_settings(use_empty=True)
bpy.ops.import_scene.gltf(filepath=src)
sc = bpy.context.scene

# ---- materials: dark tinted glass, glossy paint -------------------------------------
tint = {"lens_red": (0.5, 0.02, 0.02), "lens_brake": (0.5, 0.02, 0.02),
        "lens_amber": (0.8, 0.35, 0.03), "lens_clear": (0.7, 0.72, 0.75)}
for m in bpy.data.materials:
    if not m.use_nodes:
        continue
    for n in m.node_tree.nodes:
        if n.type != 'BSDF_PRINCIPLED':
            continue
        t = n.inputs.get("Transmission Weight")
        if t is not None and t.default_value > 0.01 or m.blend_method == 'BLEND' or "glass" in m.name:
            # Opaque dark glass with a sky reflection: reads at icon size
            # (see-through glass shows a muddle of seats).
            if t is not None:
                t.default_value = 0.0
            rgb = next((v for k, v in tint.items() if m.name.startswith(k)), (0.015, 0.02, 0.03))
            n.inputs["Base Color"].default_value = (*rgb, 1)
            n.inputs["Roughness"].default_value = 0.06
            if n.inputs.get("Alpha"):
                n.inputs["Alpha"].default_value = 1.0
        elif m.name.startswith("carpaint."):
            # Clear-coated paint, like the real thing.
            n.inputs["Roughness"].default_value = 0.3
            if n.inputs.get("Coat Weight"):
                n.inputs["Coat Weight"].default_value = 1.0
                n.inputs["Coat Roughness"].default_value = 0.03

# ---- the truck on a turntable ------------------------------------------------------------
meshes = [o for o in sc.objects if o.type == 'MESH']
pts = [o.matrix_world @ Vector(c) for o in meshes for c in o.bound_box]
lo = Vector((min(p.x for p in pts), min(p.y for p in pts), min(p.z for p in pts)))
hi = Vector((max(p.x for p in pts), max(p.y for p in pts), max(p.z for p in pts)))
centre = (lo + hi) / 2
lens = [o.matrix_world @ Vector(c) for o in meshes
        for s in o.material_slots if s.material and s.material.name.startswith("lens_clear")
        for c in o.bound_box]
front = (sum(lens, Vector()) / len(lens)) if lens else Vector((centre.x, hi.y, centre.z))
fwd = Vector((front.x - centre.x, front.y - centre.y, 0)).normalized()
nose_yaw = math.atan2(fwd.y, fwd.x)

# Everything under one empty at the truck's ground centre, which turns.
pivot = bpy.data.objects.new("pivot", None)
sc.collection.objects.link(pivot)
pivot.location = (centre.x, centre.y, lo.z)
for o in sc.objects:
    if o is not pivot and o.parent is None:
        o.parent = pivot
        o.matrix_parent_inverse = pivot.matrix_world.inverted()

# Its shadow, caught on an invisible ground.
bpy.ops.mesh.primitive_plane_add(size=30, location=(centre.x, centre.y, lo.z))
ground = bpy.context.active_object
ground.is_shadow_catcher = True

# ---- light: bright sky and a high sun, fixed to the screen -------------------------------
world = bpy.data.worlds.new("sky")
world.use_nodes = True
bg = world.node_tree.nodes["Background"]
bg.inputs[0].default_value = (0.8, 0.84, 0.9, 1)
bg.inputs[1].default_value = 0.9
sc.world = world
sun = bpy.data.objects.new("sun", bpy.data.lights.new("sun", 'SUN'))
sun.data.energy = 3.2
sun.data.angle = math.radians(12)            # soft-edged shadow
sc.collection.objects.link(sun)

# ---- render settings ---------------------------------------------------------------------
sc.render.engine = 'CYCLES'
prefs = bpy.context.preferences.addons["cycles"].preferences
for kind in ("METAL", "CUDA", "OPTIX", "HIP"):
    try:
        prefs.compute_device_type = kind
        prefs.get_devices()
        if any(d.type == kind for d in prefs.devices):
            for d in prefs.devices:
                d.use = True
            sc.cycles.device = 'GPU'
            break
    except TypeError:
        continue
sc.cycles.samples = 96
sc.cycles.use_denoising = True
sc.render.film_transparent = True
sc.render.resolution_x = sc.render.resolution_y = FRAME
sc.render.image_settings.file_format = 'PNG'
sc.render.image_settings.color_mode = 'RGBA'
sc.view_settings.view_transform = 'Standard'
sc.view_settings.look = 'None'

cam_data = bpy.data.cameras.new("cam")
cam_data.type = 'ORTHO'
cam_data.ortho_scale = VIEW
cam = bpy.data.objects.new("cam", cam_data)
sc.collection.objects.link(cam)
sc.camera = cam

height = hi.z - lo.z
frames = {"frame": FRAME, "headings": HEADINGS, "view": VIEW, "tilts": []}
for elev, min_pitch in TILTS:
    e = math.radians(elev)
    # Looking from behind (screen down = towards the camera), at the
    # truck's middle; the ground centre then sits a little below the frame
    # centre, by `drop` pixels.
    aim = Vector((centre.x, centre.y, lo.z + height / 2))
    back = Vector((0, -math.cos(e), math.sin(e)))
    cam.location = aim + back * 50
    cam.rotation_euler = (math.pi / 2 - e, 0, 0)
    drop = (height / 2) * math.cos(e) / VIEW * FRAME
    # The sun, up and to the left of the camera, a little in front.
    sun.rotation_euler = (math.radians(32), math.radians(-24), math.radians(-20))
    frames["tilts"].append({"elevation": elev, "minPitch": min_pitch, "drop": round(drop, 2)})
    for h in range(HEADINGS):
        heading = h * 360 / HEADINGS          # clockwise on screen, 0 = nose up
        # Screen up is world +Y; turn the nose there, then clockwise.
        pivot.rotation_euler = (0, 0, math.pi / 2 - nose_yaw - math.radians(heading))
        sc.render.filepath = os.path.join(out, f"t{elev}_h{h:02d}.png")
        bpy.ops.render.render(write_still=True)

with open(os.path.join(out, "frames.json"), "w") as f:
    json.dump(frames, f, indent=1)
print("CAR SPRITES", out, "forward", tuple(round(v, 3) for v in fwd), "height", round(height, 3))
