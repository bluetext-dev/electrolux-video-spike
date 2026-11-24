import bpy
import bmesh
import math
from mathutils import Vector, Matrix

# Remove every object, including hidden objects.
for obj in list(bpy.data.objects):
    bpy.data.objects.remove(obj, do_unlink=True)

bpy.context.scene.unit_settings.system = 'METRIC'
bpy.context.scene.unit_settings.scale_length = 1.0

# Cabinet dimensions, metres. Front faces -Y.
W, D, H = 0.597, 0.636, 0.847
F = -D / 2
DZ = 0.454
HX, HZ = 0.166, 0.078
PX, PZ = HX - 0.010, HZ + 0.004


# --------------------------------------------------------------------------
# Helpers
# --------------------------------------------------------------------------

def material(name, color, metallic=0, roughness=0.4,
             transmission=0, emission=0):
    mat = bpy.data.materials.new(name)
    mat.use_nodes = True
    bsdf = next(n for n in mat.node_tree.nodes
                if n.type == "BSDF_PRINCIPLED")
    bsdf.inputs["Base Color"].default_value = (*color, 1)
    bsdf.inputs["Metallic"].default_value = metallic
    bsdf.inputs["Roughness"].default_value = roughness
    if transmission:
        bsdf.inputs["Transmission Weight"].default_value = transmission
        bsdf.inputs["IOR"].default_value = 1.47
    if emission:
        bsdf.inputs["Emission Color"].default_value = (*color, 1)
        bsdf.inputs["Emission Strength"].default_value = emission
    return mat


white = material("Warm white enamel", (0.86, 0.875, 0.87), roughness=0.25)
plastic = material("Ivory service plastic", (0.77, 0.79, 0.75), roughness=0.36)
black = material("Gloss black door edge", (0.006, 0.007, 0.008), roughness=0.19)
graphite = material("Satin graphite door face", (0.018, 0.019, 0.019),
                    metallic=0.20, roughness=0.33)
groove_mat = material("Door radial engraving", (0.006, 0.007, 0.007),
                      roughness=0.46)
fascia_mat = material("Black control fascia", (0.007, 0.009, 0.009),
                      roughness=0.29)
rubber = material("Dark rubber bellows", (0.026, 0.029, 0.028), roughness=0.73)
shadow = material("Deep recess", (0.008, 0.010, 0.010), roughness=0.8)
steel = material("Stainless steel", (0.52, 0.55, 0.56),
                 metallic=0.95, roughness=0.26)
chrome = material("Polished narrow trim", (0.70, 0.73, 0.74),
                  metallic=1, roughness=0.18)
glass_mat = material("Clear lightly tinted glass", (0.93, 0.965, 0.955),
                     roughness=0.035, transmission=1)
blue = material("Blue folding drain guide", (0.025, 0.19, 0.48), roughness=0.32)
red = material("Emergency release red", (0.55, 0.012, 0.017), roughness=0.4)
green = material("Green dosing insert", (0.025, 0.35, 0.12), roughness=0.4)
ink = material("Charcoal printing", (0.035, 0.044, 0.045), roughness=0.6)
pale = material("Silver fascia printing", (0.60, 0.64, 0.63), roughness=0.5)
screen_mat = material("Black display glass", (0.003, 0.007, 0.007), roughness=0.2)
digits_mat = material("White display segments", (0.80, 0.88, 0.86),
                       roughness=0.3, emission=0.35)


def finish(obj, name, mat=None, label=None):
    obj.name = name
    obj["label"] = label or name.replace("_", " ").lower()
    if mat is not None:
        obj.data.materials.append(mat)
    return obj


def bevel(obj, width=0.002, segments=3):
    mod = obj.modifiers.new("Manufactured edge radius", 'BEVEL')
    mod.width = width
    mod.segments = segments
    return mod


def apply(obj, mod):
    bpy.context.view_layer.objects.active = obj
    bpy.ops.object.modifier_apply(modifier=mod.name)


def box(name, loc, dims, mat, edge=0):
    bpy.ops.mesh.primitive_cube_add(size=1, location=loc)
    obj = bpy.context.object
    obj.dimensions = dims
    bpy.ops.object.transform_apply(location=False, rotation=False, scale=True)
    finish(obj, name, mat)
    if edge:
        bevel(obj, edge)
    return obj


def cylinder(name, loc, radius, depth, mat, edge=0, vertices=96):
    bpy.ops.mesh.primitive_cylinder_add(
        vertices=vertices, radius=radius, depth=depth,
        location=loc, rotation=(math.pi / 2, 0, 0))
    obj = bpy.context.object
    # Moving assemblies must retain machine-aligned local axes.
    bpy.ops.object.transform_apply(location=False, rotation=True, scale=True)
    finish(obj, name, mat)
    for p in obj.data.polygons:
        p.use_smooth = len(p.vertices) == 4
    if edge:
        bevel(obj, edge)
    return obj


def mesh_object(name, vertices, faces, mat, smooth=False):
    mesh = bpy.data.meshes.new(name + " mesh")
    mesh.from_pydata(vertices, [], faces)
    mesh.update()

    # Recalculate actual surface normals, especially on glass vessels.
    bm = bmesh.new()
    bm.from_mesh(mesh)
    bmesh.ops.recalc_face_normals(bm, faces=list(bm.faces))
    bm.to_mesh(mesh)
    bm.free()

    obj = bpy.data.objects.new(name, mesh)
    bpy.context.collection.objects.link(obj)
    finish(obj, name, mat)
    for p in mesh.polygons:
        p.use_smooth = smooth
    return obj


def lathe(name, cx, cz, profile, mat, segments=192):
    """Closed radial section around Y; profile points are (radius, world Y).
    Supports radius-zero poles without degenerate quads.
    """
    vertices, rows, faces = [], [], []
    for radius, y in profile:
        if radius == 0:
            rows.append([len(vertices)])
            vertices.append((cx, y, cz))
        else:
            row = []
            for j in range(segments):
                a = 2 * math.pi * j / segments
                row.append(len(vertices))
                vertices.append((cx + radius * math.cos(a),
                                 y, cz + radius * math.sin(a)))
            rows.append(row)

    for k, row in enumerate(rows):
        nxt = rows[(k + 1) % len(rows)]
        if len(row) == 1 and len(nxt) == 1:
            continue
        for j in range(segments):
            j2 = (j + 1) % segments
            if len(row) == 1:
                faces.append((row[0], nxt[j2], nxt[j]))
            elif len(nxt) == 1:
                faces.append((row[j], row[j2], nxt[0]))
            else:
                faces.append((row[j], row[j2], nxt[j2], nxt[j]))
    return mesh_object(name, vertices, faces, mat, True)


def ring(name, x, z, outer, inner, yf, yb, mat, segments=160):
    return lathe(name, x, z,
                 [(outer, yf), (inner, yf), (inner, yb), (outer, yb)],
                 mat, segments)


def subtract(obj, cutter):
    mod = obj.modifiers.new("Physical opening", 'BOOLEAN')
    mod.operation = 'DIFFERENCE'
    mod.object = cutter
    apply(obj, mod)
    bpy.data.objects.remove(cutter, do_unlink=True)


def parent_keep(obj, parent):
    # Explicit update is essential for newly created and repositioned objects.
    bpy.context.view_layer.update()
    world = obj.matrix_world.copy()
    parent_world = parent.matrix_world.copy()
    obj.parent = parent
    obj.matrix_parent_inverse = Matrix.Identity(4)
    obj.matrix_basis = parent_world.inverted() @ world
    bpy.context.view_layer.update()
    return obj


def pivot_at(obj, point):
    """Change the origin without changing world geometry. Use before parenting."""
    bpy.context.view_layer.update()
    old = obj.matrix_world.copy()
    new = Matrix.Translation(Vector(point))
    obj.data.transform(new.inverted() @ old)
    obj.matrix_world = new
    bpy.context.view_layer.update()


def text(name, body, loc, size, mat, align='LEFT', parent=None):
    data = bpy.data.curves.new(name + " lettering", type='FONT')
    data.body = body
    data.size = size
    data.align_x = align
    data.extrude = 0
    obj = bpy.data.objects.new(name, data)
    bpy.context.collection.objects.link(obj)
    obj.location = loc
    obj.rotation_euler = (math.pi / 2, 0, 0)
    finish(obj, name, mat)
    if parent is not None:
        parent_keep(obj, parent)
    return obj


def tube_path(name, points, radius, mat, parent=None):
    data = bpy.data.curves.new(name + " curve", type='CURVE')
    data.dimensions = '3D'
    data.bevel_depth = radius
    data.bevel_resolution = 2
    spline = data.splines.new('POLY')
    spline.points.add(len(points) - 1)
    for dst, src in zip(spline.points, points):
        dst.co = (*src, 1)
    obj = bpy.data.objects.new(name, data)
    bpy.context.collection.objects.link(obj)
    finish(obj, name, mat)
    if parent is not None:
        parent_keep(obj, parent)
    return obj


def join_meshes(objects, name):
    bpy.ops.object.select_all(action='DESELECT')
    for obj in objects:
        for mod in list(obj.modifiers):
            apply(obj, mod)
        obj.select_set(True)
    bpy.context.view_layer.objects.active = objects[0]
    bpy.ops.object.join()
    result = bpy.context.object
    result.name = name
    result["label"] = "white washing machine cabinet"
    return result


# --------------------------------------------------------------------------
# Hollow cabinet and genuinely open service apertures
# --------------------------------------------------------------------------

front = box("Front steel skin", (0, F + 0.011, 0.368),
            (W - 0.008, 0.022, 0.700), white)
subtract(front, cylinder("Door aperture cutter", (0, F, DZ),
                         0.207, 0.10, None))
subtract(front, cylinder("Service aperture cutter", (HX, F, HZ),
                         0.0675, 0.10, None))
bevel(front, 0.0022, 4)
shell = [front]

for side in (-1, 1):
    side_obj = box("Left side" if side < 0 else "Right side",
                   (side * (W / 2 - 0.007), 0.009, 0.427),
                   (0.014, D - 0.018, 0.800), white)
    for row in range(8):
        cutter = box("Side pressing cutter",
                     (side * (W / 2 + 0.001), 0.018, 0.111 + row * 0.087),
                     (0.010, 0.456, 0.027), None, 0.004)
        apply(cutter, cutter.modifiers[0])
        subtract(side_obj, cutter)
    bevel(side_obj, 0.002)
    shell.append(side_obj)

shell.append(box("Back skin", (0, D / 2 - 0.007, 0.421),
                 (W - 0.022, 0.014, 0.802), white, 0.002))
shell.append(box("Base tray", (0, 0.003, 0.022),
                 (W - 0.027, D - 0.026, 0.012), shadow, 0.002))
body = join_meshes(shell, "Body")
body["cabinet_dimensions_m"] = [W, D, H]
body["reference"] = "Electrolux PerfectCare front-loading washing machine"

box("Top cover seam", (0, 0, 0.829),
    (W - 0.006, D - 0.006, 0.002), rubber, 0.0005)
box("Top cover", (0, 0, 0.839),
    (W, D, 0.016), white, 0.003)

for x in (-0.238, 0.238):
    for y in (-0.248, 0.248):
        bpy.ops.mesh.primitive_cylinder_add(
            vertices=40, radius=0.021, depth=0.018,
            location=(x, y, 0.009))
        foot = finish(bpy.context.object, "Adjustable foot", rubber)
        bevel(foot, 0.002)

# No raised decorative plinth crossing the service hatch.
box("Lower enamel return", (0, F + 0.004, 0.021),
    (W - 0.020, 0.012, 0.012), white, 0.002)

# Electronics occupy only the upper-right area.
box("Electronics casing", (0.115, F + 0.032, 0.779),
    (0.357, 0.062, 0.115), plastic, 0.003)
box("White fascia bridge", (0, F + 0.002, 0.731),
    (W - 0.008, 0.014, 0.033), white, 0.002)

# Drawer aperture remains empty and extends into the cabinet.
box("Drawer left jamb", (-0.289, -0.135, 0.784),
    (0.008, 0.354, 0.099), plastic, 0.001)
box("Drawer right jamb", (-0.069, -0.135, 0.784),
    (0.008, 0.354, 0.099), plastic, 0.001)
box("Drawer housing roof", (-0.179, -0.135, 0.831),
    (0.213, 0.354, 0.004), plastic)
box("Drawer housing floor", (-0.179, -0.135, 0.738),
    (0.213, 0.354, 0.005), plastic)
box("Drawer housing rear", (-0.179, 0.047, 0.784),
    (0.213, 0.008, 0.095), shadow)

control = box("ControlPanel", (0.112, F - 0.001, 0.793),
              (0.361, 0.006, 0.083), fascia_mat, 0.001)
control["label"] = "black programme and touch control panel"

display = box("Display", (0.157, F - 0.0045, 0.799),
              (0.125, 0.001, 0.051), screen_mat, 0.0005)
display["label"] = "digital wash display"

text("Temperature digits", "60°", (0.101, F - 0.0053, 0.803),
     0.014, digits_mat)
text("Remaining time digits", "1:50", (0.223, F - 0.0053, 0.803),
     0.016, digits_mat, 'RIGHT')
text("Spin digits", "1200", (0.101, F - 0.0053, 0.781),
     0.0115, digits_mat)
text("Display temperature caption", "Temperature",
     (0.101, F - 0.0053, 0.794), 0.0036, pale)
text("SteamCare caption", "SteamCare System",
     (0.246, F - 0.0044, 0.827), 0.0052, pale, 'CENTER')

KX, KZ = -0.005, 0.799
cylinder("Selector silver bezel", (KX, F - 0.005, KZ),
         0.0275, 0.004, chrome, 0.0007)
knob = cylinder("ProgramKnob", (KX, F - 0.011, KZ),
                0.0245, 0.010, black, 0.0017)
knob["label"] = "wash programme selector"
parent_keep(box("Selector index", (KX, F - 0.0163, KZ + 0.0205),
                (0.0012, 0.0005, 0.0045), pale, 0.0002), knob)

left_programs = ["Anti-Allergy", "Duvet", "Denim",
                 "Sport", "Outdoor", "Rapid 20 min"]
right_programs = ["Eco 40-60", "Cottons", "Synthetics",
                  "Delicates", "Wool / Silk", "FreshScent"]
for i in range(6):
    z = 0.826 - i * 0.012
    text("Left programme %02d" % i, left_programs[i],
         (-0.064, F - 0.0043, z), 0.0038, pale)
    text("Right programme %02d" % i, right_programs[i],
         (0.084, F - 0.0043, z), 0.0038, pale, 'RIGHT')

keys = ["Prewash", "Stains", "Extra Rinse", "Soft Plus", "Plus Steam", "Pods"]
for i, caption in enumerate(keys):
    x = 0.103 + i * 0.031
    box("Touch zone " + caption, (x, F - 0.0043, 0.760),
        (0.029, 0.0005, 0.014), fascia_mat, 0.0003)
    box("Touch divider " + caption, (x - 0.015, F - 0.0048, 0.760),
        (0.00035, 0.0002, 0.012), pale)
    text("Touch legend " + caption, caption,
         (x, F - 0.0049, 0.758), 0.0034, pale, 'CENTER')

# Thin outlined start/pause area, rather than a bright grey button.
sx, sz = 0.261, 0.800
for x in (sx - 0.012, sx + 0.012):
    box("Start button vertical outline", (x, F - 0.0048, sz),
        (0.00045, 0.0003, 0.031), pale)
for z in (sz - 0.0155, sz + 0.0155):
    box("Start button horizontal outline", (sx, F - 0.0048, z),
        (0.024, 0.0003, 0.00045), pale)
text("Start pause icon", "> II", (sx, F - 0.0052, sz - 0.003),
     0.007, pale, 'CENTER')

box("Power key", (0.100, F - 0.006, 0.738),
    (0.023, 0.003, 0.006), plastic, 0.002)
text("Power legend", "On/Off", (0.100, F - 0.0077, 0.726),
     0.0046, ink, 'CENTER')


# --------------------------------------------------------------------------
# Detergent drawer: closed face, full tray, all children move together
# --------------------------------------------------------------------------

drawer = box("DetergentDrawer", (-0.180, F + 0.002, 0.792),
             (0.217, 0.012, 0.085), white, 0.002)
drawer["label"] = "detergent dosing drawer"
pivot_at(drawer, (-0.180, 0.020, 0.744))
drawer["motion"] = '{"translate": [0, -0.25, 0]}'

def dp(obj):
    return parent_keep(obj, drawer)

dp(box("Drawer finger recess", (-0.180, F + 0.001, 0.748),
       (0.139, 0.014, 0.010), shadow, 0.003))
dp(box("Drawer finger pull lip", (-0.180, F - 0.004, 0.751),
       (0.157, 0.009, 0.007), white, 0.0025))
dp(box("Drawer tray floor", (-0.180, -0.140, 0.746),
       (0.202, 0.319, 0.005), plastic, 0.001))
for x in (-0.278, -0.082):
    dp(box("Drawer tray side", (x, -0.140, 0.776),
           (0.005, 0.319, 0.061), plastic, 0.0015))
for y in (-0.297, 0.017):
    dp(box("Drawer tray end", (-0.180, y, 0.776),
           (0.201, 0.005, 0.060), plastic, 0.0015))
dp(box("Main wash divider", (-0.159, -0.139, 0.771),
       (0.004, 0.303, 0.047), plastic, 0.001))
dp(box("Softener divider", (-0.218, -0.198, 0.771),
       (0.116, 0.004, 0.047), plastic, 0.001))
dp(box("Prewash divider", (-0.119, -0.056, 0.771),
       (0.076, 0.004, 0.047), plastic, 0.001))
dp(box("Green dosing insert", (-0.219, -0.042, 0.784),
       (0.099, 0.102, 0.011), green, 0.005))
dp(box("Insert dosing well", (-0.219, -0.042, 0.790),
       (0.074, 0.073, 0.002), shadow, 0.006))
dp(box("Liquid detergent insert", (-0.218, -0.143, 0.771),
       (0.098, 0.073, 0.012), plastic, 0.006))

# Compact geometric emblem and wordmark.
dp(box("Brand emblem square", (-0.181, F - 0.0045, 0.809),
       (0.017, 0.0007, 0.017), ink, 0.0006))
dp(cylinder("Brand emblem light circle", (-0.181, F - 0.005, 0.809),
            0.007, 0.0004, white, vertices=48))
dp(box("Brand emblem bar", (-0.181, F - 0.0054, 0.809),
       (0.014, 0.0002, 0.0025), ink))
text("Electrolux wordmark", "Electrolux", (-0.181, F - 0.0046, 0.789),
     0.010, ink, 'CENTER', drawer)
text("Drawer product line", "PERFECTCARE 700 | UniversalDose | 9 kg",
     (-0.180, F - 0.0046, 0.765), 0.004, ink, 'CENTER', drawer)


# --------------------------------------------------------------------------
# Bellows and steel drum
# --------------------------------------------------------------------------

lathe("Enamel door aperture shoulder", 0, DZ,
      [(0.256, F + 0.001), (0.249, F - 0.002),
       (0.216, F - 0.003), (0.205, F + 0.005),
       (0.205, F + 0.019), (0.252, F + 0.013)], white)

lathe("Rubber door bellows", 0, DZ,
      [(0.210, F + 0.008), (0.202, F - 0.003),
       (0.190, F + 0.008), (0.184, F + 0.030),
       (0.190, F + 0.054), (0.199, F + 0.046),
       (0.203, F + 0.023), (0.211, F + 0.020)], rubber)

ring("Stainless drum barrel", 0, DZ, 0.199, 0.196,
     F + 0.050, 0.265, steel)
cylinder("Drum rear plate", (0, 0.267, DZ), 0.196, 0.005, steel)
lathe("Drum rear pressed rings", 0, DZ,
      [(0.173, 0.263), (0.164, 0.251), (0.142, 0.249),
       (0.131, 0.259), (0.072, 0.259), (0.060, 0.245),
       (0.048, 0.245), (0.046, 0.263)], steel)
cylinder("Drum rear hub", (0, 0.247, DZ), 0.036, 0.018, steel, 0.004)

# Combined small recessed-looking perforation discs.
verts, faces = [], []
for row in range(25):
    y = F + 0.065 + row * 0.020
    for j in range(72):
        a = 2 * math.pi * (j + (row % 2) * 0.5) / 72
        center = Vector((0.1958 * math.cos(a), y,
                         DZ + 0.1958 * math.sin(a)))
        tangent = Vector((-math.sin(a), 0, math.cos(a)))
        start = len(verts)
        for k in range(6):
            t = 2 * math.pi * k / 6
            v = center + 0.00135 * (
                math.cos(t) * tangent + Vector((0, math.sin(t), 0)))
            verts.append(tuple(v))
        faces.append(tuple(start + k for k in range(6)))
mesh_object("Drum perforations", verts, faces, shadow)

for i in range(3):
    a = -math.pi / 2 + i * 2 * math.pi / 3
    lifter = box("Drum lifting paddle %d" % (i + 1),
                 (0.181 * math.cos(a), -0.005,
                  DZ + 0.181 * math.sin(a)),
                 (0.028, 0.400, 0.032), plastic, 0.010)
    lifter.rotation_euler[1] = -a


# --------------------------------------------------------------------------
# Door: broad, nearly flat annular face, not an inflated torus
# --------------------------------------------------------------------------

door = lathe("Door", 0, DZ,
             [(0.247, F + 0.003),
              (0.251, F - 0.005),
              (0.250, F - 0.016),
              (0.245, F - 0.024),
              (0.232, F - 0.028),
              (0.214, F - 0.027),
              (0.178, F - 0.020),
              (0.171, F - 0.010),
              (0.174, F + 0.007),
              (0.225, F + 0.008)], black, 256)
door["label"] = "left hinged loading door"
pivot_at(door, (-0.228, F + 0.005, DZ))
door["motion"] = '{"rotate": {"axis": "Z", "degrees": -105}}'

def door_part(obj):
    return parent_keep(obj, door)

door_part(lathe("Satin inner door annulus", 0, DZ,
                [(0.219, F - 0.0273), (0.212, F - 0.0274),
                 (0.181, F - 0.0213), (0.176, F - 0.016),
                 (0.178, F - 0.013), (0.219, F - 0.024)],
                graphite, 256))

# Many fine radial moulded lines, not a handful of concentric rings.
verts, faces = [], []
for j in range(640):
    a = 2 * math.pi * j / 640
    da = 0.00065
    idx = len(verts)
    for r, angle in ((0.182, a - da), (0.215, a - da),
                     (0.215, a + da), (0.182, a + da)):
        y = F - 0.0213 - (r - 0.181) * (0.0061 / 0.031)
        verts.append((r * math.cos(angle), y - 0.00012,
                      DZ + r * math.sin(angle)))
    faces.append((idx, idx + 1, idx + 2, idx + 3))
door_part(mesh_object("Fine radial door face engraving", verts, faces, groove_mat))

door_part(lathe("Narrow glass retaining trim", 0, DZ,
                [(0.178, F - 0.018), (0.176, F - 0.021),
                 (0.173, F - 0.019), (0.171, F - 0.010),
                 (0.174, F - 0.008)], chrome, 256))
door_part(ring("Glass edge seal", 0, DZ,
               0.1725, 0.168, F - 0.009, F + 0.003, rubber))

# Closed, thin-walled bowl with a broad clear centre.
door_glass = lathe("DoorGlass", 0, DZ,
                   [(0.171, F - 0.010),
                    (0.163, F - 0.008),
                    (0.153, F + 0.002),
                    (0.143, F + 0.022),
                    (0.131, F + 0.040),
                    (0.112, F + 0.049),
                    (0.065, F + 0.054),
                    (0, F + 0.055),
                    (0, F + 0.058),
                    (0.065, F + 0.057),
                    (0.113, F + 0.052),
                    (0.134, F + 0.043),
                    (0.146, F + 0.025),
                    (0.156, F + 0.005),
                    (0.164, F - 0.004),
                    (0.171, F - 0.006)], glass_mat, 256)
door_glass["label"] = "clear recessed loading door glass"
door_part(door_glass)

door_part(box("DoorHandle", (0.225, F + 0.001, DZ + 0.029),
              (0.022, 0.024, 0.101), black, 0.008))
door_part(box("Door handle finger pocket", (0.209, F + 0.005, DZ + 0.029),
              (0.013, 0.017, 0.073), shadow, 0.005))
door_part(box("Door latch tongue", (0.225, F + 0.021, DZ),
              (0.014, 0.028, 0.013), plastic, 0.002))
box("Door latch receiver", (0.225, F + 0.006, DZ),
    (0.018, 0.009, 0.024), shadow, 0.002)

for z in (DZ - 0.049, DZ + 0.049):
    box("Fixed door hinge mounting", (-0.228, F + 0.010, z),
        (0.025, 0.025, 0.026), steel, 0.003)
    door_part(box("Moving door hinge leaf", (-0.219, F + 0.002, z),
                  (0.028, 0.013, 0.020), steel, 0.002))

box("Wool care badge", (0.241, F - 0.0005, 0.670),
    (0.044, 0.001, 0.026), blue, 0.0005)
text("Wool badge symbols", "O  O", (0.241, F - 0.0012, 0.673),
     0.010, pale, 'CENTER')
text("Wool badge lettering", "WOOLMARK", (0.241, F - 0.0012, 0.661),
     0.0037, pale, 'CENTER')


# --------------------------------------------------------------------------
# Service recess, real pump socket and removable threaded filter
# --------------------------------------------------------------------------

# Seam visible with the flush cover closed.
ring("Hatch perimeter shadow", HX, HZ, 0.0674, 0.0655,
     F + 0.0005, F + 0.008, shadow)
ring("Service opening enamel edge", HX, HZ, 0.0690, 0.0673,
     F + 0.001, F + 0.014, white)

# Hollow recess; no disc blocking the removable basket.
ring("Service recess moulded wall", HX, HZ, 0.0670, 0.0635,
     F + 0.014, F + 0.075, plastic)
back = cylinder("Service recess back plate", (HX, F + 0.078, HZ),
                0.0635, 0.006, plastic)
subtract(back, cylinder("Pump bore cutter", (PX, F + 0.078, PZ),
                        0.036, 0.05, None))

ring("Pump socket body", PX, PZ, 0.041, 0.0345,
     F + 0.039, F + 0.184, plastic)
ring("Pump socket inner bore", PX, PZ, 0.0355, 0.0336,
     F + 0.050, F + 0.170, shadow)
ring("Pump socket front flange", PX, PZ, 0.0430, 0.0350,
     F + 0.034, F + 0.043, white)
cylinder("Pump housing rear", (PX, F + 0.190, PZ),
         0.039, 0.010, shadow, 0.002)

pump = cylinder("PumpFilter", (PX, F + 0.030, PZ),
                0.037, 0.010, plastic, 0.0013)
pump["label"] = "drain pump filter"
pivot_at(pump, (PX, F + 0.046, PZ))
pump["motion"] = (
    '{"rotate": {"axis": "Y", "degrees": -720}, '
    '"translate": [0, -0.145, 0]}'
)

def pp(obj):
    return parent_keep(obj, pump)

pp(ring("Filter cap raised perimeter", PX, PZ, 0.0355, 0.032,
        F + 0.0235, F + 0.029, white))
pp(box("Filter white turning rib", (PX, F + 0.018, PZ),
       (0.008, 0.019, 0.061), white, 0.002))
for z in (PZ - 0.018, PZ + 0.018):
    pp(box("Filter grip moulded notch", (PX, F + 0.0079, z),
           (0.004, 0.001, 0.008), plastic, 0.0008))

pp(ring("Filter sealing O ring", PX, PZ, 0.0348, 0.0305,
        F + 0.036, F + 0.039, rubber))
pp(ring("Filter threaded neck", PX, PZ, 0.0323, 0.0275,
        F + 0.039, F + 0.063, plastic))

# A genuine continuous helical thread rather than disconnected washers.
points = []
for j in range(361):
    t = j / 360
    a = 2 * math.pi * 3 * t
    points.append((PX + 0.0330 * math.cos(a),
                   F + 0.041 + 0.020 * t,
                   PZ + 0.0330 * math.sin(a)))
tube_path("Filter helical thread", points, 0.00125, plastic, pump)

for i in range(5):
    y = F + 0.066 + i * 0.017
    pp(ring("Filter basket hoop %d" % i, PX, PZ,
            0.029, 0.0258, y, y + 0.003, plastic, 96))
for i in range(10):
    a = 2 * math.pi * i / 10
    pp(box("Filter basket rail %02d" % i,
           (PX + 0.0274 * math.cos(a), F + 0.101,
            PZ + 0.0274 * math.sin(a)),
           (0.003, 0.075, 0.003), plastic, 0.0007))
pp(cylinder("Filter basket end", (PX, F + 0.141, PZ),
            0.028, 0.004, plastic, 0.0007))

# Fixed red emergency-release tab and fasteners, as seen in the close-up.
box("Emergency release tab", (HX + 0.044, F + 0.032, HZ + 0.008),
    (0.008, 0.005, 0.041), red, 0.001)
for z in (HZ - 0.027, HZ + 0.033):
    box("Service hinge mounting boss", (HX + 0.051, F + 0.029, z),
        (0.016, 0.025, 0.014), plastic, 0.002)
    cylinder("Service hinge screw", (HX + 0.051, F + 0.015, z),
             0.0042, 0.003, steel, 0.0004, 48)
    for angle in (0, math.pi / 2):
        slot = box("Service screw cross slot",
                   (HX + 0.051, F + 0.0133, z),
                   (0.005, 0.0003, 0.0007), shadow)
        slot.rotation_euler[1] = angle


# --------------------------------------------------------------------------
# Separate folding blue drain guide, never parented to the removable filter
# --------------------------------------------------------------------------

# Model the guide deployed, then bake the inverse opening rotation to store
# it upright behind the closed hatch.
guide_pivot = Vector((PX, F + 0.012, 0.029))
outline = [
    (-0.029, 0.000, 0.003),
    ( 0.029, 0.000, 0.003),
    ( 0.029, -0.016, 0.001),
    ( 0.019, -0.046, -0.005),
    ( 0.012, -0.051, -0.006),
    (-0.012, -0.051, -0.006),
    (-0.019, -0.046, -0.005),
    (-0.029, -0.016, 0.001),
]
guide = mesh_object("BlueDrainGuide", outline,
                    [tuple(range(len(outline)))], blue)
guide["label"] = "folding blue drain guide"
solid = guide.modifiers.new("Moulded guide thickness", 'SOLIDIFY')
solid.thickness = 0.0017
bevel(guide, 0.001, 3)

# Local geometry is stored in its closed, upright orientation.
closed_rotation = Matrix.Rotation(math.radians(-88), 4, 'X')
guide.data.transform(closed_rotation)
guide.location = guide_pivot
guide["motion"] = '{"rotate": {"axis": "X", "degrees": 88}}'

for side in (-1, 1):
    local_points = [
        Vector((side * 0.028, -0.002, 0.005)),
        Vector((side * 0.027, -0.016, 0.004)),
        Vector((side * 0.018, -0.044, -0.002)),
    ]
    world_points = [tuple(guide_pivot + closed_rotation @ p)
                    for p in local_points]
    tube_path("Blue guide raised side lip", world_points, 0.0014, blue, guide)

for x in (PX - 0.029, PX + 0.029):
    box("Drain guide fixed pivot support", (x, F + 0.014, 0.030),
        (0.007, 0.009, 0.011), plastic, 0.001)


# --------------------------------------------------------------------------
# Flush circular service hatch with a right-side hinge
# --------------------------------------------------------------------------

hatch = cylinder("FilterHatch", (HX, F + 0.0036, HZ),
                 0.0658, 0.0064, white, 0.0010, 160)
hatch["label"] = "right hinged pump access hatch"
hinge_point = (HX + 0.0645, F + 0.008, HZ)
pivot_at(hatch, hinge_point)
hatch["motion"] = '{"rotate": {"axis": "Z", "degrees": 105}}'

def hp(obj):
    return parent_keep(obj, hatch)

hp(ring("Hatch inner reinforcing rim", HX, HZ,
        0.0598, 0.0574, F + 0.0068, F + 0.0108, plastic))
hp(box("Hatch latch clip", (HX - 0.055, F + 0.014, HZ + 0.009),
       (0.007, 0.014, 0.012), plastic, 0.001))

# Ribbed offset hinge web. Closed web stays inside the service opening.
hp(box("Hatch offset hinge web", (HX + 0.055, F + 0.018, HZ),
       (0.020, 0.026, 0.036), plastic, 0.002))
for i in range(5):
    hp(box("Hatch hinge reinforcing rib %d" % i,
           (HX + 0.054, F + 0.020, HZ - 0.014 + i * 0.007),
           (0.023, 0.028, 0.002), white, 0.0007))

# Vertical hinge pin stays attached to the housing.
bpy.ops.mesh.primitive_cylinder_add(
    vertices=40, radius=0.0023, depth=0.044,
    location=hinge_point)
finish(bpy.context.object, "Service hatch fixed hinge pin", steel)


# --------------------------------------------------------------------------
# Restrained rear details
# --------------------------------------------------------------------------

box("Rear service cover", (0, D / 2 - 0.001, 0.409),
    (0.455, 0.002, 0.630), white, 0.003)
for x in (-0.213, 0.213):
    for z in (0.108, 0.710):
        cylinder("Rear cover fastener", (x, D / 2 + 0.0005, z),
                 0.0038, 0.001, steel, 0.0003, 40)

# All objects, including text and helper detail meshes, carry caption metadata.
for obj in bpy.context.scene.objects:
    if "label" not in obj:
        obj["label"] = obj.name.replace("_", " ").lower()

# Save the closed state. The later animation template reads the JSON strings.
bpy.context.view_layer.update()
bpy.ops.object.select_all(action='DESELECT')
body.select_set(True)
bpy.context.view_layer.objects.active = body

import sys
bpy.ops.wm.save_as_mainfile(filepath=sys.argv[sys.argv.index("--") + 1])
