"""Deterministic Blender helpers shared by the check renders and the video template.
Imported inside Blender (run with `blender -b ... --python <script>`)."""
import math
import bpy
from mathutils import Vector


def set_engine(scene, fast=True):
    # Engine identifiers move between Blender versions; try the current names in order.
    for eng in ("BLENDER_EEVEE", "BLENDER_EEVEE_NEXT", "CYCLES"):
        try:
            scene.render.engine = eng
            break
        except TypeError:
            continue
    if scene.render.engine == "CYCLES":
        scene.cycles.samples = 32 if fast else 96
    else:
        try:
            scene.eevee.taa_render_samples = 16 if fast else 24
        except AttributeError:
            pass


def studio(scene, floor=True):
    """A neutral white studio: world light, a key and a fill area light, and a floor."""
    world = scene.world or bpy.data.worlds.new("World")
    scene.world = world
    world.use_nodes = True
    bg = next(n for n in world.node_tree.nodes if n.type == "BACKGROUND")
    bg.inputs[0].default_value = (0.92, 0.93, 0.95, 1)
    bg.inputs[1].default_value = 0.6
    for name, loc, energy, size in (("Key", (1.6, -2.2, 2.4), 600, 1.6), ("Fill", (-2.0, -1.2, 1.6), 250, 2.0), ("Rim", (0.4, 2.0, 2.2), 200, 1.2)):
        if name in bpy.data.objects:
            continue
        ld = bpy.data.lights.new(name, "AREA")
        ld.energy = energy
        ld.size = size
        lo = bpy.data.objects.new(name, ld)
        scene.collection.objects.link(lo)
        lo.location = loc
        look_at(lo, Vector((0, 0, 0.45)))
    if floor and "Floor" not in bpy.data.objects:
        bpy.ops.mesh.primitive_plane_add(size=20, location=(0, 0, 0))
        f = bpy.context.active_object
        f.name = "Floor"
        m = bpy.data.materials.new("FloorMat")
        m.use_nodes = True
        p = next(n for n in m.node_tree.nodes if n.type == "BSDF_PRINCIPLED")
        p.inputs["Base Color"].default_value = (0.85, 0.85, 0.87, 1)
        p.inputs["Roughness"].default_value = 0.5
        f.data.materials.append(m)


def look_at(obj, target):
    d = Vector(target) - obj.location
    obj.rotation_euler = d.to_track_quat("-Z", "Y").to_euler()


def camera(scene, loc, target, lens=40, name="Camera"):
    cam = bpy.data.objects.get(name)
    if cam is None:
        cam = bpy.data.objects.new(name, bpy.data.cameras.new(name))
        scene.collection.objects.link(cam)
    cam.location = loc
    cam.data.lens = lens
    look_at(cam, target)
    scene.camera = cam
    return cam


def machine_bounds():
    """World-space bounding box of everything except studio objects."""
    lo = Vector((1e9, 1e9, 1e9)); hi = Vector((-1e9, -1e9, -1e9))
    for o in bpy.data.objects:
        if o.type != "MESH" or o.name == "Floor" or o.name.startswith("Env_"):
            continue
        for c in o.bound_box:
            w = o.matrix_world @ Vector(c)
            lo = Vector(map(min, lo, w)); hi = Vector(map(max, hi, w))
    return lo, hi


def motion_of(obj):
    import json
    m = obj.get("motion")
    return json.loads(m) if isinstance(m, str) else None


def apply_motion(obj, t, rest=None):
    """Pose obj a fraction t (0..1) of the way along its motion, from its rest transform.
    motion = {"rotate": {"axis": "Z", "degrees": -100}, "translate": [x, y, z]} (both optional),
    about and along the object's own origin, in its parent's space."""
    m = motion_of(obj)
    if not m:
        return False
    if rest is None:
        rest = obj.get("_rest")
        if rest is None:
            rest = list(obj.location) + list(obj.rotation_euler)
            obj["_rest"] = rest
    obj.location = rest[:3]
    obj.rotation_euler = rest[3:6]
    if "rotate" in m:
        ax = "XYZ".index(m["rotate"]["axis"].upper())
        obj.rotation_euler[ax] = rest[3 + ax] + math.radians(m["rotate"]["degrees"]) * t
    if "translate" in m:
        obj.location = [rest[i] + m["translate"][i] * t for i in range(3)]
    return True
