"""gpt-6-astra builds the room around the machine, to match a reference photo.

    python3 environment.py [rounds]

Astra writes a Blender script that adds a laundry-room set around the existing model (it may not
touch the machine), using CC0 assets from assets/index.json, plus a camera "Env_RefCamera"
framed like the photo. Blender renders that view; astra compares it with the photo and rewrites.
"""
import json, os, subprocess, sys
from llm import ask, code_block, image_part, HERE

BLENDER = "/Applications/Blender.app/Contents/MacOS/Blender"
MODEL = os.path.join(HERE, "runs", "model", "model_v3.blend")
REF = os.path.join(HERE, "photos", "scene-reference.png")
REF2 = os.path.join(HERE, "photos", "scene-reference-2.png")
OUT = os.path.join(HERE, "runs", "env")
ASSETS = json.load(open(os.path.join(HERE, "assets", "index.json")))

CONTRACT = f"""You write Blender 5.1 Python (bpy) that builds the room around a washing machine that is already in the scene,
so that the scene looks like the reference photo. It runs headless:
  blender -b model_v3.blend --python env_script.py -- out.blend
The machine: centred on x = 0, y = 0, standing on z = 0, front facing -Y, 597 mm wide (X), 636 mm deep (Y), 847 mm high (Z).
Its objects already exist; never delete, move, rename or re-material them. Everything you create is named "Env_...".

Build the set in the photo: the machine built in flush between light-oak cabinet runs with flat handleless fronts, a stone
worktop running over cabinets and machine, a veined stone wall behind, a white plaster wall at the left end, a dark concrete
floor, a green rug in front, a wicker basket with folded towels, a plant, soap and spray bottles on the worktop, a tap, a
folded towel on the worktop at the right. Match proportions, colours and layout to the photo; the machine must keep its
position, so build the room to it. Keep at least 1.5 m clear in front of the machine (the video's cameras move there), and do
not put anything within 0.5 m in front of the machine's front below the worktop, or in front of the door or the filter hatch.

Materials: Principled BSDF found by type (next(n for n in mat.node_tree.nodes if n.type == "BSDF_PRINCIPLED")), with the PBR maps
given (colour map in sRGB, the others Non-Color; normal map through a Normal Map node), and box or UV mapping at a realistic
scale. Tint a texture with a mix or hue node where the photo's colour differs. Models: import the glTF files with
bpy.ops.import_scene.gltf and rename, parent and scale them to plausible real sizes (dimensions are given in mm; they may be
wrong for this use, so decide the size from the photo). Model what has no asset (towels, rug, tap, cabinet fronts) simply.
Light: the HDRI as the world, rotated so the brightest side comes from the photo's left, plus an area or sun light from the
left like the window light in the photo. Set the render engine to EEVEE if you like, but do not set resolution or output.
There are TWO reference photos of the same room. Photo 1 looks at the machine with the left end of the set (white wall, left
cabinet run, plant, basket of towels on the floor). Photo 2 looks at the same machine with the right end: a sink and tap in the
worktop left of the machine, folded towels on the worktop above it, a large round wicker basket with a handle on the right, and
at the far right a tall window or glass door with a white sheer curtain, through which low, warm sunlight falls across the set
and floor, casting long shadows. Build ONE room that is consistent with both, lit mainly by that sun through the window.
Create two cameras framed like the photos: "Env_RefCamera" like photo 1 and "Env_RefCamera2" like photo 2, and make
Env_RefCamera scene.camera.
All file paths below are relative to the spike folder; the script can build absolute paths from
os.environ["VP_HERE"]. End with bpy.ops.wm.save_as_mainfile(filepath=sys.argv[sys.argv.index("--") + 1]).
Reply with a short note on what you see in the photo, then the complete script in one ```python block.

Assets (CC0, Poly Haven):
{json.dumps(ASSETS, indent=1)}"""

RENDER = """import bpy, sys
s = bpy.context.scene
s.render.resolution_x, s.render.resolution_y, s.render.resolution_percentage = 1440, 820, 50
s.render.image_settings.media_type = "IMAGE"; s.render.image_settings.file_format = "PNG"
base = sys.argv[sys.argv.index("--") + 1]
for name, suffix in (("Env_RefCamera", ""), ("Env_RefCamera2", "-2")):
    cam = bpy.data.objects.get(name)
    if cam:
        s.camera = cam
        s.render.filepath = base.replace(".png", suffix + ".png")
        bpy.ops.render.render(write_still=True)
"""


def run(script, n):
    path = os.path.join(OUT, f"env_v{n}.py"); open(path, "w").write(script)
    blend = os.path.join(OUT, f"env_v{n}.blend")
    env = dict(os.environ, VP_HERE=HERE)
    r = subprocess.run([BLENDER, "-b", MODEL, "--python-exit-code", "1", "--python", path, "--", blend], capture_output=True, text=True, timeout=900, env=env)
    if r.returncode or not os.path.exists(blend):
        return None, (r.stdout + r.stderr)[-5000:]
    rpath = os.path.join(OUT, "render_check.py"); open(rpath, "w").write(RENDER)
    png = os.path.join(OUT, f"check_v{n}.png")
    r = subprocess.run([BLENDER, "-b", blend, "--python-exit-code", "1", "--python", rpath, "--", png], capture_output=True, text=True, timeout=900, env=env)
    return (png if os.path.exists(png) else None), (r.stdout + r.stderr)[-3000:]


GUIDANCE = os.environ.get("VP_ENV_GUIDANCE", "")


def main(rounds, start=None):
    os.makedirs(OUT, exist_ok=True)
    if start:
        first = int(start.split("_v")[1].split(".")[0])
        script = open(start).read()
        png = os.path.join(OUT, f"check_v{first}.png"); png2 = png.replace(".png", "-2.png")
        msg = [{"type": "text", "text": "Reference photo 1, your render from Env_RefCamera, reference photo 2, your render from Env_RefCamera2. A reviewer's notes, to fix first:\n" + GUIDANCE + "\nThen compare each pair yourself. List what you change, then give the complete improved script."},
               image_part(REF), image_part(png), image_part(REF2), image_part(png2), {"type": "text", "text": f"Your script:\n```python\n{script}\n```"}]
        script = code_block(ask(f"env v{first + 1}", CONTRACT, msg, max_tokens=40000))
        for n in range(first + 1, first + 1 + rounds):
            png, log = run(script, n)
            print(f"v{n}: " + ("rendered " + png if png else "failed"))
            if n == first + rounds:
                return
            if png is None:
                msg = [{"type": "text", "text": f"Your script failed in Blender 5.1.2. The end of the log:\n{log}\n\nThe script:\n```python\n{script}\n```\nReply with the complete corrected script."}]
            else:
                png2 = png.replace(".png", "-2.png")
                msg = [{"type": "text", "text": "Reference photo 1, your render from Env_RefCamera, reference photo 2, your render from Env_RefCamera2. The reviewer's notes still apply:\n" + GUIDANCE + "\nCompare each pair. List what you change, then give the complete improved script."},
                       image_part(REF), image_part(png), image_part(REF2)] + ([image_part(png2)] if os.path.exists(png2) else []) + [{"type": "text", "text": f"Your script:\n```python\n{script}\n```"}]
            script = code_block(ask(f"env v{n + 1}", CONTRACT, msg, max_tokens=40000))
        return
    reply = ask("env v1", CONTRACT, [{"type": "text", "text": "Reference photo 1, then reference photo 2:"}, image_part(REF), image_part(REF2)], max_tokens=40000)
    script = code_block(reply)
    for n in range(1, rounds + 1):
        png, log = run(script, n)
        if png is None:
            print(f"v{n}: failed")
            msg = [{"type": "text", "text": f"Your script failed in Blender 5.1.2. The end of the log:\n{log}\n\nThe script:\n```python\n{script}\n```\nReply with the complete corrected script."}]
        else:
            print(f"v{n}: rendered {png}")
            if n == rounds:
                return
            png2 = png.replace(".png", "-2.png")
            msg = [{"type": "text", "text": "Reference photo 1, your render from Env_RefCamera, reference photo 2, your render from Env_RefCamera2. Compare each pair: camera framing, layout and proportions of the cabinets, worktop and wall, materials and colours (oak tone, stone, concrete), the props, and the light (direction, softness, brightness, no blown-out or muddy areas). List what you change, then give the complete improved script."},
                   image_part(REF), image_part(png), image_part(REF2)] + ([image_part(png2)] if os.path.exists(png2) else []) + [{"type": "text", "text": f"Your script:\n```python\n{script}\n```"}]
        if n == rounds:
            return
        script = code_block(ask(f"env v{n + 1}", CONTRACT, msg, max_tokens=40000))


if __name__ == "__main__":
    main(int(sys.argv[1]) if len(sys.argv) > 1 else 4, sys.argv[2] if len(sys.argv) > 2 else None)
