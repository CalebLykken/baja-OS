"""Make web/map/truck.glb: the Baja for the map, drawn in 3D among the
streets. Lighter than the Truck page's model (the map draws it at ~70 px):
no interior, plates, lamp reflectors or brake discs, the rest simplified,
the body in one piece and each wheel its own piece, centred on its hub,
so the map can turn and steer them.

    blender -b --python tools/make_map_truck.py -- qml/assets/baja-3d.glb web/map/truck.glb

The truck stands on the ground at the origin, nose towards +Z (glTF axes).
"""
import bpy, sys
from mathutils import Matrix, Vector

src, out = sys.argv[-2], sys.argv[-1]
TARGET_TRIS = 32000

bpy.ops.wm.read_factory_settings(use_empty=True)
bpy.ops.import_scene.gltf(filepath=src)
sc = bpy.context.scene


def material(o):
    return o.material_slots[0].material.name if o.material_slots and o.material_slots[0].material else ""


# ---- drop what can't be seen at this size ---------------------------------------
DROP = ("interior", "LicPlate", "refl_", "brakedisk", "scoop_duct")
for o in list(sc.objects):
    if o.type == 'MESH' and any(material(o).startswith(d) for d in DROP):
        bpy.data.objects.remove(o, do_unlink=True)

# ---- materials: what the map should show ---------------------------------------------
for m in bpy.data.materials:
    if not m.use_nodes:
        continue
    bsdf = next((n for n in m.node_tree.nodes if n.type == 'BSDF_PRINCIPLED'), None)
    if bsdf is None:
        continue
    t = bsdf.inputs.get("Transmission Weight")
    glassy = (t is not None and t.default_value > 0.01) or "glass" in m.name
    if glassy and not m.name.startswith("lens_"):
        t.default_value = 0.0
        bsdf.inputs["Base Color"].default_value = (0.008, 0.01, 0.013, 1)
        bsdf.inputs["Roughness"].default_value = 0.18
        bsdf.inputs["Alpha"].default_value = 1.0
        m.surface_render_method = 'DITHERED'
    elif m.name.startswith("lens_"):
        if t is not None:
            t.default_value = 0.0
        tint = {"lens_red": (0.5, 0.02, 0.02), "lens_brake": (0.5, 0.02, 0.02),
                "lens_amber": (0.85, 0.36, 0.03), "lens_clear": (0.75, 0.78, 0.82)}
        rgb = next((v for k, v in tint.items() if m.name.startswith(k)), (0.7, 0.7, 0.7))
        bsdf.inputs["Base Color"].default_value = (*rgb, 1)
        bsdf.inputs["Roughness"].default_value = 0.08
        bsdf.inputs["Alpha"].default_value = 1.0
        m.surface_render_method = 'DITHERED'
    elif m.name.startswith("carpaint."):
        bsdf.inputs["Metallic"].default_value = 0.0
        bsdf.inputs["Roughness"].default_value = 0.28
    elif m.name.startswith("carpaint_second"):
        bsdf.inputs["Metallic"].default_value = 0.0
        bsdf.inputs["Roughness"].default_value = 0.75
    elif m.name.startswith("rim"):
        bsdf.inputs["Roughness"].default_value = 0.35

# ---- one body, four wheels ---------------------------------------------------------------
meshes = [o for o in sc.objects if o.type == 'MESH']
wheels = {}
body = []
for o in meshes:
    for corner in ("FL", "FR", "RL", "RR"):
        if o.name.lower().startswith("wheel_" + corner.lower()):
            wheels.setdefault(corner, []).append(o)
            break
    else:
        body.append(o)


def join(objs, name):
    bpy.ops.object.select_all(action='DESELECT')
    for o in objs:
        o.select_set(True)
    bpy.context.view_layer.objects.active = objs[0]
    if len(objs) > 1:
        bpy.ops.object.join()
    o = bpy.context.view_layer.objects.active
    o.name = o.data.name = name
    return o


# Bake every transform into the meshes first.
bpy.ops.object.select_all(action='SELECT')
for o in sc.objects:
    if o.type != 'MESH':
        o.select_set(False)
bpy.context.view_layer.objects.active = meshes[0]
bpy.ops.object.parent_clear(type='CLEAR_KEEP_TRANSFORM')
bpy.ops.object.transform_apply(location=True, rotation=True, scale=True)
for o in list(sc.objects):
    if o.type != 'MESH':
        bpy.data.objects.remove(o, do_unlink=True)

parts = [join(body, "body")] + [join(objs, "wheel_" + c) for c, objs in sorted(wheels.items())]

# ---- simplify --------------------------------------------------------------------------------
def tris(o):
    return sum(len(p.vertices) - 2 for p in o.data.polygons)

total = sum(tris(o) for o in parts)
ratio = min(1.0, TARGET_TRIS / total)
for o in parts:
    mod = o.modifiers.new("simplify", 'DECIMATE')
    mod.ratio = ratio
    mod.use_collapse_triangulate = True
    bpy.context.view_layer.objects.active = o
    bpy.ops.object.modifier_apply(modifier=mod.name)

# ---- stand it at the origin, nose to +Z (glTF) ---------------------------------------------------
pts = [o.matrix_world @ v.co for o in parts for v in o.data.vertices]
lo = Vector((min(p.x for p in pts), min(p.y for p in pts), min(p.z for p in pts)))
hi = Vector((max(p.x for p in pts), max(p.y for p in pts), max(p.z for p in pts)))
shift = Vector(((lo.x + hi.x) / -2, (lo.y + hi.y) / -2, -lo.z))
for o in parts:
    o.data.transform(Matrix.Translation(shift))
# Wheels: origin at the hub, so they can spin and steer in place.
for o in parts[1:]:
    c = sum((v.co for v in o.data.vertices), Vector()) / len(o.data.vertices)
    o.data.transform(Matrix.Translation(-c))
    o.location = c
# The source model's nose points to Blender -Y, which is glTF +Z: as wanted.

bpy.ops.export_scene.gltf(filepath=out, export_format='GLB', use_selection=False,
                          export_apply=True, export_animations=False, export_cameras=False,
                          export_lights=False, export_yup=True)
print("MAP TRUCK", out, "triangles", sum(tris(o) for o in parts), "from", total,
      "size", tuple(round(v, 3) for v in (hi - lo)))
