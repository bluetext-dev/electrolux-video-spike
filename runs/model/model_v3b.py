import bpy
import bmesh
import math
from mathutils import Vector, Matrix

# Delete every object, including hidden objects.
for obj in list(bpy.data.objects):
    bpy.data.objects.remove(obj, do_unlink=True)

bpy.context.scene.unit_settings.system = 'METRIC'
bpy.context.scene.unit_settings.scale_length = 1.0

# Retain the supplied appliance dimensions. Photographs are not dimensioned.
W, D, H = 0.597, 0.636, 0.847
F = -D / 2
DZ = 0.456
HX, HZ = 0.167, 0.099  # hand fix 2026-09-29: raised 25 mm so the hatch clears the lower front trim (was 0.074)
PX, PZ = HX - 0.009, HZ + 0.006


# ---------------------------------------------------------------------------
# Materials
# ---------------------------------------------------------------------------

def material(name, rgb, metallic=0.0, roughness=0.4,
             transmission=0.0, emission=0.0):
    mat = bpy.data.materials.new(name)
    mat.use_nodes = True
    bsdf = next(n for n in mat.node_tree.nodes
                if n.type == "BSDF_PRINCIPLED")
    bsdf.inputs["Base Color"].default_value = (*rgb, 1.0)
    bsdf.inputs["Metallic"].default_value = metallic
    bsdf.inputs["Roughness"].default_value = roughness
    bsdf.inputs["Transmission Weight"].default_value = transmission
    if transmission:
        bsdf.inputs["IOR"].default_value = 1.45
    if emission:
        bsdf.inputs["Emission Color"].default_value = (*rgb, 1)
        bsdf.inputs["Emission Strength"].default_value = emission
    return mat


white = material("White enamel", (0.89, 0.90, 0.89), roughness=0.27)
ivory = material("Service moulding", (0.79, 0.81, 0.77), roughness=0.39)
black = material("Black polished door perimeter",
                 (0.007, 0.008, 0.009), roughness=0.22)
graphite = material("Satin dark graphite annulus",
                    (0.032, 0.035, 0.036), metallic=0.25, roughness=0.36)
groove = material("Fine dark moulded grooves",
                  (0.008, 0.009, 0.010), roughness=0.46)
panel_mat = material("Black control fascia",
                     (0.009, 0.011, 0.012), roughness=0.30)
screen_mat = material("Display cover",
                      (0.004, 0.007, 0.008), roughness=0.22)
rubber = material("Door bellows rubber",
                  (0.033, 0.038, 0.038), roughness=0.72)
dark = material("Recess and perforation darkness",
                (0.008, 0.011, 0.012), roughness=0.82)
steel = material("Brushed stainless steel",
                 (0.57, 0.61, 0.63), metallic=0.93, roughness=0.32)
chrome = material("Thin polished metal trim",
                  (0.68, 0.71, 0.73), metallic=1.0, roughness=0.21)
glass_mat = material("Clear thin door glass",
                     (0.985, 0.995, 0.99), roughness=0.045,
                     transmission=1.0)
blue = material("Blue drain flap", (0.025, 0.19, 0.48), roughness=0.35)
red = material("Emergency release tab red",
               (0.62, 0.012, 0.02), roughness=0.4)
green = material("Dosing insert green",
                 (0.025, 0.34, 0.12), roughness=0.38)
ink = material("Dark printed lettering",
               (0.033, 0.042, 0.044), roughness=0.55)
pale = material("Light fascia lettering",
                (0.68, 0.72, 0.72), roughness=0.55)
digits = material("Illuminated display digits",
                  (0.85, 0.95, 0.94), roughness=0.4, emission=0.45)

# Very restrained microtexture on the stainless steel.
bsdf = next(n for n in steel.node_tree.nodes
            if n.type == "BSDF_PRINCIPLED")
noise = steel.node_tree.nodes.new("ShaderNodeTexNoise")
noise.inputs["Scale"].default_value = 650.0
noise.inputs["Detail"].default_value = 2.0
bump = steel.node_tree.nodes.new("ShaderNodeBump")
bump.inputs["Strength"].default_value = 0.11
bump.inputs["Distance"].default_value = 0.00012
steel.node_tree.links.new(noise.outputs["Fac"], bump.inputs["Height"])
steel.node_tree.links.new(bump.outputs["Normal"], bsdf.inputs["Normal"])


# ---------------------------------------------------------------------------
# Geometry and transform helpers
# ---------------------------------------------------------------------------

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


def apply_modifier(obj, mod):
    bpy.context.view_layer.objects.active = obj
    bpy.ops.object.modifier_apply(modifier=mod.name)


def box(name, loc, dims, mat, edge=0.0):
    bpy.ops.mesh.primitive_cube_add(size=1, location=loc)
    obj = bpy.context.object
    obj.dimensions = dims
    bpy.ops.object.transform_apply(location=False, rotation=False, scale=True)
    finish(obj, name, mat)
    if edge:
        bevel(obj, edge)
    return obj


def cylinder(name, loc, radius, depth, mat, edge=0.0, vertices=96):
    """Cylinder along Y, with identity local rotation."""
    bpy.ops.mesh.primitive_cylinder_add(
        vertices=vertices, radius=radius, depth=depth,
        location=loc, rotation=(math.pi / 2, 0, 0))
    obj = bpy.context.object
    bpy.ops.object.transform_apply(location=False, rotation=True, scale=True)
    finish(obj, name, mat)
    for face in obj.data.polygons:
        face.use_smooth = len(face.vertices) == 4
    if edge:
        bevel(obj, edge)
    return obj


def mesh_object(name, vertices, faces, mat, smooth=False, origin=None):
    """Vertices are supplied in world space; store sensible local coordinates."""
    if origin is None:
        origin = tuple(
            (min(v[k] for v in vertices) + max(v[k] for v in vertices)) / 2
            for k in range(3))
    origin = Vector(origin)
    local_vertices = [tuple(Vector(v) - origin) for v in vertices]
    mesh = bpy.data.meshes.new(name + " mesh")
    mesh.from_pydata(local_vertices, [], faces)
    mesh.update()

    bm = bmesh.new()
    bm.from_mesh(mesh)
    bmesh.ops.recalc_face_normals(bm, faces=list(bm.faces))
    bm.to_mesh(mesh)
    bm.free()

    obj = bpy.data.objects.new(name, mesh)
    bpy.context.collection.objects.link(obj)
    obj.location = origin
    finish(obj, name, mat)
    for face in mesh.polygons:
        face.use_smooth = smooth
    return obj


def lathe(name, cx, cz, profile, mat, segments=192):
    """Closed section revolved around Y. Profile contains (radius, world Y)."""
    vertices, faces, rows = [], [], []
    for radius, y in profile:
        if radius == 0:
            rows.append([len(vertices)])
            vertices.append((cx, y, cz))
        else:
            row = []
            for j in range(segments):
                a = math.tau * j / segments
                row.append(len(vertices))
                vertices.append((cx + radius * math.cos(a), y,
                                 cz + radius * math.sin(a)))
            rows.append(row)

    for i, row in enumerate(rows):
        nxt = rows[(i + 1) % len(rows)]
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

    ym = (min(p[1] for p in profile) + max(p[1] for p in profile)) / 2
    return mesh_object(name, vertices, faces, mat, True, (cx, ym, cz))


def ring(name, x, z, outer, inner, yf, yb, mat, segments=160):
    return lathe(name, x, z,
                 [(outer, yf), (inner, yf), (inner, yb), (outer, yb)],
                 mat, segments)


def subtract(obj, cutter):
    bpy.context.view_layer.update()
    mod = obj.modifiers.new("Actual opening", 'BOOLEAN')
    mod.operation = 'DIFFERENCE'
    mod.object = cutter
    apply_modifier(obj, mod)
    bpy.data.objects.remove(cutter, do_unlink=True)


def pivot_at(obj, point):
    """Move only the origin. All moving roots keep machine-aligned axes."""
    bpy.context.view_layer.update()
    old_world = obj.matrix_world.copy()
    new_world = Matrix.Translation(Vector(point))
    obj.data.transform(new_world.inverted() @ old_world)
    obj.matrix_world = new_world
    bpy.context.view_layer.update()


def parent_keep(obj, parent):
    bpy.context.view_layer.update()
    world = obj.matrix_world.copy()
    obj.parent = parent
    obj.matrix_parent_inverse = Matrix.Identity(4)
    obj.matrix_basis = parent.matrix_world.inverted() @ world
    bpy.context.view_layer.update()
    return obj


def text(name, body, loc, size, mat, align='LEFT', parent=None):
    data = bpy.data.curves.new(name + " lettering", 'FONT')
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


def tube(name, points, radius, mat, parent=None):
    data = bpy.data.curves.new(name + " curve", 'CURVE')
    data.dimensions = '3D'
    data.bevel_depth = radius
    data.bevel_resolution = 2
    spline = data.splines.new('POLY')
    spline.points.add(len(points) - 1)
    for dst, src in zip(spline.points, points):
        dst.co = (*src, 1.0)
    obj = bpy.data.objects.new(name, data)
    bpy.context.collection.objects.link(obj)
    finish(obj, name, mat)
    # Give the curve a useful origin as well.
    p = Vector(points[0])
    obj.data.transform(Matrix.Translation(-p))
    obj.location = p
    if parent is not None:
        parent_keep(obj, parent)
    return obj


def extruded_outline(name, outline_xy, z0, z1, mat):
    n = len(outline_xy)
    vertices = [(x, y, z0) for x, y in outline_xy]
    vertices += [(x, y, z1) for x, y in outline_xy]
    faces = [tuple(reversed(range(n))), tuple(range(n, 2 * n))]
    for i in range(n):
        j = (i + 1) % n
        faces.append((i, j, n + j, n + i))
    return mesh_object(name, vertices, faces, mat)


# ---------------------------------------------------------------------------
# Hollow cabinet with real door and service openings
# ---------------------------------------------------------------------------

body = box("Body", (0, F + 0.010, 0.369),
           (W - 0.009, 0.020, 0.704), white)
body["label"] = "white washing machine cabinet"
subtract(body, cylinder("Door aperture cutter", (0, F, DZ),
                         0.208, 0.10, None))
subtract(body, cylinder("Service aperture cutter", (HX, F, HZ),
                         0.0675, 0.10, None))
bevel(body, 0.0022, 4)
pivot_at(body, (0, 0, H / 2))
body["cabinet_dimensions_m"] = [W, D, H]
body["reference"] = "Electrolux PerfectCare front-loading washer"

for side in (-1, 1):
    name = "Left cabinet side" if side < 0 else "Right cabinet side"
    side_obj = box(name, (side * (W / 2 - 0.006), 0.008, 0.426),
                   (0.012, D - 0.016, 0.802), white)
    for row in range(8):
        cutter = box("Pressed channel cutter",
                     (side * (W / 2 + 0.001), 0.016, 0.111 + row * 0.087),
                     (0.009, 0.454, 0.028), None, 0.004)
        apply_modifier(cutter, cutter.modifiers[0])
        subtract(side_obj, cutter)
    bevel(side_obj, 0.0016, 3)

box("Cabinet rear", (0, D / 2 - 0.007, 0.422),
    (W - 0.022, 0.014, 0.802), white, 0.002)
box("Internal base", (0, 0.004, 0.021),
    (W - 0.027, D - 0.027, 0.012), dark, 0.002)
box("Top lid seam", (0, 0, 0.829),
    (W - 0.006, D - 0.006, 0.002), rubber, 0.0005)
box("Top lid", (0, 0, 0.839),
    (W, D, 0.016), white, 0.0025)
box("Lower front return", (0, F + 0.005, 0.020),
    (W - 0.023, 0.012, 0.009), white, 0.0015)

for x in (-0.238, 0.238):
    for y in (-0.245, 0.245):
        bpy.ops.mesh.primitive_cylinder_add(
            vertices=40, radius=0.020, depth=0.018,
            location=(x, y, 0.009))
        foot = finish(bpy.context.object, "Adjustable rubber foot", rubber)
        bevel(foot, 0.002)

box("White fascia lower bridge", (0, F + 0.003, 0.731),
    (W - 0.009, 0.015, 0.025), white, 0.002)
box("Electronics enclosure", (0.115, F + 0.037, 0.790),
    (0.353, 0.064, 0.092), ivory, 0.003)

# Drawer opening is genuinely hollow.
for x in (-0.289, -0.070):
    box("Drawer housing jamb", (x, -0.133, 0.785),
        (0.007, 0.354, 0.093), ivory, 0.001)
box("Drawer housing floor", (-0.180, -0.133, 0.739),
    (0.215, 0.354, 0.004), ivory)
box("Drawer housing roof", (-0.180, -0.133, 0.831),
    (0.215, 0.354, 0.004), ivory)
box("Drawer housing rear", (-0.180, 0.047, 0.785),
    (0.215, 0.006, 0.095), dark)


# ---------------------------------------------------------------------------
# Fascia: left selector area, right display and bottom touch strip
# ---------------------------------------------------------------------------

control = box("ControlPanel", (0.112, F + 0.0005, 0.792),
              (0.361, 0.006, 0.086), panel_mat, 0.0008)
control["label"] = "programme and touch control panel"
display = box("Display", (0.158, F - 0.0030, 0.802),
              (0.126, 0.001, 0.049), screen_mat, 0.0004)
display["label"] = "digital wash display"

KX, KZ = -0.004, 0.800
cylinder("Selector silver bezel", (KX, F - 0.0050, KZ),
         0.0280, 0.004, chrome, 0.0006)
knob = cylinder("ProgramKnob", (KX, F - 0.0110, KZ),
                0.0255, 0.011, black, 0.0012)
knob["label"] = "wash programme selector"
parent_keep(box("Selector index", (KX, F - 0.0167, KZ + 0.0215),
                (0.0011, 0.0004, 0.004), pale, 0.00015), knob)

left_programs = [
    "Anti-Allergy", "Duvet", "Denim",
    "Sport", "Outdoor", "Rapid 20 min"
]
right_programs = [
    "Eco 40-60", "Cottons", "Synthetics",
    "Delicates", "Wool / Silk", "FreshScent"
]
for i in range(6):
    z = 0.828 - i * 0.0118
    text("Programme left %02d" % i, left_programs[i],
         (-0.065, F - 0.0028, z), 0.0038, pale)
    text("Programme right %02d" % i, right_programs[i],
         (0.083, F - 0.0028, z), 0.0038, pale, 'RIGHT')

text("Temperature display", "60°", (0.101, F - 0.0037, 0.805),
     0.014, digits)
text("Time remaining display", "1:50", (0.218, F - 0.0037, 0.805),
     0.016, digits, 'RIGHT')
text("Spin speed display", "1200", (0.101, F - 0.0037, 0.785),
     0.011, digits)
text("SteamCare heading", "SteamCare System",
     (0.244, F - 0.0028, 0.828), 0.0046, pale, 'CENTER')
text("Temperature heading", "Temperature",
     (0.098, F - 0.0037, 0.823), 0.0031, pale)

keys = ["Prewash", "Stains", "Extra Rinse", "Soft Plus", "Plus Steam", "Pods"]
for i, caption in enumerate(keys):
    x = 0.103 + i * 0.031
    box("Touch divider " + caption, (x - 0.015, F - 0.0028, 0.759),
        (0.0003, 0.0002, 0.013), pale)
    text("Touch legend " + caption, caption,
         (x, F - 0.0030, 0.7575), 0.0034, pale, 'CENTER')
    box("Touch indicator " + caption, (x, F - 0.0029, 0.765),
        (0.003, 0.0002, 0.0006), pale)

sx, sz = 0.261, 0.800
for x in (sx - 0.012, sx + 0.012):
    box("Start pause outline side", (x, F - 0.0029, sz),
        (0.0004, 0.0002, 0.031), pale)
for z in (sz - 0.0155, sz + 0.0155):
    box("Start pause outline end", (sx, F - 0.0029, z),
        (0.024, 0.0002, 0.0004), pale)
text("Start pause icon", "> II", (sx, F - 0.0032, sz - 0.0025),
     0.0065, pale, 'CENTER')
box("Power key", (0.104, F - 0.004, 0.738),
    (0.023, 0.003, 0.006), ivory, 0.002)
text("Power key caption", "On/Off", (0.104, F - 0.0056, 0.726),
     0.0043, ink, 'CENTER')


# ---------------------------------------------------------------------------
# Detergent drawer
# ---------------------------------------------------------------------------

drawer = box("DetergentDrawer", (-0.180, F + 0.003, 0.792),
             (0.217, 0.012, 0.085), white, 0.0018)
drawer["label"] = "detergent dosing drawer"
# For this purely translational part, use the rear slide centre as origin.
pivot_at(drawer, (-0.180, 0.020, 0.747))
drawer["motion"] = '{"translate": [0, -0.25, 0]}'

def dp(obj):
    return parent_keep(obj, drawer)

dp(box("Drawer underside finger recess", (-0.180, F + 0.005, 0.748),
       (0.141, 0.015, 0.009), dark, 0.003))
dp(box("Drawer pull lip", (-0.180, F - 0.0035, 0.751),
       (0.158, 0.008, 0.006), white, 0.002))
dp(box("Drawer tray floor", (-0.180, -0.140, 0.746),
       (0.202, 0.318, 0.005), ivory, 0.001))
for x in (-0.278, -0.082):
    dp(box("Drawer tray side", (x, -0.140, 0.775),
           (0.005, 0.318, 0.058), ivory, 0.001))
for y in (-0.296, 0.016):
    dp(box("Drawer tray end", (-0.180, y, 0.775),
           (0.201, 0.005, 0.058), ivory, 0.001))
dp(box("Main wash divider", (-0.159, -0.139, 0.770),
       (0.004, 0.304, 0.046), ivory, 0.001))
dp(box("Softener compartment wall", (-0.218, -0.196, 0.770),
       (0.114, 0.004, 0.046), ivory, 0.001))
dp(box("Prewash compartment wall", (-0.119, -0.055, 0.770),
       (0.075, 0.004, 0.046), ivory, 0.001))
dp(box("Green dosing insert", (-0.219, -0.043, 0.782),
       (0.098, 0.100, 0.009), green, 0.004))
dp(box("Green insert dosing well", (-0.219, -0.043, 0.787),
       (0.072, 0.072, 0.0015), dark, 0.005))
dp(box("Liquid detergent insert", (-0.219, -0.143, 0.771),
       (0.097, 0.072, 0.010), ivory, 0.004))

dp(box("Brand emblem square", (-0.181, F - 0.0033, 0.809),
       (0.017, 0.0005, 0.017), ink, 0.0004))
dp(cylinder("Brand emblem circle", (-0.181, F - 0.0037, 0.809),
            0.0071, 0.00025, white, vertices=48))
dp(box("Brand emblem bar", (-0.181, F - 0.0039, 0.809),
       (0.0145, 0.00015, 0.0026), ink))
text("Electrolux wordmark", "Electrolux",
     (-0.181, F - 0.0034, 0.789), 0.010, ink, 'CENTER', drawer)
text("Drawer product line", "PERFECTCARE 700 | UniversalDose | 9 kg",
     (-0.180, F - 0.0034, 0.764), 0.0038, ink, 'CENTER', drawer)


# ---------------------------------------------------------------------------
# Door aperture, bellows and drum
# ---------------------------------------------------------------------------

lathe("Enamel aperture shoulder", 0, DZ,
      [(0.265, F + 0.001), (0.257, F - 0.0015),
       (0.216, F - 0.002), (0.207, F + 0.005),
       (0.207, F + 0.018), (0.262, F + 0.012)], white)

lathe("Rubber door bellows", 0, DZ,
      [(0.210, F + 0.009), (0.202, F - 0.001),
       (0.189, F + 0.006), (0.183, F + 0.022),
       (0.190, F + 0.035), (0.185, F + 0.047),
       (0.197, F + 0.063), (0.204, F + 0.043),
       (0.211, F + 0.022)], rubber)

ring("Drum front rolled rim", 0, DZ, 0.198, 0.189,
     F + 0.063, F + 0.073, steel)
ring("Stainless drum barrel", 0, DZ, 0.199, 0.196,
     F + 0.070, 0.226, steel)
cylinder("Drum rear plate", (0, 0.230, DZ),
         0.196, 0.007, steel, 0.001)
lathe("Drum back pressed concentric relief", 0, DZ,
      [(0.182, 0.225), (0.169, 0.211), (0.152, 0.209),
       (0.142, 0.221), (0.079, 0.221), (0.065, 0.203),
       (0.047, 0.203), (0.044, 0.225)], steel)
cylinder("Drum central hub", (0, 0.207, DZ),
         0.038, 0.016, steel, 0.004)

# Dark small discs just inside the metal surface read as drum perforations.
vertices, faces = [], []
for row in range(24):
    y = F + 0.083 + row * 0.0185
    for j in range(84):
        a = math.tau * (j + 0.5 * (row % 2)) / 84
        centre = Vector((0.19575 * math.cos(a), y,
                         DZ + 0.19575 * math.sin(a)))
        tangent = Vector((-math.sin(a), 0, math.cos(a)))
        start = len(vertices)
        for k in range(6):
            t = math.tau * k / 6
            v = centre + 0.00125 * (
                math.cos(t) * tangent + Vector((0, math.sin(t), 0)))
            vertices.append(tuple(v))
        faces.append(tuple(start + k for k in range(6)))

# Perforated rear plate as well, not a featureless mirrored disc.
for row in range(7):
    radius = 0.087 + row * 0.0115
    count = 40 + row * 8
    for j in range(count):
        a = math.tau * (j + 0.5 * (row % 2)) / count
        cx, cz = radius * math.cos(a), DZ + radius * math.sin(a)
        start = len(vertices)
        for k in range(6):
            t = math.tau * k / 6
            vertices.append((cx + 0.00115 * math.cos(t), 0.2078,
                             cz + 0.00115 * math.sin(t)))
        faces.append(tuple(start + k for k in range(6)))
mesh_object("Drum perforation pattern", vertices, faces, dark)

for i in range(3):
    a = -math.pi / 2 + i * math.tau / 3
    paddle = box("Drum lifting paddle %d" % (i + 1),
                 (0.180 * math.cos(a), -0.022,
                  DZ + 0.180 * math.sin(a)),
                 (0.035, 0.337, 0.025), ivory, 0.009)
    # Local Z is the radial thickness; local X is the tangential width.
    paddle.rotation_euler[1] = math.pi / 2 - a


# ---------------------------------------------------------------------------
# Door: flatter perimeter, broad ribbed annulus, thin glass bowl
# ---------------------------------------------------------------------------

door = lathe("Door", 0, DZ,
             [(0.251, F + 0.006),
              (0.257, F - 0.002),
              (0.257, F - 0.011),
              (0.252, F - 0.017),
              (0.244, F - 0.020),
              (0.226, F - 0.022),
              (0.220, F - 0.021),
              (0.174, F - 0.012),
              (0.171, F - 0.003),
              (0.177, F + 0.010),
              (0.244, F + 0.010)], black, 256)
door["label"] = "left hinged loading door"
pivot_at(door, (-0.232, F + 0.004, DZ))
door["motion"] = '{"rotate": {"axis": "Z", "degrees": -105}}'

def door_part(obj):
    return parent_keep(obj, door)

door_part(lathe("Door satin ribbed annulus", 0, DZ,
                [(0.225, F - 0.0223), (0.219, F - 0.0222),
                 (0.181, F - 0.0143), (0.175, F - 0.009),
                 (0.177, F - 0.006), (0.225, F - 0.019)],
                graphite, 256))

vertices, faces = [], []
for j in range(800):
    a = math.tau * j / 800
    half_width = 0.00058
    start = len(vertices)
    for r, angle in ((0.182, a - half_width), (0.219, a - half_width),
                     (0.219, a + half_width), (0.182, a + half_width)):
        y = F - 0.0143 - (r - 0.181) * (0.0079 / 0.038) - 0.00007
        vertices.append((r * math.cos(angle), y,
                         DZ + r * math.sin(angle)))
    faces.append((start, start + 1, start + 2, start + 3))
door_part(mesh_object("Fine radial door moulding", vertices, faces, groove))

door_part(lathe("Thin glass retaining trim", 0, DZ,
                [(0.177, F - 0.010), (0.175, F - 0.013),
                 (0.173, F - 0.012), (0.1715, F - 0.004),
                 (0.173, F - 0.002)], chrome, 256))
door_part(ring("Glass perimeter seal", 0, DZ, 0.172, 0.169,
               F - 0.004, F + 0.003, rubber))

# A continuous closed 2.5 mm glass vessel, not a solid glass lens.
# Its central portion is broad and nearly flat; curvature is near the rim.
door_glass = lathe("DoorGlass", 0, DZ,
                   [(0.172, F - 0.004),
                    (0.166, F - 0.002),
                    (0.157, F + 0.005),
                    (0.147, F + 0.022),
                    (0.137, F + 0.040),
                    (0.123, F + 0.050),
                    (0.092, F + 0.053),
                    (0.045, F + 0.054),
                    (0, F + 0.0545),
                    (0, F + 0.0570),
                    (0.045, F + 0.0565),
                    (0.092, F + 0.0555),
                    (0.124, F + 0.0525),
                    (0.139, F + 0.0425),
                    (0.1495, F + 0.024),
                    (0.1595, F + 0.007),
                    (0.167, F + 0.0005),
                    (0.172, F - 0.0015)], glass_mat, 256)
door_glass["label"] = "clear recessed door glass"
door_part(door_glass)

# Handle is concealed behind the right edge, not a bar over the glass.
door_part(box("DoorHandle", (0.235, F + 0.008, DZ + 0.023),
              (0.020, 0.021, 0.092), black, 0.007))
door_part(box("Door handle finger pocket", (0.220, F + 0.012, DZ + 0.023),
              (0.013, 0.017, 0.068), dark, 0.005))
door_part(box("Door latch tongue", (0.224, F + 0.027, DZ),
              (0.012, 0.028, 0.013), ivory, 0.002))
box("Door latch receiver", (0.224, F + 0.007, DZ),
    (0.019, 0.009, 0.025), dark, 0.002)

for z in (DZ - 0.046, DZ + 0.046):
    box("Fixed loading door hinge", (-0.232, F + 0.014, z),
        (0.021, 0.026, 0.024), steel, 0.002)
    door_part(box("Moving loading door hinge leaf",
                  (-0.222, F + 0.004, z),
                  (0.030, 0.012, 0.019), steel, 0.002))

box("Wool care badge", (0.239, F - 0.0006, 0.681),
    (0.043, 0.001, 0.025), blue, 0.0005)
text("Wool badge symbols", "O  O",
     (0.239, F - 0.0012, 0.683), 0.010, pale, 'CENTER')
text("Wool badge lettering", "WOOLMARK",
     (0.239, F - 0.0012, 0.672), 0.0035, pale, 'CENTER')


# ---------------------------------------------------------------------------
# Service recess and fixed pump housing
# ---------------------------------------------------------------------------

ring("Hatch perimeter seam", HX, HZ, 0.0674, 0.0657,
     F + 0.0006, F + 0.010, dark)
ring("Service opening enamel return", HX, HZ, 0.0688, 0.0673,
     F + 0.001, F + 0.015, white)
ring("Service recess moulded wall", HX, HZ, 0.0670, 0.0635,
     F + 0.015, F + 0.086, ivory)
back = cylinder("Service recess back", (HX, F + 0.089, HZ),
                0.0635, 0.006, ivory)
subtract(back, cylinder("Pump bore cutter", (PX, F + 0.089, PZ),
                        0.0355, 0.05, None))

ring("Pump socket body", PX, PZ, 0.041, 0.0345,
     F + 0.053, F + 0.203, ivory)
ring("Pump socket dark inner bore", PX, PZ, 0.0347, 0.0335,
     F + 0.065, F + 0.197, dark)
ring("Pump socket flange", PX, PZ, 0.043, 0.035,
     F + 0.049, F + 0.056, white)
cylinder("Pump housing rear", (PX, F + 0.211, PZ),
         0.039, 0.008, dark, 0.002)

# Red emergency release and the two hinge-side screws.
box("Emergency release tab", (HX + 0.042, F + 0.048, HZ + 0.009),
    (0.008, 0.005, 0.043), red, 0.001)
for z in (HZ - 0.025, HZ + 0.031):
    box("Service hinge mounting boss", (HX + 0.051, F + 0.036, z),
        (0.015, 0.022, 0.014), ivory, 0.002)
    cylinder("Service hinge screw", (HX + 0.051, F + 0.024, z),
             0.0042, 0.002, steel, 0.0003, 40)
    for angle in (0, math.pi / 2):
        slot = box("Service screw cross slot",
                   (HX + 0.051, F + 0.0228, z),
                   (0.005, 0.0002, 0.00065), dark)
        slot.rotation_euler[1] = angle


# ---------------------------------------------------------------------------
# Removable pump filter: cap, seal, continuous thread and open basket
# ---------------------------------------------------------------------------

pump = cylinder("PumpFilter", (PX, F + 0.047, PZ),
                0.037, 0.009, ivory, 0.0012)
pump["label"] = "drain pump filter"
pivot_at(pump, (PX, F + 0.062, PZ))
# Viewed from the front, negative Y rotation is counterclockwise.
pump["motion"] = (
    '{"rotate": {"axis": "Y", "degrees": -720}, '
    '"translate": [0, -0.16, 0]}'
)

def pp(obj):
    return parent_keep(obj, pump)

pp(ring("Filter cap raised perimeter", PX, PZ, 0.0354, 0.0325,
        F + 0.0405, F + 0.045, white))
pp(box("Filter vertical turning grip", (PX, F + 0.0345, PZ),
       (0.008, 0.016, 0.061), white, 0.0018))
for z in (PZ - 0.018, PZ + 0.018):
    pp(box("Filter grip notch", (PX, F + 0.0262, z),
           (0.0042, 0.0005, 0.007), ivory, 0.0005))
pp(ring("Filter rubber sealing ring", PX, PZ, 0.0346, 0.030,
        F + 0.052, F + 0.055, rubber))
pp(ring("Filter threaded neck", PX, PZ, 0.032, 0.027,
        F + 0.055, F + 0.080, ivory))

thread_points = []
for j in range(433):
    t = j / 432
    a = math.tau * 3 * t
    thread_points.append((PX + 0.0327 * math.cos(a),
                          F + 0.058 + 0.019 * t,
                          PZ + 0.0327 * math.sin(a)))
tube("Filter continuous helical thread", thread_points, 0.0011, ivory, pump)

for i in range(5):
    y = F + 0.082 + i * 0.017
    pp(ring("Filter basket hoop %d" % i, PX, PZ,
            0.029, 0.026, y, y + 0.0028, ivory, 96))
for i in range(10):
    a = math.tau * i / 10
    rail = box("Filter basket rail %02d" % i,
               (PX + 0.0273 * math.cos(a), F + 0.118,
                PZ + 0.0273 * math.sin(a)),
               (0.003, 0.074, 0.003), ivory, 0.0006)
    pp(rail)
pp(cylinder("Filter basket rear end", (PX, F + 0.156, PZ),
            0.028, 0.003, ivory, 0.0005))


# ---------------------------------------------------------------------------
# Folding blue drainage guide
# ---------------------------------------------------------------------------

# The guide is stored upright, clear of both the cap and closed hatch.
# Rotation about local X lowers it forward without passing below the floor.
guide_pivot = Vector((PX, F + 0.014, 0.029))
deployed_outline = [
    (-0.030,  0.000,  0.002),
    ( 0.030,  0.000,  0.002),
    ( 0.030, -0.014,  0.001),
    ( 0.020, -0.042, -0.004),
    ( 0.012, -0.049, -0.005),
    (-0.012, -0.049, -0.005),
    (-0.020, -0.042, -0.004),
    (-0.030, -0.014,  0.001)
]
closed_rotation = Matrix.Rotation(math.radians(-88), 4, 'X')
closed_vertices = [
    tuple(guide_pivot + closed_rotation @ Vector(p))
    for p in deployed_outline
]
guide = mesh_object("BlueDrainGuide", closed_vertices,
                    [tuple(range(len(closed_vertices)))],
                    blue, origin=guide_pivot)
guide["label"] = "folding blue drain guide"
solid = guide.modifiers.new("Moulded flap thickness", 'SOLIDIFY')
solid.thickness = 0.0016
bevel(guide, 0.0008, 3)
guide["motion"] = '{"rotate": {"axis": "X", "degrees": 88}}'

for side in (-1, 1):
    local_points = [
        (side * 0.029, -0.002, 0.004),
        (side * 0.028, -0.014, 0.003),
        (side * 0.019, -0.041, -0.002)
    ]
    points = [tuple(guide_pivot + closed_rotation @ Vector(p))
              for p in local_points]
    tube("Blue guide raised side lip", points, 0.0012, blue, guide)
    box("Drain flap fixed pivot support",
        (PX + side * 0.031, F + 0.019, 0.030),
        (0.006, 0.009, 0.009), ivory, 0.001)


# ---------------------------------------------------------------------------
# Flush right-hinged service hatch and curved, ribbed offset hinge arm
# ---------------------------------------------------------------------------

hatch = cylinder("FilterHatch", (HX, F + 0.0036, HZ),
                 0.0658, 0.006, white, 0.0008, 160)
hatch["label"] = "right hinged pump access hatch"
hinge_point = (HX + 0.064, F + 0.007, HZ)
pivot_at(hatch, hinge_point)
hatch["motion"] = '{"rotate": {"axis": "Z", "degrees": 105}}'

def hp(obj):
    return parent_keep(obj, hatch)

hp(ring("Hatch inner reinforcing rim", HX, HZ,
        0.0600, 0.0578, F + 0.0068, F + 0.0100, ivory))
hp(box("Hatch latch clip", (HX - 0.055, F + 0.013, HZ + 0.008),
       (0.006, 0.012, 0.011), ivory, 0.001))

# A C-shaped web folds into the recess when shut. When opened, it becomes
# the projecting ribbed arm visible between the housing and white cover.
hinge_outline = [
    (HX + 0.042, F + 0.007),
    (HX + 0.046, F + 0.007),
    (HX + 0.047, F + 0.020),
    (HX + 0.052, F + 0.026),
    (HX + 0.060, F + 0.026),
    (HX + 0.063, F + 0.018),
    (HX + 0.063, F + 0.007),
    (HX + 0.066, F + 0.007),
    (HX + 0.066, F + 0.019),
    (HX + 0.062, F + 0.030),
    (HX + 0.050, F + 0.030),
    (HX + 0.043, F + 0.022)
]
web = extruded_outline("Hatch curved offset hinge web",
                       hinge_outline, HZ - 0.017, HZ + 0.017, ivory)
bevel(web, 0.0008, 2)
hp(web)

rib_path_xy = [
    (HX + 0.043, F + 0.008),
    (HX + 0.044, F + 0.021),
    (HX + 0.051, F + 0.0285),
    (HX + 0.061, F + 0.0285),
    (HX + 0.0645, F + 0.019),
    (HX + 0.0645, F + 0.008)
]
for i in range(5):
    z = HZ - 0.014 + i * 0.007
    tube("Hatch hinge reinforcing rib %d" % i,
         [(x, y, z) for x, y in rib_path_xy],
         0.00125, white, hatch)

bpy.ops.mesh.primitive_cylinder_add(
    vertices=40, radius=0.002, depth=0.043,
    location=hinge_point)
finish(bpy.context.object, "Fixed service hatch hinge pin", steel)


# ---------------------------------------------------------------------------
# Rear service details
# ---------------------------------------------------------------------------

box("Rear service cover", (0, D / 2 - 0.0007, 0.414),
    (0.452, 0.0014, 0.622), white, 0.002)
for x in (-0.211, 0.211):
    for z in (0.119, 0.708):
        cylinder("Rear cover fastener", (x, D / 2 - 0.0001, z),
                 0.0037, 0.0002, steel, vertices=40)


# ---------------------------------------------------------------------------
# Finalize in the CLOSED state
# ---------------------------------------------------------------------------

# Convert lettering and small tube details to meshes so downstream templates
# that enumerate only meshes still retain the captions, thread and hinge ribs.
bpy.ops.object.select_all(action='DESELECT')
for obj in list(bpy.context.scene.objects):
    if obj.type in {'FONT', 'CURVE'}:
        bpy.ops.object.select_all(action='DESELECT')
        obj.select_set(True)
        bpy.context.view_layer.objects.active = obj
        bpy.ops.object.convert(target='MESH')

for obj in bpy.context.scene.objects:
    if "label" not in obj:
        obj["label"] = obj.name.replace("_", " ").lower()

# Machine-aligned roots are crucial: Y is the pump thread axis, Z is the
# vertical door/hatch hinge axis, and X is the drainage flap hinge axis.
for obj in (door, drawer, hatch, pump, guide):
    assert obj.parent is None
    assert max(abs(a) for a in obj.rotation_euler) < 1e-6  # patched by hand: Euler has no .length
    assert "motion" in obj

assert door_glass.parent == door
assert bpy.data.objects["DoorHandle"].parent == door

bpy.context.view_layer.update()
bpy.ops.object.select_all(action='DESELECT')
body.select_set(True)
bpy.context.view_layer.objects.active = body

import sys
bpy.ops.wm.save_as_mainfile(filepath=sys.argv[sys.argv.index("--") + 1])
