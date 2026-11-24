"""Stage 3b: the fixed video template. Plays a procedure on a model and renders the frames.

    blender -b model.blend --python video.py -- runs/procedure.json runs/timing.json OUTDIR [--preview]

Nothing here comes from a model: the camera moves, the part motions, the highlight and the
captions are the same code for every procedure, so the look is the same for every video.
--preview renders a quarter-size frame every 6th frame, to check the choreography quickly.
"""
import json, math, os, sys
import bpy
from mathutils import Vector
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from blender_common import set_engine, studio, machine_bounds, apply_motion, motion_of

args = sys.argv[sys.argv.index("--") + 1:]
proc = json.load(open(args[0])); timing = json.load(open(args[1])); outdir = args[2]
preview = "--preview" in args
scene = bpy.context.scene
FPS = timing["fps"]
F = lambda seconds: int(round(seconds * FPS)) + 1

# In a room built around the machine (objects named Env_...), keep its renderer and light; render
# with Cycles on the GPU; captions come later as overlays (VP_NO_HUD), so brand colours stay exact.
ENV = any(o.name.startswith("Env_") for o in bpy.data.objects)
FORCE_CYCLES = bool(os.environ.get("VP_FORCE_CYCLES"))
NO_HUD = ENV or bool(os.environ.get("VP_NO_HUD"))
if ENV or FORCE_CYCLES:
    scene.render.engine = "CYCLES"
    scene.cycles.samples = int(os.environ.get("VP_SAMPLES", "96"))
    scene.cycles.use_denoising = True
    prefs = bpy.context.preferences.addons["cycles"].preferences
    for kind in ("OPTIX", "CUDA"):
        try:
            prefs.compute_device_type = kind; prefs.get_devices()
            if any(d.type == kind for d in prefs.devices):
                break
        except TypeError:
            continue
    for d in prefs.devices:
        d.use = d.type != "CPU"
    scene.cycles.device = "GPU"
    print("CYCLES", prefs.compute_device_type, [d.name for d in prefs.devices if d.use])
else:
    set_engine(scene, fast=preview)
scene.render.fps = FPS
scene.render.resolution_x, scene.render.resolution_y = (640, 360) if preview else (1280, 720)
scene.render.image_settings.media_type = "IMAGE"
scene.render.image_settings.file_format = "PNG"
scene.frame_start, scene.frame_end = 1, F(timing["total"] + 1.0)
scene.frame_step = 6 if preview else 1
if not ENV:
    studio(scene)

lo, hi = machine_bounds()
centre = (lo + hi) / 2
NAVY, ACCENT, WHITE = (0.008, 0.03, 0.09, 1), (0.05, 0.45, 1.0, 1), (1, 1, 1, 1)

# Rest poses for every moving part, so actions are absolute fractions of the opening movement.
state = {}
for o in bpy.data.objects:
    if motion_of(o):
        o["_rest"] = list(o.location) + list(o.rotation_euler)
        state[o.name] = 0.0


def target_point(name):
    if name == "Machine":
        return centre.copy()
    o = bpy.data.objects[name]
    pts = [o.matrix_world @ Vector(c) for c in o.bound_box]
    return sum(pts, Vector()) / 8


# Camera on a rig: the camera tracks an empty, and both are keyframed.
tgt = bpy.data.objects.new("CamTarget", None); scene.collection.objects.link(tgt)
cam = bpy.data.objects.new("Camera", bpy.data.cameras.new("Camera")); scene.collection.objects.link(cam)
cam.data.lens = 35
cam.data.clip_start = 0.01
# On-screen graphics sit this far in front of the lens, closer than anything in a close-up;
# they are laid out for 1 m and scaled by D.
D = 0.12
c = cam.constraints.new("TRACK_TO"); c.target = tgt; c.track_axis = "TRACK_NEGATIVE_Z"; c.up_axis = "UP_Y"
scene.camera = cam


def shot_pose(shot):
    p = target_point(shot["target"])
    d = float(shot.get("distance", 1.5)); az = math.radians(shot.get("azimuth", 0)); el = math.radians(shot.get("elevation", 15))
    if ENV and shot["target"] == "Machine":   # in a room: step back and aim higher, so the worktop and room are in frame
        d *= 1.5; p = p + Vector((0, 0, 0.16))
    return p + Vector((d * math.sin(az) * math.cos(el), -d * math.cos(az) * math.cos(el), d * math.sin(el))), p


def key_cam(frame, pos, look):
    cam.location = pos; cam.keyframe_insert("location", frame=frame)
    tgt.location = look; tgt.keyframe_insert("location", frame=frame)


def emissive(name, colour, strength=1.0):
    m = bpy.data.materials.new(name); m.use_nodes = True
    p = next(n for n in m.node_tree.nodes if n.type == "BSDF_PRINCIPLED")
    p.inputs["Base Color"].default_value = colour
    p.inputs["Emission Color"].default_value = colour
    p.inputs["Emission Strength"].default_value = strength
    return m


def flat(name, colour):
    """An unlit material for on-screen graphics: exactly this colour whatever the lighting."""
    m = bpy.data.materials.new(name); m.use_nodes = True
    nt = m.node_tree
    for n in list(nt.nodes):
        if n.type != "OUTPUT_MATERIAL":
            nt.nodes.remove(n)
    out = next(n for n in nt.nodes if n.type == "OUTPUT_MATERIAL")
    em = nt.nodes.new("ShaderNodeEmission"); em.inputs[0].default_value = colour; em.inputs[1].default_value = 1.0
    nt.links.new(em.outputs[0], out.inputs[0])
    return m


# The frame at the HUD's distance (1 m in front of a 35 mm lens on a 36 mm sensor, 16:9).
HALF_W = 18 / 35
HALF_H = HALF_W * 9 / 16


def hud(text, size, xy, mat, frame_in, frame_out, bold=False):
    """Text fixed to the camera, shown between two frames."""
    if NO_HUD:
        return None
    cu = bpy.data.curves.new("hud", "FONT"); cu.body = text; cu.size = size * D; cu.align_y = "CENTER"
    ob = bpy.data.objects.new("HUD", cu); scene.collection.objects.link(ob)
    ob.data.materials.append(mat); ob.parent = cam; ob.location = (xy[0] * D, xy[1] * D, -D)
    show(ob, frame_in, frame_out)
    return ob


def bar(xy, w, h, mat, frame_in, frame_out):
    if NO_HUD:
        return
    bpy.ops.mesh.primitive_plane_add(size=1)
    ob = bpy.context.active_object; ob.name = "HUDBar"; ob.scale = (w * D, h * D, 1)
    ob.data.materials.append(mat); ob.parent = cam; ob.location = (xy[0] * D, xy[1] * D, -D * 1.001)
    show(ob, frame_in, frame_out)


def show(ob, frame_in, frame_out):
    for f, hidden in ((1, True), (frame_in, False), (frame_out, True)):
        ob.hide_render = hidden; ob.keyframe_insert("hide_render", frame=max(1, f))


white, navy, accent = flat("HudWhite", WHITE), flat("HudNavy", NAVY), flat("HudAccent", ACCENT)

# Title: the camera orbits the machine while the title shows.
t_end = F(timing["title_seconds"])
first = proc["steps"][0]["shot"]
for f, az in ((1, -40), (t_end, first.get("azimuth", 0))):
    pos, look = shot_pose({**first, "azimuth": az})
    key_cam(f, pos, look)
bar((0, -0.02), 2 * HALF_W, 0.2, navy, 1, t_end)
bar((-HALF_W + 0.04, -0.02), 0.01, 0.2, accent, 1, t_end)
hud(proc["title"], 0.05, (-HALF_W + 0.08, 0.02), white, 1, t_end)
hud(proc.get("subtitle", ""), 0.025, (-HALF_W + 0.08, -0.06), white, 1, t_end)

# Effects: a tray under the lowered drain guide, water, debris in the filter. Built here, the same for
# every procedure that asks for them; placed from the model's own geometry.
def pbr_mat(name, colour, rough=0.4, metal=0.0, transmission=0.0, ior=1.45):
    m = bpy.data.materials.new(name); m.use_nodes = True
    p = next(n for n in m.node_tree.nodes if n.type == "BSDF_PRINCIPLED")
    p.inputs["Base Color"].default_value = colour; p.inputs["Roughness"].default_value = rough
    p.inputs["Metallic"].default_value = metal
    for key in ("Transmission Weight", "Transmission"):
        if key in p.inputs:
            p.inputs[key].default_value = transmission; break
    p.inputs["IOR"].default_value = ior
    return m


FX = {}
wants = {k for st in proc["steps"] for e in st.get("effects", []) for k in e}
if wants and "BlueDrainGuide" in bpy.data.objects:
    guide = bpy.data.objects["BlueDrainGuide"]
    apply_motion(guide, 1.0); bpy.context.view_layer.update()
    pts = []
    for o in [guide] + [c for c in guide.children_recursive if c.type == "MESH"]:
        pts += [o.matrix_world @ v.co for v in o.data.vertices]
    apply_motion(guide, 0.0); bpy.context.view_layer.update()
    ymin = min(p.y for p in pts); front = [p for p in pts if p.y < ymin + 0.004]
    lip = Vector(((min(p.x for p in front) + max(p.x for p in front)) / 2, ymin, min(p.z for p in front)))
    TW, TD, TH = 0.30, 0.20, max(0.012, min(0.02, lip.z - 0.004))       # a flat tray that fits under the lip
    home = Vector((lip.x, lip.y - TD / 2 + 0.012, 0.0))                   # the lip overhangs the tray's back edge
    away = home + Vector((1.6, -0.5, 0))                                 # well out of frame
    import bmesh                                                            # an open-topped tray: a box without its lid
    me = bpy.data.meshes.new("FX_Tray"); bm = bmesh.new()
    bmesh.ops.create_cube(bm, size=1.0)
    for v in bm.verts:
        v.co.x *= TW; v.co.y *= TD; v.co.z = (v.co.z + 0.5) * TH
    bmesh.ops.delete(bm, geom=[f for f in bm.faces if f.normal.z > 0.9], context="FACES")
    bm.to_mesh(me); bm.free()
    tray = bpy.data.objects.new("FX_Tray", me); scene.collection.objects.link(tray)
    sol = tray.modifiers.new("wall", "SOLIDIFY"); sol.thickness = 0.003
    bev = tray.modifiers.new("round", "BEVEL"); bev.width = 0.003; bev.segments = 3
    tray.data.materials.append(pbr_mat("FX_TrayMat", (0.72, 0.74, 0.76, 1), rough=0.35))
    tray.location = away
    water = pbr_mat("FX_Water", (0.55, 0.78, 0.98, 1), rough=0.06, transmission=0.82, ior=1.33)  # tinted so it reads on camera
    bpy.ops.mesh.primitive_cube_add(size=1); pool = bpy.context.active_object; pool.name = "FX_TrayWater"
    pool.scale = (TW - 0.012, TD - 0.012, 1); bpy.ops.object.transform_apply(scale=True)
    pool.data.transform(__import__("mathutils").Matrix.Translation((0, 0, 0.5)))
    pool.data.materials.append(water); pool.parent = tray; pool.location = (0, 0, 0.002); pool.scale = (1, 1, 0.0001)
    fall = lip.z - 0.004
    bpy.ops.mesh.primitive_cylinder_add(radius=1, depth=1, vertices=24); stream = bpy.context.active_object; stream.name = "FX_Stream"
    stream.data.transform(__import__("mathutils").Matrix.Translation((0, 0, -0.5)))
    stream.location = (lip.x, lip.y - 0.004, lip.z); stream.scale = (0.0001, 0.0001, fall)
    stream.data.materials.append(water)
    tex = bpy.data.textures.new("FX_ripple", "CLOUDS"); tex.noise_scale = 0.004
    dsp = stream.modifiers.new("ripple", "DISPLACE"); dsp.texture = tex; dsp.strength = 0.0015; dsp.texture_coords = "OBJECT"
    empty = bpy.data.objects.new("FX_RippleDriver", None); scene.collection.objects.link(empty); dsp.texture_coords_object = empty
    empty.location = (0, 0, 0); empty.keyframe_insert("location", frame=1)
    empty.location = (0, 0, -0.03 * (scene.frame_end / FPS)); empty.keyframe_insert("location", frame=scene.frame_end)
    for fc in getattr(empty.animation_data.action, "fcurves", []):
        for kp in fc.keyframe_points:
            kp.interpolation = "LINEAR"
    FX.update(tray=tray, pool=pool, stream=stream, home=home, away=away, TH=TH, level=0.0, radius=0.0001)
    for key, obj in (("tray", tray), ("pool", pool), ("stream", stream)):
        obj.keyframe_insert("location", frame=1); obj.keyframe_insert("scale", frame=1)
    pool.hide_render = True; pool.keyframe_insert("hide_render", frame=1)          # no water until it starts filling
if "debris" in wants and "PumpFilter" in bpy.data.objects:
    pf = bpy.data.objects["PumpFilter"]
    items = []
    bpy.ops.mesh.primitive_cylinder_add(radius=0.0115, depth=0.0022, vertices=48); coin = bpy.context.active_object
    coin.name = "FX_Coin"; coin.data.materials.append(pbr_mat("FX_Brass", (0.80, 0.62, 0.30, 1), rough=0.3, metal=1.0))
    coin.location = (0.006, 0.055, -0.021); coin.rotation_euler = (0.25, 0, 0.3); items.append(coin)
    import random
    rnd = random.Random(7)
    # hair: a small tangle of dark strands
    hc = bpy.data.curves.new("FX_Hair", "CURVE"); hc.dimensions = "3D"; hc.bevel_depth = 0.0003; hc.bevel_resolution = 1
    for k in range(22):
        sp = hc.splines.new("NURBS"); sp.points.add(7); sp.order_u = 4
        x, y, z = rnd.uniform(-0.01, 0.01), rnd.uniform(0.03, 0.07), rnd.uniform(-0.022, -0.008)
        for q in sp.points:
            q.co = (x, y, z, 1)
            x += rnd.uniform(-0.006, 0.006); y += rnd.uniform(-0.004, 0.006); z += rnd.uniform(-0.002, 0.003)
    hair = bpy.data.objects.new("FX_Hair", hc); scene.collection.objects.link(hair)
    hc.materials.append(pbr_mat("FX_HairMat", (0.06, 0.035, 0.02, 1), rough=0.45))
    items.append(hair)
    # wet dust: a flattened, lumpy clump with a damp sheen
    bpy.ops.mesh.primitive_ico_sphere_add(radius=0.012, subdivisions=4); dust = bpy.context.active_object; dust.name = "FX_WetDust"
    dt = bpy.data.textures.new("FX_dust", "CLOUDS"); dt.noise_scale = 0.004
    dd = dust.modifiers.new("lumps", "DISPLACE"); dd.texture = dt; dd.strength = 0.005
    dust.data.materials.append(pbr_mat("FX_WetDustMat", (0.23, 0.21, 0.19, 1), rough=0.28))
    dust.location = (-0.006, 0.05, -0.019); dust.scale = (1.4, 1.1, 0.55); items.append(dust)
    # a crinkled candy wrapper in bright foil
    bpy.ops.mesh.primitive_grid_add(x_subdivisions=24, y_subdivisions=16, size=1); wrap = bpy.context.active_object; wrap.name = "FX_CandyWrapper"
    wrap.scale = (0.034, 0.022, 1)
    wt = bpy.data.textures.new("FX_crinkle", "VORONOI"); wt.noise_scale = 0.18
    wd = wrap.modifiers.new("crinkle", "DISPLACE"); wd.texture = wt; wd.strength = 0.004; wd.texture_coords = "LOCAL"
    wrap.modifiers.new("thick", "SOLIDIFY").thickness = 0.0003
    wrap.data.materials.append(pbr_mat("FX_FoilMat", (0.95, 0.70, 0.10, 1), rough=0.22, metal=0.9))
    wrap.location = (0.008, 0.065, -0.012); wrap.rotation_euler = (0.5, 0.2, 0.6); items.append(wrap)
    for it in items:
        it.parent = pf; it.keyframe_insert("location", frame=1); it.keyframe_insert("scale", frame=1)
    FX["debris"] = items


def fx_keys(obj, frame):
    obj.keyframe_insert("location", frame=frame); obj.keyframe_insert("scale", frame=frame)


def do_effect(e, a, b):
    """Play one effect between frames a and b."""
    (k, v), = e.items()
    if k == "container" and "tray" in FX:
        t = FX["tray"]; fx_keys(t, a)
        if v in ("place", "back"):
            if v == "back":
                t.location = FX["away"]; fx_keys(t, a)
            t.location = FX["home"]; fx_keys(t, b)
        elif v == "out":
            t.location = FX["away"]; fx_keys(t, b)
            p = FX["pool"]; fx_keys(p, b); p.scale = (1, 1, 0.0001); FX["level"] = 0.0; fx_keys(p, b + 1)
            p.hide_render = True; p.keyframe_insert("hide_render", frame=b + 1)
    elif k == "water" and "stream" in FX:
        st = FX["stream"]; fx_keys(st, a)
        r = {"flow": 0.006, "trickle": 0.0022, "stop": 0.0001}[v]
        st.scale = (r, r, st.scale.z); fx_keys(st, min(b, a + 8))
    elif k == "level" and "pool" in FX:
        p = FX["pool"]; fx_keys(p, a)
        if float(v) > 0:
            p.hide_render = False; p.keyframe_insert("hide_render", frame=a)
        p.scale = (1, 1, max(0.0001, float(v) * (FX["TH"] - 0.004))); fx_keys(p, b)
    elif k == "debris" and "debris" in FX:
        # all together: lifted out of the basket, held side by side above the filter, then put aside
        n = len(FX["debris"])
        for j, it in enumerate(FX["debris"]):
            fx_keys(it, a)
            start = it.location.copy()
            it.location = start + Vector((0.0, 0.0, 0.065)); fx_keys(it, a + int((b - a) * 0.22))
            spread = (j - (n - 1) / 2) * 0.03 - 0.035          # held left of the open hatch door
            it.location = Vector((spread, start.y - 0.075, 0.10)); fx_keys(it, a + int((b - a) * 0.38))
            fx_keys(it, a + int((b - a) * 0.8))
            it.location = Vector((0.17, start.y - 0.10, 0.12)); it.scale = (0.0001,) * 3; fx_keys(it, b)


# Steps.
for i, (s, tm) in enumerate(zip(proc["steps"], timing["steps"]), 1):
    f0, f1 = F(tm["start"]), F(tm["start"] + tm["length"])
    # camera: hold, then move to the step's shot in the first second
    pos, look = shot_pose(s["shot"])
    key_cam(f0, cam.location.copy(), tgt.location.copy())
    key_cam(min(f1 - 1, f0 + FPS), pos, look)
    cue = s.get("cue")
    if cue:   # a second shot, timed to the narration: e.g. close in on a part as it is named
        c0 = f0 + int(round(cue["from"] * FPS)); c1 = f0 + int(round(cue["to"] * FPS))
        key_cam(c0, pos, look)
        pos, look = shot_pose(cue["shot"])
        key_cam(c1, pos, look)
    key_cam(f1 - 1, pos, look)
    # part motions, after the camera has arrived
    for a in s.get("actions", []):
        o = bpy.data.objects[a["part"]]
        a0 = f0 + FPS; a1 = min(f1 - 2, a0 + int(2.0 * FPS))
        apply_motion(o, state[o.name]); o.keyframe_insert("location", frame=a0); o.keyframe_insert("rotation_euler", frame=a0)
        state[o.name] = float(a["to"])
        apply_motion(o, state[o.name]); o.keyframe_insert("location", frame=a1); o.keyframe_insert("rotation_euler", frame=a1)
    # effects, one after another, after the part motions
    effects = s.get("effects", [])
    if effects:
        e0 = f0 + FPS + (int(2.0 * FPS) + 4 if s.get("actions") else 0)
        e1 = max(e0 + len(effects) * 12, f1 - 8)
        for k, e in enumerate(effects):
            do_effect(e, e0 + (e1 - e0) * k // len(effects), e0 + (e1 - e0) * (k + 1) // len(effects))
    # highlight: the part glows in the accent colour, pulsing once
    h = s.get("highlight")
    if h and h != "Machine":
        o = bpy.data.objects[h]
        mats = [emissive(f"hl_{h}_{i}_{k}", ACCENT, 0.0) for k in range(max(1, len(o.material_slots)))]
        for k, m in enumerate(mats):
            node = next(n for n in m.node_tree.nodes if n.type == "BSDF_PRINCIPLED")
            base = o.material_slots[k].material if k < len(o.material_slots) and o.material_slots[k].material else None
            if base and base.use_nodes:
                bp = next((n for n in base.node_tree.nodes if n.type == "BSDF_PRINCIPLED"), None)
                if bp:
                    node.inputs["Base Color"].default_value = bp.inputs["Base Color"].default_value
            es = node.inputs["Emission Strength"]
            for f, v in ((f0, 0.0), (f0 + FPS, 0.0), (f0 + int(1.6 * FPS), 3.0), (f1 - 6, 1.5), (f1, 0.0)):
                es.default_value = v; es.keyframe_insert("default_value", frame=min(f, f1))
        # swap the part's materials for the highlight copies during the step, by keyframing an overlay object
        dup = o.copy(); dup.data = o.data; scene.collection.objects.link(dup)
        dup.parent = o; dup.matrix_parent_inverse.identity(); dup.location = (0, 0, 0); dup.rotation_euler = (0, 0, 0); dup.scale = (1.003, 1.003, 1.003)
        dup.animation_data_clear()
        for k in range(len(dup.material_slots)):
            dup.material_slots[k].link = "OBJECT"; dup.material_slots[k].material = mats[k]
        show(dup, f0, f1)
    # caption: a lower third with the step number
    y = -HALF_H + 0.075
    bar((0, y), 2 * HALF_W, 0.075, navy, f0, f1)
    bar((-HALF_W + 0.04, y), 0.01, 0.075, accent, f0, f1)
    hud(f"{i}", 0.032, (-HALF_W + 0.065, y), accent, f0, f1)
    hud(s["caption"], 0.03, (-HALF_W + 0.11, y), white, f0, f1)

os.makedirs(os.path.join(outdir, "frames"), exist_ok=True)
scene.render.filepath = os.path.join(outdir, "frames", "f_")
bpy.ops.wm.save_as_mainfile(filepath=os.path.join(outdir, "video.blend"))
if os.environ.get("VP_FRAMES"):          # render only these frames, e.g. "36,145,324"
    wanted = []
    for part in os.environ["VP_FRAMES"].split(","):
        a_, _, b_ = part.partition("-"); wanted += list(range(int(a_), int(b_ or a_) + 1))
    for fr in wanted:
        scene.frame_set(fr); scene.render.filepath = os.path.join(outdir, "frames", f"f_{fr:04d}.png")
        bpy.ops.render.render(write_still=True)
else:
    bpy.ops.render.render(animation=True)
