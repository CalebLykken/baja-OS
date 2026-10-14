"""Build qml/assets/baja-3d.glb (the Truck page model) from the portfolio's
baja.glb. Run with Blender:

    blender -b --python tools/export_truck.py -- path/to/baja.glb qml/assets/baja-3d.glb

Swaps transmissive glass for opaque tints, tones the paint down from fully
metallic (real-time engines need far more environment light than we have to
make metallic paint read as its colour), and simplifies only the trim,
interior and tyres so the painted panels keep every triangle.
"""
import bpy, sys
src, out = sys.argv[-2], sys.argv[-1]
bpy.ops.wm.read_factory_settings(use_empty=True)
bpy.ops.import_scene.gltf(filepath=src)

# Glass and lenses: same opaque tints as the stills (transmission is
# expensive and renders poorly in real-time engines).
tint = {"lens_red": (0.45, 0.02, 0.02), "lens_brake": (0.45, 0.02, 0.02),
        "lens_amber": (0.75, 0.32, 0.03), "lens_clear": (0.55, 0.57, 0.6)}
for m in bpy.data.materials:
    if not m.use_nodes: continue
    for n in m.node_tree.nodes:
        if n.type == 'BSDF_PRINCIPLED':
            t = n.inputs.get("Transmission Weight")
            if t is not None and t.default_value > 0.01:
                t.default_value = 0.0
                rgb = next((v for k, v in tint.items() if m.name.startswith(k)), (0.01, 0.012, 0.015))
                n.inputs["Base Color"].default_value = (*rgb, 1)
                n.inputs["Roughness"].default_value = 0.05
                n.inputs["Metallic"].default_value = 0.0
                if m.name.startswith(("windowglass", "darkglass", "clearglass")):
                    n.inputs["Alpha"].default_value = 0.92

# Paint: mostly dielectric with a glossy coat, so the orange shows as colour
# instead of reflecting the (dark) studio as near-black metal.
for m in bpy.data.materials:
    if m.use_nodes and m.name.startswith("carpaint."):
        for n in m.node_tree.nodes:
            if n.type == 'BSDF_PRINCIPLED':
                n.inputs["Metallic"].default_value = 0.25
                n.inputs["Roughness"].default_value = 0.28

def tris(o):
    o.data.calc_loop_triangles(); return len(o.data.loop_triangles)

before = sum(tris(o) for o in bpy.context.scene.objects if o.type == 'MESH')

# Split the body and wheels by material so only the parts where detail is
# invisible get simplified; painted panels and glass keep every triangle
# (decimating them smears their shading).
for name in ["Body", "Wheel_FL", "Wheel_FR", "Wheel_RL", "Wheel_RR"]:
    o = bpy.data.objects[name]
    bpy.ops.object.select_all(action='DESELECT')
    o.select_set(True); bpy.context.view_layer.objects.active = o
    bpy.ops.object.mode_set(mode='EDIT')
    bpy.ops.mesh.separate(type='MATERIAL')
    bpy.ops.object.mode_set(mode='OBJECT')

RATIOS = {"interior": 0.2, "black": 0.3, "tire": 0.35}
for o in list(bpy.context.scene.objects):
    if o.type != 'MESH' or not o.data.materials:
        continue
    mat = o.data.materials[0].name
    ratio = next((r for k, r in RATIOS.items() if mat.startswith(k)), None)
    if ratio is None:
        continue
    mod = o.modifiers.new("dec", 'DECIMATE')
    mod.ratio = ratio
    bpy.ops.object.select_all(action='DESELECT')
    o.select_set(True); bpy.context.view_layer.objects.active = o
    bpy.ops.object.modifier_apply(modifier="dec")
    bpy.ops.object.shade_smooth_by_angle(angle=0.6)

after = sum(tris(o) for o in bpy.context.scene.objects if o.type == 'MESH')
print("TRIS", before, "->", after)

bpy.ops.export_scene.gltf(filepath=out, export_format='GLB', export_apply=True,
                          export_draco_mesh_compression_enable=False, export_yup=True)


def strip_material_extensions(path):
    """Drop clearcoat/specular/sheen/ior extensions from the GLB's materials.

    Qt's importer reads these differently from Blender (the paint came out
    grey with orange only at grazing angles); plain metallic-roughness
    values render the same everywhere.
    """
    import json
    import struct
    data = open(path, "rb").read()
    json_len = struct.unpack_from("<I", data, 12)[0]
    doc = json.loads(data[20:20 + json_len])
    rest = data[20 + json_len:]                       # the BIN chunk, untouched
    for m in doc.get("materials", []):
        m.pop("extensions", None)
    doc["extensionsUsed"] = [e for e in doc.get("extensionsUsed", [])
                             if not e.startswith("KHR_materials_")]
    if not doc["extensionsUsed"]:
        del doc["extensionsUsed"]
    new_json = json.dumps(doc, separators=(",", ":")).encode()
    new_json += b" " * (-len(new_json) % 4)           # chunks are 4-byte aligned
    out = struct.pack("<I", len(new_json)) + b"JSON" + new_json + rest
    open(path, "wb").write(struct.pack("<III", 0x46546C67, 2, 12 + len(out)) + out)


strip_material_extensions(out)
print("stripped material extensions")

