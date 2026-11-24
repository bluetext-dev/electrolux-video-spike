"""A branded intro: the Electrolux logo builds on white, then a line naming the guide.

    blender -b --factory-startup --python intro.py -- brand/electrolux-logo.svg "Care guide · …" OUTDIR
Renders OUTDIR/frames/i_####.png, 1280x720 at 24 fps, 5 s. Deterministic: same code, same intro.
"""
import math, os, sys
import bpy
from mathutils import Vector

svg, line, outdir = sys.argv[sys.argv.index("--") + 1:][:3]
def linear(c):  # Blender colours are linear; brand colours are sRGB
    c /= 255
    return c / 12.92 if c <= 0.04045 else ((c + 0.055) / 1.055) ** 2.4


NAVY = tuple(linear(v) for v in (0x04, 0x1E, 0x41))  # the logo's own colour, #041E41
FPS, SECONDS = 24, 5
scene = bpy.context.scene
for o in list(bpy.data.objects):
    bpy.data.objects.remove(o, do_unlink=True)
scene.render.fps = FPS
scene.frame_start, scene.frame_end = 1, FPS * SECONDS
scene.render.resolution_x, scene.render.resolution_y = 1280, 720
scene.render.film_transparent = False
scene.view_settings.view_transform = "Standard"  # flat graphics: the navy renders as exactly #041E41
for eng in ("BLENDER_EEVEE", "BLENDER_EEVEE_NEXT"):
    try:
        scene.render.engine = eng; break
    except TypeError:
        pass
scene.eevee.taa_render_samples = 32
world = bpy.data.worlds.new("W"); scene.world = world; world.use_nodes = True
bg = next(n for n in world.node_tree.nodes if n.type == "BACKGROUND")
bg.inputs[0].default_value = (1, 1, 1, 1); bg.inputs[1].default_value = 1.0


def fade_material(name, colour):
    """Emission in colour, mixed with transparency by a keyframable factor (0 = invisible)."""
    m = bpy.data.materials.new(name); m.use_nodes = True
    for attr, val in (("surface_render_method", "BLENDED"), ("blend_method", "BLEND")):
        try:
            setattr(m, attr, val)
        except (AttributeError, TypeError):
            pass
    nt = m.node_tree
    for n in list(nt.nodes):
        if n.type != "OUTPUT_MATERIAL":
            nt.nodes.remove(n)
    out = next(n for n in nt.nodes if n.type == "OUTPUT_MATERIAL")
    em = nt.nodes.new("ShaderNodeEmission"); em.inputs[0].default_value = (*colour, 1); em.inputs[1].default_value = 1
    tr = nt.nodes.new("ShaderNodeBsdfTransparent")
    mix = nt.nodes.new("ShaderNodeMixShader")
    nt.links.new(tr.outputs[0], mix.inputs[1]); nt.links.new(em.outputs[0], mix.inputs[2]); nt.links.new(mix.outputs[0], out.inputs[0])
    return m, mix.inputs[0]


def key_fade(socket, f0, f1):
    socket.default_value = 0.0; socket.keyframe_insert("default_value", frame=1)
    socket.keyframe_insert("default_value", frame=f0)
    socket.default_value = 1.0; socket.keyframe_insert("default_value", frame=f1)


# The logo: one curve of 16 outlines. As a mesh, split into loose pieces: the emblem, then letters.
bpy.ops.import_curve.svg(filepath=svg)
curve = bpy.data.objects[0]
bpy.context.view_layer.objects.active = curve; curve.select_set(True)
bpy.ops.object.convert(target="MESH")
bpy.ops.object.mode_set(mode="EDIT"); bpy.ops.mesh.select_all(action="SELECT")
bpy.ops.mesh.separate(type="LOOSE"); bpy.ops.object.mode_set(mode="OBJECT")
pieces = [o for o in bpy.data.objects if o.type == "MESH"]
for o in pieces:
    bpy.context.view_layer.objects.active = o; bpy.ops.object.origin_set(type="ORIGIN_GEOMETRY", center="BOUNDS")
lo = Vector((min(o.location.x - o.dimensions.x / 2 for o in pieces), min(o.location.y - o.dimensions.y / 2 for o in pieces), 0))
hi = Vector((max(o.location.x + o.dimensions.x / 2 for o in pieces), max(o.location.y + o.dimensions.y / 2 for o in pieces), 0))
size = hi - lo
scale = 0.62 / size.x                      # the logo spans 62% of the frame's width (ortho width 1.0)
centre = (lo + hi) / 2
for o in pieces:
    o.location = (o.location - centre) * scale + Vector((0, 0.035, 0)); o.scale = (scale, scale, scale)
emblem_right = (lo.x + size.y * 1.02 - centre.x) * scale   # the emblem is square: as wide as the logo is tall
emblem = [o for o in pieces if o.location.x < emblem_right]
letters = sorted((o for o in pieces if o not in emblem), key=lambda o: o.location.x)

# Emblem: fades in and settles from 92% size.
em_mat, em_fac = fade_material("Emblem", NAVY)
em_root = bpy.data.objects.new("EmblemRoot", None); scene.collection.objects.link(em_root)
em_root.location = sum((o.location for o in emblem), Vector()) / len(emblem)
bpy.context.view_layer.update()  # the pivot's matrix must be current before parenting to it
for o in emblem:
    o.data.materials.clear(); o.data.materials.append(em_mat)
    o.parent = em_root; o.matrix_parent_inverse = em_root.matrix_world.inverted()
key_fade(em_fac, 6, 26)
em_root.scale = (0.92,) * 3; em_root.keyframe_insert("scale", frame=6)
em_root.scale = (1.0,) * 3; em_root.keyframe_insert("scale", frame=34)

# Letters: each fades in and rises a little, one after another.
for k, o in enumerate(letters):
    m, fac = fade_material(f"Letter{k}", NAVY)
    o.data.materials.clear(); o.data.materials.append(m)
    f0 = 22 + 3 * k
    key_fade(fac, f0, f0 + 10)
    y = o.location.y
    o.location.y = y - 0.012; o.keyframe_insert("location", index=1, frame=f0)
    o.location.y = y; o.keyframe_insert("location", index=1, frame=f0 + 12)

# The line under the logo.
cu = bpy.data.curves.new("line", "FONT"); cu.body = line; cu.size = 0.026; cu.align_x = "CENTER"; cu.align_y = "CENTER"
try:
    cu.font = bpy.data.fonts.load("/System/Library/Fonts/Supplemental/Arial.ttf")
except RuntimeError:
    pass
txt = bpy.data.objects.new("Line", cu); scene.collection.objects.link(txt); txt.location = (0, -0.095, 0)
tm, tfac = fade_material("LineMat", NAVY); txt.data.materials.append(tm)
key_fade(tfac, 62, 78)

# Everything eases.
for a in bpy.data.actions:
    for fc in getattr(a, "fcurves", []):
        for kp in fc.keyframe_points:
            kp.interpolation = "SINE"; kp.easing = "EASE_OUT"

cam = bpy.data.objects.new("Cam", bpy.data.cameras.new("Cam")); scene.collection.objects.link(cam)
cam.data.type = "ORTHO"; cam.data.ortho_scale = 1.0; cam.location = (0, 0, 2); scene.camera = cam
os.makedirs(os.path.join(outdir, "frames"), exist_ok=True)
scene.render.image_settings.media_type = "IMAGE"; scene.render.image_settings.file_format = "PNG"
scene.render.filepath = os.path.join(outdir, "frames", "i_")
bpy.ops.render.render(animation=True)
