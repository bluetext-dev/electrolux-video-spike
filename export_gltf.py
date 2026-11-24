"""Export the Blender model for Unreal: glTF binary with every part as its own node (pivots
kept), plus the moving parts' motions and labels as JSON.

    blender -b model.blend --python export_gltf.py -- OUT.glb OUT-parts.json
"""
import json, sys
import bpy
out, parts_out = sys.argv[sys.argv.index("--") + 1:][:2]
bpy.ops.export_scene.gltf(filepath=out, export_format="GLB", use_selection=False, export_apply=True,
                          export_yup=True, export_extras=True, export_cameras=False, export_lights=False)
parts = {}
for o in bpy.data.objects:
    if o.get("motion") or o.get("label"):
        parts[o.name] = {"label": o.get("label"), "motion": json.loads(o["motion"]) if o.get("motion") else None,
                         "location": list(o.matrix_world.translation), "parent": o.parent.name if o.parent else None}
json.dump(parts, open(parts_out, "w"), indent=1)
