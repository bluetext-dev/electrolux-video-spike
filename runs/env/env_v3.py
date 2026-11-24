import bpy
import math
import os
import sys
import random
from mathutils import Vector, Matrix

random.seed(21)
BASE = os.environ["VP_HERE"]
scene = bpy.context.scene

# Record the source datablocks. Never edit the washer or its materials.
TRACK = (
    "objects", "meshes", "curves", "materials", "images", "collections",
    "cameras", "lights", "worlds", "node_groups", "armatures", "actions",
)
original = {k: set(getattr(bpy.data, k)) for k in TRACK}

# Existing presentation lights can overwhelm the new window lighting.
# Only LIGHT objects are disabled; washer objects are not changed.
for obj in list(scene.objects):
    if obj.type == "LIGHT":
        obj.hide_render = True

env = bpy.data.collections.new("Env_Set")
scene.collection.children.link(env)


def path(relative):
    p = os.path.join(BASE, relative)
    if not os.path.isfile(p):
        raise FileNotFoundError(p)
    return p


def link_env(obj):
    for c in list(obj.users_collection):
        c.objects.unlink(obj)
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


def plain(name, color, roughness=0.5, metallic=0):
    mat = bpy.data.materials.new("Env_" + name)
    mat.use_nodes = True
    bs = principled(mat)
    bs.inputs["Base Color"].default_value = (*color, 1)
    bs.inputs["Roughness"].default_value = roughness
    bs.inputs["Metallic"].default_value = metallic
    return mat


def pbr(name, asset, tile=1, tint=None, tint_amount=0,
        tint_mode="MIX", saturation=1, rough=(0.45, 0.7),
        normal_strength=0.2, bump_distance=0.0004,
        rotation=(0, 0, 0), ao_amount=0.06):
    mat = plain(name, (0.5, 0.5, 0.5))
    nt = mat.node_tree
    n, l = nt.nodes, nt.links
    bs = principled(mat)

    tc = n.new("ShaderNodeTexCoord")
    tc.object = texture_space
    mapping = n.new("ShaderNodeMapping")
    mapping.vector_type = "POINT"
    if isinstance(tile, (int, float)):
        tile = (tile, tile, tile)
    mapping.inputs["Scale"].default_value = tuple(1 / t for t in tile)
    mapping.inputs["Rotation"].default_value = rotation
    l.new(tc.outputs["Object"], mapping.inputs["Vector"])

    maps = {}
    for kind in ("diffuse", "roughness", "normal", "displacement", "ao"):
        tex = n.new("ShaderNodeTexImage")
        tex.name = "Env_" + name + "_" + kind
        tex.image = bpy.data.images.load(
            path(f"assets/textures/{asset}/{kind}.jpg"),
            check_existing=False,
        )
        tex.image.colorspace_settings.name = (
            "sRGB" if kind == "diffuse" else "Non-Color"
        )
        tex.projection = "BOX"
        tex.projection_blend = 0.15
        l.new(mapping.outputs["Vector"], tex.inputs["Vector"])
        maps[kind] = tex

    hue = n.new("ShaderNodeHueSaturation")
    hue.inputs["Saturation"].default_value = saturation
    l.new(maps["diffuse"].outputs["Color"], hue.inputs["Color"])
    color = hue.outputs["Color"]

    if tint is not None:
        mix = n.new("ShaderNodeMixRGB")
        mix.blend_type = tint_mode
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
    bump.inputs["Strength"].default_value = 0.10
    bump.inputs["Distance"].default_value = bump_distance
    l.new(maps["displacement"].outputs["Color"], bump.inputs["Height"])
    l.new(normal.outputs["Normal"], bump.inputs["Normal"])
    l.new(bump.outputs["Normal"], bs.inputs["Normal"])
    return mat


oak = pbr(
    "HoneyOak", "oak_veneer_01",
    tile=(0.78, 0.90, 1.55),
    rotation=(0, math.pi / 2, 0),
    tint=(0.47, 0.285, 0.12), tint_amount=0.25,
    saturation=0.90, rough=(0.40, 0.57),
    normal_strength=0.12, ao_amount=0.035,
)
oak_edge = pbr(
    "OakEdging", "oak_veneer_01",
    tile=(0.90, 0.90, 1.75),
    rotation=(0, math.pi / 2, 0),
    tint=(0.39, 0.235, 0.095), tint_amount=0.32,
    saturation=0.90, rough=(0.43, 0.60),
    normal_strength=0.08,
)

# Use the real stone map, without the previous large Voronoi vein overlay.
stone = pbr(
    "GreyVeinedStone", "marble_01",
    tile=(1.55, 1.55, 1.55),
    rotation=(0, -0.20, 0),
    tint=(0.34, 0.345, 0.33), tint_amount=0.82,
    tint_mode="MULTIPLY", saturation=0.12,
    rough=(0.31, 0.47), normal_strength=0.07,
    bump_distance=0.00015, ao_amount=0.025,
)
floor_mat = pbr(
    "CharcoalConcrete", "concrete_floor_02", tile=1.8,
    tint=(0.045, 0.052, 0.049), tint_amount=0.72,
    saturation=0.16, rough=(0.68, 0.85),
    normal_strength=0.24, bump_distance=0.0007,
)
plaster = pbr(
    "WarmWhitePlaster", "white_plaster_02", tile=1.5,
    tint=(0.72, 0.705, 0.66), tint_amount=0.75,
    saturation=0.15, rough=(0.82, 0.94),
    normal_strength=0.10,
)
rug_mat = pbr(
    "OliveGreenRug", "denim_fabric", tile=0.105,
    tint=(0.085, 0.125, 0.071), tint_amount=0.97,
    saturation=0, rough=(0.91, 0.99), normal_strength=0.45,
)
cream = pbr(
    "IvoryTerry", "denim_fabric", tile=0.065,
    tint=(0.64, 0.615, 0.54), tint_amount=0.97,
    saturation=0, rough=(0.88, 0.98), normal_strength=0.38,
)
linen = pbr(
    "TaupeLinen", "denim_fabric", tile=0.075,
    tint=(0.285, 0.24, 0.185), tint_amount=0.97,
    saturation=0, rough=(0.87, 0.98), normal_strength=0.32,
)
grey_cloth = pbr(
    "GreyTowel", "denim_fabric", tile=0.070,
    tint=(0.19, 0.205, 0.19), tint_amount=0.97,
    saturation=0, rough=(0.88, 0.98), normal_strength=0.34,
)
for mat in (cream, linen, grey_cloth, rug_mat):
    principled(mat).inputs["Sheen Weight"].default_value = 0.18

dark = plain("CabinetReveal", (0.055, 0.036, 0.019), 0.85)
steel = plain("Chrome", (0.56, 0.59, 0.58), 0.17, 0.97)
sink_mat = plain("SinkSteel", (0.32, 0.35, 0.34), 0.28, 0.92)
ceramic = plain("CreamCeramic", (0.66, 0.655, 0.59), 0.30)
amber = plain("AmberSoap", (0.145, 0.077, 0.017), 0.24)
black = plain("DarkPump", (0.012, 0.016, 0.013), 0.34)
window_wood = plain("WindowOak", (0.205, 0.080, 0.021), 0.38)
wicker_inner = plain("BasketInterior", (0.12, 0.073, 0.029), 0.89)
wicker_mats = [
    plain(
        "Willow_%02d" % i,
        (0.235 + i * 0.013, 0.151 + i * 0.010, 0.069 + i * 0.006),
        0.77,
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
        mod = obj.modifiers.new("Env_EdgeRound", "BEVEL")
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

    # Supply metric planar UVs for tangent-space normal-map evaluation.
    uv = data.uv_layers.new(name="Env_MetricUV")
    for poly in data.polygons:
        axis = max(range(3), key=lambda k: abs(poly.normal[k]))
        axes = ((1, 2), (0, 2), (0, 1))[axis]
        for li in poly.loop_indices:
            co = data.vertices[data.loops[li].vertex_index].co
            uv.data[li].uv = (co[axes[0]], co[axes[1]])
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
    bevel = obj.modifiers.new("Env_RoundedLip", "BEVEL")
    bevel.width = min(0.002, depth / 5)
    bevel.segments = 3
    obj.modifiers.new("Env_WeightedNormals", "WEIGHTED_NORMAL")
    for p in obj.data.polygons:
        p.use_smooth = True
    return obj


def import_asset(asset, name, dims, location, angle=0):
    before = set(bpy.data.objects)
    bpy.ops.import_scene.gltf(
        filepath=path(f"assets/models/{asset}/{asset}_2k.gltf")
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


def tint_imported(parts, color, amount, saturation=0.15):
    # Edit copies, never a material possibly shared with the source scene.
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
                mat.name = "Env_Tinted_" + old.name
                copies[old] = mat
                bs = principled(mat)
                nt = mat.node_tree
                hue = nt.nodes.new("ShaderNodeHueSaturation")
                hue.inputs["Saturation"].default_value = saturation
                if bs.inputs["Base Color"].is_linked:
                    source = bs.inputs["Base Color"].links[0].from_socket
                    nt.links.new(source, hue.inputs["Color"])
                else:
                    hue.inputs["Color"].default_value = tuple(
                        bs.inputs["Base Color"].default_value
                    )
                mix = nt.nodes.new("ShaderNodeMixRGB")
                mix.inputs[0].default_value = amount
                mix.inputs[2].default_value = (*color, 1)
                nt.links.new(hue.outputs["Color"], mix.inputs[1])
                nt.links.new(mix.outputs[0], bs.inputs["Base Color"])
            slot.material = copies[old]


# -------------------------------------------------------------------
# Room and cabinets: washer envelope remains completely untouched.
# -------------------------------------------------------------------

FRONT = -0.318
TOP = 0.881
BOTTOM = 0.857
X0, X1 = -1.345, 1.010
Y0, Y1 = -0.347, 0.377

box("Floor", (0, -1.7, -0.06), (8, 8, 0.12), floor_mat, 0.002)
box("StoneBackWall", (-0.16, 0.425, 1.4),
    (2.39, 0.09, 2.8), stone, 0.001)
box("LeftPlasterWall", (-1.405, -0.90, 1.4),
    (0.12, 2.74, 2.8), plaster, 0.002)
box("RightRearReturn", (1.075, 0.425, 1.4),
    (0.10, 0.09, 2.8), plaster, 0.002)


def cabinet(name, xa, xb):
    width = xb - xa
    x = (xa + xb) / 2

    # Real hollow cabinet: the sink bowl must not intersect a solid carcass.
    for side, xx in (("L", xa + 0.009), ("R", xb - 0.009)):
        box(name + "CarcassSide" + side, (xx, 0.022, 0.45),
            (0.018, 0.625, 0.804), oak, 0.0008)
    box(name + "CarcassBack", (x, 0.324, 0.45),
        (width - 0.036, 0.015, 0.804), oak)
    box(name + "Base", (x, 0.014, 0.062),
        (width - 0.036, 0.60, 0.018), oak)
    box(name + "ToeShadow", (x, -0.250, 0.021),
        (width - 0.006, 0.065, 0.042), dark)
    box(name + "Plinth", (x, -0.279, 0.029),
        (width - 0.006, 0.014, 0.050), oak_edge, 0.001)
    box(name + "RevealBacking", (x, -0.290, 0.450),
        (width - 0.006, 0.010, 0.803), dark)

    for label, za, zb in (
        ("Lower", 0.046, 0.443),
        ("Upper", 0.448, 0.851),
    ):
        w = width - 0.006
        h = zb - za
        z = (za + zb) / 2
        # Flat, handleless fronts with restrained, nearly flush oak lipping.
        box(name + label + "Panel", (x, FRONT + 0.012, z),
            (w - 0.014, 0.022, h - 0.014), oak, 0.001)
        edge = 0.0075
        for side in (-1, 1):
            box(name + label + "VerticalLip" + str(side),
                (x + side * (w - edge) / 2, FRONT + 0.0115, z),
                (edge, 0.023, h), oak_edge, 0.0007)
            box(name + label + "HorizontalLip" + str(side),
                (x, FRONT + 0.0115, z + side * (h - edge) / 2),
                (w - 2 * edge, 0.023, edge), oak_edge, 0.0007)


cabinet("LeftA", -1.325, -0.820)
cabinet("LeftB", -0.820, -0.310)
cabinet("RightA", 0.310, 0.990)
box("RightCabinetEnd", (0.998, 0.018, 0.436),
    (0.016, 0.65, 0.842), oak, 0.001)

HX0, HX1 = -0.918, -0.493
HY0, HY1 = -0.242, 0.137


def slab(name, xa, xb, ya, yb):
    box(name, ((xa + xb) / 2, (ya + yb) / 2, (TOP + BOTTOM) / 2),
        (xb - xa, yb - ya, TOP - BOTTOM), stone, 0.001)


slab("CounterLeft", X0, HX0, Y0, Y1)
slab("CounterRight", HX1, X1, Y0, Y1)
slab("CounterSinkFront", HX0, HX1, Y0, HY0)
slab("CounterSinkBack", HX0, HX1, HY1, Y1)
box("CounterBackJoint", (-0.167, 0.375, TOP),
    (2.35, 0.003, 0.003), stone, 0.0005)


def rounded_ring(cx, cy, w, d, r, z, steps=12):
    result = []
    for ox, oy, start in (
        (w / 2 - r, d / 2 - r, 0),
        (-w / 2 + r, d / 2 - r, 90),
        (-w / 2 + r, -d / 2 + r, 180),
        (w / 2 - r, -d / 2 + r, 270),
    ):
        for i in range(steps):
            a = math.radians(start + i * 90 / steps)
            result.append((
                cx + ox + r * math.cos(a),
                cy + oy + r * math.sin(a), z,
            ))
    return result


cx, cy = (HX0 + HX1) / 2, (HY0 + HY1) / 2
specs = (
    (0.439, 0.393, 0.045, TOP + 0.0015),
    (0.417, 0.372, 0.043, TOP + 0.0017),
    (0.399, 0.354, 0.047, TOP - 0.016),
    (0.300, 0.255, 0.060, TOP - 0.150),
)
verts, faces = [], []
for w, d, r, z in specs:
    verts += rounded_ring(cx, cy, w, d, r, z)
N = 48
for j in range(len(specs) - 1):
    for i in range(N):
        k = (i + 1) % N
        faces.append((j*N+i, j*N+k, (j+1)*N+k, (j+1)*N+i))
faces.append(tuple(range(3*N, 4*N)))
sink = mesh_obj("InsetSink", verts, faces, sink_mat)
for p in sink.data.polygons:
    p.use_smooth = True
solid = sink.modifiers.new("Env_SinkThickness", "SOLIDIFY")
solid.thickness = 0.001
cylinder("SinkDrain", (cx, cy, TOP - 0.148), 0.023, 0.002, steel)
for i in range(6):
    a = math.tau * i / 6
    cylinder(
        "DrainSlot_%d" % i,
        (cx + 0.014 * math.cos(a), cy + 0.014 * math.sin(a), TOP - 0.1465),
        0.0017, 0.0005, black, 12,
    )

tx, ty = -0.745, 0.223
cylinder("TapBase", (tx, ty, TOP + 0.004), 0.022, 0.008, steel)
points = [(tx, ty, TOP + 0.006), (tx, ty, 1.120)]
for i in range(49):
    a = math.pi * i / 48
    points.append((
        tx, ty - 0.061 + 0.061 * math.cos(a),
        1.120 + 0.061 * math.sin(a),
    ))
points.append((tx, ty - 0.122, 1.080))
curve("GooseneckTap", points, 0.009, steel)
cylinder("TapNozzle", (tx, ty - 0.122, 1.083), 0.010, 0.012, steel)
curve("TapLever", [
    (tx + 0.009, ty, 0.956),
    (tx + 0.046, ty, 0.956),
    (tx + 0.051, ty, 0.998),
], 0.0036, steel)


def soap(name, x, y, z, mat, height=0.073):
    cylinder(name + "Body", (x, y, z + height/2), 0.020, height, mat)
    cylinder(name + "Collar", (x, y, z + height + 0.005),
             0.010, 0.010, steel)
    cylinder(name + "Stem", (x, y, z + height + 0.016),
             0.003, 0.015, black)
    curve(name + "Pump", [
        (x, y, z + height + 0.025),
        (x, y - 0.025, z + height + 0.025),
        (x, y - 0.029, z + height + 0.021),
    ], 0.003, black)


soap("SinkAmberSoap", -0.577, 0.211, TOP, amber)
soap("SinkCreamSoap", -0.514, 0.232, TOP, ceramic, 0.066)

# -------------------------------------------------------------------
# Imported plant and cleaning bottles.
# -------------------------------------------------------------------

plant_root, plant_parts = import_asset(
    "potted_plant_02", "Plant",
    (0.265, 0.240, 0.365), (-1.133, 0.143, TOP), -0.32,
)
# Preserve imported leaves; assign ceramic only to low exterior pot faces.
for obj in plant_parts:
    if obj.type != "MESH":
        continue
    obj.data.materials.append(ceramic)
    idx = len(obj.data.materials) - 1
    nm = obj.matrix_world.to_3x3().inverted().transposed()
    for poly in obj.data.polygons:
        co = obj.matrix_world @ poly.center
        no = (nm @ poly.normal).normalized()
        if TOP - 0.004 <= co.z < TOP + 0.098 and no.z < 0.70:
            poly.material_index = idx

box("BottleTray", (0.222, 0.252, TOP + 0.004),
    (0.228, 0.112, 0.008), ceramic, 0.006)
spray_root, spray_parts = import_asset(
    "multi_cleaner_bottle", "SprayBottle",
    (0.054, 0.055, 0.150), (0.154, 0.260, TOP + 0.008), 0.15,
)
bleach_root, bleach_parts = import_asset(
    "bleach_bottle", "SmallCleaningBottle",
    (0.040, 0.030, 0.112), (0.240, 0.277, TOP + 0.008), -0.28,
)
tint_imported(spray_parts, (0.19, 0.225, 0.19), 0.40)
tint_imported(bleach_parts, (0.53, 0.515, 0.45), 0.63)

for obj in spray_parts:
    if obj.type != "MESH":
        continue
    obj.data.materials.append(black)
    idx = len(obj.data.materials) - 1
    for poly in obj.data.polygons:
        if (obj.matrix_world @ poly.center).z > TOP + 0.130:
            poly.material_index = idx

soap("SmallTraySoap", 0.302, 0.239, TOP + 0.008, ceramic, 0.063)

# -------------------------------------------------------------------
# Cloth: rounded folded volumes and continuous draped surfaces.
# -------------------------------------------------------------------

def folded_towel(name, position, width, depth, height, mat, angle=0):
    parent = empty(name)
    parent.location = position
    parent.rotation_euler.z = angle
    nu, nv = 30, 22
    verts, faces = [], []
    phase = random.uniform(0, math.tau)

    for layer in range(2):
        for j in range(nv + 1):
            v = j / nv
            for i in range(nu + 1):
                u = i / nu
                x = (u - 0.5) * width
                y = (v - 0.5) * depth
                x *= 1 - 0.04 * abs(2*v - 1)**8
                y *= 1 - 0.045 * abs(2*u - 1)**8
                crown = (
                    max(0, math.sin(math.pi*u) * math.sin(math.pi*v))
                )**0.45
                ripple = (
                    0.0017 * math.sin(19*u + 7*v + phase)
                    + 0.0011 * math.sin(31*v - 9*u)
                )
                z = (
                    height * (0.70 + 0.30*crown) + ripple
                    if layer == 0
                    else height * (0.13 - 0.10*crown) + ripple * 0.25
                )
                verts.append((x, y, z))

    count = (nu + 1) * (nv + 1)
    for j in range(nv):
        for i in range(nu):
            a = j*(nu+1) + i
            faces.append((a, a+1, a+nu+2, a+nu+1))
            b = a + count
            faces.append((b+nu+1, b+nu+2, b+1, b))

    boundary = (
        list(range(nu + 1))
        + [j*(nu+1)+nu for j in range(1, nv+1)]
        + [nv*(nu+1)+i for i in range(nu-1, -1, -1)]
        + [j*(nu+1) for j in range(nv-1, 0, -1)]
    )
    for i, a in enumerate(boundary):
        b = boundary[(i+1) % len(boundary)]
        faces.append((a, a+count, b+count, b))

    obj = mesh_obj(name + "Cloth", verts, faces, mat)
    obj.parent = parent
    for p in obj.data.polygons:
        p.use_smooth = True
    sub = obj.modifiers.new("Env_SoftFold", "SUBSURF")
    sub.levels = sub.render_levels = 1

    hem = [
        ((i/48 - 0.5) * width * 0.96,
         -depth * 0.496,
         height * 0.40 + 0.0015 * math.sin(13*i/48 + phase))
        for i in range(49)
    ]
    obj = curve(name + "FoldHem", hem, 0.0007, mat)
    obj.parent = parent
    return parent


def catmull(points, t):
    p = [Vector(a) for a in points]
    s = t * (len(p) - 1)
    j = min(int(s), len(p) - 2)
    u = s - j
    a, b = p[max(0, j-1)], p[j]
    c, d = p[j+1], p[min(len(p)-1, j+2)]
    return 0.5 * (
        2*b + (-a+c)*u + (2*a-5*b+4*c-d)*u*u
        + (-a+3*b-3*c+d)*u*u*u
    )


def drape(name, route, width, mat, amplitude=0.008):
    nu, nv = 40, 60
    verts, faces = [], []
    for j in range(nv + 1):
        t = j / nv
        center = catmull(route, t)
        tangent = (
            catmull(route, min(1, t + 0.003))
            - catmull(route, max(0, t - 0.003))
        ).normalized()
        lateral = Vector((1, 0, 0))
        normal = lateral.cross(tangent).normalized()
        for i in range(nu + 1):
            u = i / nu
            ripple = amplitude * (
                0.70 * math.sin(u*math.tau*2.8 + t*2.5)
                + 0.30 * math.sin(u*math.tau*5.1 - t*4)
            )
            q = center + lateral * ((u - 0.5) * width)
            q += normal * ripple
            q.z += 0.002 * math.sin(9*u + 12*t)
            verts.append(tuple(q))

    for j in range(nv):
        for i in range(nu):
            a = j*(nu+1) + i
            faces.append((a, a+1, a+nu+2, a+nu+1))

    obj = mesh_obj(name, verts, faces, mat)
    for p in obj.data.polygons:
        p.use_smooth = True
    sub = obj.modifiers.new("Env_ClothSmooth", "SUBSURF")
    sub.levels = sub.render_levels = 1
    solid = obj.modifiers.new("Env_ClothThickness", "SOLIDIFY")
    solid.thickness = 0.0015

    for side, ix in (("L", 1), ("R", nu-1)):
        pts = [verts[j*(nu+1)+ix] for j in range(nv+1)]
        curve(name + "Hem" + side, pts, 0.0006, mat)
    return obj


# No wicker tray on the counter: substantial folded towels sit on stone.
folded_towel("CounterBottomFold", (-0.032, -0.015, TOP + 0.001),
             0.278, 0.192, 0.030, grey_cloth, -0.055)
folded_towel("CounterIvoryFold", (-0.027, -0.009, TOP + 0.028),
             0.252, 0.179, 0.033, cream, 0.015)
folded_towel("CounterTaupeFold", (-0.009, 0.005, TOP + 0.057),
             0.233, 0.167, 0.030, linen, 0.07)
drape("CounterLooseFold", [
    (-0.075, 0.099, TOP + 0.089),
    (-0.073, -0.019, TOP + 0.091),
    (-0.067, -0.096, TOP + 0.066),
    (-0.057, -0.144, TOP + 0.023),
], 0.153, linen, 0.009)

folded_towel("RightGreyFold", (0.892, 0.072, TOP + 0.001),
             0.214, 0.235, 0.022, grey_cloth, -0.12)
drape("RightGreyDrape", [
    (0.895, 0.124, TOP + 0.027),
    (0.895, -0.118, TOP + 0.022),
    (0.912, -0.326, TOP + 0.017),
    (0.925, -0.366, TOP - 0.014),
    (0.943, -0.379, TOP - 0.084),
], 0.213, grey_cloth, 0.006)

# -------------------------------------------------------------------
# Round wicker hampers. Assets remain at plausible unstretched sizes.
# -------------------------------------------------------------------

def round_basket(name, center, rx0, ry0, height):
    cx, cy, base = center
    stakes = 100
    segments = 400

    def radii(t):
        f = 0.85 + 0.15*t + 0.060*math.sin(math.pi*t)
        return rx0*f, ry0*f

    verts, faces = [], []
    for j in range(17):
        t = j / 16
        rx, ry = radii(t)
        for i in range(stakes):
            a = math.tau * i / stakes
            verts.append((
                cx + (rx - 0.004) * math.cos(a),
                cy + (ry - 0.004) * math.sin(a),
                base + 0.012 + t*(height - 0.017),
            ))
    for j in range(16):
        for i in range(stakes):
            k = (i + 1) % stakes
            faces.append((
                j*stakes+i, j*stakes+k,
                (j+1)*stakes+k, (j+1)*stakes+i,
            ))
    faces.append(tuple(reversed(range(stakes))))
    obj = mesh_obj(name + "InnerWeave", verts, faces, wicker_inner)
    for p in obj.data.polygons:
        p.use_smooth = True

    for i in range(stakes):
        a = math.tau * i / stakes
        pts = []
        for j in range(35):
            t = j / 34
            rx, ry = radii(t)
            pts.append((
                cx + rx*math.cos(a), cy + ry*math.sin(a),
                base + 0.009 + t*(height - 0.014),
            ))
        curve(name + "Stake_%03d" % i, pts, 0.00185,
              wicker_mats[i % 6], resolution=1)

    rows = int(height / 0.0037)
    for row in range(rows):
        t = (row + 0.5) / rows
        rx, ry = radii(t)
        pts = []
        for i in range(segments):
            a = math.tau * i / segments
            weave = 0.0023 * math.cos(
                a*stakes/2 + math.pi*(row % 2)
            )
            pts.append((
                cx + (rx+weave)*math.cos(a),
                cy + (ry+weave)*math.sin(a),
                base + 0.010 + t*(height - 0.020),
            ))
        curve(name + "Weaver_%03d" % row, pts, 0.0016,
              wicker_mats[(row*3 + row//4) % 6], True, 1)

    for label, t, z, radius in (
        ("FootRim", 0, base + 0.011, 0.0045),
        ("MouthRim", 1, base + height - 0.004, 0.006),
    ):
        rx, ry = radii(t)
        pts = [
            (cx + rx*math.cos(math.tau*i/240),
             cy + ry*math.sin(math.tau*i/240), z)
            for i in range(240)
        ]
        curve(name + label, pts, radius, wicker_mats[3], True)

    for side in (-1, 1):
        y = cy + side * ry0 * 0.76
        pts = [
            (cx + rx0*0.30*math.cos(math.pi*i/64),
             y,
             base + height - 0.012 + 0.064*math.sin(math.pi*i/64))
            for i in range(65)
        ]
        curve(name + "Handle" + str(side), pts, 0.005, wicker_mats[2])
        binding = []
        for i in range(401):
            a = math.pi * i / 400
            b = math.tau * 26 * i / 400
            binding.append((
                cx + rx0*0.30*math.cos(a)
                + 0.0053*math.cos(b)*math.cos(a),
                y + 0.0053*math.sin(b),
                base + height - 0.012 + 0.064*math.sin(a)
                + 0.0053*math.cos(b)*math.sin(a),
            ))
        curve(name + "HandleBinding" + str(side),
              binding, 0.00085, wicker_mats[4], resolution=1)


round_basket("LeftBasket", (-1.137, -0.611, 0.006),
             0.163, 0.153, 0.418)
round_basket("RightBasket", (0.729, -0.602, 0.006),
             0.219, 0.200, 0.373)

# The supplied shallow basket becomes an inset towel caddy inside the
# left hamper rather than an incorrect tray beneath the counter towels.
_, basket_parts = import_asset(
    "wicker_basket_01", "InsetWickerCaddy",
    (0.276, 0.231, 0.073), (-1.137, -0.608, 0.330), -0.09,
)
tint_imported(basket_parts, (0.24, 0.15, 0.07), 0.20, 0.8)

folded_towel("LeftBasketIvory", (-1.133, -0.609, 0.369),
             0.246, 0.214, 0.029, cream, -0.12)
folded_towel("LeftBasketGrey", (-1.157, -0.595, 0.395),
             0.199, 0.157, 0.025, grey_cloth, 0.20)
drape("LeftBasketHangingTowel", [
    (-1.035, -0.578, 0.434),
    (-1.023, -0.738, 0.424),
    (-1.007, -0.777, 0.337),
    (-0.987, -0.784, 0.159),
    (-0.966, -0.806, 0.038),
    (-0.937, -0.866, 0.019),
    (-0.892, -0.973, 0.017),
], 0.185, cream, 0.012)

folded_towel("RightBasketTaupe", (0.729, -0.600, 0.320),
             0.310, 0.250, 0.034, linen, -0.12)
folded_towel("RightBasketIvory", (0.716, -0.605, 0.347),
             0.282, 0.225, 0.030, cream, 0.10)
drape("RightBasketLooseTowel", [
    (0.798, -0.548, 0.382),
    (0.803, -0.640, 0.387),
    (0.820, -0.739, 0.373),
], 0.140, cream, 0.009)

# No raised prop enters the washer corridor.
# The rug is also kept to the left of the machine's door/filter corridor.
rug_xa, rug_xb = -1.58, -0.34
rug_ya, rug_yb = -1.77, -0.95
box("GreenRug",
    ((rug_xa+rug_xb)/2, (rug_ya+rug_yb)/2, 0.003),
    (rug_xb-rug_xa, rug_yb-rug_ya, 0.006), rug_mat, 0.002)
for j, y in enumerate((rug_ya+0.002, rug_yb-0.002)):
    curve("RugHem_%d" % j,
          [(rug_xa+0.007, y, 0.006), (rug_xb-0.007, y, 0.006)],
          0.0014, rug_mat)
for i in range(78):
    x = rug_xa + 0.012 + i*(rug_xb-rug_xa-0.024)/77
    curve("RugFringe_%03d" % i, [
        (x, rug_ya, 0.004),
        (x + random.uniform(-0.003, 0.003),
         rug_ya - 0.018 - random.random()*0.008, 0.002),
    ], 0.00065, rug_mat, resolution=1)

# -------------------------------------------------------------------
# Right window, gathered sheer, and distant garden.
# -------------------------------------------------------------------

WX = 1.16
YA, YB = -2.55, 0.275
box("WindowRearPier", (WX, 0.367, 1.40),
    (0.13, 0.15, 2.8), plaster, 0.002)
box("WindowFrontPier", (WX, -2.655, 1.40),
    (0.13, 0.17, 2.8), plaster, 0.002)
box("WindowHeader", (WX, -1.1375, 2.735),
    (0.15, 3.005, 0.13), plaster, 0.002)
box("WindowThreshold", (WX, -1.1375, 0.031),
    (0.19, 2.87, 0.062), stone, 0.002)

for label, y in (("Rear", YB), ("Front", YA)):
    box("WindowJamb" + label, (WX, y, 1.35),
        (0.072, 0.058, 2.56), window_wood, 0.002)
for label, z in (("Bottom", 0.081), ("Top", 2.626)):
    box("WindowRail" + label, (WX, -1.1375, z),
        (0.072, 2.88, 0.054), window_wood, 0.002)
box("WindowMullion", (WX, -1.70, 1.35),
    (0.065, 0.038, 2.52), window_wood, 0.002)

glass = plain("WindowGlass", (0.95, 0.98, 0.99), 0.04)
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
box("WindowGlazing", (WX+0.025, -1.1375, 1.35),
    (0.004, 2.77, 2.49), glass)

curtain_mat = pbr(
    "WhiteSheer", "denim_fabric", tile=0.055,
    tint=(0.72, 0.705, 0.65), tint_amount=0.99,
    saturation=0, rough=(0.88, 0.98), normal_strength=0.10,
)
nt = curtain_mat.node_tree
bs = principled(curtain_mat)
bs.inputs["Sheen Weight"].default_value = 0.26
out = next(n for n in nt.nodes if n.type == "OUTPUT_MATERIAL")
translucent = nt.nodes.new("ShaderNodeBsdfTranslucent")
translucent.inputs["Color"].default_value = (0.73, 0.715, 0.67, 1)
mix1 = nt.nodes.new("ShaderNodeMixShader")
mix1.inputs[0].default_value = 0.36
nt.links.new(bs.outputs[0], mix1.inputs[1])
nt.links.new(translucent.outputs[0], mix1.inputs[2])
transparent = nt.nodes.new("ShaderNodeBsdfTransparent")
mix2 = nt.nodes.new("ShaderNodeMixShader")
mix2.inputs[0].default_value = 0.16
nt.links.new(mix1.outputs[0], mix2.inputs[1])
nt.links.new(transparent.outputs[0], mix2.inputs[2])
nt.links.new(mix2.outputs[0], out.inputs["Surface"])

verts, faces = [], []
NU, NV = 90, 40
for j in range(NV + 1):
    v = j / NV
    for i in range(NU + 1):
        u = i / NU
        y = -0.340 + 0.615*u
        x = (
            1.066 + 0.030*math.sin(u*math.tau*5.3)
            + 0.006*math.sin(u*math.tau*10.6)
            - 0.017*(1-v)**4
        )
        z = 0.017 + 2.615*v
        z += (1-v)**12 * (0.010 + 0.007*math.cos(u*math.tau*5.3))
        verts.append((x, y, z))
for j in range(NV):
    for i in range(NU):
        a = j*(NU+1) + i
        faces.append((a, a+1, a+NU+2, a+NU+1))
curtain = mesh_obj("GatheredSheerCurtain", verts, faces, curtain_mat)
for p in curtain.data.polygons:
    p.use_smooth = True
sub = curtain.modifiers.new("Env_SheerSmooth", "SUBSURF")
sub.levels = sub.render_levels = 1
curve("CurtainRail", [(1.075, -0.39, 2.656), (1.075, 0.29, 2.656)],
      0.007, ceramic)
curve("CurtainBottomHem", verts[:NU+1], 0.0013, curtain_mat)

# Camera-visible exterior only: cannot block direct or indirect light.
garden = plain("DistantGarden", (0.20, 0.28, 0.13), 1)
nt = garden.node_tree
n, l = nt.nodes, nt.links
tc = n.new("ShaderNodeTexCoord")
noise = n.new("ShaderNodeTexNoise")
noise.inputs["Scale"].default_value = 11
noise.inputs["Detail"].default_value = 3
l.new(tc.outputs["Generated"], noise.inputs["Vector"])
ramp = n.new("ShaderNodeValToRGB")
ramp.color_ramp.elements[0].position = 0.22
ramp.color_ramp.elements[0].color = (0.045, 0.085, 0.020, 1)
ramp.color_ramp.elements[1].position = 0.80
ramp.color_ramp.elements[1].color = (0.46, 0.53, 0.30, 1)
l.new(noise.outputs["Fac"], ramp.inputs["Fac"])
emission = n.new("ShaderNodeEmission")
emission.inputs["Strength"].default_value = 0.70
l.new(ramp.outputs["Color"], emission.inputs["Color"])
transparent = n.new("ShaderNodeBsdfTransparent")
lp = n.new("ShaderNodeLightPath")
mix = n.new("ShaderNodeMixShader")
l.new(lp.outputs["Is Camera Ray"], mix.inputs[0])
l.new(transparent.outputs[0], mix.inputs[1])
l.new(emission.outputs[0], mix.inputs[2])
out = next(node for node in n if node.type == "OUTPUT_MATERIAL")
l.new(mix.outputs[0], out.inputs["Surface"])
box("ExteriorGarden", (3.5, -0.9, 1.7), (0.015, 8, 5), garden)

# -------------------------------------------------------------------
# Lighting: low right-hand sun, restrained left HDRI/bounce fill.
# -------------------------------------------------------------------

world = bpy.data.worlds.new("Env_World")
world.use_nodes = True
scene.world = world
nt = world.node_tree
nt.nodes.clear()
out = nt.nodes.new("ShaderNodeOutputWorld")
background = nt.nodes.new("ShaderNodeBackground")
background.inputs["Strength"].default_value = 0.105
environment = nt.nodes.new("ShaderNodeTexEnvironment")
environment.image = bpy.data.images.load(
    path("assets/hdri/photo_studio_loft_hall.hdr"),
    check_existing=False,
)
environment.image.colorspace_settings.name = "Non-Color"
coord = nt.nodes.new("ShaderNodeTexCoord")
mapping = nt.nodes.new("ShaderNodeMapping")

# Find a broad bright upper-hemisphere patch, not one isolated hot pixel.
import numpy as np

image = environment.image
w, h = image.size
pixels = np.empty(len(image.pixels), dtype=np.float32)
image.pixels.foreach_get(pixels)
pixels = pixels.reshape(h, w, 4)
sx, sy = max(1, w//180), max(1, h//90)
sample = pixels[h//2:int(h*0.93):sy, ::sx, :3]
lum = sample @ np.array((0.2126, 0.7152, 0.0722), dtype=np.float32)
lum = np.nan_to_num(lum, nan=0, posinf=0, neginf=0)
smooth = sum(np.roll(lum, k, axis=1) for k in range(-4, 5)) / 9
_, col = np.unravel_index(np.argmax(smooth), smooth.shape)
u = (col*sx + 0.5) / w
bright_azimuth = math.tau * (0.5 - u)
desired_azimuth = math.atan2(-1.7, -2.5)
mapping.inputs["Rotation"].default_value[2] = (
    bright_azimuth - desired_azimuth
)
del pixels, sample, lum, smooth

nt.links.new(coord.outputs["Generated"], mapping.inputs["Vector"])
nt.links.new(mapping.outputs["Vector"], environment.inputs["Vector"])
nt.links.new(environment.outputs["Color"], background.inputs["Color"])
nt.links.new(background.outputs[0], out.inputs["Surface"])


def aim(obj, target):
    obj.rotation_euler = (
        Vector(target) - obj.location
    ).to_track_quat("-Z", "Y").to_euler()


def light(name, kind, position, target, energy, color, size=1):
    data = bpy.data.lights.new("Env_" + name, kind)
    data.energy = energy
    data.color = color
    if kind == "AREA":
        data.shape = "DISK"
        data.size = size
    elif kind == "SUN":
        data.angle = math.radians(0.65)
    obj = bpy.data.objects.new("Env_" + name, data)
    env.objects.link(obj)
    obj.location = position
    aim(obj, target)
    return obj


# Clear diagonal path through the window; approximately 24-degree elevation.
light(
    "AfternoonSun", "SUN",
    (5.0, -4.0, 3.10), (0, 0, 0.25),
    2.35, (1.0, 0.86, 0.67),
)
light(
    "WindowSky", "AREA",
    (1.45, -1.03, 1.85), (-0.40, 0.02, 0.72),
    48, (0.88, 0.94, 1.0), 1.65,
)
# Inside the left wall; subtle enough to preserve the sun/shade separation.
light(
    "LeftSoftBounce", "AREA",
    (-1.12, -2.00, 1.95), (-0.1, 0.0, 0.57),
    29, (0.94, 0.97, 1.0), 2.0,
)
light(
    "FrontBounce", "AREA",
    (0.0, -3.1, 1.65), (0, 0, 0.55),
    8, (1.0, 0.96, 0.88), 2.5,
)

# -------------------------------------------------------------------
# Cameras. No resolution or render-output settings are changed.
# -------------------------------------------------------------------

def camera(name, position, target, lens):
    data = bpy.data.cameras.new("Env_" + name)
    obj = bpy.data.objects.new("Env_" + name, data)
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


cam1 = camera(
    "RefCamera",
    (-0.60, -4.25, 1.00),
    (-0.31, -0.20, 0.535),
    58.0,
)
camera(
    "RefCamera2",
    (0.83, -4.15, 0.970),
    (0.105, -0.18, 0.535),
    58.0,
)
scene.camera = cam1

scene.render.engine = "CYCLES"
scene.cycles.samples = 192
scene.cycles.use_denoising = True
scene.cycles.max_bounces = 10
scene.cycles.diffuse_bounces = 5
scene.cycles.glossy_bounces = 4
scene.cycles.transmission_bounces = 8
scene.cycles.transparent_max_bounces = 16

scene.view_settings.view_transform = "AgX"
scene.view_settings.exposure = -0.30
scene.view_settings.gamma = 1.0

# Prefer a moderate contrast look without assuming a particular OCIO list.
look_items = scene.view_settings.bl_rna.properties["look"].enum_items
look_ids = {item.identifier for item in look_items}
for candidate in ("AgX - Medium High Contrast", "Medium High Contrast"):
    if candidate in look_ids:
        scene.view_settings.look = candidate
        break

# New datablocks, including glTF assets, all receive the environment prefix.
for kind in TRACK:
    for block in getattr(bpy.data, kind):
        if block not in original[kind] and not block.name.startswith("Env_"):
            block.name = "Env_" + block.name

bpy.context.view_layer.update()
bpy.ops.wm.save_as_mainfile(filepath=sys.argv[sys.argv.index("--") + 1])
