"""Render check views of a generated model, to compare with the product photos.

    blender -b model.blend --python render_check.py -- out_prefix
Writes out_prefix-front.png, -angle.png and -hatch.png (the filter hatch opened), plus
out_prefix-parts.json listing the objects and their world-space centres.
"""
import json, math, os, sys
import bpy
from mathutils import Vector
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from blender_common import set_engine, studio, camera, machine_bounds

out = sys.argv[sys.argv.index("--") + 1]
scene = bpy.context.scene
set_engine(scene, fast=True)
scene.render.resolution_x, scene.render.resolution_y = 720, 720
scene.render.image_settings.file_format = "PNG"
studio(scene)
lo, hi = machine_bounds()
c = (lo + hi) / 2
h = hi.z - lo.z

views = {
    "front": ((c.x, lo.y - 2.2, c.z), (c.x, c.y, c.z), 50),
    "angle": ((c.x + 1.4, lo.y - 1.6, c.z + 0.45), (c.x, c.y, c.z), 45),
}
for name, (loc, tgt, lens) in views.items():
    camera(scene, loc, tgt, lens)
    scene.render.filepath = f"{out}-{name}.png"
    bpy.ops.render.render(write_still=True)

# Put every moving part in its end position, the way its "motion" property says, and look at
# the filter hatch close up.
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from blender_common import apply_motion
for o in bpy.data.objects:
    apply_motion(o, 1.0)
bpy.context.view_layer.update()
hatch = bpy.data.objects.get("FilterHatch")
if hatch:
    hc = hatch.matrix_world.translation
    camera(scene, (hc.x + 0.35, hc.y - 0.9, hc.z + 0.35), (hc.x, hc.y, hc.z), 50)
    scene.render.filepath = f"{out}-hatch.png"
    bpy.ops.render.render(write_still=True)

parts = {o.name: {"centre": [round(v, 3) for v in o.matrix_world.translation], "parent": o.parent.name if o.parent else None,
                  "motion": o.get("motion")}
         for o in bpy.data.objects if o.type in ("MESH", "EMPTY") and o.name != "Floor"}
json.dump({"bounds": [list(lo), list(hi)], "parts": parts}, open(f"{out}-parts.json", "w"), indent=1)
