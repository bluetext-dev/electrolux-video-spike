import bpy
import math
import os
import sys
import random
from mathutils import Vector, Matrix

random.seed(21)
BASE = os.environ["VP_HERE"]
scene = bpy.context.scene

# The source scene, including every washer object and material, is untouched.
TRACK = (
    "objects", "meshes", "curves", "materials", "images", "collections",
    "cameras", "lights", "worlds", "node_groups", "armatures", "actions",
)
original = {k: set(getattr(bpy.data, k)) for k in TRACK}

env = bpy.data.collections.new("Env_Set")
scene.collection.children.link(env)


def asset_path(relative):
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


texture_space = empty("MetricTextureSpace")


def principled(mat):
    return next(
        n for n in mat.node_tree.nodes
        if n.type == "BSDF_PRINCIPLED"
    )


def plain(name, color, roughness=0.5, metallic=0.0):
    mat = bpy.data.materials.new("Env_" + name)
    mat.use_nodes = True
    bs = principled(mat)
    bs.inputs["Base Color"].default_value = (*color, 1)
    bs.inputs["Roughness"].default_value = roughness
    bs.inputs["Metallic"].default_value = metallic
    return mat


def pbr(name, asset, tile=1.0, tint=None, tint_amount=0.0,
        saturation=1.0, rough=(0.4, 0.7), normal_strength=0.2,
        bump_distance=0.0005, rotation=(0, 0, 0), ao_amount=0.08):
    mat = plain(name, (0.5, 0.5, 0.5))
    nt = mat.node_tree
    n, l = nt.nodes, nt.links
    bs = principled(mat)

    coord = n.new("ShaderNodeTexCoord")
    coord.object = texture_space
    mapping = n.new("ShaderNodeMapping")
    mapping.vector_type = "POINT"
    if isinstance(tile, (int, float)):
        tile = (tile, tile, tile)
    mapping.inputs["Scale"].default_value = tuple(1.0 / a for a in tile)
    mapping.inputs["Rotation"].default_value = rotation
    l.new(coord.outputs["Object"], mapping.inputs["Vector"])

    maps = {}
    for kind in ("diffuse", "roughness", "normal", "displacement", "ao"):
        node = n.new("ShaderNodeTexImage")
        node.name = "Env_" + name + "_" + kind
        node.image = bpy.data.images.load(
            asset_path(f"assets/textures/{asset}/{kind}.jpg"),
            check_existing=False,
        )
        node.image.colorspace_settings.name = (
            "sRGB" if kind == "diffuse" else "Non-Color"
        )
        node.projection = "BOX"
        node.projection_blend = 0.25
        l.new(mapping.outputs["Vector"], node.inputs["Vector"])
        maps[kind] = node

    hue = n.new("ShaderNodeHueSaturation")
    hue.inputs["Saturation"].default_value = saturation
    l.new(maps["diffuse"].outputs["Color"], hue.inputs["Color"])
    color = hue.outputs["Color"]

    if tint is not None:
        mix = n.new("ShaderNodeMixRGB")
        mix.blend_type = "MIX"
        mix.inputs[0].default_value = tint_amount
        mix.inputs[2].default_value = (*tint, 1)
        l.new(color, mix.inputs[1])
        color = mix.outputs[0]

    ao = n.new("ShaderNodeMixRGB")
    ao.blend_type = "MULTIPLY"
    ao.inputs[0].default_value = ao_amount
    l.new(color, ao.inputs[1])
    l.new(maps["ao"].outputs["Color"], ao.inputs[2])
    l.new(ao.outputs[0], bs.inputs["Base Color"])

    remap = n.new("ShaderNodeMapRange")
    remap.inputs["To Min"].default_value = rough[0]
    remap.inputs["To Max"].default_value = rough[1]
    l.new(maps["roughness"].outputs["Color"], remap.inputs["Value"])
    l.new(remap.outputs["Result"], bs.inputs["Roughness"])

    normal = n.new("ShaderNodeNormalMap")
    normal.inputs["Strength"].default_value = normal_strength
    l.new(maps["normal"].outputs["Color"], normal.inputs["Color"])

    bump = n.new("ShaderNodeBump")
    bump.inputs["Strength"].default_value = 0.12
    bump.inputs["Distance"].default_value = bump_distance
    l.new(maps["displacement"].outputs["Color"], bump.inputs["Height"])
    l.new(normal.outputs["Normal"], bump.inputs["Normal"])
    l.new(bump.outputs["Normal"], bs.inputs["Normal"])
    return mat


oak = pbr(
    "LightHoneyOak", "oak_veneer_01",
    tile=(0.90, 0.90, 1.85),
    rotation=(0, math.pi / 2, 0),
    tint=(0.57, 0.405, 0.225), tint_amount=0.48,
    saturation=0.65, rough=(0.43, 0.60),
    normal_strength=0.12, ao_amount=0.04,
)
oak_edge = pbr(
    "OakFineEdging", "oak_veneer_01",
    tile=(1.3, 1.3, 2.2),
    rotation=(0, math.pi / 2, 0),
    tint=(0.54, 0.38, 0.205), tint_amount=0.65,
    saturation=0.6, normal_strength=0.08,
)
stone = pbr(
    "ContinuousGreyMarble", "marble_01", tile=2.8,
    tint=(0.255, 0.265, 0.255), tint_amount=0.88,
    saturation=0.12, rough=(0.36, 0.48),
    normal_strength=0.035, bump_distance=0.00012, ao_amount=0.02,
)

# Broad, continuous veining in world metres.
# The supplied marble maps remain connected for its underlying PBR finish.
nt = stone.node_tree
n, l = nt.nodes, nt.links
bs = principled(stone)
underlying = bs.inputs["Base Color"].links[0].from_socket

tc = n.new("ShaderNodeTexCoord")
tc.object = texture_space
mapping = n.new("ShaderNodeMapping")
mapping.inputs["Scale"].default_value = (0.95, 1.0, 1.3)
mapping.inputs["Rotation"].default_value = (0, -0.38, 0)
l.new(tc.outputs["Object"], mapping.inputs["Vector"])

noise = n.new("ShaderNodeTexNoise")
noise.inputs["Scale"].default_value = 2.1
noise.inputs["Detail"].default_value = 4.0
noise.inputs["Roughness"].default_value = 0.68
l.new(mapping.outputs["Vector"], noise.inputs["Vector"])

warp = n.new("ShaderNodeVectorMath")
warp.operation = "SCALE"
warp.inputs["Scale"].default_value = 0.31
l.new(noise.outputs["Color"], warp.inputs[0])
add = n.new("ShaderNodeVectorMath")
add.operation = "ADD"
l.new(mapping.outputs["Vector"], add.inputs[0])
l.new(warp.outputs["Vector"], add.inputs[1])

vor = n.new("ShaderNodeTexVoronoi")
vor.feature = "DISTANCE_TO_EDGE"
vor.inputs["Scale"].default_value = 1.65
l.new(add.outputs["Vector"], vor.inputs["Vector"])

veins = n.new("ShaderNodeValToRGB")
veins.color_ramp.elements[0].position = 0.006
veins.color_ramp.elements[0].color = (0.9, 0.9, 0.9, 1)
veins.color_ramp.elements[1].position = 0.032
veins.color_ramp.elements[1].color = (0, 0, 0, 1)
l.new(vor.outputs["Distance"], veins.inputs["Fac"])

variation = n.new("ShaderNodeMapRange")
variation.inputs["To Min"].default_value = 0.28
variation.inputs["To Max"].default_value = 0.95
l.new(noise.outputs["Fac"], variation.inputs["Value"])
multiply = n.new("ShaderNodeMath")
multiply.operation = "MULTIPLY"
l.new(veins.outputs["Color"], multiply.inputs[0])
l.new(variation.outputs["Result"], multiply.inputs[1])

mix = n.new("ShaderNodeMixRGB")
mix.inputs[2].default_value = (0.68, 0.69, 0.655, 1)
l.new(multiply.outputs[0], mix.inputs[0])
l.new(underlying, mix.inputs[1])
l.new(mix.outputs[0], bs.inputs["Base Color"])

floor_mat = pbr(
    "DarkQuietConcrete", "concrete_floor_02", tile=2.1,
    tint=(0.055, 0.063, 0.061), tint_amount=0.78,
    saturation=0.12, rough=(0.70, 0.86),
    normal_strength=0.20, bump_distance=0.0007,
)
plaster = pbr(
    "SoftWhitePlaster", "white_plaster_02", tile=1.6,
    tint=(0.83, 0.815, 0.77), tint_amount=0.83,
    saturation=0.15, rough=(0.80, 0.94),
    normal_strength=0.13,
)
rug_mat = pbr(
    "MutedOliveRug", "denim_fabric", tile=0.13,
    tint=(0.135, 0.19, 0.115), tint_amount=0.96,
    saturation=0, rough=(0.90, 0.99), normal_strength=0.48,
)
cream = pbr(
    "WarmIvoryTerry", "denim_fabric", tile=0.075,
    tint=(0.73, 0.71, 0.65), tint_amount=0.97,
    saturation=0, rough=(0.88, 0.98), normal_strength=0.36,
)
linen = pbr(
    "NaturalLinen", "denim_fabric", tile=0.09,
    tint=(0.385, 0.35, 0.29), tint_amount=0.96,
    saturation=0, rough=(0.86, 0.98), normal_strength=0.3,
)
grey_cloth = pbr(
    "SoftGreyTowel", "denim_fabric", tile=0.08,
    tint=(0.28, 0.295, 0.28), tint_amount=0.96,
    saturation=0, rough=(0.87, 0.98), normal_strength=0.3,
)

dark = plain("FineCabinetShadow", (0.12, 0.092, 0.055), 0.8)
steel = plain("SatinChrome", (0.57, 0.59, 0.57), 0.19, 0.95)
sink_mat = plain("BrushedSinkSteel", (0.36, 0.39, 0.38), 0.3, 0.9)
ceramic = plain("IvoryCeramic", (0.78, 0.775, 0.715), 0.30)
amber = plain("AmberGlassSoap", (0.18, 0.105, 0.026), 0.24)
black = plain("CharcoalPump", (0.018, 0.022, 0.019), 0.32)
window_wood = plain("WarmWindowFrame", (0.24, 0.105, 0.035), 0.37)
stitch_mat = plain("TowelHemThread", (0.51, 0.49, 0.435), 0.95)
wicker_inner = plain("BasketInterior", (0.19, 0.13, 0.065), 0.86)
wicker_mats = [
    plain(
        "Willow_%02d" % i,
        (0.34 + i * 0.016, 0.245 + i * 0.012, 0.13 + i * 0.008),
        0.73,
    )
    for i in range(6)
]


def box(name, loc, size, mat, bevel=0):
    bpy.ops.mesh.primitive_cube_add(size=1, location=loc)
    obj = link_env(bpy.context.object)
    obj.name = "Env_" + name
    obj.dimensions = size
    bpy.ops.object.transform_apply(location=False, rotation=False, scale=True)
    if mat:
        obj.data.materials.append(mat)
    if bevel:
        mod = obj.modifiers.new("Env_SoftEdges", "BEVEL")
        mod.width = bevel
        mod.segments = 3
        mod = obj.modifiers.new("Env_WeightedNormals", "WEIGHTED_NORMAL")
        mod.keep_sharp = True
    return obj


def mesh_obj(name, verts, faces, mat):
    data = bpy.data.meshes.new("Env_" + name + "Mesh")
    data.from_pydata(verts, [], faces)
    data.update()
    obj = bpy.data.objects.new("Env_" + name, data)
    env.objects.link(obj)
    if mat:
        data.materials.append(mat)
    return obj


def curve(name, points, radius, mat, cyclic=False, resolution=2):
    data = bpy.data.curves.new("Env_" + name + "Curve", "CURVE")
    data.dimensions = "3D"
    data.bevel_depth = radius
    data.bevel_resolution = resolution
    sp = data.splines.new("POLY")
    sp.points.add(len(points) - 1)
    for p, co in zip(sp.points, points):
        p.co = (*co, 1)
    sp.use_cyclic_u = cyclic
    obj = bpy.data.objects.new("Env_" + name, data)
    env.objects.link(obj)
    data.materials.append(mat)
    return obj


def cylinder(name, loc, radius, depth, mat, vertices=48):
    bpy.ops.mesh.primitive_cylinder_add(
        vertices=vertices, radius=radius, depth=depth, location=loc
    )
    obj = link_env(bpy.context.object)
    obj.name = "Env_" + name
    obj.data.materials.append(mat)
    mod = obj.modifiers.new("Env_RoundedLip", "BEVEL")
    mod.width = min(0.0025, depth / 5)
    mod.segments = 3
    obj.modifiers.new("Env_WeightedNormals", "WEIGHTED_NORMAL")
    for p in obj.data.polygons:
        p.use_smooth = True
    return obj


def import_asset(asset, name, dims, location, angle=0):
    before = set(bpy.data.objects)
    bpy.ops.import_scene.gltf(
        filepath=asset_path(f"assets/models/{asset}/{asset}_2k.gltf")
    )
    imported = set(bpy.data.objects) - before
    bpy.context.view_layer.update()

    corners = [
        obj.matrix_world @ Vector(c)
        for obj in imported if obj.type == "MESH"
        for c in obj.bound_box
    ]
    if not corners:
        raise RuntimeError("No mesh in " + asset)

    lo = Vector(tuple(min(v[i] for v in corners) for i in range(3)))
    hi = Vector(tuple(max(v[i] for v in corners) for i in range(3)))
    extent = hi - lo
    root = empty(name)

    for i, obj in enumerate(sorted(imported, key=lambda o: o.name)):
        obj.name = f"Env_{name}_Part_{i:03d}"
        if obj.parent not in imported:
            matrix = obj.matrix_world.copy()
            obj.parent = root
            obj.matrix_world = matrix
        link_env(obj)

    scale = Vector(tuple(dims[i] / max(extent[i], 1e-6) for i in range(3)))
    anchor = Vector(((lo.x + hi.x) / 2, (lo.y + hi.y) / 2, lo.z))
    offset = Vector(tuple(anchor[i] * scale[i] for i in range(3)))
    rotation = Matrix.Rotation(angle, 3, "Z")
    root.scale = scale
    root.rotation_euler.z = angle
    root.location = Vector(location) - rotation @ offset
    bpy.context.view_layer.update()
    return root, imported


# ---------- Room and fitted cabinetry ----------

FRONT = -0.318
TOP = 0.881
BOTTOM = 0.858
X0, X1 = -1.345, 1.01
Y0, Y1 = -0.347, 0.377

box("Floor", (0, -1.6, -0.06), (8, 8, 0.12), floor_mat, 0.003)
box("StoneBackWall", (-0.163, 0.425, 1.4),
    (2.385, 0.09, 2.8), stone, 0.001)
box("LeftPlasterWall", (-1.405, -0.9, 1.4),
    (0.12, 2.74, 2.8), plaster, 0.003)
box("RightBackReturn", (1.08, 0.425, 1.4),
    (0.10, 0.09, 2.8), plaster, 0.002)


def cabinet(name, xa, xb):
    width = xb - xa
    x = (xa + xb) / 2
    box(name + "Carcass", (x, 0.024, 0.451),
        (width - 0.004, 0.62, 0.806), oak, 0.001)
    box(name + "RevealBacking", (x, -0.294, 0.455),
        (width - 0.004, 0.024, 0.798), dark)
    box(name + "ToeShadow", (x, -0.25, 0.023),
        (width - 0.006, 0.07, 0.046), dark, 0.001)
    box(name + "OakPlinth", (x, -0.287, 0.032),
        (width - 0.006, 0.014, 0.05), oak_edge, 0.001)

    for label, za, zb in (
        ("Lower", 0.047, 0.444),
        ("Upper", 0.449, 0.852),
    ):
        w = width - 0.006
        h = zb - za
        z = (za + zb) / 2
        # Almost flush, narrow perimeter edging rather than deep shaker doors.
        box(name + label + "FlatFront", (x, FRONT + 0.012, z),
            (w - 0.015, 0.022, h - 0.015), oak, 0.0012)
        edge = 0.008
        for side in (-1, 1):
            box(name + label + "SideEdge" + str(side),
                (x + side * (w - edge) / 2, FRONT + 0.01, z),
                (edge, 0.024, h), oak_edge, 0.0008)
            box(name + label + "CrossEdge" + str(side),
                (x, FRONT + 0.01, z + side * (h - edge) / 2),
                (w - 2 * edge, 0.024, edge), oak_edge, 0.0008)


cabinet("LeftA", -1.325, -0.82)
cabinet("LeftB", -0.82, -0.310)
cabinet("RightA", 0.310, 0.990)
box("RightCabinetEnd", (0.998, 0.018, 0.436),
    (0.016, 0.65, 0.842), oak, 0.0015)

# Genuine sink opening; no solid slab underneath the basin.
HX0, HX1 = -0.912, -0.492
HY0, HY1 = -0.242, 0.137


def slab(name, xa, xb, ya, yb):
    box(name, ((xa + xb) / 2, (ya + yb) / 2, (TOP + BOTTOM) / 2),
        (xb - xa, yb - ya, TOP - BOTTOM), stone, 0.0012)


slab("CounterLeft", X0, HX0, Y0, Y1)
slab("CounterRight", HX1, X1, Y0, Y1)
slab("CounterSinkFront", HX0, HX1, Y0, HY0)
slab("CounterSinkBack", HX0, HX1, HY1, Y1)
box("CounterBackJoint", (-0.167, 0.375, TOP),
    (2.35, 0.003, 0.003), stone, 0.0005)


def rounded_ring(cx, cy, w, d, r, z, steps=12):
    points = []
    for ox, oy, start in (
        (w / 2 - r, d / 2 - r, 0),
        (-w / 2 + r, d / 2 - r, 90),
        (-w / 2 + r, -d / 2 + r, 180),
        (w / 2 - r, -d / 2 + r, 270),
    ):
        for i in range(steps):
            a = math.radians(start + i * 90 / steps)
            points.append((
                cx + ox + r * math.cos(a),
                cy + oy + r * math.sin(a), z
            ))
    return points


cx, cy = -0.702, -0.0525
specs = (
    (0.434, 0.393, 0.045, TOP + 0.0015),
    (0.413, 0.373, 0.043, TOP + 0.0018),
    (0.395, 0.355, 0.047, TOP - 0.017),
    (0.295, 0.255, 0.060, TOP - 0.146),
)
verts = []
for w, d, r, z in specs:
    verts.extend(rounded_ring(cx, cy, w, d, r, z))
faces = []
N = 48
for j in range(len(specs) - 1):
    for i in range(N):
        k = (i + 1) % N
        faces.append((j*N+i, j*N+k, (j+1)*N+k, (j+1)*N+i))
faces.append(tuple(range((len(specs)-1)*N, len(specs)*N)))
basin = mesh_obj("InsetSink", verts, faces, sink_mat)
for p in basin.data.polygons:
    p.use_smooth = True
mod = basin.modifiers.new("Env_SinkThickness", "SOLIDIFY")
mod.thickness = 0.001
cylinder("SinkDrain", (cx, cy, TOP-0.144), 0.023, 0.002, steel)
for i in range(6):
    a = math.tau * i / 6
    cylinder("DrainSlot_%d" % i,
             (cx + 0.014*math.cos(a), cy + 0.014*math.sin(a), TOP-0.1425),
             0.0017, 0.0005, black, 12)

tx, ty = -0.745, 0.223
cylinder("TapBase", (tx, ty, TOP+0.004), 0.022, 0.008, steel)
points = [(tx, ty, TOP+0.005), (tx, ty, 1.113)]
for i in range(49):
    t = math.pi * i / 48
    points.append((tx, ty-0.060+0.060*math.cos(t),
                   1.113+0.060*math.sin(t)))
points.append((tx, ty-0.120, 1.072))
curve("GooseneckTap", points, 0.009, steel)
cylinder("TapNozzle", (tx, ty-0.120, 1.076), 0.0105, 0.015, steel)
curve("TapLever", [
    (tx+0.009, ty, 0.955),
    (tx+0.046, ty, 0.955),
    (tx+0.052, ty, 0.993),
], 0.0036, steel)


def soap(name, x, y, z, mat, height=0.075):
    cylinder(name+"Body", (x, y, z+height/2), 0.021, height, mat)
    cylinder(name+"Collar", (x, y, z+height+0.005), 0.011, 0.01, steel)
    cylinder(name+"Stem", (x, y, z+height+0.017), 0.003, 0.017, black)
    curve(name+"Pump", [
        (x, y, z+height+0.027),
        (x, y-0.024, z+height+0.027),
        (x, y-0.029, z+height+0.022),
    ], 0.0032, black)


soap("SinkSoap", -0.556, 0.222, TOP, amber)
soap("SinkSmallSoap", -0.485, 0.243, TOP, ceramic, 0.068)

# ---------- Countertop props ----------

plant_root, plant_parts = import_asset(
    "potted_plant_02", "Plant",
    (0.30, 0.28, 0.35), (-1.135, 0.133, TOP), -0.35
)

# Recolour only the imported pot's low outer faces; preserve foliage and soil.
for obj in plant_parts:
    if obj.type != "MESH":
        continue
    obj.data.materials.append(ceramic)
    index = len(obj.data.materials) - 1
    normal_matrix = obj.matrix_world.to_3x3().inverted().transposed()
    for poly in obj.data.polygons:
        center = obj.matrix_world @ poly.center
        normal = (normal_matrix @ poly.normal).normalized()
        if TOP-0.003 <= center.z < TOP+0.091 and normal.z < 0.65:
            poly.material_index = index

box("SmallSoapTray", (0.225, 0.205, TOP+0.006),
    (0.265, 0.135, 0.012), ceramic, 0.008)

spray_root, spray_parts = import_asset(
    "multi_cleaner_bottle", "NeutralSprayBottle",
    (0.061, 0.063, 0.170), (0.157, 0.215, TOP+0.012), 0.13
)
bottle_root, bottle_parts = import_asset(
    "bleach_bottle", "NeutralCleaningBottle",
    (0.049, 0.038, 0.135), (0.253, 0.233, TOP+0.012), -0.25
)


def tint_imported_materials(parts, color, amount):
    # Copy before editing, even if the importer reused a source datablock.
    copies = {}
    for obj in parts:
        if obj.type != "MESH":
            continue
        for slot in obj.material_slots:
            old = slot.material
            if old is None or not old.use_nodes:
                continue
            if old not in copies:
                mat = old.copy()
                mat.name = "Env_Neutralized_" + old.name
                copies[old] = mat
                bs = principled(mat)
                nt = mat.node_tree
                hue = nt.nodes.new("ShaderNodeHueSaturation")
                hue.inputs["Saturation"].default_value = 0.06
                if bs.inputs["Base Color"].is_linked:
                    source = bs.inputs["Base Color"].links[0].from_socket
                    nt.links.new(source, hue.inputs["Color"])
                else:
                    hue.inputs["Color"].default_value = (
                        bs.inputs["Base Color"].default_value
                    )
                mix = nt.nodes.new("ShaderNodeMixRGB")
                mix.inputs[0].default_value = amount
                mix.inputs[2].default_value = (*color, 1)
                nt.links.new(hue.outputs["Color"], mix.inputs[1])
                nt.links.new(mix.outputs[0], bs.inputs["Base Color"])
            slot.material = copies[old]


tint_imported_materials(spray_parts, (0.32, 0.345, 0.315), 0.5)
tint_imported_materials(bottle_parts, (0.72, 0.70, 0.63), 0.76)

# Make the imported trigger head dark, leaving its actual shape intact.
for obj in spray_parts:
    if obj.type != "MESH":
        continue
    obj.data.materials.append(black)
    index = len(obj.data.materials)-1
    for poly in obj.data.polygons:
        if (obj.matrix_world @ poly.center).z > TOP+0.012+0.137:
            poly.material_index = index

soap("TrayPumpSoap", 0.315, 0.165, TOP+0.012, ceramic, 0.082)

# Keep the provided shallow wicker asset at an appropriate shallow size.
# It supports the small towel stack above the washer.
import_asset(
    "wicker_basket_01", "CounterWickerTray",
    (0.275, 0.205, 0.037), (-0.035, 0.064, TOP), -0.045
)


def folded_towel(name, position, width, depth, height, mat, angle=0):
    # A closed, softly irregular cloth volume, rather than three rigid plates.
    parent = empty(name)
    parent.location = position
    parent.rotation_euler.z = angle
    nu, nv = 32, 24
    verts, faces = [], []
    phase = random.uniform(0, 6)
    for layer in range(2):
        for j in range(nv+1):
            v = j/nv
            for i in range(nu+1):
                u = i/nu
                # Slightly rounded corners in plan.
                x = (u-0.5)*width
                y = (v-0.5)*depth
                x *= 1-0.025*abs(2*v-1)**8
                y *= 1-0.035*abs(2*u-1)**8
                crown = (math.sin(math.pi*u)*math.sin(math.pi*v))**0.45
                ripple = (
                    0.0018*math.sin(19*u+7*v+phase)
                    + 0.0012*math.sin(31*v-9*u)
                )
                if layer == 0:
                    z = height*(0.72+0.28*crown)+ripple
                else:
                    z = height*(0.13-0.10*crown)+ripple*0.25
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
    obj = mesh_obj(name+"Cloth", verts, faces, mat)
    obj.parent = parent
    for p in obj.data.polygons:
        p.use_smooth = True
    mod = obj.modifiers.new("Env_SoftFold", "SUBSURF")
    mod.levels = 1
    mod.render_levels = 1
    hem = []
    for i in range(49):
        u = i/48
        hem.append((
            (u-0.5)*width*0.96, -depth*0.497,
            height*0.40+0.0015*math.sin(13*u+phase),
        ))
    edge = curve(name+"FoldedHem", hem, 0.00065, mat)
    edge.parent = parent
    return parent


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


def drape(name, route, width, mat, amplitude=0.007):
    nu, nv = 36, 52
    verts, faces = [], []
    for j in range(nv+1):
        t = j/nv
        center = catmull(route, t)
        tangent = (
            catmull(route, min(1, t+0.003))
            - catmull(route, max(0, t-0.003))
        ).normalized()
        lateral = Vector((1, 0, 0))
        normal = lateral.cross(tangent).normalized()
        for i in range(nu+1):
            u = i/nu
            ripple = amplitude*(
                0.7*math.sin(u*math.tau*2.3+t*2.5)
                + 0.3*math.sin(u*math.tau*4.1-t*4)
            )
            q = center+lateral*((u-0.5)*width)
            q += normal*ripple
            q.z += 0.002*math.sin(9*u+12*t)
            verts.append(tuple(q))
    for j in range(nv):
        for i in range(nu):
            a = j*(nu+1)+i
            faces.append((a, a+1, a+nu+2, a+nu+1))
    obj = mesh_obj(name, verts, faces, mat)
    for p in obj.data.polygons:
        p.use_smooth = True
    sub = obj.modifiers.new("Env_ClothSmooth", "SUBSURF")
    sub.levels = 1
    sub.render_levels = 1
    solid = obj.modifiers.new("Env_ClothThickness", "SOLIDIFY")
    solid.thickness = 0.0016
    return obj


folded_towel("CounterIvoryFold", (-0.036, 0.063, TOP+0.025),
             0.254, 0.185, 0.027, cream, -0.035)
folded_towel("CounterLinenFold", (-0.018, 0.071, TOP+0.051),
             0.233, 0.176, 0.027, linen, 0.075)
drape("CounterLooseLinen", [
    (-0.072, 0.135, TOP+0.084),
    (-0.072, 0.025, TOP+0.083),
    (-0.064, -0.029, TOP+0.059),
    (-0.052, -0.064, TOP+0.027),
], 0.165, linen, 0.007)

folded_towel("RightFoldedGreyTowel", (0.883, 0.08, TOP),
             0.22, 0.25, 0.023, grey_cloth, -0.13)
drape("RightGreyTowelDrape", [
    (0.894, 0.127, TOP+0.027),
    (0.895, -0.115, TOP+0.024),
    (0.912, -0.325, TOP+0.019),
    (0.925, -0.366, TOP-0.013),
    (0.943, -0.382, TOP-0.090),
], 0.225, grey_cloth, 0.005)

# ---------- Finely woven ROUND floor baskets ----------

def round_basket(name, center, radius_x, radius_y, height):
    cx, cy, base = center
    stakes = 112
    segments = 448

    def radii(t):
        # Taper at the base, a slight belly, and a restrained rolled mouth.
        factor = 0.86+0.14*t+0.045*math.sin(math.pi*t)
        return radius_x*factor, radius_y*factor

    # Dark woven inner backing: open at the top, no solid lid.
    verts, faces = [], []
    for j in range(17):
        t = j/16
        rx, ry = radii(t)
        for i in range(stakes):
            a = math.tau*i/stakes
            verts.append((
                cx+(rx-0.0035)*math.cos(a),
                cy+(ry-0.0035)*math.sin(a),
                base+0.012+t*(height-0.016),
            ))
    for j in range(16):
        for i in range(stakes):
            k = (i+1) % stakes
            faces.append((
                j*stakes+i, j*stakes+k,
                (j+1)*stakes+k, (j+1)*stakes+i
            ))
    faces.append(tuple(reversed(range(stakes))))
    shell = mesh_obj(name+"InnerWeave", verts, faces, wicker_inner)
    for p in shell.data.polygons:
        p.use_smooth = True

    # Vertical willow stakes.
    for i in range(stakes):
        a = math.tau*i/stakes
        points = []
        for j in range(41):
            t = j/40
            rx, ry = radii(t)
            points.append((
                cx+rx*math.cos(a), cy+ry*math.sin(a),
                base+0.009+t*(height-0.014),
            ))
        curve(name+"Stake_%03d" % i, points, 0.0017,
              wicker_mats[i % 6], resolution=1)

    # Closely spaced over-and-under horizontal weavers.
    rows = max(50, int(height/0.0034))
    for row in range(rows):
        t = (row+0.5)/rows
        rx, ry = radii(t)
        points = []
        for i in range(segments):
            a = math.tau*i/segments
            weave = 0.0022*math.cos(a*stakes/2+math.pi*(row % 2))
            points.append((
                cx+(rx+weave)*math.cos(a),
                cy+(ry+weave)*math.sin(a),
                base+0.010+t*(height-0.020),
            ))
        curve(name+"Weaver_%03d" % row, points, 0.00145,
              wicker_mats[(row*3+row//4) % 6], True, 1)

    for label, t, z, r in (
        ("FootRim", 0, base+0.011, 0.0045),
        ("MouthRim", 1, base+height-0.004, 0.006),
    ):
        rx, ry = radii(t)
        points = [
            (cx+rx*math.cos(math.tau*i/256),
             cy+ry*math.sin(math.tau*i/256), z)
            for i in range(256)
        ]
        curve(name+label, points, r, wicker_mats[3], True)

    # Two restrained wrapped loop handles, not oversized rope handles.
    for side in (-1, 1):
        y = cy+side*radius_y*0.76
        points = []
        for i in range(65):
            a = math.pi*i/64
            points.append((
                cx+radius_x*0.30*math.cos(a), y,
                base+height-0.012+0.071*math.sin(a),
            ))
        curve(name+"Handle"+str(side), points, 0.0052, wicker_mats[2])
        # Fine binding around the handle.
        bound = []
        for i in range(481):
            a = math.pi*i/480
            b = math.tau*28*i/480
            px = cx+radius_x*0.30*math.cos(a)
            pz = base+height-0.012+0.071*math.sin(a)
            bound.append((
                px+0.0055*math.cos(b)*math.cos(a),
                y+0.0055*math.sin(b),
                pz+0.0055*math.cos(b)*math.sin(a),
            ))
        curve(name+"HandleBinding"+str(side),
              bound, 0.00085, wicker_mats[4], resolution=1)


# Everything raised remains outside the washer's x corridor.
round_basket("LeftRoundBasket", (-1.132, -0.623, 0.006),
             0.167, 0.156, 0.425)
round_basket("RightRoundBasket", (0.723, -0.615, 0.006),
             0.222, 0.205, 0.375)

folded_towel("LeftBasketIvory", (-1.13, -0.625, 0.374),
             0.255, 0.220, 0.032, cream, -0.1)
folded_towel("LeftBasketGrey", (-1.145, -0.611, 0.402),
             0.206, 0.164, 0.027, grey_cloth, 0.18)
drape("LeftBasketLongTowel", [
    (-1.028, -0.596, 0.440),
    (-1.015, -0.750, 0.427),
    (-1.002, -0.797, 0.330),
    (-0.976, -0.812, 0.139),
    (-0.952, -0.845, 0.025),
    (-0.909, -0.971, 0.010),
], 0.174, cream, 0.009)

folded_towel("RightBasketLinen", (0.727, -0.609, 0.320),
             0.320, 0.259, 0.035, linen, -0.13)
folded_towel("RightBasketIvory", (0.718, -0.616, 0.350),
             0.292, 0.235, 0.031, cream, 0.12)
drape("RightBasketSoftTowel", [
    (0.797, -0.570, 0.385),
    (0.805, -0.663, 0.390),
    (0.833, -0.756, 0.373),
], 0.145, cream, 0.008)

# Flat rug only: the central camera/door corridor has no raised dressing.
# Back edge -0.92 is over 0.60 m ahead of the washer's front.
box("GreenRug", (-0.82, -1.295, 0.003),
    (1.28, 0.75, 0.006), rug_mat, 0.002)
for y in (-0.921, -1.668):
    curve("RugHem"+str(y),
          [(-1.45, y, 0.0065), (-0.19, y, 0.0065)],
          0.0016, rug_mat)
for i in range(80):
    x = -1.443+i*1.25/79
    curve("RugFringe_%03d" % i, [
        (x, -1.668, 0.004),
        (x+random.uniform(-0.003, 0.003),
         -1.69-random.random()*0.008, 0.002),
    ], 0.00065, rug_mat, resolution=1)

# ---------- Tall bright right-hand window ----------

WX = 1.16
YA, YB = -2.55, 0.275
box("WindowRearPier", (WX, 0.367, 1.4),
    (0.13, 0.15, 2.8), plaster, 0.002)
box("WindowFrontPier", (WX, -2.655, 1.4),
    (0.13, 0.17, 2.8), plaster, 0.002)
box("WindowHeader", (WX, -1.1375, 2.735),
    (0.15, 3.005, 0.13), plaster, 0.002)
box("WindowThreshold", (WX, -1.1375, 0.033),
    (0.19, 2.87, 0.066), stone, 0.002)
for label, y in (("Rear", YB), ("Front", YA)):
    box("WindowJamb"+label, (WX, y, 1.35),
        (0.072, 0.056, 2.56), window_wood, 0.002)
for label, z in (("Bottom", 0.084), ("Top", 2.626)):
    box("WindowRail"+label, (WX, -1.1375, z),
        (0.072, 2.88, 0.054), window_wood, 0.002)
box("WindowMullion", (WX, -1.64, 1.35),
    (0.065, 0.035, 2.52), window_wood, 0.002)

# Thin glazing, transparent to shadow rays for dependable window sunlight.
glass = plain("ClearWindowGlass", (0.94, 0.97, 0.98), 0.055)
gbs = principled(glass)
gbs.inputs["Transmission Weight"].default_value = 1
gbs.inputs["IOR"].default_value = 1.45
nt = glass.node_tree
out = next(n for n in nt.nodes if n.type == "OUTPUT_MATERIAL")
lp = nt.nodes.new("ShaderNodeLightPath")
tr = nt.nodes.new("ShaderNodeBsdfTransparent")
mx = nt.nodes.new("ShaderNodeMixShader")
nt.links.new(lp.outputs["Is Shadow Ray"], mx.inputs[0])
nt.links.new(gbs.outputs[0], mx.inputs[1])
nt.links.new(tr.outputs[0], mx.inputs[2])
nt.links.new(mx.outputs[0], out.inputs["Surface"])
box("WindowGlass", (WX+0.025, -1.1375, 1.35),
    (0.004, 2.77, 2.49), glass)

curtain_mat = pbr(
    "WhiteSheerLinen", "denim_fabric", tile=0.065,
    tint=(0.87, 0.855, 0.81), tint_amount=0.99,
    saturation=0, rough=(0.88, 0.98), normal_strength=0.12,
)
nt = curtain_mat.node_tree
bs = principled(curtain_mat)
bs.inputs["Sheen Weight"].default_value = 0.25
out = next(n for n in nt.nodes if n.type == "OUTPUT_MATERIAL")
translucent = nt.nodes.new("ShaderNodeBsdfTranslucent")
translucent.inputs["Color"].default_value = (0.84, 0.82, 0.77, 1)
mix = nt.nodes.new("ShaderNodeMixShader")
mix.inputs[0].default_value = 0.30
nt.links.new(bs.outputs[0], mix.inputs[1])
nt.links.new(translucent.outputs[0], mix.inputs[2])
transparent = nt.nodes.new("ShaderNodeBsdfTransparent")
mix2 = nt.nodes.new("ShaderNodeMixShader")
mix2.inputs[0].default_value = 0.10
nt.links.new(mix.outputs[0], mix2.inputs[1])
nt.links.new(transparent.outputs[0], mix2.inputs[2])
nt.links.new(mix2.outputs[0], out.inputs["Surface"])

verts, faces = [], []
NU, NV = 88, 36
for j in range(NV+1):
    v = j/NV
    for i in range(NU+1):
        u = i/NU
        y = -0.365+0.640*u
        fold = math.sin(u*math.tau*5.4)
        x = 1.075+0.029*fold+0.007*math.sin(u*math.tau*10.8)
        x -= 0.018*(1-v)**4
        z = 0.017+2.615*v
        z += (1-v)**12*(0.009+0.007*math.cos(u*math.tau*5.4))
        verts.append((x, y, z))
for j in range(NV):
    for i in range(NU):
        a = j*(NU+1)+i
        faces.append((a, a+1, a+NU+2, a+NU+1))
curtain = mesh_obj("GatheredWhiteSheer", verts, faces, curtain_mat)
for p in curtain.data.polygons:
    p.use_smooth = True
sub = curtain.modifiers.new("Env_SheerSmooth", "SUBSURF")
sub.levels = 1
sub.render_levels = 1
curve("CurtainRail", [(1.08, -0.40, 2.655), (1.08, 0.29, 2.655)],
      0.008, ceramic)

# Soft, distant garden colour through the side glazing.
# Camera rays see it, but it cannot obstruct the lighting.
garden = plain("DistantGarden", (0.34, 0.40, 0.26), 1)
nt = garden.node_tree
n, l = nt.nodes, nt.links
tc = n.new("ShaderNodeTexCoord")
noise = n.new("ShaderNodeTexNoise")
noise.inputs["Scale"].default_value = 8
noise.inputs["Detail"].default_value = 2
l.new(tc.outputs["Generated"], noise.inputs["Vector"])
ramp = n.new("ShaderNodeValToRGB")
ramp.color_ramp.elements[0].position = 0.20
ramp.color_ramp.elements[0].color = (0.11, 0.17, 0.075, 1)
ramp.color_ramp.elements[1].position = 0.80
ramp.color_ramp.elements[1].color = (0.68, 0.73, 0.57, 1)
l.new(noise.outputs["Fac"], ramp.inputs["Fac"])
em = n.new("ShaderNodeEmission")
em.inputs["Strength"].default_value = 0.9
l.new(ramp.outputs["Color"], em.inputs["Color"])
tr = n.new("ShaderNodeBsdfTransparent")
lp = n.new("ShaderNodeLightPath")
mix = n.new("ShaderNodeMixShader")
l.new(lp.outputs["Is Camera Ray"], mix.inputs[0])
l.new(tr.outputs[0], mix.inputs[1])
l.new(em.outputs[0], mix.inputs[2])
out = next(node for node in n if node.type == "OUTPUT_MATERIAL")
l.new(mix.outputs[0], out.inputs["Surface"])
box("DistantExterior", (3.5, -0.9, 1.7), (0.015, 8, 5), garden)

# ---------- Lighting ----------

world = bpy.data.worlds.new("Env_LoftWorld")
world.use_nodes = True
scene.world = world
nt = world.node_tree
nt.nodes.clear()
out = nt.nodes.new("ShaderNodeOutputWorld")
background = nt.nodes.new("ShaderNodeBackground")
background.inputs["Strength"].default_value = 0.38
environment = nt.nodes.new("ShaderNodeTexEnvironment")
environment.image = bpy.data.images.load(
    asset_path("assets/hdri/photo_studio_loft_hall.hdr"),
    check_existing=False,
)
coord = nt.nodes.new("ShaderNodeTexCoord")
mapping = nt.nodes.new("ShaderNodeMapping")

# Locate the HDRI's brightest upper patch and bring it around to front-left.
import numpy as np
image = environment.image
w, h = image.size
pixels = np.empty(len(image.pixels), dtype=np.float32)
image.pixels.foreach_get(pixels)
pixels = pixels.reshape(h, w, 4)
sx, sy = max(1, w//160), max(1, h//80)
sample = pixels[h//2:int(h*0.94):sy, ::sx, :3]
lum = sample @ np.array((0.2126, 0.7152, 0.0722), dtype=np.float32)
_, col = np.unravel_index(np.argmax(lum), lum.shape)
u = (col*sx+0.5)/w
# Blender environment longitude: atan2(y, x) = 2*pi*(0.5-u).
bright_azimuth = math.tau*(0.5-u)
desired_azimuth = math.atan2(-1.7, -2.5)
mapping.inputs["Rotation"].default_value[2] = (
    bright_azimuth-desired_azimuth
)
del pixels, sample, lum

nt.links.new(coord.outputs["Generated"], mapping.inputs["Vector"])
nt.links.new(mapping.outputs["Vector"], environment.inputs["Vector"])
nt.links.new(environment.outputs["Color"], background.inputs["Color"])
nt.links.new(background.outputs[0], out.inputs["Surface"])


def aim(obj, target):
    obj.rotation_euler = (
        Vector(target)-obj.location
    ).to_track_quat("-Z", "Y").to_euler()


def light(name, kind, location, target, energy, color, size=1):
    data = bpy.data.lights.new("Env_"+name, kind)
    data.energy = energy
    data.color = color
    if kind == "AREA":
        data.shape = "DISK"
        data.size = size
    elif kind == "SUN":
        data.angle = math.radians(0.8)
    obj = bpy.data.objects.new("Env_"+name, data)
    env.objects.link(obj)
    obj.location = location
    aim(obj, target)
    return obj


# Dominant low afternoon sun, entering through the clear part of the window.
light("LowWarmWindowSun", "SUN",
      (4.8, -4.8, 3.13), (0, 0, 0.38),
      2.6, (1.0, 0.88, 0.71))

# Broad window illumination lifts the curtain and the shaded cabinet fronts.
light("WindowSkySoftbox", "AREA",
      (1.48, -1.05, 1.95), (-0.50, 0.06, 0.70),
      165, (1.0, 0.95, 0.86), 1.7)

# Crucially INSIDE the left wall, unlike the earlier blocked fill.
light("LeftSoftBounce", "AREA",
      (-1.15, -2.15, 2.20), (-0.15, 0.05, 0.55),
      115, (0.89, 0.94, 1.0), 2.2)

light("FrontGentleBounce", "AREA",
      (0.15, -3.15, 1.8), (0, 0, 0.55),
      38, (1.0, 0.97, 0.91), 2.6)

# ---------- Reference cameras ----------

def camera(name, position, target, lens):
    data = bpy.data.cameras.new("Env_"+name)
    obj = bpy.data.objects.new("Env_"+name, data)
    env.objects.link(obj)
    obj.location = position
    aim(obj, target)
    data.lens = lens
    data.sensor_width = 36
    data.sensor_fit = "HORIZONTAL"
    data.clip_start = 0.04
    data.clip_end = 100
    data.dof.use_dof = False
    return obj


# Lower viewpoints, much less visible countertop, floor retained in frame.
cam1 = camera(
    "RefCamera",
    (-0.52, -4.05, 0.955),
    (-0.34, 0.0, 0.603),
    59,
)
camera(
    "RefCamera2",
    (0.84, -3.85, 0.925),
    (0.095, 0.0, 0.592),
    57,
)
scene.camera = cam1

scene.render.engine = "CYCLES"
scene.cycles.samples = 128
scene.cycles.use_denoising = True
scene.cycles.max_bounces = 10
scene.cycles.diffuse_bounces = 4
scene.cycles.glossy_bounces = 4
scene.cycles.transmission_bounces = 8
scene.cycles.transparent_max_bounces = 16
scene.view_settings.view_transform = "AgX"
scene.view_settings.exposure = 0.0

# Do not alter resolution, render filepath, or any original datablock.
# Prefix everything newly created, including imported asset datablocks.
for kind in TRACK:
    for block in getattr(bpy.data, kind):
        if block not in original[kind] and not block.name.startswith("Env_"):
            block.name = "Env_"+block.name

bpy.context.view_layer.update()
bpy.ops.wm.save_as_mainfile(filepath=sys.argv[sys.argv.index("--") + 1])
