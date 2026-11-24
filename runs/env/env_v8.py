# Hand-tuned by Claude from astra's env_v6.py (2026-09-28): paler oak, lighter stone, exposure 0, camera 2 moved right.
import bpy
import math
import os
import sys
import random
import numpy as np
from mathutils import Vector, Matrix

random.seed(21)
BASE = os.environ["VP_HERE"]
scene = bpy.context.scene

# Replace only previously generated environment geometry.
for obj in list(bpy.data.objects):
    if obj.name.startswith("Env_"):
        bpy.data.objects.remove(obj, do_unlink=True)
for collection in list(bpy.data.collections):
    if collection.name.startswith("Env_"):
        bpy.data.collections.remove(collection)

TRACK = (
    "objects", "meshes", "curves", "materials", "images", "collections",
    "cameras", "lights", "worlds", "node_groups", "armatures", "actions",
)
original = {key: set(getattr(bpy.data, key)) for key in TRACK}

# Remove competing presentation light from the render without deleting,
# moving, renaming, or altering any existing machine geometry/materials.
for obj in scene.objects:
    if obj.type == "LIGHT":
        obj.hide_render = True

env = bpy.data.collections.new("Env_Set")
scene.collection.children.link(env)


def path(relative):
    result = os.path.join(BASE, relative)
    if not os.path.isfile(result):
        raise FileNotFoundError(result)
    return result


def link_env(obj):
    for collection in list(obj.users_collection):
        collection.objects.unlink(obj)
    env.objects.link(obj)
    return obj


def empty(name):
    obj = bpy.data.objects.new("Env_" + name, None)
    env.objects.link(obj)
    return obj


metric_space = empty("MetricTextureSpace")


def principled(mat):
    return next(
        n for n in mat.node_tree.nodes
        if n.type == "BSDF_PRINCIPLED"
    )


def plain(name, color, roughness=0.5, metallic=0):
    mat = bpy.data.materials.new("Env_" + name)
    mat.use_nodes = True
    bs = principled(mat)
    bs.inputs["Base Color"].default_value = (*color, 1)
    bs.inputs["Roughness"].default_value = roughness
    bs.inputs["Metallic"].default_value = metallic
    return mat


def color_mix(nt, source, color, amount, mode="MIX"):
    mix = nt.nodes.new("ShaderNodeMixRGB")
    mix.blend_type = mode
    mix.inputs[0].default_value = amount
    nt.links.new(source, mix.inputs[1])
    if hasattr(color, "node"):
        nt.links.new(color, mix.inputs[2])
    else:
        mix.inputs[2].default_value = (*color[:3], 1)
    return mix.outputs[0]


# ---------------------------------------------------------------------
# Image loading.
#
# Some marble-map releases include straight tile/grout lines. If present,
# select an interior, square patch from the ACTUAL map, consistently for
# all five channels. This is not a generated vein or replacement texture.
# Without clearly detected grout, use the original maps unchanged.
# ---------------------------------------------------------------------

image_cache = {}
marble_crop = None


def image_array(image):
    w, h = image.size
    pixels = np.empty(w * h * 4, dtype=np.float32)
    image.pixels.foreach_get(pixels)
    return pixels.reshape(h, w, 4)


def grout_free_crop(image):
    pixels = image_array(image)
    h, w = pixels.shape[:2]
    stride = max(1, max(w, h) // 768)
    rgb = pixels[::stride, ::stride, :3]
    lum = rgb @ np.array((0.2126, 0.7152, 0.0722), np.float32)
    hh, ww = lum.shape

    def largest_interval(a, axis):
        count = a.shape[axis]
        radius = max(3, count // 90)
        # A grout line must be darker than BOTH parallel neighbours,
        # across most of the image. Fine marble veins normally fail this.
        before = np.roll(a, radius, axis=axis)
        after = np.roll(a, -radius, axis=axis)
        dark = (np.minimum(before, after) - a) > 0.016
        coverage = dark.mean(axis=1-axis)
        candidates = np.flatnonzero(coverage > 0.78)
        candidates = candidates[
            (candidates > radius) & (candidates < count-radius)
        ]
        if len(candidates) == 0:
            return (0, count), False

        groups = np.split(
            candidates, np.where(np.diff(candidates) > 2)[0] + 1
        )
        boundaries = [0] + [int(np.median(g)) for g in groups] + [count]
        intervals = list(zip(boundaries[:-1], boundaries[1:]))
        lo, hi = max(intervals, key=lambda pair: pair[1]-pair[0])
        guard = max(3, count // 150)
        lo += guard if lo else 0
        hi -= guard if hi < count else 0
        return (lo, hi), True

    (y0, y1), found_y = largest_interval(lum, 0)
    (x0, x1), found_x = largest_interval(lum, 1)
    if not (found_x or found_y):
        return None

    # A square crop avoids distorting the stone's vein aspect ratio.
    side = min(x1-x0, y1-y0)
    if side < min(hh, ww) * 0.18:
        return None
    xc, yc = (x0+x1)/2, (y0+y1)/2
    return (
        (xc-side/2)/ww, (yc-side/2)/hh,
        (xc+side/2)/ww, (yc+side/2)/hh,
    )


def texture_image(asset, kind):
    global marble_crop
    key = (asset, kind)
    if key in image_cache:
        return image_cache[key]

    image = bpy.data.images.load(
        path(f"assets/textures/{asset}/{kind}.jpg"),
        check_existing=False,
    )
    image.name = f"Env_{asset}_{kind}"
    image.colorspace_settings.name = (
        "sRGB" if kind == "diffuse" else "Non-Color"
    )

    if asset == "marble_01":
        if kind == "diffuse":
            marble_crop = grout_free_crop(image)
        if marble_crop:
            w, h = image.size
            u0, v0, u1, v1 = marble_crop
            x0, x1 = int(u0*w), int(u1*w)
            y0, y1 = int(v0*h), int(v1*h)
            data = image_array(image)[y0:y1, x0:x1].copy()
            cropped = bpy.data.images.new(
                f"Env_MarbleInterior_{kind}",
                width=x1-x0, height=y1-y0,
                alpha=True, float_buffer=False,
            )
            cropped.colorspace_settings.name = image.colorspace_settings.name
            cropped.pixels.foreach_set(data.ravel())
            cropped.update()
            cropped.pack()
            image = cropped

    image_cache[key] = image
    return image


def pbr(name, asset, tile=1, tint=None, tint_amount=0,
        saturation=1, value=1, rough=(0.45, 0.7),
        normal_strength=0.15, bump_distance=0.0003,
        rotation=(0, 0, 0), ao_amount=0.025):
    mat = plain(name, (0.5, 0.5, 0.5))
    nt = mat.node_tree
    n, l = nt.nodes, nt.links
    bs = principled(mat)

    tc = n.new("ShaderNodeTexCoord")
    tc.object = metric_space
    mapping = n.new("ShaderNodeMapping")
    mapping.name = "Env_RealMetreMapping"
    if isinstance(tile, (int, float)):
        tile = (tile, tile, tile)
    mapping.inputs["Scale"].default_value = tuple(1/x for x in tile)
    mapping.inputs["Rotation"].default_value = rotation
    l.new(tc.outputs["Object"], mapping.inputs["Vector"])

    maps = {}
    for kind in ("diffuse", "roughness", "normal", "displacement", "ao"):
        tex = n.new("ShaderNodeTexImage")
        tex.name = "Env_Map_" + kind
        tex.image = texture_image(asset, kind)
        tex.projection = "BOX"
        tex.projection_blend = 0.16
        l.new(mapping.outputs["Vector"], tex.inputs["Vector"])
        maps[kind] = tex

    hue = n.new("ShaderNodeHueSaturation")
    hue.name = "Env_DesaturateAndDarken"
    hue.inputs["Saturation"].default_value = saturation
    hue.inputs["Value"].default_value = value
    l.new(maps["diffuse"].outputs["Color"], hue.inputs["Color"])
    color = hue.outputs["Color"]
    if tint is not None:
        color = color_mix(nt, color, tint, tint_amount)
    color = color_mix(
        nt, color, maps["ao"].outputs["Color"], ao_amount, "MULTIPLY"
    )
    l.new(color, bs.inputs["Base Color"])

    remap = n.new("ShaderNodeMapRange")
    remap.inputs["To Min"].default_value = rough[0]
    remap.inputs["To Max"].default_value = rough[1]
    l.new(maps["roughness"].outputs["Color"], remap.inputs["Value"])
    l.new(remap.outputs["Result"], bs.inputs["Roughness"])

    normal = n.new("ShaderNodeNormalMap")
    normal.inputs["Strength"].default_value = normal_strength
    l.new(maps["normal"].outputs["Color"], normal.inputs["Color"])

    bump = n.new("ShaderNodeBump")
    bump.inputs["Strength"].default_value = 0.06
    bump.inputs["Distance"].default_value = bump_distance
    l.new(maps["displacement"].outputs["Color"], bump.inputs["Height"])
    l.new(normal.outputs["Normal"], bump.inputs["Normal"])
    l.new(bump.outputs["Normal"], bs.inputs["Normal"])
    return mat


oak = pbr(
    "PaleNaturalOak", "oak_veneer_01",
    tile=(1.55, 0.85, 0.43), rotation=(0, math.pi/2, 0),
    tint=(0.70, 0.58, 0.37), tint_amount=0.30,
    saturation=0.64, value=1.12, rough=(0.46, 0.62), normal_strength=0.07,
)
oak_edge = pbr(
    "OakFineLipping", "oak_veneer_01",
    tile=(1.55, 0.85, 0.43), rotation=(0, math.pi/2, 0),
    tint=(0.64, 0.52, 0.33), tint_amount=0.32,
    saturation=0.64, value=1.05, rough=(0.47, 0.63), normal_strength=0.05,
)
stone = pbr(
    "ContinuousMidGreyMarble", "marble_01", tile=1.5,
    saturation=0.03, value=0.66,
    tint=(0.195, 0.211, 0.218), tint_amount=0.08,
    rough=(0.46, 0.59), normal_strength=0.045,
    bump_distance=0.00007, ao_amount=0.01,
)
floor_mat = pbr(
    "DarkConcrete", "concrete_floor_02", tile=2.3,
    tint=(0.059, 0.065, 0.061), tint_amount=0.79,
    saturation=0.12, rough=(0.72, 0.86),
    normal_strength=0.19, bump_distance=0.0005,
)
plaster = pbr(
    "SoftWhitePlaster", "white_plaster_02", tile=1.7,
    tint=(0.78, 0.775, 0.745), tint_amount=0.87,
    saturation=0.1, rough=(0.84, 0.96), normal_strength=0.07,
)


def fabric(name, color, tile=0.065):
    mat = pbr(
        name, "denim_fabric", tile=tile,
        tint=color, tint_amount=0.975, saturation=0,
        rough=(0.88, 0.99), normal_strength=0.28,
        bump_distance=0.00022, ao_amount=0.015,
    )
    principled(mat).inputs["Sheen Weight"].default_value = 0.22
    return mat


cream = fabric("IvoryTerry", (0.67, 0.638, 0.553))
linen = fabric("NaturalTaupeLinen", (0.35, 0.294, 0.223))
grey_cloth = fabric("GreyGreenTowel", (0.225, 0.237, 0.217))
rug_mat = fabric("OliveGreenRug", (0.105, 0.175, 0.089), 0.095)
dark = plain("RecessShadow", (0.055, 0.039, 0.023), 0.88)
steel = plain("PolishedTapChrome", (0.62, 0.64, 0.62), 0.14, 0.98)
sink_mat = plain("BrushedSinkSteel", (0.30, 0.32, 0.30), 0.30, 0.94)
ceramic = plain("WarmCreamCeramic", (0.74, 0.72, 0.655), 0.32)
amber = plain("AmberSoapBottle", (0.19, 0.109, 0.029), 0.28)
black = plain("BlackPump", (0.016, 0.020, 0.016), 0.35)
window_wood = plain("WarmWindowOak", (0.26, 0.103, 0.035), 0.43)
wicker_inner = plain("WickerInterior", (0.13, 0.083, 0.036), 0.9)
wicker_mats = [
    plain(
        f"Willow{i:02d}",
        (0.255+0.014*i, 0.173+0.010*i, 0.087+0.006*i), 0.79,
    )
    for i in range(6)
]


def box(name, location, size, mat, bevel=0):
    bpy.ops.mesh.primitive_cube_add(size=1, location=location)
    obj = link_env(bpy.context.object)
    obj.name = "Env_" + name
    obj.dimensions = size
    bpy.ops.object.transform_apply(location=False, rotation=False, scale=True)
    if mat:
        obj.data.materials.append(mat)
    if bevel:
        mod = obj.modifiers.new("Env_EdgeSoftness", "BEVEL")
        mod.width = bevel
        mod.segments = 3
        mod = obj.modifiers.new("Env_WeightedNormals", "WEIGHTED_NORMAL")
        mod.keep_sharp = True
    return obj


def mesh_obj(name, verts, faces, mat, smooth=False):
    data = bpy.data.meshes.new("Env_" + name + "Mesh")
    data.from_pydata(verts, [], faces)
    data.update()
    obj = bpy.data.objects.new("Env_" + name, data)
    env.objects.link(obj)
    if mat:
        data.materials.append(mat)
    uv = data.uv_layers.new(name="Env_MetricUV")
    for poly in data.polygons:
        poly.use_smooth = smooth
        axis = max(range(3), key=lambda k: abs(poly.normal[k]))
        axes = ((1, 2), (0, 2), (0, 1))[axis]
        for li in poly.loop_indices:
            co = data.vertices[data.loops[li].vertex_index].co
            uv.data[li].uv = (co[axes[0]], co[axes[1]])
    return obj


def multi_curve(name, paths, radius, mat, cyclic=False, resolution=2):
    data = bpy.data.curves.new("Env_" + name + "Curve", "CURVE")
    data.dimensions = "3D"
    data.bevel_depth = radius
    data.bevel_resolution = resolution
    for points in paths:
        sp = data.splines.new("POLY")
        sp.points.add(len(points)-1)
        for p, co in zip(sp.points, points):
            p.co = (*co, 1)
        sp.use_cyclic_u = cyclic
    obj = bpy.data.objects.new("Env_" + name, data)
    env.objects.link(obj)
    data.materials.append(mat)
    return obj


def curve(name, points, radius, mat, cyclic=False, resolution=2):
    return multi_curve(name, [points], radius, mat, cyclic, resolution)


def cylinder(name, location, radius, depth, mat, vertices=48):
    bpy.ops.mesh.primitive_cylinder_add(
        vertices=vertices, radius=radius, depth=depth, location=location
    )
    obj = link_env(bpy.context.object)
    obj.name = "Env_" + name
    obj.data.materials.append(mat)
    mod = obj.modifiers.new("Env_RimBevel", "BEVEL")
    mod.width = min(0.0015, depth/5)
    mod.segments = 3
    obj.modifiers.new("Env_WeightedNormals", "WEIGHTED_NORMAL")
    for poly in obj.data.polygons:
        poly.use_smooth = True
    return obj


def import_asset(asset, name, dimensions, location, angle=0):
    before = set(bpy.data.objects)
    bpy.ops.import_scene.gltf(
        filepath=path(f"assets/models/{asset}/{asset}_2k.gltf")
    )
    imported = set(bpy.data.objects)-before
    bpy.context.view_layer.update()
    corners = [
        obj.matrix_world @ Vector(c)
        for obj in imported if obj.type == "MESH"
        for c in obj.bound_box
    ]
    if not corners:
        raise RuntimeError("No mesh imported from " + asset)
    lo = Vector(tuple(min(v[i] for v in corners) for i in range(3)))
    hi = Vector(tuple(max(v[i] for v in corners) for i in range(3)))
    extent = hi-lo
    root = empty(name)
    for i, obj in enumerate(sorted(imported, key=lambda o: o.name)):
        obj.name = f"Env_{name}_Part{i:03d}"
        if obj.parent not in imported:
            matrix = obj.matrix_world.copy()
            obj.parent = root
            obj.matrix_world = matrix
        link_env(obj)
        if obj.type in {"LIGHT", "CAMERA"}:
            obj.hide_render = True

    scale = Vector(tuple(
        dimensions[i]/max(extent[i], 1e-6) for i in range(3)
    ))
    anchor = Vector(((lo.x+hi.x)/2, (lo.y+hi.y)/2, lo.z))
    offset = Vector(tuple(anchor[i]*scale[i] for i in range(3)))
    root.scale = scale
    root.rotation_euler.z = angle
    root.location = Vector(location)-Matrix.Rotation(angle, 3, "Z") @ offset
    bpy.context.view_layer.update()
    return root, imported


def tint_imported(parts, color, amount, saturation=0.5):
    copies = {}
    for obj in parts:
        if obj.type != "MESH":
            continue
        for slot in obj.material_slots:
            old = slot.material
            if not old or not old.use_nodes:
                continue
            if old not in copies:
                mat = old.copy()
                mat.name = "Env_AssetTint_" + old.name
                copies[old] = mat
                nt = mat.node_tree
                bs = principled(mat)
                hue = nt.nodes.new("ShaderNodeHueSaturation")
                hue.inputs["Saturation"].default_value = saturation
                inp = bs.inputs["Base Color"]
                if inp.is_linked:
                    nt.links.new(inp.links[0].from_socket, hue.inputs["Color"])
                else:
                    hue.inputs["Color"].default_value = tuple(inp.default_value)
                output = color_mix(nt, hue.outputs["Color"], color, amount)
                nt.links.new(output, bs.inputs["Base Color"])
            slot.material = copies[old]


# ---------------------------------------------------------------------
# Architecture, built around the unchanged machine.
# Washer: X +/-0.2985, Y +/-0.318, Z 0..0.847.
# ---------------------------------------------------------------------

FRONT = -0.318
BOTTOM, TOP = 0.858, 0.881
X0, X1 = -1.345, 0.912
Y0, Y1 = -0.343, 0.377

box("Floor", (0, -1.6, -0.06), (8, 8, 0.12), floor_mat, 0.001)
box("StoneBackWall", (-0.205, 0.425, 1.4),
    (2.40, 0.09, 2.8), stone, 0.0005)
box("LeftWhiteWall", (-1.405, -0.95, 1.4),
    (0.12, 2.85, 2.8), plaster, 0.001)

# Rear return only: no forward-running grey/right wall panel.
box("RightRearPlasterReturn", (0.995, 0.422, 1.4),
    (0.088, 0.09, 2.8), plaster, 0.001)


def cabinet(name, xa, xb):
    width, x = xb-xa, (xa+xb)/2
    for label, xx in (("L", xa+0.009), ("R", xb-0.009)):
        box(name+"Side"+label, (xx, 0.015, 0.45),
            (0.018, 0.625, 0.802), oak, 0.0007)
    box(name+"Back", (x, 0.324, 0.45),
        (width-0.036, 0.014, 0.802), oak)
    box(name+"Base", (x, 0.015, 0.059),
        (width-0.036, 0.60, 0.018), oak)
    box(name+"ToeRecess", (x, -0.262, 0.021),
        (width-0.006, 0.056, 0.042), dark)
    box(name+"Plinth", (x, -0.290, 0.026),
        (width-0.006, 0.012, 0.041), oak_edge, 0.0006)
    box(name+"FrontReveal", (x, -0.290, 0.447),
        (width-0.006, 0.010, 0.80), dark)

    for label, za, zb in (("Lower", 0.044, 0.441),
                           ("Upper", 0.446, 0.852)):
        w, h, z, edge = width-0.005, zb-za, (za+zb)/2, 0.007
        box(name+label+"Front", (x, FRONT+0.011, z),
            (w-2*edge, 0.022, h-2*edge), oak, 0.0008)
        for side in (-1, 1):
            box(name+label+"Upright"+str(side),
                (x+side*(w-edge)/2, FRONT+0.011, z),
                (edge, 0.022, h), oak_edge, 0.0006)
            box(name+label+"Rail"+str(side),
                (x, FRONT+0.011, z+side*(h-edge)/2),
                (w-2*edge, 0.022, edge), oak_edge, 0.0006)


cabinet("LeftA", -1.325, -0.819)
cabinet("LeftB", -0.819, -0.310)
cabinet("RightA", 0.310, 0.890)
box("RightEndPanel", (0.899, 0.018, 0.443),
    (0.018, 0.65, 0.829), oak, 0.001)

# Worktop with a genuine inset-sink opening.
HX0, HX1 = -0.919, -0.504
HY0, HY1 = -0.232, 0.137


def slab(name, xa, xb, ya, yb):
    return box(
        name, ((xa+xb)/2, (ya+yb)/2, (TOP+BOTTOM)/2),
        (xb-xa, yb-ya, TOP-BOTTOM), stone, 0.0005,
    )


slab("CounterLeft", X0, HX0, Y0, Y1)
slab("CounterMain", HX1, X1, Y0, Y1)
slab("CounterSinkFront", HX0, HX1, Y0, HY0)
slab("CounterSinkRear", HX0, HX1, HY1, Y1)
box("StoneBackSeal", ((X0+X1)/2, 0.376, TOP),
    (X1-X0, 0.0025, 0.0025), stone, 0.0004)


def rounded_ring(cx, cy, w, d, r, z, steps=12):
    result = []
    for ox, oy, start in (
        (w/2-r, d/2-r, 0), (-w/2+r, d/2-r, 90),
        (-w/2+r, -d/2+r, 180), (w/2-r, -d/2+r, 270),
    ):
        for i in range(steps):
            a = math.radians(start+90*i/steps)
            result.append((
                cx+ox+r*math.cos(a), cy+oy+r*math.sin(a), z
            ))
    return result


cx, cy = (HX0+HX1)/2, (HY0+HY1)/2
rings = (
    (0.430, 0.384, 0.040, TOP+0.0013),
    (0.407, 0.361, 0.041, TOP+0.0015),
    (0.391, 0.345, 0.045, TOP-0.014),
    (0.292, 0.246, 0.057, TOP-0.150),
)
verts, faces = [], []
for w, d, r, z in rings:
    verts.extend(rounded_ring(cx, cy, w, d, r, z))
N = 48
for j in range(3):
    for i in range(N):
        k = (i+1) % N
        faces.append((j*N+i, j*N+k, (j+1)*N+k, (j+1)*N+i))
faces.append(tuple(range(3*N, 4*N)))
sink = mesh_obj("InsetSink", verts, faces, sink_mat, True)
sink.modifiers.new("Env_SinkThickness", "SOLIDIFY").thickness = 0.001
cylinder("SinkDrain", (cx, cy, TOP-0.148), 0.023, 0.002, steel)
for i in range(6):
    a = math.tau*i/6
    cylinder(
        "DrainHole"+str(i),
        (cx+0.014*math.cos(a), cy+0.014*math.sin(a), TOP-0.1465),
        0.0016, 0.0005, black, 12,
    )

tx, ty = -0.745, 0.226
cylinder("TapFoot", (tx, ty, TOP+0.004), 0.022, 0.008, steel)
points = [(tx, ty, TOP+0.005), (tx, ty, 1.124)]
for i in range(49):
    a = math.pi*i/48
    points.append((
        tx, ty-0.059+0.059*math.cos(a), 1.124+0.059*math.sin(a)
    ))
points.append((tx, ty-0.118, 1.085))
curve("GooseneckTap", points, 0.009, steel)
cylinder("TapAerator", (tx, ty-0.118, 1.087), 0.0096, 0.010, steel)
curve("TapLever", [
    (tx+0.009, ty, 0.952), (tx+0.045, ty, 0.952),
    (tx+0.049, ty, 0.994),
], 0.0035, steel)


def soap(name, x, y, z, mat, height=0.073):
    cylinder(name+"Body", (x, y, z+height/2), 0.019, height, mat)
    cylinder(name+"Collar", (x, y, z+height+0.004), 0.009, 0.008, steel)
    cylinder(name+"Stem", (x, y, z+height+0.013), 0.003, 0.012, black)
    curve(name+"Pump", [
        (x, y, z+height+0.022), (x, y-0.022, z+height+0.022),
        (x, y-0.026, z+height+0.018),
    ], 0.0028, black)


soap("AmberSinkSoap", -0.626, 0.226, TOP, amber, 0.071)
soap("IvorySinkSoap", -0.566, 0.237, TOP, ceramic, 0.065)

# ---------------------------------------------------------------------
# Imported props. All changes below apply only to newly imported assets.
# ---------------------------------------------------------------------

_, plant_parts = import_asset(
    "potted_plant_02", "Plant",
    (0.231, 0.211, 0.345), (-1.149, 0.168, TOP), -0.4,
)
for obj in plant_parts:
    if obj.type != "MESH":
        continue
    obj.data.materials.append(ceramic)
    idx = len(obj.data.materials)-1
    normal_matrix = obj.matrix_world.to_3x3().inverted().transposed()
    for poly in obj.data.polygons:
        co = obj.matrix_world @ poly.center
        normal = (normal_matrix @ poly.normal).normalized()
        if TOP-0.004 < co.z < TOP+0.101 and normal.z < 0.7:
            poly.material_index = idx

box("CleaningTray", (0.420, 0.279, TOP+0.003),
    (0.184, 0.101, 0.006), ceramic, 0.005)
_, spray_parts = import_asset(
    "multi_cleaner_bottle", "SprayBottle",
    (0.050, 0.051, 0.143), (0.365, 0.282, TOP+0.006), 0.15,
)
_, bleach_parts = import_asset(
    "bleach_bottle", "SmallCleaningBottle",
    (0.035, 0.026, 0.104), (0.428, 0.298, TOP+0.006), -0.2,
)
tint_imported(spray_parts, (0.265, 0.285, 0.245), 0.38, 0.18)
tint_imported(bleach_parts, (0.63, 0.606, 0.535), 0.62, 0.12)
soap("TraySoap", 0.483, 0.267, TOP+0.006, ceramic, 0.060)

for obj in spray_parts:
    if obj.type != "MESH":
        continue
    obj.data.materials.append(black)
    idx = len(obj.data.materials)-1
    for poly in obj.data.polygons:
        if (obj.matrix_world @ poly.center).z > TOP+0.126:
            poly.material_index = idx

# ---------------------------------------------------------------------
# Modeled cloth.
# ---------------------------------------------------------------------

def folded_towel(name, position, width, depth, height, mat, angle=0):
    root = empty(name)
    root.location = position
    root.rotation_euler.z = angle
    nu, nv = 28, 20
    verts, faces = [], []
    phase = random.uniform(0, math.tau)
    for layer in range(2):
        for j in range(nv+1):
            v = j/nv
            for i in range(nu+1):
                u = i/nu
                x = (u-0.5)*width*(1-0.045*abs(2*v-1)**8)
                y = (v-0.5)*depth*(1-0.045*abs(2*u-1)**8)
                crown = max(
                    0, math.sin(math.pi*u)*math.sin(math.pi*v)
                )**0.45
                ripple = (
                    0.0014*math.sin(19*u+7*v+phase)
                    + 0.0008*math.sin(31*v-9*u)
                )
                z = (
                    height*(0.70+0.30*crown)+ripple if layer == 0
                    else height*(0.13-0.10*crown)+ripple*0.2
                )
                verts.append((x, y, z))

    count = (nu+1)*(nv+1)
    for j in range(nv):
        for i in range(nu):
            a = j*(nu+1)+i
            faces.append((a, a+1, a+nu+2, a+nu+1))
            b = a+count
            faces.append((b+nu+1, b+nu+2, b+1, b))
    boundary = (
        list(range(nu+1))
        + [j*(nu+1)+nu for j in range(1, nv+1)]
        + [nv*(nu+1)+i for i in range(nu-1, -1, -1)]
        + [j*(nu+1) for j in range(nv-1, 0, -1)]
    )
    for i, a in enumerate(boundary):
        b = boundary[(i+1) % len(boundary)]
        faces.append((a, a+count, b+count, b))

    obj = mesh_obj(name+"Cloth", verts, faces, mat, True)
    obj.parent = root
    mod = obj.modifiers.new("Env_SoftFold", "SUBSURF")
    mod.levels = mod.render_levels = 1
    hem = [
        ((i/48-0.5)*width*0.955, -depth*0.491,
         height*0.40+0.001*math.sin(13*i/48+phase))
        for i in range(49)
    ]
    obj = curve(name+"FoldHem", hem, 0.00065, mat)
    obj.parent = root
    return root


def catmull(points, t):
    p = [Vector(a) for a in points]
    s = t*(len(p)-1)
    j = min(int(s), len(p)-2)
    u = s-j
    a, b = p[max(0, j-1)], p[j]
    c, d = p[j+1], p[min(len(p)-1, j+2)]
    return 0.5*(
        2*b+(-a+c)*u+(2*a-5*b+4*c-d)*u*u
        +(-a+3*b-3*c+d)*u*u*u
    )


def drape(name, route, width, mat, amplitude=0.008):
    nu, nv = 36, 56
    verts, faces = [], []
    for j in range(nv+1):
        t = j/nv
        center = catmull(route, t)
        tangent = (
            catmull(route, min(1, t+0.003))
            -catmull(route, max(0, t-0.003))
        ).normalized()
        lateral = Vector((1, 0, 0))
        normal = lateral.cross(tangent).normalized()
        for i in range(nu+1):
            u = i/nu
            ripple = amplitude*(
                0.72*math.sin(u*math.tau*2.8+t*2.5)
                +0.28*math.sin(u*math.tau*5.1-t*4)
            )
            q = center+lateral*((u-0.5)*width)+normal*ripple
            q.z += 0.0016*math.sin(9*u+12*t)
            verts.append(tuple(q))
    for j in range(nv):
        for i in range(nu):
            a = j*(nu+1)+i
            faces.append((a, a+1, a+nu+2, a+nu+1))
    obj = mesh_obj(name, verts, faces, mat, True)
    mod = obj.modifiers.new("Env_ClothSmooth", "SUBSURF")
    mod.levels = mod.render_levels = 1
    obj.modifiers.new("Env_ClothThickness", "SOLIDIFY").thickness = 0.0014
    for label, ix in (("L", 1), ("R", nu-1)):
        curve(
            name+"Hem"+label,
            [verts[j*(nu+1)+ix] for j in range(nv+1)],
            0.0006, mat,
        )
    return obj


folded_towel("CounterBaseTowel", (-0.045, 0.023, TOP+0.001),
             0.263, 0.178, 0.027, grey_cloth, -0.05)
folded_towel("CounterIvoryTowel", (-0.040, 0.029, TOP+0.025),
             0.244, 0.167, 0.031, cream, 0.02)
folded_towel("CounterLinenTowel", (-0.028, 0.039, TOP+0.053),
             0.226, 0.158, 0.029, linen, 0.06)
drape("CounterLooseLinen", [
    (-0.065, 0.103, TOP+0.083), (-0.071, 0.028, TOP+0.085),
    (-0.065, -0.064, TOP+0.057), (-0.048, -0.111, TOP+0.017),
], 0.159, linen, 0.009)

folded_towel("RightGreyFold", (0.805, 0.075, TOP+0.001),
             0.185, 0.218, 0.019, grey_cloth, -0.10)
drape("RightCounterDrape", [
    (0.804, 0.125, TOP+0.024), (0.808, -0.130, TOP+0.019),
    (0.816, -0.326, TOP+0.014), (0.827, -0.362, TOP-0.013),
    (0.841, -0.374, TOP-0.085),
], 0.178, grey_cloth, 0.006)

# ---------------------------------------------------------------------
# Wicker hampers. Both remain laterally clear of the washer.
# ---------------------------------------------------------------------

def round_basket(name, center, rx0, ry0, height, stake_count=104):
    cx, cy, base = center

    def radii(t):
        f = 0.89+0.11*t+0.052*math.sin(math.pi*t)
        return rx0*f, ry0*f

    verts, faces = [], []
    for j in range(17):
        t = j/16
        rx, ry = radii(t)
        for i in range(stake_count):
            a = math.tau*i/stake_count
            verts.append((
                cx+(rx-0.0035)*math.cos(a),
                cy+(ry-0.0035)*math.sin(a),
                base+0.008+t*(height-0.013),
            ))
    for j in range(16):
        for i in range(stake_count):
            k = (i+1) % stake_count
            faces.append((
                j*stake_count+i, j*stake_count+k,
                (j+1)*stake_count+k, (j+1)*stake_count+i,
            ))
    faces.append(tuple(reversed(range(stake_count))))
    mesh_obj(name+"InnerBody", verts, faces, wicker_inner, True)

    groups = [[] for _ in wicker_mats]
    for i in range(stake_count):
        a = math.tau*i/stake_count
        points = []
        for j in range(33):
            t = j/32
            rx, ry = radii(t)
            points.append((
                cx+rx*math.cos(a), cy+ry*math.sin(a),
                base+0.008+t*(height-0.013),
            ))
        groups[i % len(groups)].append(points)
    for i, paths in enumerate(groups):
        multi_curve(name+f"Stakes{i}", paths, 0.00165,
                    wicker_mats[i], resolution=1)

    groups = [[] for _ in wicker_mats]
    rows, segments = int(height/0.0035), stake_count*4
    for row in range(rows):
        t = (row+0.5)/rows
        rx, ry = radii(t)
        points = []
        for i in range(segments):
            a = math.tau*i/segments
            weave = 0.0020*math.cos(a*stake_count/2+math.pi*(row % 2))
            points.append((
                cx+(rx+weave)*math.cos(a),
                cy+(ry+weave)*math.sin(a),
                base+0.009+t*(height-0.018),
            ))
        groups[(row+row//7) % len(groups)].append(points)
    for i, paths in enumerate(groups):
        multi_curve(name+f"WovenRows{i}", paths, 0.00145,
                    wicker_mats[i], cyclic=True, resolution=1)

    for label, t, z, radius in (
        ("BottomRim", 0, base+0.010, 0.004),
        ("TopRim", 1, base+height-0.004, 0.0055),
    ):
        rx, ry = radii(t)
        curve(name+label, [
            (cx+rx*math.cos(math.tau*i/240),
             cy+ry*math.sin(math.tau*i/240), z)
            for i in range(240)
        ], radius, wicker_mats[3], True)

    for side in (-1, 1):
        y = cy+side*ry0*0.77
        points = [
            (cx+rx0*0.29*math.cos(math.pi*i/64), y,
             base+height-0.014+0.059*math.sin(math.pi*i/64))
            for i in range(65)
        ]
        curve(name+"Handle"+str(side), points, 0.0046, wicker_mats[2])
        binding = []
        for i in range(321):
            a, b = math.pi*i/320, math.tau*24*i/320
            binding.append((
                cx+rx0*0.29*math.cos(a)+0.0048*math.cos(b)*math.cos(a),
                y+0.0048*math.sin(b),
                base+height-0.014+0.059*math.sin(a)
                +0.0048*math.cos(b)*math.sin(a),
            ))
        curve(name+"HandleBinding"+str(side), binding, 0.0007,
              wicker_mats[4], resolution=1)


round_basket("LeftHamper", (-1.157, -0.583, 0.006),
             0.149, 0.137, 0.399)
round_basket("RightHamper", (0.694, -0.542, 0.004),
             0.204, 0.185, 0.342)

_, caddy_parts = import_asset(
    "wicker_basket_01", "LeftInsetCaddy",
    (0.255, 0.215, 0.073), (-1.157, -0.583, 0.315), -0.08,
)
tint_imported(caddy_parts, (0.285, 0.19, 0.094), 0.20, 0.8)

folded_towel("LeftHamperIvory", (-1.162, -0.582, 0.356),
             0.237, 0.204, 0.028, cream, -0.1)
folded_towel("LeftHamperGrey", (-1.176, -0.565, 0.382),
             0.188, 0.154, 0.025, grey_cloth, 0.22)
drape("LeftHangingTowel", [
    (-1.065, -0.548, 0.418), (-1.048, -0.687, 0.411),
    (-1.034, -0.730, 0.339), (-1.017, -0.744, 0.165),
    (-0.998, -0.772, 0.044), (-0.975, -0.829, 0.021),
    (-0.935, -0.946, 0.019),
], 0.177, cream, 0.010)

folded_towel("RightHamperBaseTowel", (0.689, -0.539, 0.292),
             0.299, 0.242, 0.029, linen, -0.1)
folded_towel("RightHamperIvory", (0.680, -0.548, 0.317),
             0.277, 0.213, 0.028, cream, 0.12)
drape("RightHamperLooseLinen", [
    (0.758, -0.472, 0.353), (0.753, -0.555, 0.359),
    (0.764, -0.659, 0.349),
], 0.146, cream, 0.009)

# Visible olive rug, confined to the left-cabinet floor area.
# The entire washer-width approach stays free of props/rug for >1.5 m.
RX0, RX1 = -1.337, -0.365
RY0, RY1 = -1.40, -0.445
box("GreenRug", ((RX0+RX1)/2, (RY0+RY1)/2, 0.002),
    (RX1-RX0, RY1-RY0, 0.004), rug_mat, 0.0015)
for i, y in enumerate((RY0+0.004, RY1-0.004)):
    curve("RugBoundEdge"+str(i),
          [(RX0+0.005, y, 0.0045), (RX1-0.005, y, 0.0045)],
          0.001, rug_mat)
for i, x in enumerate((RX0+0.004, RX1-0.004)):
    curve("RugSideBinding"+str(i),
          [(x, RY0+0.005, 0.0045), (x, RY1-0.005, 0.0045)],
          0.001, rug_mat)
fringes = []
for i in range(78):
    x = RX0+0.012+i*(RX1-RX0-0.024)/77
    fringes.append([
        (x, RY0, 0.003),
        (x+random.uniform(-0.003, 0.003),
         RY0-0.014-random.random()*0.006, 0.0015),
    ])
multi_curve("RugFringe", fringes, 0.0005, rug_mat, resolution=1)

# ---------------------------------------------------------------------
# Right glazed door: the opening, timber divisions and gathered sheer
# provide real shadow geometry. No opaque foreground right wall.
# ---------------------------------------------------------------------

WX = 1.085
YA, YB = -2.55, 0.278

box("WindowRearPier", (WX+0.025, 0.378, 1.40),
    (0.115, 0.13, 2.8), plaster, 0.001)
box("WindowHeader", (WX, (YA+YB)/2, 2.75),
    (0.16, YB-YA+0.16, 0.15), plaster, 0.001)
box("WindowThreshold", (WX, (YA+YB)/2, 0.026),
    (0.17, YB-YA+0.06, 0.052), stone, 0.001)

for label, y in (("Rear", YB), ("Front", YA)):
    box("WindowJamb"+label, (WX, y, 1.35),
        (0.080, 0.052, 2.57), window_wood, 0.0015)
for label, z in (("Bottom", 0.073), ("Top", 2.628)):
    box("WindowRail"+label, (WX, (YA+YB)/2, z),
        (0.080, YB-YA+0.05, 0.048), window_wood, 0.0015)

# Positioned to throw separate oblique streaks over the fronts and floor.
for i, y in enumerate((-0.74, -1.57)):
    box("WindowMullion"+str(i), (WX, y, 1.35),
        (0.088, 0.048, 2.51), window_wood, 0.001)
box("WindowTransom", (WX, (YA+YB)/2, 1.60),
    (0.088, YB-YA, 0.043), window_wood, 0.001)
box("RearDoorGasket", (WX-0.043, YB-0.026, 1.35),
    (0.006, 0.009, 2.50), black, 0.0005)

glass = plain("ClearWindowGlass", (0.97, 0.985, 0.99), 0.035)
bs = principled(glass)
bs.inputs["Transmission Weight"].default_value = 1
bs.inputs["IOR"].default_value = 1.45
nt = glass.node_tree
out = next(n for n in nt.nodes if n.type == "OUTPUT_MATERIAL")
lp = nt.nodes.new("ShaderNodeLightPath")
transparent = nt.nodes.new("ShaderNodeBsdfTransparent")
mix = nt.nodes.new("ShaderNodeMixShader")
nt.links.new(lp.outputs["Is Shadow Ray"], mix.inputs[0])
nt.links.new(bs.outputs[0], mix.inputs[1])
nt.links.new(transparent.outputs[0], mix.inputs[2])
nt.links.new(mix.outputs[0], out.inputs["Surface"])
box("WindowGlass", (WX+0.035, (YA+YB)/2, 1.35),
    (0.003, YB-YA-0.06, 2.49), glass)

curtain_mat = fabric("WarmWhiteSheer", (0.80, 0.795, 0.76), 0.05)
nt = curtain_mat.node_tree
bs = principled(curtain_mat)
out = next(n for n in nt.nodes if n.type == "OUTPUT_MATERIAL")
translucent = nt.nodes.new("ShaderNodeBsdfTranslucent")
translucent.inputs["Color"].default_value = (0.80, 0.79, 0.75, 1)
mix = nt.nodes.new("ShaderNodeMixShader")
mix.inputs[0].default_value = 0.42
nt.links.new(bs.outputs[0], mix.inputs[1])
nt.links.new(translucent.outputs[0], mix.inputs[2])
transparent = nt.nodes.new("ShaderNodeBsdfTransparent")
sheer_mix = nt.nodes.new("ShaderNodeMixShader")
sheer_mix.inputs[0].default_value = 0.27
nt.links.new(mix.outputs[0], sheer_mix.inputs[1])
nt.links.new(transparent.outputs[0], sheer_mix.inputs[2])
nt.links.new(sheer_mix.outputs[0], out.inputs["Surface"])


def gathered_curtain(name, ya, yb, folds, x=0.985):
    verts, faces = [], []
    nu, nv = 144, 56
    for j in range(nv+1):
        v = j/nv
        pool = (1-v)**15
        for i in range(nu+1):
            u = i/nu
            phase = u*math.tau*folds
            xx = (
                x+0.041*math.sin(phase)
                +0.008*math.sin(2*phase+0.3)
                -pool*(0.021+0.010*math.sin(phase))
            )
            # Small backtracking in Y makes overlapping folds, producing
            # actual narrow differences in transmitted sunlight.
            yy = ya+(yb-ya)*u+0.010*math.sin(phase+0.6)
            yy -= pool*(0.019+0.008*math.sin(phase+0.5))
            zz = 0.010+2.62*v+pool*(0.007+0.006*math.cos(phase))
            verts.append((xx, yy, zz))
    for j in range(nv):
        for i in range(nu):
            a = j*(nu+1)+i
            faces.append((a, a+1, a+nu+2, a+nu+1))
    obj = mesh_obj(name, verts, faces, curtain_mat, True)
    mod = obj.modifiers.new("Env_SheerSmooth", "SUBSURF")
    mod.levels = mod.render_levels = 1
    curve(name+"BottomHem", verts[:nu+1], 0.0012, curtain_mat)
    return obj


gathered_curtain("RearGatheredWhiteSheer", -0.335, 0.255, 8.3)

# The farther curtain bounds the sunlight opening without adding an
# opaque wall panel to Camera 2. It remains beside, not before, the washer.
gathered_curtain("FarGatheredWhiteSheer", -2.51, -1.98, 8.0, 1.005)
curve("CurtainRail", [(1.0, YA, 2.663), (1.0, 0.29, 2.663)],
      0.006, ceramic)

# A distant garden visible through the glass, transparent to illumination.
garden = plain("DistantGarden", (0.2, 0.28, 0.13), 1)
nt = garden.node_tree
n, l = nt.nodes, nt.links
tc = n.new("ShaderNodeTexCoord")
noise = n.new("ShaderNodeTexNoise")
noise.inputs["Scale"].default_value = 14
noise.inputs["Detail"].default_value = 4
l.new(tc.outputs["Generated"], noise.inputs["Vector"])
ramp = n.new("ShaderNodeValToRGB")
ramp.color_ramp.elements[0].position = 0.2
ramp.color_ramp.elements[0].color = (0.035, 0.069, 0.013, 1)
ramp.color_ramp.elements[1].position = 0.82
ramp.color_ramp.elements[1].color = (0.48, 0.55, 0.28, 1)
l.new(noise.outputs["Fac"], ramp.inputs["Fac"])
emission = n.new("ShaderNodeEmission")
emission.inputs["Strength"].default_value = 1.1
l.new(ramp.outputs["Color"], emission.inputs["Color"])
transparent = n.new("ShaderNodeBsdfTransparent")
lp = n.new("ShaderNodeLightPath")
mix = n.new("ShaderNodeMixShader")
l.new(lp.outputs["Is Camera Ray"], mix.inputs[0])
l.new(transparent.outputs[0], mix.inputs[1])
l.new(emission.outputs[0], mix.inputs[2])
out = next(node for node in n if node.type == "OUTPUT_MATERIAL")
l.new(mix.outputs[0], out.inputs["Surface"])
box("GardenBeyondWindow", (3.8, -1.1, 1.7), (0.012, 8, 5), garden)

# ---------------------------------------------------------------------
# Lighting: direct low sun dominates; weak HDRI and genuine multibounce
# illumination retain readable, warm shadows without studio-flat fill.
# ---------------------------------------------------------------------

world = bpy.data.worlds.new("Env_World")
world.use_nodes = True
scene.world = world
nt = world.node_tree
nt.nodes.clear()
out = nt.nodes.new("ShaderNodeOutputWorld")
background = nt.nodes.new("ShaderNodeBackground")
background.inputs["Strength"].default_value = 0.012
environment = nt.nodes.new("ShaderNodeTexEnvironment")
environment.image = bpy.data.images.load(
    path("assets/hdri/photo_studio_loft_hall.hdr"), check_existing=False
)
environment.image.name = "Env_LoftHDRI"
environment.image.colorspace_settings.name = "Non-Color"
tc = nt.nodes.new("ShaderNodeTexCoord")
mapping = nt.nodes.new("ShaderNodeMapping")

# Rotate the strongest broad HDRI region toward the photo's left;
# its intensity is intentionally far below the right-window sun.
image = environment.image
w, h = image.size
pixels = image_array(image)
sx, sy = max(1, w//180), max(1, h//90)
sample = pixels[h//2:int(h*0.93):sy, ::sx, :3]
lum = sample @ np.array((0.2126, 0.7152, 0.0722), np.float32)
lum = np.nan_to_num(lum, nan=0, posinf=0, neginf=0)
smooth = sum(np.roll(lum, k, axis=1) for k in range(-5, 6))/11
_, col = np.unravel_index(np.argmax(smooth), smooth.shape)
u = (col*sx+0.5)/w
bright_azimuth = math.tau*(0.5-u)
desired_azimuth = math.atan2(-1.8, -2.5)
mapping.inputs["Rotation"].default_value[2] = (
    bright_azimuth-desired_azimuth
)
del pixels, sample, lum, smooth

nt.links.new(tc.outputs["Generated"], mapping.inputs["Vector"])
nt.links.new(mapping.outputs["Vector"], environment.inputs["Vector"])
nt.links.new(environment.outputs["Color"], background.inputs["Color"])
nt.links.new(background.outputs[0], out.inputs["Surface"])


def aim(obj, target):
    obj.rotation_euler = (
        Vector(target)-obj.location
    ).to_track_quat("-Z", "Y").to_euler()


def srgb_to_linear(v):
    return v/12.92 if v <= 0.04045 else ((v+0.055)/1.055)**2.4


def kelvin_rgb(kelvin):
    t = kelvin/100
    r = 255 if t <= 66 else 329.698727446*(t-60)**-0.1332047592
    g = (
        99.4708025861*math.log(t)-161.1195681661 if t <= 66
        else 288.1221695283*(t-60)**-0.0755148492
    )
    b = (
        255 if t >= 66 else 0 if t <= 19
        else 138.5177312231*math.log(t-10)-305.0447927307
    )
    return tuple(
        srgb_to_linear(max(0, min(255, c))/255) for c in (r, g, b)
    )


def light(name, kind, location, target, energy, color, size=1):
    data = bpy.data.lights.new("Env_"+name, kind)
    data.energy = energy
    data.color = color
    if kind == "SUN":
        data.angle = math.radians(0.38)
    elif kind == "AREA":
        data.shape = "DISK"
        data.size = size
    obj = bpy.data.objects.new("Env_"+name, data)
    env.objects.link(obj)
    obj.location = location
    aim(obj, target)
    return obj


# Low late-afternoon angle; the slightly more oblique direction gives
# stronger diagonal frame shadows than the previous shallow streak.
elevation = math.radians(23)
azimuth = math.radians(-39)
to_sun = Vector((
    math.cos(elevation)*math.cos(azimuth),
    math.cos(elevation)*math.sin(azimuth),
    math.sin(elevation),
))
sun_target = Vector((-0.10, 0.04, 0.60))
sun = light(
    "LowWarmAfternoonSun", "SUN",
    sun_target+to_sun*8, sun_target, 5.2, kelvin_rgb(4400),
)
sun.data["Env_ColorTemperatureK"] = 4400
sun.data["Env_ElevationDegrees"] = 23

# These are deliberately small compared with the sun. Most warm fill
# comes from Cycles diffuse bounces off the existing set surfaces.
light("WindowSkyFill", "AREA",
      (1.32, -1.30, 1.95), (-0.42, 0.08, 0.68),
      7.0, (0.86, 0.92, 1.0), 1.9)
light("LeftWarmBounce", "AREA",
      (-1.13, -1.90, 1.70), (-0.02, 0.08, 0.60),
      3.0, kelvin_rgb(4900), 2.1)

# ---------------------------------------------------------------------
# Cameras: both inside the window plane. Lower framing includes the
# floor/rug and the whole right basket, without a foreground wall panel.
# ---------------------------------------------------------------------

def camera(name, location, target, lens):
    data = bpy.data.cameras.new("Env_"+name)
    obj = bpy.data.objects.new("Env_"+name, data)
    env.objects.link(obj)
    obj.location = location
    aim(obj, target)
    data.lens = lens
    data.sensor_width = 36
    data.sensor_fit = "HORIZONTAL"
    data.clip_start = 0.035
    data.clip_end = 100
    data.dof.use_dof = False
    return obj


cam1 = camera(
    "RefCamera",
    (-0.52, -4.15, 0.985),
    (-0.345, -0.14, 0.515),
    58.0,
)
camera(
    "RefCamera2",
    (0.86, -3.97, 0.985),
    (0.26, -0.08, 0.505),
    57.0,
)
scene.camera = cam1

# No change to resolution, aspect ratio, or render output.
scene.render.engine = "CYCLES"
scene.cycles.samples = 256
scene.cycles.use_denoising = True
scene.cycles.max_bounces = 14
scene.cycles.diffuse_bounces = 8
scene.cycles.glossy_bounces = 5
scene.cycles.transmission_bounces = 8
scene.cycles.transparent_max_bounces = 32
scene.cycles.seed = 21

scene.view_settings.view_transform = "AgX"
scene.view_settings.exposure = 0.0
scene.view_settings.gamma = 1.0
for candidate in ("AgX - Medium High Contrast", "Medium High Contrast"):
    try:
        scene.view_settings.look = candidate
        break
    except (TypeError, ValueError):
        pass

# Prefix every newly created datablock, including imported asset data.
for kind in TRACK:
    for block in getattr(bpy.data, kind):
        if block not in original[kind] and not block.name.startswith("Env_"):
            block.name = "Env_" + block.name

bpy.context.view_layer.update()
bpy.ops.wm.save_as_mainfile(filepath=sys.argv[sys.argv.index("--") + 1])
