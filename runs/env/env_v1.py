import bpy
import math
import os
import sys
import random
from mathutils import Vector, Matrix

random.seed(21)
BASE = os.environ["VP_HERE"]

# Preserve every existing object and datablock. Only new environment objects
# are constructed or modified.
TRACK = (
    "objects", "meshes", "curves", "materials", "images", "collections",
    "cameras", "lights", "worlds", "node_groups", "armatures", "actions",
)
original = {
    k: set(getattr(bpy.data, k))
    for k in TRACK
}

scene = bpy.context.scene
env = bpy.data.collections.new("Env_Set")
scene.collection.children.link(env)


def path(rel):
    p = os.path.join(BASE, rel)
    if not os.path.isfile(p):
        raise FileNotFoundError(p)
    return p


def put_in_env(obj):
    for collection in list(obj.users_collection):
        collection.objects.unlink(obj)
    env.objects.link(obj)
    return obj


def empty(name):
    obj = bpy.data.objects.new("Env_" + name, None)
    env.objects.link(obj)
    return obj


texture_space = empty("TextureSpace")


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
        saturation=1.0, rough=(0.35, 0.7), normal_strength=0.35,
        bump_distance=0.001, rotation=(0, 0, 0), tint_mode="MULTIPLY"):
    mat = plain(name, (0.5, 0.5, 0.5))
    nt = mat.node_tree
    nodes, links = nt.nodes, nt.links
    bs = principled(mat)

    coord = nodes.new("ShaderNodeTexCoord")
    coord.object = texture_space
    mapping = nodes.new("ShaderNodeMapping")
    mapping.vector_type = "POINT"
    if isinstance(tile, (int, float)):
        tile = (tile, tile, tile)
    mapping.inputs["Scale"].default_value = tuple(1 / v for v in tile)
    mapping.inputs["Rotation"].default_value = rotation
    links.new(coord.outputs["Object"], mapping.inputs["Vector"])

    tex = {}
    for kind in ("diffuse", "normal", "roughness", "displacement", "ao"):
        node = nodes.new("ShaderNodeTexImage")
        node.name = "Env_" + name + "_" + kind
        node.image = bpy.data.images.load(
            path(f"assets/textures/{asset}/{kind}.jpg"),
            check_existing=False,
        )
        node.image.colorspace_settings.name = (
            "sRGB" if kind == "diffuse" else "Non-Color"
        )
        node.projection = "BOX"
        node.projection_blend = 0.22
        links.new(mapping.outputs["Vector"], node.inputs["Vector"])
        tex[kind] = node

    hue = nodes.new("ShaderNodeHueSaturation")
    hue.inputs["Saturation"].default_value = saturation
    links.new(tex["diffuse"].outputs["Color"], hue.inputs["Color"])
    color = hue.outputs["Color"]

    if tint is not None:
        mix = nodes.new("ShaderNodeMixRGB")
        mix.blend_type = tint_mode
        mix.inputs[0].default_value = tint_amount
        mix.inputs[2].default_value = (*tint, 1)
        links.new(color, mix.inputs[1])
        color = mix.outputs[0]

    ao = nodes.new("ShaderNodeMixRGB")
    ao.blend_type = "MULTIPLY"
    ao.inputs[0].default_value = 0.25
    links.new(color, ao.inputs[1])
    links.new(tex["ao"].outputs["Color"], ao.inputs[2])
    links.new(ao.outputs[0], bs.inputs["Base Color"])

    remap = nodes.new("ShaderNodeMapRange")
    remap.inputs["From Min"].default_value = 0
    remap.inputs["From Max"].default_value = 1
    remap.inputs["To Min"].default_value = rough[0]
    remap.inputs["To Max"].default_value = rough[1]
    links.new(tex["roughness"].outputs["Color"], remap.inputs["Value"])
    links.new(remap.outputs["Result"], bs.inputs["Roughness"])

    normal = nodes.new("ShaderNodeNormalMap")
    normal.inputs["Strength"].default_value = normal_strength
    links.new(tex["normal"].outputs["Color"], normal.inputs["Color"])

    bump = nodes.new("ShaderNodeBump")
    bump.inputs["Strength"].default_value = 0.20
    bump.inputs["Distance"].default_value = bump_distance
    links.new(tex["displacement"].outputs["Color"], bump.inputs["Height"])
    links.new(normal.outputs["Normal"], bump.inputs["Normal"])
    links.new(bump.outputs["Normal"], bs.inputs["Normal"])
    return mat


oak = pbr(
    "PaleOak", "oak_veneer_01", tile=(0.65, 0.65, 1.30),
    tint=(0.76, 0.62, 0.41), tint_amount=0.22,
    saturation=0.68, rough=(0.40, 0.63),
    rotation=(0, math.pi / 2, 0),
)
stone = pbr(
    "GreyVeinedStone", "marble_01", tile=1.55,
    tint=(0.46, 0.45, 0.41), tint_amount=0.72,
    saturation=0.30, rough=(0.28, 0.47), normal_strength=0.23,
)
floor_mat = pbr(
    "CharcoalConcrete", "concrete_floor_02", tile=1.65,
    tint=(0.16, 0.18, 0.17), tint_amount=0.80,
    saturation=0.35, rough=(0.66, 0.88), bump_distance=0.002,
)
plaster = pbr(
    "WarmWhitePlaster", "white_plaster_02", tile=1.20,
    tint=(0.88, 0.85, 0.77), tint_amount=0.25,
    rough=(0.78, 0.94), normal_strength=0.25,
)
rug_mat = pbr(
    "SageRug", "denim_fabric", tile=0.16,
    tint=(0.17, 0.23, 0.135), tint_amount=0.87,
    tint_mode="MIX", saturation=0,
    rough=(0.88, 0.99), normal_strength=0.60,
)
cream = pbr(
    "CreamTerry", "denim_fabric", tile=0.085,
    tint=(0.75, 0.72, 0.62), tint_amount=0.91,
    tint_mode="MIX", saturation=0, rough=(0.86, 0.98),
)
linen = pbr(
    "TaupeLinen", "denim_fabric", tile=0.10,
    tint=(0.41, 0.39, 0.33), tint_amount=0.87,
    tint_mode="MIX", saturation=0, rough=(0.82, 0.98),
)
grey_cloth = pbr(
    "GreyCloth", "denim_fabric", tile=0.09,
    tint=(0.32, 0.34, 0.32), tint_amount=0.86,
    tint_mode="MIX", saturation=0, rough=(0.83, 0.98),
)
dark = plain("CabinetReveals", (0.105, 0.087, 0.061), 0.70)
steel = plain("BrushedNickel", (0.48, 0.48, 0.43), 0.23, 0.92)
sink_mat = plain("SinkSteel", (0.33, 0.35, 0.34), 0.32, 0.85)
ceramic = plain("OffWhiteCeramic", (0.84, 0.82, 0.73), 0.25)
amber = plain("AmberSoap", (0.22, 0.12, 0.025), 0.23)
black = plain("PumpBlack", (0.025, 0.027, 0.023), 0.30)
wicker_trim = plain("WickerTrim", (0.43, 0.29, 0.135), 0.73)
window_wood = plain("WindowOak", (0.27, 0.115, 0.042), 0.39)
stitch_mat = plain("LinenStitch", (0.59, 0.56, 0.47), 0.95)


def box(name, loc, size, mat, bevel=0.0):
    bpy.ops.mesh.primitive_cube_add(size=1, location=loc)
    obj = put_in_env(bpy.context.object)
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


def mesh_obj(name, vertices, faces, mat):
    mesh = bpy.data.meshes.new("Env_" + name + "Mesh")
    mesh.from_pydata(vertices, [], faces)
    mesh.update()
    obj = bpy.data.objects.new("Env_" + name, mesh)
    env.objects.link(obj)
    if mat:
        mesh.materials.append(mat)
    return obj


def curve(name, points, radius, mat, cyclic=False):
    data = bpy.data.curves.new("Env_" + name + "Curve", "CURVE")
    data.dimensions = "3D"
    data.resolution_u = 16
    data.bevel_depth = radius
    data.bevel_resolution = 3
    spline = data.splines.new("POLY")
    spline.points.add(len(points) - 1)
    for p, co in zip(spline.points, points):
        p.co = (*co, 1)
    spline.use_cyclic_u = cyclic
    obj = bpy.data.objects.new("Env_" + name, data)
    env.objects.link(obj)
    data.materials.append(mat)
    return obj


def cylinder(name, loc, radius, depth, mat, vertices=48):
    bpy.ops.mesh.primitive_cylinder_add(
        vertices=vertices, radius=radius, depth=depth, location=loc
    )
    obj = put_in_env(bpy.context.object)
    obj.name = "Env_" + name
    obj.data.materials.append(mat)
    bevel = obj.modifiers.new("Env_RoundedLip", "BEVEL")
    bevel.width = min(0.003, depth / 5)
    bevel.segments = 3
    obj.modifiers.new("Env_WeightedNormals", "WEIGHTED_NORMAL")
    for poly in obj.data.polygons:
        poly.use_smooth = True
    return obj


def import_asset(asset, name, target_dims, location, angle=0):
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
        raise RuntimeError("No mesh in asset: " + asset)

    lo = Vector(tuple(min(v[i] for v in corners) for i in range(3)))
    hi = Vector(tuple(max(v[i] for v in corners) for i in range(3)))
    extent = hi - lo
    root = empty(name)
    for i, obj in enumerate(sorted(imported, key=lambda o: o.name)):
        obj.name = f"Env_{name}_Part_{i:03d}"
        if obj.parent not in imported:
            world = obj.matrix_world.copy()
            obj.parent = root
            obj.matrix_world = world
        put_in_env(obj)

    scale = Vector(tuple(target_dims[i] / max(extent[i], 1e-6)
                         for i in range(3)))
    anchor = Vector(((lo.x + hi.x) / 2, (lo.y + hi.y) / 2, lo.z))
    scaled_anchor = Vector(tuple(anchor[i] * scale[i] for i in range(3)))
    rotation = Matrix.Rotation(angle, 3, "Z")
    root.scale = scale
    root.rotation_euler.z = angle
    root.location = Vector(location) - rotation @ scaled_anchor
    bpy.context.view_layer.update()
    return root


# Architecture, in metres. Washer remains at its original origin.
box("Floor", (0, -1.15, -0.075), (8, 8, 0.15), floor_mat, 0.006)
box("StoneBackWall", (-0.17, 0.425, 1.39),
    (2.43, 0.09, 2.78), stone, 0.003)
box("LeftPlasterWall", (-1.415, -1.05, 1.40),
    (0.13, 3.10, 2.80), plaster, 0.008)
box("RightBackPlaster", (1.245, 0.425, 1.40),
    (0.40, 0.10, 2.80), plaster, 0.005)

# Handleless cabinets: flush face at the washer's front plane.
FRONT = -0.318
TOP = 0.887
SLAB_BOTTOM = 0.863

def cabinet(name, x0, x1):
    w = x1 - x0
    x = (x0 + x1) / 2
    box(name + "Carcass", (x, 0.027, 0.451),
        (w - 0.006, 0.622, 0.810), oak, 0.002)
    box(name + "ShadowBacking", (x, -0.299, 0.457),
        (w - 0.008, 0.026, 0.789), dark, 0.001)
    # Two broad flat fronts, no handles, small horizontal shadow joint.
    for label, z0, z1 in (
        ("LowerFront", 0.055, 0.451),
        ("UpperFront", 0.456, 0.853),
    ):
        box(name + label, (x, FRONT + 0.009, (z0 + z1) / 2),
            (w - 0.006, 0.021, z1 - z0), oak, 0.0015)
    box(name + "RecessedPlinth", (x, -0.248, 0.027),
        (w - 0.014, 0.075, 0.052), dark, 0.002)


cabinet("LeftCabinetA", -1.325, -0.820)
cabinet("LeftCabinetB", -0.820, -0.311)
cabinet("RightCabinet", 0.311, 0.985)
box("RightEndPanel", (0.989, 0.02, 0.434),
    (0.018, 0.65, 0.858), oak, 0.002)

# Worktop is genuinely open over the sink rather than hiding a solid slab.
X0, X1 = -1.34, 1.01
Y0, Y1 = -0.354, 0.378
HX0, HX1 = -0.915, -0.485
HY0, HY1 = -0.252, 0.142

def slab(name, xa, xb, ya, yb):
    box(name, ((xa + xb) / 2, (ya + yb) / 2,
               (TOP + SLAB_BOTTOM) / 2),
        (xb - xa, yb - ya, TOP - SLAB_BOTTOM), stone, 0.002)


slab("WorktopLeft", X0, HX0, Y0, Y1)
slab("WorktopRight", HX1, X1, Y0, Y1)
slab("WorktopSinkFront", HX0, HX1, Y0, HY0)
slab("WorktopSinkBack", HX0, HX1, HY1, Y1)
box("BackSiliconeJoint", (-0.165, 0.373, TOP + 0.001),
    (2.35, 0.007, 0.004), stone, 0.001)

# A rounded rectangular stainless basin, including its sloping inside.
def rounded_ring(cx, cy, w, d, r, z, steps=12):
    points = []
    for ox, oy, start in (
        (w/2-r, d/2-r, 0),
        (-w/2+r, d/2-r, 90),
        (-w/2+r, -d/2+r, 180),
        (w/2-r, -d/2+r, 270),
    ):
        for i in range(steps):
            a = math.radians(start + i * 90 / steps)
            points.append((cx + ox + r*math.cos(a),
                           cy + oy + r*math.sin(a), z))
    return points


cx, cy = -0.700, -0.055
specs = [
    (0.445, 0.409, 0.045, TOP + 0.0025),
    (0.418, 0.382, 0.042, TOP + 0.0030),
    (0.397, 0.361, 0.047, TOP - 0.019),
    (0.300, 0.264, 0.065, TOP - 0.149),
    (0.275, 0.239, 0.065, TOP - 0.156),
]
verts = []
for w, d, r, z in specs:
    verts.extend(rounded_ring(cx, cy, w, d, r, z))
n = 48
faces = []
for j in range(len(specs)-1):
    for i in range(n):
        k = (i+1) % n
        faces.append((j*n+i, j*n+k, (j+1)*n+k, (j+1)*n+i))
faces.append(tuple(range((len(specs)-1)*n, len(specs)*n)))
basin = mesh_obj("InsetSink", verts, faces, sink_mat)
for poly in basin.data.polygons:
    poly.use_smooth = True
solid = basin.modifiers.new("Env_SinkThickness", "SOLIDIFY")
solid.thickness = 0.0015
cylinder("SinkDrain", (cx, cy, TOP - 0.154), 0.027, 0.003, steel)
for i in range(6):
    a = i * math.tau / 6
    cylinder("DrainHole_%02d" % i,
             (cx + 0.016*math.cos(a), cy + 0.016*math.sin(a),
              TOP - 0.1518), 0.0021, 0.0008, black, 16)

# Tall gooseneck tap behind the sink.
tx, ty = -0.735, 0.218
cylinder("TapFoot", (tx, ty, TOP + 0.005), 0.026, 0.010, steel)
tap_points = [(tx, ty, TOP + 0.007), (tx, ty, 1.108)]
for i in range(33):
    t = math.pi * i / 32
    tap_points.append((tx, ty - 0.068 + 0.068*math.cos(t),
                       1.108 + 0.068*math.sin(t)))
tap_points.append((tx, ty - 0.136, 1.074))
curve("GooseneckTap", tap_points, 0.0105, steel)
cylinder("TapAerator", (tx, ty - 0.136, 1.074),
         0.012, 0.019, steel)
curve("TapLever", [
    (tx + 0.010, ty, 0.966),
    (tx + 0.050, ty, 0.966),
    (tx + 0.065, ty, 1.005),
], 0.004, steel)

# Imported countertop accessories.
import_asset("potted_plant_02", "Plant",
             (0.33, 0.30, 0.385), (-1.115, 0.095, TOP), -0.24)

box("BottleTray", (0.424, 0.105, TOP + 0.008),
    (0.310, 0.190, 0.016), ceramic, 0.012)
import_asset("multi_cleaner_bottle", "SprayBottle",
             (0.073, 0.075, 0.194), (0.360, 0.116, TOP + 0.016), 0.22)
import_asset("bleach_bottle", "CleaningBottle",
             (0.062, 0.047, 0.193), (0.476, 0.139, TOP + 0.016), -0.35)


def soap(name, x, y, z, mat, height=0.095):
    cylinder(name + "Body", (x, y, z + height/2),
             0.024, height, mat)
    cylinder(name + "Collar", (x, y, z + height + 0.005),
             0.013, 0.012, steel)
    cylinder(name + "Stem", (x, y, z + height + 0.019),
             0.0035, 0.021, black)
    curve(name + "Pump", [
        (x, y, z + height + 0.029),
        (x, y - 0.024, z + height + 0.029),
        (x, y - 0.031, z + height + 0.023),
    ], 0.004, black)


soap("SinkSoap", -0.577, 0.238, TOP, amber, 0.075)
soap("TraySoap", 0.527, 0.053, TOP + 0.016, ceramic, 0.084)

# Folded towels built as softly rounded layers with understated seam lines.
def folded_towel(name, center, width, depth, height, mat, angle=0):
    x, y, z = center
    parent = empty(name)
    parent.location = (x, y, z)
    parent.rotation_euler.z = angle
    for layer in range(3):
        obj = box(
            name + "_Fold_%d" % layer,
            (0, 0, height*(layer + 0.5)/3),
            (width*(1 - layer*0.018), depth, height/3),
            mat, min(0.009, height/6),
        )
        obj.parent = parent
    seam = curve(
        name + "_Hem",
        [(-width*0.45, -depth/2-0.0005, height*0.69),
         (0, -depth/2-0.001, height*0.68),
         (width*0.45, -depth/2-0.0005, height*0.69)],
        0.00065, stitch_mat,
    )
    seam.parent = parent
    return parent


folded_towel("CounterTowelBottom", (0.015, 0.025, TOP),
             0.285, 0.218, 0.032, grey_cloth, -0.035)
folded_towel("CounterTowelMiddle", (0.025, 0.028, TOP+0.032),
             0.275, 0.206, 0.035, cream, 0.045)
folded_towel("CounterTowelTop", (0.018, 0.040, TOP+0.067),
             0.255, 0.191, 0.028, linen, -0.06)


def catmull(points, t):
    p = [Vector(v) for v in points]
    scaled = t * (len(p)-1)
    j = min(int(scaled), len(p)-2)
    u = scaled-j
    a = p[max(j-1, 0)]
    b = p[j]
    c = p[j+1]
    d = p[min(j+2, len(p)-1)]
    return 0.5 * (
        2*b + (-a+c)*u + (2*a-5*b+4*c-d)*u*u
        + (-a+3*b-3*c+d)*u*u*u
    )


def drape(name, route, width, mat, lateral=(1, 0, 0)):
    lateral = Vector(lateral).normalized()
    vertices, faces = [], []
    nu, nv = 28, 48
    for j in range(nv+1):
        t = j/nv
        center = catmull(route, t)
        for i in range(nu+1):
            u = i/nu
            q = center + lateral*((u-0.5)*width)
            ripple = math.sin(u*math.tau*4.5 + t*1.7)
            q.z += 0.0055*ripple + 0.002*math.sin(t*19 + u*7)
            q.y += 0.006*ripple*math.sin(math.pi*t)
            vertices.append(tuple(q))
    for j in range(nv):
        for i in range(nu):
            a = j*(nu+1)+i
            faces.append((a, a+1, a+nu+2, a+nu+1))
    obj = mesh_obj(name, vertices, faces, mat)
    for p in obj.data.polygons:
        p.use_smooth = True
    sub = obj.modifiers.new("Env_ClothSmooth", "SUBSURF")
    sub.levels = 1
    sub.render_levels = 1
    sol = obj.modifiers.new("Env_ClothThickness", "SOLIDIFY")
    sol.thickness = 0.002
    return obj


drape("RightCounterDrape", [
    (0.855, 0.180, TOP+0.013),
    (0.855, -0.120, TOP+0.010),
    (0.855, -0.345, TOP+0.010),
    (0.855, -0.378, TOP-0.046),
    (0.868, -0.378, TOP-0.128),
], 0.235, grey_cloth)

# Baskets remain entirely lateral to the washer's access/camera corridor.
# Their photo-sized proportions deliberately override the shallow asset's
# catalogue dimensions.
import_asset("wicker_basket_01", "LeftLaundryBasket",
             (0.355, 0.325, 0.455), (-1.119, -0.702, 0.008), -0.10)
import_asset("wicker_basket_01", "RightLaundryBasket",
             (0.450, 0.425, 0.447), (1.005, -0.687, 0.008), 0.12)


def basket_handle(name, x, y, z, radius):
    points = []
    for i in range(49):
        a = math.pi*i/48
        points.append((x + radius*math.cos(a), y,
                       z + radius*0.90*math.sin(a)))
    curve(name, points, 0.009, wicker_trim)


basket_handle("LeftBasketHandle", -1.119, -0.614, 0.423, 0.071)
basket_handle("RightBasketHandle", 1.005, -0.573, 0.425, 0.083)

folded_towel("LeftBasketTowelA", (-1.118, -0.700, 0.396),
             0.258, 0.210, 0.037, cream, 0.16)
folded_towel("LeftBasketTowelB", (-1.102, -0.690, 0.433),
             0.226, 0.186, 0.032, grey_cloth, -0.12)
drape("LeftBasketHangingLinen", [
    (-1.060, -0.677, 0.469),
    (-1.044, -0.839, 0.458),
    (-1.010, -0.893, 0.343),
    (-0.985, -0.915, 0.145),
    (-0.960, -0.960, 0.023),
    (-0.923, -1.054, 0.010),
], 0.192, cream)

folded_towel("RightBasketTowelA", (1.011, -0.697, 0.374),
             0.320, 0.255, 0.039, linen, -0.09)
folded_towel("RightBasketTowelB", (0.993, -0.696, 0.413),
             0.292, 0.226, 0.041, cream, 0.12)
drape("RightBasketLooseTowel", [
    (1.092, -0.646, 0.452),
    (1.108, -0.736, 0.464),
    (1.127, -0.823, 0.442),
], 0.140, cream)

# A nearly flush rug is the only dressing in the open central floor.
# Its back edge is 0.61 m ahead of the washer, outside the 0.5 m exclusion.
box("GreenRug", (-0.28, -1.52, 0.0045),
    (1.90, 1.18, 0.009), rug_mat, 0.004)
for edge in (-2.11, -0.93):
    curve("RugBoundEdge_%s" % str(edge), [
        (-1.218, edge, 0.0095), (0.658, edge, 0.0095)
    ], 0.0025, rug_mat)
for i in range(100):
    x = -1.20 + i*1.85/99
    curve("RugFringe_%03d" % i, [
        (x, -2.106, 0.006),
        (x+random.uniform(-0.004, 0.004), -2.133, 0.0035),
        (x+random.uniform(-0.005, 0.005),
         -2.15-random.random()*0.012, 0.003),
    ], 0.0008, rug_mat)

# Tall side window/glazed-door opening on the room's right.
# The clear opening is intentionally unobstructed by a shadow-casting
# glass proxy; the frame and sheer curtain provide its visual definition.
WX = 1.515
box("WindowRearPier", (WX, 0.295, 1.40),
    (0.15, 0.29, 2.80), plaster, 0.004)
box("WindowFrontPier", (WX, -2.83, 1.40),
    (0.15, 0.24, 2.80), plaster, 0.004)
box("WindowHeader", (WX, -1.28, 2.72),
    (0.15, 2.95, 0.16), plaster, 0.004)
box("WindowSill", (WX, -1.28, 0.043),
    (0.23, 2.95, 0.086), stone, 0.004)
for name, y in (("Rear", 0.133), ("Front", -2.695)):
    box("WindowJamb"+name, (WX, y, 1.37),
        (0.090, 0.067, 2.57), window_wood, 0.004)
for name, z in (("Bottom", 0.105), ("Top", 2.645)):
    box("WindowRail"+name, (WX, -1.28, z),
        (0.090, 2.87, 0.065), window_wood, 0.004)
box("WindowMullion", (WX, -1.65, 1.37),
    (0.073, 0.045, 2.52), window_wood, 0.003)

curtain_mat = pbr(
    "SheerLinen", "denim_fabric", tile=0.065,
    tint=(0.93, 0.91, 0.83), tint_amount=0.97,
    tint_mode="MIX", saturation=0, rough=(0.87, 0.98),
    normal_strength=0.15,
)
nt = curtain_mat.node_tree
bs = principled(curtain_mat)
output = next(n for n in nt.nodes if n.type == "OUTPUT_MATERIAL")
transparent = nt.nodes.new("ShaderNodeBsdfTransparent")
mix = nt.nodes.new("ShaderNodeMixShader")
mix.inputs[0].default_value = 0.57
nt.links.new(transparent.outputs[0], mix.inputs[1])
nt.links.new(bs.outputs[0], mix.inputs[2])
nt.links.new(mix.outputs[0], output.inputs["Surface"])
if hasattr(curtain_mat, "surface_render_method"):
    curtain_mat.surface_render_method = "DITHERED"

vertices, faces = [], []
NU, NV = 92, 32
for j in range(NV+1):
    v = j/NV
    for i in range(NU+1):
        u = i/NU
        y = -0.635 + 0.850*u
        fold = math.sin(u*math.tau*8.5)
        x = 1.372 + 0.047*fold + 0.011*math.sin(u*math.tau*17)
        x -= 0.024*(1-v)**3
        z = 0.025 + 2.585*v
        z += (1-v)**10 * (0.012 + 0.010*math.cos(u*math.tau*8.5))
        vertices.append((x, y, z))
for j in range(NV):
    for i in range(NU):
        a = j*(NU+1)+i
        faces.append((a, a+1, a+NU+2, a+NU+1))
curtain = mesh_obj("WhiteSheerCurtain", vertices, faces, curtain_mat)
for poly in curtain.data.polygons:
    poly.use_smooth = True
sub = curtain.modifiers.new("Env_SheerSmooth", "SUBSURF")
sub.levels = 1
sub.render_levels = 1
curve("CurtainRail", [(1.36, -0.69, 2.635), (1.36, 0.24, 2.635)],
      0.012, ceramic)

# HDRI fill, with its brightest upper-hemisphere patch rotated to the left.
world = bpy.data.worlds.new("Env_LoftWorld")
world.use_nodes = True
scene.world = world
nt = world.node_tree
nt.nodes.clear()
out = nt.nodes.new("ShaderNodeOutputWorld")
background = nt.nodes.new("ShaderNodeBackground")
background.inputs["Strength"].default_value = 0.22
environment = nt.nodes.new("ShaderNodeTexEnvironment")
environment.image = bpy.data.images.load(
    path("assets/hdri/photo_studio_loft_hall.hdr"), check_existing=False
)
coord = nt.nodes.new("ShaderNodeTexCoord")
mapping = nt.nodes.new("ShaderNodeMapping")

# Sample the HDRI efficiently without modifying its image.
import numpy as np
image = environment.image
w, h = image.size
pixels = np.empty(len(image.pixels), dtype=np.float32)
image.pixels.foreach_get(pixels)
pixels = pixels.reshape(h, w, 4)
sx, sy = max(1, w//128), max(1, h//64)
sample = pixels[h//2:int(h*0.94):sy, ::sx, :3]
luminance = sample @ np.array([0.2126, 0.7152, 0.0722], dtype=np.float32)
_, col = np.unravel_index(np.argmax(luminance), luminance.shape)
bright_u = (col*sx + 0.5)/w
bright_longitude = math.tau*(bright_u - 0.5)
desired_longitude = math.atan2(-0.8, -3.0)
mapping.inputs["Rotation"].default_value[2] = (
    bright_longitude - desired_longitude
)
del pixels, sample, luminance

nt.links.new(coord.outputs["Generated"], mapping.inputs["Vector"])
nt.links.new(mapping.outputs["Vector"], environment.inputs["Vector"])
nt.links.new(environment.outputs["Color"], background.inputs["Color"])
nt.links.new(background.outputs[0], out.inputs["Surface"])


def aim(obj, target):
    obj.rotation_euler = (
        Vector(target) - obj.location
    ).to_track_quat("-Z", "Y").to_euler()


def light(name, kind, location, target, energy, color, size=None):
    data = bpy.data.lights.new("Env_" + name, kind)
    data.energy = energy
    data.color = color
    if kind == "AREA":
        data.shape = "DISK"
        data.size = size or 1.0
    if kind == "SUN":
        data.angle = math.radians(1.2)
    obj = bpy.data.objects.new("Env_" + name, data)
    env.objects.link(obj)
    obj.location = location
    aim(obj, target)
    return obj


# Dominant low sun enters through the clear section of the right window.
light("WarmWindowSun", "SUN", (4.8, -4.8, 3.55),
      (0, 0, 0.36), 3.0, (1.0, 0.79, 0.55))
light("WindowSoftLight", "AREA", (2.35, -1.90, 2.10),
      (-0.45, 0.1, 0.65), 190, (1.0, 0.88, 0.71), 1.85)
light("LeftWindowFill", "AREA", (-2.6, -2.15, 2.55),
      (-0.35, 0.05, 0.64), 105, (0.85, 0.91, 1.0), 2.75)


def camera(name, position, target, lens):
    data = bpy.data.cameras.new("Env_" + name)
    obj = bpy.data.objects.new("Env_" + name, data)
    env.objects.link(obj)
    obj.location = position
    aim(obj, target)
    data.lens = lens
    data.sensor_width = 36
    data.clip_start = 0.04
    data.clip_end = 150
    data.dof.use_dof = False
    return obj


cam1 = camera("RefCamera", (-0.83, -3.67, 1.37),
              (-0.18, -0.01, 0.70), 48)
camera("RefCamera2", (1.08, -3.55, 1.36),
       (0.02, -0.005, 0.70), 47)
scene.camera = cam1

scene.render.engine = "CYCLES"
scene.cycles.samples = 64
scene.cycles.use_denoising = True
scene.cycles.max_bounces = 8
scene.cycles.transparent_max_bounces = 12
scene.view_settings.view_transform = "AgX"
scene.view_settings.exposure = -0.25

# Prefix all newly created datablocks, including those produced by glTF.
# Original washer objects, names, transforms and materials remain untouched.
for kind in TRACK:
    for block in getattr(bpy.data, kind):
        if block not in original[kind] and not block.name.startswith("Env_"):
            block.name = "Env_" + block.name

bpy.context.view_layer.update()
bpy.ops.wm.save_as_mainfile(filepath=sys.argv[sys.argv.index("--") + 1])
