"""Stage 1: gpt-6-astra models the appliance in Blender from its product photos.

    python3 model.py [iterations]

Astra writes a Blender script from the photos and the dimensions; Blender runs it headless
and renders check views (render_check.py); astra compares the renders with the photos and
rewrites the script. Each version is kept in runs/model/.
"""
import json, os, subprocess, sys
from llm import ask, code_block, image_part, HERE

BLENDER = "/Applications/Blender.app/Contents/MacOS/Blender"
PHOTOS = os.environ.get("VP_PHOTOS", os.path.join(HERE, "photos"))
OUT = os.path.join(HERE, "runs", "model")
PRODUCT = json.load(open(os.path.join(HERE, "product.json")))

CONTRACT = """You write Blender 5.1 Python (bpy) that builds a 3D model of one real appliance, to be
animated later by a fixed template. The script runs headless: blender -b --factory-startup --python model_script.py -- out.blend

Rules:
- Start by deleting every object in the scene. Build only the appliance: no camera, lights, floor or render settings.
- Units are metres. The floor is z = 0. The machine is centred on x = 0 and y = 0, its front faces -Y
  (so the front face sits at y = -depth/2), width along X, depth along Y, height along Z. Use the real dimensions.
- Use only bpy, bmesh, math and mathutils. bpy.ops.mesh.primitive_* and modifiers (Bevel, Boolean, Solidify) are fine.
- Materials: create them with use_nodes and set colours on the Principled BSDF node, found by type:
  next(n for n in mat.node_tree.nodes if n.type == "BSDF_PRINCIPLED"). Never look nodes up by name.
  Never hard-code enum identifiers that changed between Blender versions.
- Required objects, with exactly these names (more objects are welcome, named clearly):
  Body, ControlPanel, Display, ProgramKnob, DetergentDrawer, Door, DoorGlass, FilterHatch, PumpFilter.
- Moving parts: Door, DetergentDrawer, FilterHatch and PumpFilter. Each has its ORIGIN at its pivot (a hinge axis,
  or the centre of the thread for the filter), so rotating the object about its origin is the real motion. Parts that
  move with it (the door's glass, ring and handle) are parented to it with the transform kept.
  Give each moving part a custom property "motion", a JSON string:
    obj["motion"] = json.dumps({"rotate": {"axis": "Z", "degrees": -100}, "translate": [0, -0.25, 0]})
  (both keys optional; rotation about the object's origin in its local axes, translation in its parent's space),
  describing the full opening movement from closed: the door swinging open, the drawer pulling out, the hatch
  swinging open, the filter unscrewed and pulled out.
- Also set obj["label"] on every named part to a short English name for captions, e.g. "drain pump filter".
- End with: import sys; bpy.ops.wm.save_as_mainfile(filepath=sys.argv[sys.argv.index("--") + 1])
Reply with a short note on your reading of the photos, then the complete script in one ```python block."""


def run_blender(script, n):
    path = os.path.join(OUT, f"model_v{n}.py")
    open(path, "w").write(script)
    blend = os.path.join(OUT, f"model_v{n}.blend")
    r = subprocess.run([BLENDER, "-b", "--factory-startup", "--python-exit-code", "1", "--python", path, "--", blend],
                       capture_output=True, text=True, timeout=600)
    log = (r.stdout + r.stderr)[-4000:]
    if r.returncode or not os.path.exists(blend):
        return None, log
    prefix = os.path.join(OUT, f"check_v{n}")
    r = subprocess.run([BLENDER, "-b", blend, "--python-exit-code", "1", "--python", os.path.join(HERE, "render_check.py"), "--", prefix],
                       capture_output=True, text=True, timeout=900)
    if r.returncode:
        return None, (r.stdout + r.stderr)[-4000:]
    return prefix, log


def main(iterations):
    os.makedirs(OUT, exist_ok=True)
    photos = [os.path.join(PHOTOS, p) for p in PRODUCT["photos"]]
    facts = json.dumps({k: PRODUCT[k] for k in ("name", "model", "dimensions_mm", "colour", "notes")}, indent=1)
    content = [{"type": "text", "text": f"The appliance:\n{facts}\n\nIts product photos follow, in order: {', '.join(PRODUCT['photo_notes'])}."}]
    content += [image_part(p) for p in photos]
    print("v1: first model")
    reply = ask("model v1", CONTRACT, content)
    script = code_block(reply)
    for n in range(1, iterations + 1):
        prefix, log = run_blender(script, n)
        if prefix is None:
            print(f"v{n}: Blender failed; asking for a fix")
            if n == iterations:
                print(log); return
            reply = ask(f"fix v{n}", CONTRACT, [{"type": "text", "text": f"Your script failed in Blender 5.1.2. The end of the log:\n{log}\n\nThe script:\n```python\n{script}\n```\nReply with the complete corrected script."}])
            script = code_block(reply)
            continue
        print(f"v{n}: rendered {prefix}-*.png")
        if n == iterations:
            return
        parts = open(prefix + "-parts.json").read()
        crit = [{"type": "text", "text": "Here are the product photos again, then three renders of your model: front, three-quarter, and the moving parts opened with a close-up on the filter hatch. Then the objects it produced. Compare the renders with the photos: proportions, the door ring and glass, the control panel layout, the drawer position, the filter hatch position and how it opens, the pump filter. Make every moving part move correctly. Reply with a short list of what you change, then the complete improved script."}]
        crit += [image_part(p) for p in photos[:3]]
        crit += [image_part(f"{prefix}-{v}.png") for v in ("front", "angle", "hatch")]
        crit += [{"type": "text", "text": f"Objects:\n{parts}\n\nYour script:\n```python\n{script}\n```"}]
        reply = ask(f"model v{n + 1}", CONTRACT, crit)
        script = code_block(reply)


if __name__ == "__main__":
    main(int(sys.argv[1]) if len(sys.argv) > 1 else 3)
