import bpy
import math
from mathutils import Vector

# Clear the entire scene, including hidden objects.
bpy.ops.object.select_all(action='SELECT')
bpy.ops.object.delete(use_global=False)
for obj in list(bpy.data.objects):
    bpy.data.objects.remove(obj, do_unlink=True)

bpy.context.scene.unit_settings.system = 'METRIC'
bpy.context.scene.unit_settings.scale_length = 1.0

# Dimensions in metres. Front is -Y.
W, D, H = 0.597, 0.636, 0.847
FRONT = -D / 2
DOOR_Z = 0.457


# ---------------------------------------------------------------------------
# Utilities
# ---------------------------------------------------------------------------

def material(name, color, metallic=0.0, roughness=0.4,
             transmission=0.0, emission=0.0):
    mat = bpy.data.materials.new(name)
    mat.use_nodes = True
    bsdf = next(n for n in mat.node_tree.nodes
                if n.type == "BSDF_PRINCIPLED")
    bsdf.inputs["Base Color"].default_value = (*color, 1.0)
    bsdf.inputs["Metallic"].default_value = metallic
    bsdf.inputs["Roughness"].default_value = roughness
    if transmission:
        bsdf.inputs["Transmission Weight"].default_value = transmission
        bsdf.inputs["IOR"].default_value = 1.47
    if emission:
        bsdf.inputs["Emission Color"].default_value = (*color, 1.0)
        bsdf.inputs["Emission Strength"].default_value = emission
    return mat


white = material("Porcelain white enamel", (0.83, 0.85, 0.86), roughness=0.26)
plastic = material("White moulded plastic", (0.76, 0.79, 0.79), roughness=0.36)
black = material("Gloss black door surround", (0.009, 0.012, 0.015), roughness=0.20)
panel_mat = material("Black control fascia", (0.012, 0.017, 0.020), roughness=0.27)
rubber = material("Dark rubber", (0.034, 0.040, 0.042), roughness=0.72)
dark = material("Recess shadow", (0.012, 0.015, 0.017), roughness=0.83)
chrome = material("Chrome", (0.68, 0.73, 0.76), metallic=0.95, roughness=0.16)
steel = material("Stainless drum", (0.43, 0.48, 0.51), metallic=0.88, roughness=0.32)
glass = material("Smoked door glass", (0.13, 0.20, 0.23),
                 roughness=0.12, transmission=0.76)
blue = material("Pump filter blue grip", (0.035, 0.25, 0.57), roughness=0.35)
green = material("Drawer dosing insert green", (0.015, 0.37, 0.10), roughness=0.35)
ink = material("Printed charcoal", (0.055, 0.070, 0.075), roughness=0.55)
print_white = material("Light fascia printing", (0.69, 0.74, 0.75), roughness=0.55)
screen = material("Display smoked backing", (0.006, 0.013, 0.017), roughness=0.21)
digits = material("Display illuminated segments", (0.77, 0.90, 0.94),
                  roughness=0.3, emission=0.55)


def finish(obj, name, mat=None, label=None):
    obj.name = name
    obj["label"] = label or name.replace("_", " ").lower()
    if mat:
        obj.data.materials.append(mat)
    return obj


def bevel(obj, amount=0.002, segments=3):
    mod = obj.modifiers.new("Soft manufactured edges", 'BEVEL')
    mod.width = amount
    mod.segments = segments
    return mod


def apply_modifier(obj, mod):
    bpy.context.view_layer.objects.active = obj
    bpy.ops.object.modifier_apply(modifier=mod.name)


def box(name, loc, dims, mat, radius=0.0, label=None):
    bpy.ops.mesh.primitive_cube_add(size=1, location=loc)
    obj = bpy.context.object
    obj.dimensions = dims
    bpy.ops.object.transform_apply(location=False, rotation=False, scale=True)
    finish(obj, name, mat, label)
    if radius:
        bevel(obj, radius)
    return obj


def cylinder(name, loc, radius, depth, mat, edge=0.0, vertices=96):
    # Bake the orientation so local Y remains the machine's depth axis.
    bpy.ops.mesh.primitive_cylinder_add(
        vertices=vertices, radius=radius, depth=depth,
        location=loc, rotation=(math.pi / 2, 0, 0))
    obj = bpy.context.object
    bpy.ops.object.transform_apply(location=False, rotation=True, scale=True)
    finish(obj, name, mat)
    for poly in obj.data.polygons:
        poly.use_smooth = len(poly.vertices) == 4
    if edge:
        bevel(obj, edge)
    return obj


def lathe(name, cx, cz, profile, mat, segments=160):
    """Closed radial profile revolved around an axis parallel to Y.
    Each profile point is (radius, absolute Y).
    """
    verts, faces = [], []
    for radius, y in profile:
        for j in range(segments):
            a = 2 * math.pi * j / segments
            verts.append((cx + radius * math.cos(a),
                          y, cz + radius * math.sin(a)))
    rows = len(profile)
    for k in range(rows):
        k2 = (k + 1) % rows
        for j in range(segments):
            j2 = (j + 1) % segments
            faces.append((k * segments + j,
                          k * segments + j2,
                          k2 * segments + j2,
                          k2 * segments + j))
    mesh = bpy.data.meshes.new(name + " mesh")
    mesh.from_pydata(verts, [], faces)
    mesh.update()
    obj = bpy.data.objects.new(name, mesh)
    bpy.context.collection.objects.link(obj)
    finish(obj, name, mat)
    for poly in mesh.polygons:
        poly.use_smooth = True
    return obj


def ring(name, cx, cz, outer, inner, y_front, y_back, mat):
    return lathe(name, cx, cz,
                 [(outer, y_front), (inner, y_front),
                  (inner, y_back), (outer, y_back)], mat)


def parent_keep(obj, parent):
    world = obj.matrix_world.copy()
    obj.parent = parent
    obj.matrix_world = world


def pivot_at(obj, world_position):
    # Objects used as assembly roots have identity rotation and scale.
    bpy.context.view_layer.update()
    p = Vector(world_position)
    delta = obj.matrix_world.inverted() @ p
    for vertex in obj.data.vertices:
        vertex.co -= delta
    obj.location = p
    bpy.context.view_layer.update()


def subtract(obj, cutter):
    mod = obj.modifiers.new("Machined opening", 'BOOLEAN')
    mod.operation = 'DIFFERENCE'
    mod.object = cutter
    apply_modifier(obj, mod)
    bpy.data.objects.remove(cutter, do_unlink=True)


def text(name, body, loc, size, mat, align='LEFT', parent=None):
    curve = bpy.data.curves.new(name + " lettering", type='FONT')
    curve.body = body
    curve.size = size
    curve.align_x = align
    curve.extrude = 0.000035
    obj = bpy.data.objects.new(name, curve)
    bpy.context.collection.objects.link(obj)
    obj.location = loc
    # Text's local +Z normal points toward -Y; local +Y points up.
    obj.rotation_euler = (math.pi / 2, 0, 0)
    finish(obj, name, mat)
    if parent:
        parent_keep(obj, parent)
    return obj


def join_objects(objects, name, label):
    bpy.ops.object.select_all(action='DESELECT')
    for obj in objects:
        obj.select_set(True)
    bpy.context.view_layer.objects.active = objects[0]
    bpy.ops.object.join()
    obj = bpy.context.object
    obj.name = name
    obj["label"] = label
    return obj


# ---------------------------------------------------------------------------
# Cabinet: an actual hollow shell, not a solid block behind the openings.
# The top and door establish the frontmost -0.318 m envelope.
# ---------------------------------------------------------------------------

front = box("Front enamel panel", (0, -0.279, 0.366),
            (W - 0.008, 0.024, 0.688), white)
cut = cylinder("Temporary door opening", (0, -0.281, DOOR_Z),
               0.210, 0.12, None)
subtract(front, cut)

HATCH_X, HATCH_Z = 0.190, 0.094
cut = cylinder("Temporary service opening", (HATCH_X, -0.279, HATCH_Z),
               0.0675, 0.12, None)
subtract(front, cut)
bevel(front, 0.0035, 4)

cabinet_parts = [front]
for side in (-1, 1):
    side_panel = box(
        "Left cabinet side" if side < 0 else "Right cabinet side",
        (side * (W / 2 - 0.010), 0.013, 0.427),
        (0.020, 0.600, 0.800), white)

    # Shallow pressed horizontal reinforcing recesses, as in the side photo.
    for row in range(8):
        cut = box("Temporary side pressing",
                  (side * (W / 2 + 0.001), 0.019, 0.110 + row * 0.087),
                  (0.011, 0.441, 0.029), None, 0.0045)
        apply_modifier(cut, cut.modifiers[0])
        subtract(side_panel, cut)
    bevel(side_panel, 0.003, 3)
    cabinet_parts.append(side_panel)

cabinet_parts.append(box("Cabinet back", (0, 0.307, 0.428),
                         (W - 0.035, 0.022, 0.799), white, 0.003))
cabinet_parts.append(box("Cabinet base", (0, 0.012, 0.028),
                         (W - 0.030, 0.585, 0.020), rubber, 0.003))

# Apply edge treatment before assembling the one required Body object.
for obj in cabinet_parts:
    for mod in list(obj.modifiers):
        apply_modifier(obj, mod)
body = join_objects(cabinet_parts, "Body", "white washing machine cabinet")
body["model"] = "Electrolux EW7F7649U2"
body["dimensions_m"] = [W, D, H]
body["capacity_kg"] = 9

box("Top lid seam", (0, 0, 0.825),
    (W - 0.004, D - 0.004, 0.004), rubber, 0.001)
box("Top lid", (0, 0, 0.8365), (W, D, 0.021),
    white, 0.005, "white top cover")

for x in (-0.238, 0.238):
    for y in (-0.244, 0.248):
        bpy.ops.mesh.primitive_cylinder_add(
            vertices=40, radius=0.025, depth=0.020, location=(x, y, 0.010))
        foot = finish(bpy.context.object,
                      "Foot_%s_%s" % (x, y), rubber, "adjustable foot")
        bevel(foot, 0.003)

box("Lower front plinth", (0, -0.287, 0.033),
    (W - 0.016, 0.009, 0.021), white, 0.003)

# Upper fascia: drawer aperture on the left, electronics on the right.
box("Upper fascia backing", (0.114, -0.272, 0.771),
    (0.359, 0.037, 0.124), white, 0.004)
box("Fascia lower white bridge", (0, -0.293, 0.720),
    (W - 0.009, 0.014, 0.034), white, 0.003)
box("Drawer left jamb", (-0.292, -0.214, 0.773),
    (0.009, 0.169, 0.112), white, 0.002)
box("Drawer right jamb", (-0.067, -0.172, 0.773),
    (0.010, 0.241, 0.112), plastic, 0.002)
box("Drawer cavity ceiling", (-0.181, -0.128, 0.826),
    (0.219, 0.325, 0.006), plastic, 0.001)
box("Drawer cavity rear", (-0.181, 0.041, 0.770),
    (0.219, 0.009, 0.110), dark)

control = box("ControlPanel", (0.111, -0.299, 0.783),
              (0.362, 0.011, 0.090), panel_mat, 0.002,
              "black control panel")

display = box("Display", (0.156, -0.3054, 0.792),
              (0.130, 0.0016, 0.059), screen, 0.001,
              "digital wash display")

text("Display temperature", "60°", (0.095, -0.3066, 0.798),
     0.014, digits)
text("Display time", "1:50", (0.211, -0.3066, 0.798),
     0.017, digits, 'RIGHT')
text("Display spin", "1200", (0.095, -0.3066, 0.774),
     0.013, digits)
text("SteamCare caption", "SteamCare System",
     (0.220, -0.306, 0.820), 0.006, print_white, 'CENTER')

knob_x, knob_z = -0.002, 0.792
cylinder("Program knob bezel", (knob_x, -0.306, knob_z),
         0.0298, 0.003, chrome, 0.0008)
knob = cylinder("ProgramKnob", (knob_x, -0.311, knob_z),
                0.027, 0.010, black, 0.002)
knob["label"] = "wash programme selector"
indicator = box("Knob position marker", (knob_x, -0.3162, knob_z + 0.023),
                (0.0012, 0.0005, 0.005), print_white, 0.0003)
parent_keep(indicator, knob)

left_programs = ["Anti-Allergy", "Down", "Denim", "Sport", "Outdoor", "Rapid 20min"]
right_programs = ["Eco 40-60", "Cottons", "Synthetics", "Delicates", "Wool/Silk", "FreshScent"]
for i, caption in enumerate(left_programs):
    text("Programme left %02d" % i, caption,
         (-0.066, -0.305, 0.822 - i * 0.011),
         0.0046, print_white)
for i, caption in enumerate(right_programs):
    text("Programme right %02d" % i, caption,
         (0.037, -0.305, 0.822 - i * 0.011),
         0.0046, print_white)

button_names = ["Prewash", "Stains", "Extra Rinse", "Soft Plus", "Plus Steam", "Pods"]
for i, caption in enumerate(button_names):
    x = 0.092 + i * 0.032
    box("Touch key " + caption, (x, -0.305, 0.746),
        (0.029, 0.001, 0.015), rubber, 0.0006)
    text("Touch caption " + caption, caption,
         (x, -0.306, 0.744), 0.004, print_white, 'CENTER')
box("Start pause button", (0.266, -0.305, 0.791),
    (0.024, 0.001, 0.039), rubber, 0.001)
text("Start pause symbol", "> ||", (0.266, -0.306, 0.788),
     0.007, print_white, 'CENTER')
text("On off caption", "On/Off", (0.100, -0.301, 0.717),
     0.0055, ink, 'CENTER')
box("Power button", (0.100, -0.302, 0.727),
    (0.027, 0.003, 0.006), plastic, 0.002)


# ---------------------------------------------------------------------------
# Detergent drawer, including the tray exposed by a 260 mm outward translation.
# ---------------------------------------------------------------------------

drawer = box("DetergentDrawer", (-0.181, -0.300, 0.778),
             (0.222, 0.020, 0.099), white, 0.003,
             "detergent dosing drawer")
pivot_at(drawer, (-0.181, -0.290, 0.736))
drawer["motion"] = '{"translate": [0, -0.26, 0]}'

def drawer_part(obj):
    parent_keep(obj, drawer)
    return obj

drawer_part(box("Drawer recessed finger pull", (-0.181, -0.300, 0.728),
                (0.129, 0.011, 0.009), rubber, 0.003))
drawer_part(box("Drawer pull lower lip", (-0.181, -0.308, 0.733),
                (0.150, 0.008, 0.008), white, 0.003))
drawer_part(box("Detergent tray floor", (-0.181, -0.127, 0.742),
                (0.207, 0.320, 0.006), plastic, 0.002))
for x in (-0.282, -0.080):
    drawer_part(box("Drawer tray side wall", (x, -0.127, 0.771),
                    (0.006, 0.319, 0.058), plastic, 0.002))
for y in (-0.282, 0.030):
    drawer_part(box("Drawer tray end wall", (-0.181, y, 0.771),
                    (0.206, 0.006, 0.058), plastic, 0.002))
drawer_part(box("Main wash compartment divider", (-0.160, -0.142, 0.766),
                (0.005, 0.274, 0.045), plastic, 0.002))
drawer_part(box("Softener compartment divider", (-0.181, -0.211, 0.766),
                (0.201, 0.006, 0.045), plastic, 0.002))
drawer_part(box("Prewash compartment divider", (-0.112, -0.035, 0.766),
                (0.092, 0.005, 0.045), plastic, 0.002))
drawer_part(box("Green dosing insert", (-0.220, -0.028, 0.778),
                (0.085, 0.104, 0.017), green, 0.009))
drawer_part(box("Green insert dispensing well", (-0.220, -0.034, 0.787),
                (0.060, 0.066, 0.003), dark, 0.010))
drawer_part(box("Liquid detergent insert", (-0.220, -0.145, 0.773),
                (0.079, 0.092, 0.014), rubber, 0.014))

text("Electrolux wordmark", "Electrolux", (-0.181, -0.3104, 0.787),
     0.011, ink, 'CENTER', drawer)
text("Electrolux emblem", "E", (-0.181, -0.3104, 0.806),
     0.017, ink, 'CENTER', drawer)
text("PerfectCare drawer caption", "PERFECTCARE 700 | UniversalDose | 9 kg",
     (-0.181, -0.3104, 0.746), 0.0042, ink, 'CENTER', drawer)


# ---------------------------------------------------------------------------
# Door opening, rubber bellows, and recessed stainless drum.
# ---------------------------------------------------------------------------

ring("Door opening enamel lip", 0, DOOR_Z,
     0.257, 0.208, -0.292, -0.279, white)
lathe("Rubber door bellows", 0, DOOR_Z,
      [(0.212, -0.289), (0.204, -0.298), (0.190, -0.286),
       (0.181, -0.259), (0.187, -0.235), (0.198, -0.241),
       (0.202, -0.265), (0.214, -0.274)], rubber)

# A ~69 litre cylindrical drum envelope.
ring("Stainless drum barrel", 0, DOOR_Z,
     0.200, 0.197, -0.235, 0.310, steel)
cylinder("Drum rear plate", (0, 0.298, DOOR_Z),
         0.197, 0.005, steel, 0.001)
ring("Drum rear concentric pressing", 0, DOOR_Z,
     0.151, 0.143, 0.292, 0.296, chrome)
cylinder("Drum rear hub", (0, 0.289, DOOR_Z),
         0.044, 0.012, steel, 0.004)

# Small dark discs on the interior steel surface suggest drum perforations.
verts, faces = [], []
for row in range(23):
    y = -0.216 + row * 0.0215
    for j in range(64):
        a = 2 * math.pi * (j + 0.5 * (row % 2)) / 64
        center = Vector((0.1966 * math.cos(a), y,
                         DOOR_Z + 0.1966 * math.sin(a)))
        tangent = Vector((-math.sin(a), 0, math.cos(a)))
        along = Vector((0, 1, 0))
        start = len(verts)
        for k in range(7):
            t = 2 * math.pi * k / 7
            p = center + 0.0019 * (math.cos(t) * tangent + math.sin(t) * along)
            verts.append(tuple(p))
        faces.append(tuple(start + k for k in range(7)))
mesh = bpy.data.meshes.new("Drum perforation mesh")
mesh.from_pydata(verts, [], faces)
mesh.update()
holes = bpy.data.objects.new("Drum perforations", mesh)
bpy.context.collection.objects.link(holes)
finish(holes, "Drum perforations", dark, "drum perforations")

for i in range(3):
    a = 2 * math.pi * i / 3
    lifter = box("Drum lifter %d" % (i + 1),
                 (0.178 * math.cos(a), 0.038,
                  DOOR_Z + 0.178 * math.sin(a)),
                 (0.024, 0.420, 0.036), plastic, 0.009)
    lifter.rotation_euler[1] = -a


# Door root is the black annular surround, with a left-side hinge origin.
door = lathe("Door", 0, DOOR_Z,
             [(0.251, -0.286), (0.253, -0.298),
              (0.246, -0.311), (0.234, FRONT),
              (0.211, -0.316), (0.181, -0.304),
              (0.175, -0.295), (0.179, -0.278),
              (0.227, -0.277), (0.245, -0.280)], black)
door["label"] = "left hinged loading door"
pivot_at(door, (-0.235, -0.279, DOOR_Z))
door["motion"] = '{"rotate": {"axis": "Z", "degrees": -105}}'

inner_rim = lathe("Door chrome inner ring", 0, DOOR_Z,
                  [(0.181, -0.303), (0.177, -0.307),
                   (0.172, -0.304), (0.171, -0.294),
                   (0.175, -0.289), (0.181, -0.294)], chrome)
parent_keep(inner_rim, door)

door_glass = lathe("DoorGlass", 0, DOORAE_Z if False else DOOR_Z,
                   [(0.173, -0.298), (0.160, -0.295),
                    (0.138, -0.281), (0.109, -0.260),
                    (0.070, -0.248), (0.001, -0.243),
                    (0.001, -0.238), (0.070, -0.243),
                    (0.110, -0.255), (0.141, -0.277),
                    (0.163, -0.289), (0.173, -0.292)], glass)
door_glass["label"] = "tinted door glass"
parent_keep(glass if False else door_glass, door)

# Fine circular moulding details rather than a flat featureless black disc.
for i, radius in enumerate((0.186, 0.190, 0.195, 0.201)):
    detail = ring("Door fine circular moulding %d" % i, 0, DOOR_Z,
                  radius + 0.00045, radius,
                  -0.306 - i * 0.0015, -0.305 - i * 0.0015, rubber)
    parent_keep(detail, door)

handle = box("DoorHandle", (0.222, -0.287, DOOR_Z + 0.017),
             (0.027, 0.021, 0.117), black, 0.009,
             "recessed door handle")
parent_keep(handle, door)
latch = box("Door latch tongue", (0.232, -0.258, DOOR_Z),
            (0.018, 0.020, 0.012), plastic, 0.002)
parent_keep(latch, door)

for z in (DOOR_Z - 0.052, DOOR_Z + 0.052):
    box("Door fixed hinge bracket", (-0.229, -0.270, z),
        (0.025, 0.022, 0.026), steel, 0.003)

# Small product badge visible at the upper right of the door.
box("Wool care badge", (0.239, -0.2925, 0.665),
    (0.044, 0.001, 0.026), blue, 0.001)
text("Wool care badge caption", "WOOL CARE",
     (0.239, -0.2932, 0.660), 0.0046, print_white, 'CENTER')


# ---------------------------------------------------------------------------
# Lower-right pump service compartment, outward-opening hatch, and filter.
# ---------------------------------------------------------------------------

ring("Service opening white lip", HATCH_X, HATCH_Z,
     0.0705, 0.0655, -0.294, -0.270, white)
ring("Service recess wall", HATCH_X, HATCH_Z,
     0.0658, 0.0605, -0.280, -0.201, plastic)
cylinder("Service recess back", (HATCH_X, -0.199, HATCH_Z),
         0.061, 0.004, plastic)

ring("Pump filter socket", HATCH_X - 0.007, HATCH_Z,
     0.043, 0.0355, -0.254, -0.209, rubber)
ring("Pump socket white flange", HATCH_X - 0.007, HATCH_Z,
     0.044, 0.039, -0.259, -0.249, plastic)

pump = cylinder("PumpFilter", (HATCH_X - 0.007, -0.261, HATCH_Z),
                0.0375, 0.011, plastic, 0.002)
pump["label"] = "drain pump filter"
pivot_at(pump, (HATCH_X - 0.007, -0.246, HATCH_Z))
# Negative Y rotation is anticlockwise when viewed from the front.
pump["motion"] = (
    '{"rotate": {"axis": "Y", "degrees": -720}, '
    '"translate": [0, -0.16, 0]}'
)

def pump_part(obj):
    parent_keep(obj, pump)
    return obj

pump_part(ring("Pump cap raised rim", HATCH_X - 0.007, HATCH_Z,
               0.0354, 0.0318, -0.268, -0.263, white))
pump_part(box("Pump cap white turning rib",
              (HATCH_X - 0.007, -0.274, HATCH_Z),
              (0.007, 0.017, 0.058), white, 0.002))
pump_part(box("Pump blue grip",
              (HATCH_X - 0.007, -0.280, HATCH_Z - 0.010),
              (0.060, 0.008, 0.029), blue, 0.008))

# Removable strainer basket and thread ridges, exposed on removal.
for i in range(4):
    pump_part(ring("Filter thread ridge %d" % i,
                   HATCH_X - 0.007, HATCH_Z,
                   0.034, 0.030, -0.242 + i * 0.004,
                   -0.240 + i * 0.004, plastic))
for i in range(4):
    y = -0.224 + i * 0.020
    pump_part(ring("Filter basket hoop %d" % i,
                   HATCH_X - 0.007, HATCH_Z,
                   0.030, 0.026, y, y + 0.004, plastic))
for i in range(10):
    a = 2 * math.pi * i / 10
    pump_part(box("Filter basket rail %02d" % i,
                  (HATCH_X - 0.007 + 0.028 * math.cos(a),
                   -0.190, HATCH_Z + 0.028 * math.sin(a)),
                  (0.004, 0.075, 0.004), plastic, 0.001))
pump_part(cylinder("Filter basket end", (HATCH_X - 0.007, -0.151, HATCH_Z),
                   0.028, 0.004, plastic, 0.001))

hatch = cylinder("FilterHatch", (HATCH_X, -0.297, HATCH_Z),
                 0.0664, 0.010, white, 0.0018)
hatch["label"] = "round pump access hatch"
pivot_at(hatch, (HATCH_X + 0.064, -0.281, HATCH_Z))
hatch["motion"] = '{"rotate": {"axis": "Z", "degrees": 105}}'

inner = ring("Hatch inner reinforcing rim", HATCH_X, HATCH_Z,
             0.060, 0.056, -0.292, -0.284, plastic)
parent_keep(hatch if False else inner, hatch)
hinge_arm = box("Service hatch hinge arm",
                (HATCH_X + 0.057, -0.274, HATCH_Z),
                (0.018, 0.030, 0.035), plastic, 0.003)
parent_keep(hinge_arm, hatch)
clip = box("Service hatch closing clip",
           (HATCH_X - 0.053, -0.282, HATCH_Z + 0.012),
           (0.008, 0.014, 0.014), plastic, 0.001)
parent_keep(clip, hatch)

# Small fixed service fasteners visible only with the hatch open.
for z in (HATCH_Z - 0.033, HATCH_Z + 0.032):
    cylinder("Service bracket screw", (HATCH_X + 0.049, -0.263, z),
             0.004, 0.003, steel, 0.0005)
    box("Service screw slot", (HATCH_X + 0.049, -0.265, z),
        (0.005, 0.0007, 0.0008), dark)

# Rear cabinet details remain part of the appliance.
box("Rear service cover", (0, 0.318 - 0.003, 0.409),
    (0.464, 0.006, 0.639), white, 0.005)
for x in (-0.218, 0.218):
    for z in (0.112, 0.703):
        cylinder("Rear cover fastener", (x, 0.318, z),
                 0.004, 0.001, steel, 0.0004)

# Guarantee caption metadata on every remaining object.
for obj in bpy.context.scene.objects:
    if "label" not in obj:
        obj["label"] = obj.name.replace("_", " ").lower()

bpy.ops.object.select_all(action='DESELECT')
bpy.context.view_layer.objects.active = body
body.select_set(True)
bpy.context.view_layer.update()

import sys
bpy.ops.wm.save_as_mainfile(filepath=sys.argv[sys.argv.index("--") + 1])
