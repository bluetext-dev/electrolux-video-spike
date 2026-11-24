# /home/peder/spike/build.py
#
# Builds and saves the studio level, sequence, and MRQ configuration.
# Does not launch rendering.
#
# Run:
# /home/peder/UE/Engine/Binaries/Linux/UnrealEditor-Cmd \
#   /home/peder/spike/Spike.uproject \
#   -run=pythonscript -script=/home/peder/spike/build.py \
#   -unattended -nosplash -stdout -FullStdOutLogOutput

import collections
import itertools
import json
import math
import os
import re
import struct
import traceback
import unicodedata

import unreal


ROOT = "/home/peder/spike"
INPUT = os.path.join(ROOT, "input")
SUCCESS = os.path.join(ROOT, "build_ok.json")

LEVEL_PATH = "/Game/Maps/Spike"
SEQUENCE_PATH = "/Game/Seq/Clean"
CONFIG_PATH = "/Game/Render/Config"
PIVOT_TOLERANCE_CM = 0.15

EAL = unreal.EditorAssetLibrary
TOOLS = unreal.AssetToolsHelpers.get_asset_tools()
ACTORS = unreal.get_editor_subsystem(unreal.EditorActorSubsystem)
LEVELS = unreal.get_editor_subsystem(unreal.LevelEditorSubsystem)

KEEP = unreal.AttachmentRule.KEEP_WORLD
LINEAR = unreal.MovieSceneKeyInterpolation.LINEAR
KEEP_ALIVE = []

# Standard Blender glTF export: (x, y, z) -> (x, z, -y).
B_TO_G = [
    [1.0, 0.0, 0.0],
    [0.0, 0.0, 1.0],
    [0.0, -1.0, 0.0],
]
G_TO_B = [
    [1.0, 0.0, 0.0],
    [0.0, 0.0, -1.0],
    [0.0, 1.0, 0.0],
]


def progress(message):
    print("[SPIKE BUILD] " + message, flush=True)


def require(condition, message):
    if not condition:
        raise RuntimeError(message)


def atomic_json(path, value):
    temporary = path + ".tmp"
    with open(temporary, "w", encoding="utf-8") as handle:
        json.dump(value, handle, indent=2, ensure_ascii=False, allow_nan=False)
        handle.write("\n")
        handle.flush()
        os.fsync(handle.fileno())
    os.replace(temporary, path)


def read_json(name):
    path = os.path.join(INPUT, name)
    require(os.path.isfile(path), "Missing required input: " + path)
    with open(path, "r", encoding="utf-8") as handle:
        return json.load(handle)


def finite_number(value, description):
    require(not isinstance(value, bool), description + " must be numeric")
    try:
        number = float(value)
    except (TypeError, ValueError):
        raise RuntimeError(description + " must be numeric")
    require(math.isfinite(number), description + " must be finite")
    return number


def positive_integer(value, description):
    number = finite_number(value, description)
    require(
        number > 0 and number.is_integer(),
        description + " must be a positive integer",
    )
    return int(number)


def coordinates(value, description):
    require(
        isinstance(value, (list, tuple)) and len(value) == 3,
        description + " must contain three coordinates",
    )
    return [finite_number(item, description) for item in value]


def read_render_settings():
    render = read_json("render.json")
    require(isinstance(render, dict), "render.json must contain an object")
    require(
        "width" in render and "height" in render,
        "render.json must contain width and height",
    )
    return {
        "width": positive_integer(render["width"], "render.width"),
        "height": positive_integer(render["height"], "render.height"),
    }


def read_moving_parts(catalog):
    """
    parts.json may describe all parts, not just moving ones.
    Missing motion, null, and {} mean static.
    """
    require(
        isinstance(catalog, dict) and catalog,
        "parts.json must be a nonempty object",
    )
    moving = {}
    static_names = []

    for name, description in catalog.items():
        require(
            isinstance(name, str) and bool(name),
            "parts.json contains an invalid part name",
        )
        require(
            isinstance(description, dict),
            "Part description must be an object: " + name,
        )

        motion = description.get("motion")
        if motion is None:
            static_names.append(name)
            continue

        require(
            isinstance(motion, dict),
            "Invalid motion for {}: expected an object or null, got {}: {!r}"
            .format(name, type(motion).__name__, motion),
        )
        if not motion:
            static_names.append(name)
            continue

        unknown = set(motion) - {"rotate", "translate"}
        require(
            not unknown,
            "Unsupported motion fields for {}: {}".format(name, sorted(unknown)),
        )

        normalized_motion = {}
        translation = motion.get("translate")
        rotation = motion.get("rotate")

        if translation is not None:
            normalized_motion["translate"] = coordinates(
                translation, name + ".motion.translate"
            )

        if rotation is not None:
            require(
                isinstance(rotation, dict),
                name + ".motion.rotate must be an object",
            )
            axis = str(rotation.get("axis", "")).upper()
            require(axis in ("X", "Y", "Z"), "Invalid rotation axis for " + name)
            require(
                "degrees" in rotation,
                name + ".motion.rotate is missing degrees",
            )
            normalized_motion["rotate"] = {
                "axis": axis,
                "degrees": finite_number(
                    rotation["degrees"], name + ".motion.rotate.degrees"
                ),
            }

        if not normalized_motion:
            static_names.append(name)
            continue

        entry = dict(description)
        entry["motion"] = normalized_motion
        entry["location"] = coordinates(
            description.get("location"), name + ".location"
        )
        parent = description.get("parent")
        require(
            parent is None or (isinstance(parent, str) and bool(parent)),
            name + ".parent must be a node name or null",
        )
        moving[name] = entry

    require(moving, "parts.json contains no moving parts")
    progress(
        "Parts catalog: {} moving, {} static"
        .format(len(moving), len(static_names))
    )
    progress("Moving parts: " + ", ".join(sorted(moving)))
    return moving, static_names


def normalized(value):
    value = unicodedata.normalize("NFKD", str(value))
    return re.sub(r"[^a-z0-9]", "", value.lower())


def set_no_static_mesh_combining(mesh_pipeline):
    """
    UE 5.8 uses CombineStaticMeshesBehavior.

    Never read or write combine_static_meshes: it is deprecated and writing
    it can raise DeprecationWarning as an exception in the commandlet.

    Obtain the enum class from the actual property instead of assuming the
    spelling of its generated Python enum class name or its integer values.
    """
    property_name = "combine_static_meshes_behavior"
    current = mesh_pipeline.get_editor_property(property_name)
    enum_type = type(current)

    members = {}
    for name in dir(enum_type):
        if name.startswith("_") or not name.isupper():
            continue
        value = getattr(enum_type, name)
        if isinstance(value, enum_type):
            members[name] = value

    progress(
        "{}.{} uses {}; enum members: {}".format(
            mesh_pipeline.get_class().get_name(),
            property_name,
            enum_type.__name__,
            ", ".join(sorted(members)) or "(none exposed)",
        )
    )

    # Explicit non-combining spellings only. Do not assume enum value 0
    # and do not silently retain the import pipeline's current default.
    accepted = {
        "donotcombine",
        "donotcombinestaticmeshes",
        "nocombine",
        "nocombination",
        "none",
        "disabled",
        "keepseparate",
    }
    candidates = [
        (name, value)
        for name, value in members.items()
        if normalized(name) in accepted
    ]

    require(
        candidates,
        "Cannot identify the explicit non-combining member of {}. "
        "Available members: {}. No deprecated property was used."
        .format(enum_type.__name__, ", ".join(sorted(members))),
    )

    # Aliased names are acceptable; differing enum values are not.
    name, chosen = candidates[0]
    require(
        all(value == chosen for _, value in candidates),
        "Ambiguous non-combining enum members: "
        + ", ".join(item[0] for item in candidates),
    )

    mesh_pipeline.set_editor_property(property_name, chosen)
    require(
        mesh_pipeline.get_editor_property(property_name) == chosen,
        "Interchange did not retain the non-combining import setting",
    )
    progress("Static mesh combining disabled using {}.{}".format(
        enum_type.__name__, name
    ))


def vector(values):
    return unreal.Vector(*[float(value) for value in values])


def xyz(value):
    return [float(value.x), float(value.y), float(value.z)]


def add(a, b):
    return [a[i] + b[i] for i in range(3)]


def sub(a, b):
    return [a[i] - b[i] for i in range(3)]


def mul(a, scalar):
    return [value * scalar for value in a]


def dot(a, b):
    return sum(x * y for x, y in zip(a, b))


def cross(a, b):
    return [
        a[1] * b[2] - a[2] * b[1],
        a[2] * b[0] - a[0] * b[2],
        a[0] * b[1] - a[1] * b[0],
    ]


def length(a):
    return math.sqrt(dot(a, a))


def unit(a):
    size = length(a)
    require(size > 1e-12, "Zero-length basis vector")
    return mul(a, 1.0 / size)


def transpose(a):
    return [list(row) for row in zip(*a)]


def mm(a, b):
    bt = transpose(b)
    return [[dot(row, column) for column in bt] for row in a]


def mv(a, b):
    return [dot(row, b) for row in a]


def identity4():
    return [
        [1.0, 0.0, 0.0, 0.0],
        [0.0, 1.0, 0.0, 0.0],
        [0.0, 0.0, 1.0, 0.0],
        [0.0, 0.0, 0.0, 1.0],
    ]


def matrix_position(matrix):
    return [matrix[i][3] for i in range(3)]


def matrix_linear(matrix):
    return [row[:3] for row in matrix[:3]]


def determinant3(matrix):
    return dot(matrix[0], cross(matrix[1], matrix[2]))


def rotation_basis(matrix, description):
    columns = [unit(column) for column in transpose(matrix_linear(matrix))]
    require(
        max(
            abs(dot(columns[i], columns[j]))
            for i in range(3)
            for j in range(i + 1, 3)
        ) < 1e-4,
        description + ": sheared transform cannot define a hinge frame",
    )
    result = transpose(columns)
    require(
        determinant3(result) > 0.999,
        description + ": mirrored transform; apply negative scale in Blender",
    )
    return result


def quaternion_matrix(q):
    x, y, z, w = q
    size = math.sqrt(x*x + y*y + z*z + w*w)
    require(size > 1e-12, "Invalid glTF quaternion")
    x, y, z, w = [value / size for value in (x, y, z, w)]
    return [
        [1 - 2*(y*y + z*z), 2*(x*y - z*w), 2*(x*z + y*w)],
        [2*(x*y + z*w), 1 - 2*(x*x + z*z), 2*(y*z - x*w)],
        [2*(x*z - y*w), 2*(y*z + x*w), 1 - 2*(x*x + y*y)],
    ]


def matrix_rotator(m):
    trace = m[0][0] + m[1][1] + m[2][2]
    if trace > 0:
        s = math.sqrt(trace + 1.0) * 2
        w = 0.25 * s
        x = (m[2][1] - m[1][2]) / s
        y = (m[0][2] - m[2][0]) / s
        z = (m[1][0] - m[0][1]) / s
    elif m[0][0] > m[1][1] and m[0][0] > m[2][2]:
        s = math.sqrt(1 + m[0][0] - m[1][1] - m[2][2]) * 2
        w = (m[2][1] - m[1][2]) / s
        x = 0.25 * s
        y = (m[0][1] + m[1][0]) / s
        z = (m[0][2] + m[2][0]) / s
    elif m[1][1] > m[2][2]:
        s = math.sqrt(1 + m[1][1] - m[0][0] - m[2][2]) * 2
        w = (m[0][2] - m[2][0]) / s
        x = (m[0][1] + m[1][0]) / s
        y = 0.25 * s
        z = (m[1][2] + m[2][1]) / s
    else:
        s = math.sqrt(1 + m[2][2] - m[0][0] - m[1][1]) * 2
        w = (m[1][0] - m[0][1]) / s
        x = (m[0][2] + m[2][0]) / s
        y = (m[1][2] + m[2][1]) / s
        z = 0.25 * s
    return unreal.Quat(x, y, z, w).rotator()


def read_glb(path):
    with open(path, "rb") as handle:
        data = handle.read()
    require(len(data) >= 20, "Truncated GLB")
    magic, version, file_size = struct.unpack_from("<III", data, 0)
    require(magic == 0x46546C67 and version == 2, "Expected glTF 2.0 GLB")
    require(file_size == len(data), "GLB length mismatch")

    offset = 12
    document = None
    while offset < len(data):
        require(offset + 8 <= len(data), "Truncated GLB chunk header")
        size, kind = struct.unpack_from("<II", data, offset)
        offset += 8
        require(offset + size <= len(data), "Truncated GLB chunk")
        if kind == 0x4E4F534A:
            document = json.loads(
                data[offset:offset + size].decode("utf-8").rstrip("\x00 \t\r\n")
            )
        offset += size
    require(document is not None, "GLB has no JSON chunk")
    return document


def gltf_node_matrix(node):
    if "matrix" in node:
        values = node["matrix"]
        require(len(values) == 16, "Invalid glTF matrix")
        return [
            [float(values[column * 4 + row]) for column in range(4)]
            for row in range(4)
        ]
    result = identity4()
    rotation = quaternion_matrix(node.get("rotation", [0, 0, 0, 1]))
    scale = node.get("scale", [1, 1, 1])
    position = node.get("translation", [0, 0, 0])
    for row in range(3):
        for column in range(3):
            result[row][column] = rotation[row][column] * scale[column]
        result[row][3] = position[row]
    return result


def asset(path):
    result = unreal.load_asset(path)
    require(result is not None, "Could not load asset: " + path)
    return result


def ensure_directory(folder):
    if not EAL.does_directory_exist(folder):
        require(EAL.make_directory(folder), "Cannot create asset folder: " + folder)


def create_asset(path, asset_class, factory):
    folder, name = path.rsplit("/", 1)
    ensure_directory(folder)
    result = TOOLS.create_asset(name, folder, asset_class, factory)
    require(result is not None, "Could not create asset: " + path)
    return result


def spawn(actor_class, label, location, rotation=None):
    actor = ACTORS.spawn_actor_from_class(
        actor_class,
        vector(location),
        rotation if rotation is not None else unreal.Rotator(0, 0, 0),
        transient=False,
    )
    require(actor is not None, "Could not spawn " + label)
    actor.set_actor_label(label)
    return actor


def movable(actor):
    for component in actor.get_components_by_class(unreal.SceneComponent):
        component.set_mobility(unreal.ComponentMobility.MOVABLE)


def attach(child, parent):
    require(child != parent, "Self attachment: " + child.get_actor_label())
    child.attach_to_actor(parent, "", KEEP, KEEP, KEEP, False)
    require(
        child.get_attach_parent_actor() == parent,
        "Attachment failed: {} -> {}".format(
            child.get_actor_label(), parent.get_actor_label()
        ),
    )


def empty_actor(label, position, rotation=None):
    # A meshless StaticMeshActor supplies a native root in a commandlet.
    actor = spawn(unreal.StaticMeshActor, label, position, rotation)
    movable(actor)
    actor.static_mesh_component.set_collision_enabled(
        unreal.CollisionEnabled.NO_COLLISION
    )
    actor.static_mesh_component.set_editor_property("cast_shadow", False)
    return actor


def mesh_components(actor):
    return [
        component
        for component in actor.get_components_by_class(unreal.StaticMeshComponent)
        if component.get_editor_property("static_mesh") is not None
    ]


def descendants(actor):
    result = []
    pending = [actor]
    seen = set()
    while pending:
        item = pending.pop()
        path = item.get_path_name()
        require(path not in seen, "Actor attachment cycle")
        seen.add(path)
        result.append(item)
        pending.extend(item.get_attached_actors())
    return result


def component_bounds(component):
    low, high = component.get_local_bounds()
    low, high = xyz(low), xyz(high)
    transform = component.get_world_transform()
    points = [
        xyz(transform.transform_location(vector(point)))
        for point in itertools.product(
            (low[0], high[0]),
            (low[1], high[1]),
            (low[2], high[2]),
        )
    ]
    return (
        [min(point[i] for point in points) for i in range(3)],
        [max(point[i] for point in points) for i in range(3)],
    )


def bounds(components):
    require(components, "No renderable meshes in bounds query")
    boxes = [component_bounds(component) for component in components]
    low = [min(box[0][i] for box in boxes) for i in range(3)]
    high = [max(box[1][i] for box in boxes) for i in range(3)]
    return low, high


def material_constant(material, value, property_name):
    if isinstance(value, (tuple, list)):
        expression = unreal.MaterialEditingLibrary.create_material_expression(
            material, unreal.MaterialExpressionConstant3Vector, -300, 0
        )
        require(expression is not None, "Material expression creation failed")
        expression.set_editor_property(
            "constant", unreal.LinearColor(value[0], value[1], value[2], 1.0)
        )
    else:
        expression = unreal.MaterialEditingLibrary.create_material_expression(
            material, unreal.MaterialExpressionConstant, -300, 120
        )
        require(expression is not None, "Material expression creation failed")
        expression.set_editor_property("r", float(value))

    require(
        unreal.MaterialEditingLibrary.connect_material_property(
            expression, "", property_name
        ),
        "Material connection failed",
    )


def create_material(path, color, unlit=False, additive=False):
    material = create_asset(path, unreal.Material, unreal.MaterialFactoryNew())
    material.set_editor_property("two_sided", bool(unlit))
    if unlit:
        material.set_editor_property(
            "shading_model", unreal.MaterialShadingModel.MSM_UNLIT
        )
        material_constant(
            material, color, unreal.MaterialProperty.MP_EMISSIVE_COLOR
        )
    else:
        material_constant(material, color, unreal.MaterialProperty.MP_BASE_COLOR)
        material_constant(material, 0.72, unreal.MaterialProperty.MP_ROUGHNESS)
        material_constant(material, 0.25, unreal.MaterialProperty.MP_SPECULAR)

    if additive:
        material.set_editor_property("blend_mode", unreal.BlendMode.BLEND_ADDITIVE)
        material_constant(material, 0.20, unreal.MaterialProperty.MP_OPACITY)

    unreal.MaterialEditingLibrary.recompile_material(material)
    return material


def add_key(channel, frame, value):
    result = channel.add_key(
        time=unreal.FrameNumber(int(frame)),
        new_value=float(value),
        interpolation=LINEAR,
    )
    require(result is not None, "Could not add numeric Sequencer key")


def transform_channels(binding, end_frame):
    track = binding.add_track(unreal.MovieScene3DTransformTrack)
    require(track is not None, "Could not create transform track")
    section = track.add_section()
    require(section is not None, "Could not create transform section")
    section.set_range(0, end_frame)
    section.set_editor_property("use_quaternion_interpolation", False)
    channels = list(section.get_all_channels())
    require(len(channels) == 9, "Expected nine transform channels")

    # Translation XYZ; rotation Roll/Pitch/Yaw; scale XYZ.
    for channel, value in zip(channels, [0, 0, 0, 0, 0, 0, 1, 1, 1]):
        channel.set_default(float(value))
    return section, channels


def smoothstep(value):
    value = max(0.0, min(1.0, value))
    return value * value * (3.0 - 2.0 * value)


def lerp(a, b, fraction):
    return add(mul(a, 1 - fraction), mul(b, fraction))


def rotate_point(point, pivot, axis, degrees):
    angle = math.radians(degrees)
    point = sub(point, pivot)
    c, s = math.cos(angle), math.sin(angle)
    rotated = add(
        add(mul(point, c), mul(cross(axis, point), s)),
        mul(axis, dot(axis, point) * (1 - c)),
    )
    return add(pivot, rotated)


def main():
    for path in (SUCCESS, SUCCESS + ".tmp"):
        if os.path.exists(path):
            os.remove(path)

    progress("Reading and validating inputs")
    require(os.path.isdir(INPUT), "Missing input directory: " + INPUT)

    render = read_render_settings()
    width, height = render["width"], render["height"]
    progress("Output resolution: {} x {}".format(width, height))

    part_catalog = read_json("parts.json")
    parts, static_part_names = read_moving_parts(part_catalog)
    procedure = read_json("procedure.json")
    timing = read_json("timing.json")

    glb_path = os.path.join(INPUT, "EW7F7649U2.glb")
    require(os.path.isfile(glb_path), "Missing required input: " + glb_path)
    gltf = read_glb(glb_path)

    require(
        isinstance(procedure, dict)
        and isinstance(procedure.get("steps"), list)
        and bool(procedure["steps"]),
        "procedure.json has no steps",
    )
    require(
        isinstance(timing, dict) and isinstance(timing.get("steps"), list),
        "timing.json must contain a steps array",
    )
    require(
        len(procedure["steps"]) == len(timing["steps"]),
        "Procedure/timing step count mismatch",
    )

    fps = positive_integer(timing["fps"], "timing.fps")
    total_seconds = finite_number(timing["total"], "timing.total")
    title_seconds = finite_number(timing["title_seconds"], "timing.title_seconds")
    require(total_seconds > 0, "timing.total must be positive")

    end_frame = math.ceil((total_seconds + 1.0) * fps)
    title_frame = round(title_seconds * fps)
    require(0 < title_frame < end_frame, "Invalid title duration")

    scheduled_steps = []
    previous_end = title_frame

    for number, (step, clock) in enumerate(
        zip(procedure["steps"], timing["steps"]), 1
    ):
        require(
            isinstance(step, dict) and isinstance(clock, dict),
            "Invalid procedure/timing entry for step {}".format(number),
        )
        start_seconds = finite_number(clock["start"], "Step start")
        length_seconds = finite_number(clock["length"], "Step length")
        require(length_seconds > 0, "Non-positive step length")

        start = round(start_seconds * fps)
        finish = round((start_seconds + length_seconds) * fps)
        require(start >= previous_end, "Overlapping step {}".format(number))
        require(finish > start and finish <= end_frame, "Invalid step range")
        require(start + fps <= finish, "Camera transition requires one second")

        actions = step.get("actions", [])
        require(isinstance(actions, list), "Step actions must be an array")
        names = []
        for action in actions:
            require(
                isinstance(action, dict) and "part" in action and "to" in action,
                "Invalid action in step {}".format(number),
            )
            name = action["part"]
            require(
                name in parts,
                "Action in step {} refers to {!r}, which has no valid motion "
                "in parts.json".format(number, name),
            )
            fraction = finite_number(action["to"], "Action fraction")
            require(0 <= fraction <= 1, "Action fraction outside [0, 1]")
            names.append(name)

        require(
            len(names) == len(set(names)),
            "Duplicate simultaneous action in step {}".format(number),
        )
        if actions:
            require(
                start + 3 * fps <= finish,
                "An action requires three seconds in step {}".format(number),
            )

        shot = step.get("shot")
        require(isinstance(shot, dict), "Step is missing its shot")
        require(
            isinstance(shot.get("target"), str) and bool(shot["target"]),
            "Shot target must be a node name or Machine",
        )
        require(
            finite_number(shot["distance"], "Shot distance") > 0,
            "Non-positive shot distance",
        )
        finite_number(shot["azimuth"], "Shot azimuth")
        finite_number(shot["elevation"], "Shot elevation")

        scheduled_steps.append((start, finish, step))
        previous_end = finish

    # Read the active source hierarchy independently of Interchange.
    nodes = gltf["nodes"]
    scene = gltf["scenes"][gltf.get("scene", 0)]
    parent_index = {}
    world_matrices = {}
    active = []
    visiting = set()

    def visit(index, parent, parent_world):
        require(0 <= index < len(nodes), "Invalid glTF node index")
        require(index not in visiting, "Cycle in glTF node graph")
        require(index not in world_matrices, "glTF node has multiple parents")
        visiting.add(index)
        parent_index[index] = parent
        world = mm(parent_world, gltf_node_matrix(nodes[index]))
        world_matrices[index] = world
        active.append(index)
        for child in nodes[index].get("children", []):
            visit(child, index, world)
        visiting.remove(index)

    for root_index in scene.get("nodes", []):
        visit(root_index, None, identity4())
    require(active, "Empty glTF scene")

    node_names = {
        index: nodes[index].get("name", "GLTF_Node_{}".format(index))
        for index in active
    }
    name_to_index = {}
    for index, name in node_names.items():
        key = normalized(name)
        require(key not in name_to_index, "Ambiguous glTF node name: " + name)
        name_to_index[key] = index

    def node_for_name(name):
        key = normalized(name)
        require(key in name_to_index, "No glTF node named: " + str(name))
        return name_to_index[key]

    part_indices = {name: node_for_name(name) for name in parts}
    for step in procedure["steps"]:
        if step["shot"]["target"] != "Machine":
            node_for_name(step["shot"]["target"])
        if step.get("highlight"):
            node_for_name(step["highlight"])

    progress("Creating clean output level and folders")
    # These generated folders are exclusively owned by this build.
    for folder in (
        "/Game/Machine", "/Game/Seq", "/Game/Render", "/Game/Studio"
    ):
        if EAL.does_directory_exist(folder):
            require(EAL.delete_directory(folder), "Cannot replace " + folder)
        ensure_directory(folder)

    ensure_directory("/Game/Maps")
    if EAL.does_asset_exist(LEVEL_PATH):
        require(EAL.delete_asset(LEVEL_PATH), "Cannot replace " + LEVEL_PATH)
    require(LEVELS.new_level(LEVEL_PATH), "Could not create new level")

    existing = {actor.get_path_name() for actor in ACTORS.get_all_level_actors()}

    progress("Importing glTF scene with separate, unbaked static meshes")
    pipeline_source = "/Interchange/Pipelines/DefaultSceneAssetsPipeline"
    scene_pipeline_path = "/Interchange/Pipelines/DefaultSceneLevelPipeline"
    asset(pipeline_source)
    scene_pipeline = asset(scene_pipeline_path)

    pipeline = EAL.duplicate_asset(
        pipeline_source, "/Game/Machine/SpikeSceneAssetsPipeline"
    )
    require(pipeline is not None, "Could not duplicate scene import pipeline")

    common_meshes = pipeline.get_editor_property("common_meshes_properties")
    require(common_meshes is not None, "Common mesh import settings missing")
    common_meshes.set_editor_property("bake_meshes", False)
    require(
        common_meshes.get_editor_property("bake_meshes") is False,
        "Interchange did not disable mesh baking",
    )

    mesh_pipeline = pipeline.get_editor_property("mesh_pipeline")
    require(mesh_pipeline is not None, "Interchange mesh pipeline missing")

    # UE 5.8 correction: use the replacement enum, not the deprecated bool.
    set_no_static_mesh_combining(mesh_pipeline)

    mesh_pipeline.set_editor_property("import_static_meshes", True)
    require(
        mesh_pipeline.get_editor_property("import_static_meshes"),
        "Static mesh importing is not enabled",
    )
    KEEP_ALIVE.extend([pipeline, scene_pipeline, common_meshes, mesh_pipeline])

    manager = unreal.InterchangeManager.get_interchange_manager_scripted()
    require(manager is not None, "InterchangeManager is unavailable")
    source = unreal.InterchangeManager.create_source_data(glb_path)
    require(source is not None, "Could not create Interchange source data")

    parameters = unreal.ImportAssetParameters()
    parameters.set_editor_property("is_automated", True)
    parameters.set_editor_property("replace_existing", True)
    parameters.set_editor_property(
        "override_pipelines",
        [
            unreal.SoftObjectPath(pipeline.get_path_name()),
            unreal.SoftObjectPath(scene_pipeline.get_path_name()),
        ],
    )
    KEEP_ALIVE.extend([manager, source, parameters])

    require(
        manager.import_scene("/Game/Machine", source, parameters),
        "Interchange scene import failed",
    )

    imported = [
        actor for actor in ACTORS.get_all_level_actors()
        if actor.get_path_name() not in existing
    ]
    require(imported, "Scene import spawned no actors")
    require(
        any(mesh_components(actor) for actor in imported),
        "Scene import contains no static meshes",
    )
    for actor in imported:
        movable(actor)
    progress("Imported {} actors".format(len(imported)))

    # Match source nodes to actors independently of catalog membership.
    node_actors = {}
    used = set()
    for index in active:
        key = normalized(node_names[index])
        candidates = [
            actor for actor in imported
            if normalized(actor.get_actor_label()) == key
            and actor.get_path_name() not in used
        ]
        require(
            len(candidates) <= 1,
            "Duplicate imported label: " + node_names[index],
        )
        if candidates:
            node_actors[index] = candidates[0]
            used.add(candidates[0].get_path_name())

    for index in active:
        if index in node_actors or "mesh" not in nodes[index]:
            continue
        mesh_description = gltf["meshes"][nodes[index]["mesh"]]
        keys = {normalized(node_names[index])}
        if mesh_description.get("name"):
            keys.add(normalized(mesh_description["name"]))

        candidates = []
        for actor in imported:
            if actor.get_path_name() in used:
                continue
            if any(
                normalized(
                    component.get_editor_property("static_mesh").get_name()
                ) in keys
                for component in mesh_components(actor)
            ):
                candidates.append(actor)

        require(
            len(candidates) == 1,
            "Cannot uniquely match imported mesh node: " + node_names[index],
        )
        node_actors[index] = candidates[0]
        used.add(candidates[0].get_path_name())

    progress("Checking importer coordinates against Blender pivots")
    pairs = []
    for name, index in part_indices.items():
        if index in node_actors:
            pairs.append((
                mv(G_TO_B, matrix_position(world_matrices[index])),
                xyz(node_actors[index].get_actor_location()),
            ))
    require(len(pairs) >= 3, "Need at least three imported moving-part pivots")

    # Select a Z-up, handedness-reversing horizontal basis.
    # Scale is fixed: one Blender metre MUST equal 100 Unreal units.
    conversion_candidates = []
    for swap in (False, True):
        for sx, sy in itertools.product((-1.0, 1.0), repeat=2):
            conversion = (
                [[0, sx, 0], [sy, 0, 0], [0, 0, 1]]
                if swap else
                [[sx, 0, 0], [0, sy, 0], [0, 0, 1]]
            )
            if determinant3(conversion) > -0.999:
                continue
            offsets = [
                sub(ue, mul(mv(conversion, blender), 100))
                for blender, ue in pairs
            ]
            offset = [
                sum(point[i] for point in offsets) / len(offsets)
                for i in range(3)
            ]
            error = max(
                length(sub(
                    add(mul(mv(conversion, blender), 100), offset), ue
                ))
                for blender, ue in pairs
            )
            conversion_candidates.append((error, conversion, offset))

    conversion_candidates.sort(key=lambda item: item[0])
    calibration_error, B_TO_U, scene_offset = conversion_candidates[0]
    require(
        calibration_error <= PIVOT_TOLERANCE_CM,
        "Importer pivot check failed: {:.4f} cm error. "
        "Check baked transforms and export coordinates."
        .format(calibration_error),
    )
    require(
        conversion_candidates[1][0] > PIVOT_TOLERANCE_CM,
        "Coordinate conversion is ambiguous",
    )

    G_TO_U = mm(B_TO_U, G_TO_B)
    U_TO_G = transpose(G_TO_U)

    def source_position_ue(index):
        return add(
            mul(mv(G_TO_U, matrix_position(world_matrices[index])), 100),
            scene_offset,
        )

    def source_rotation_ue(index):
        matrix = identity4() if index is None else world_matrices[index]
        source_rotation = rotation_basis(
            matrix,
            "glTF node " + ("scene" if index is None else node_names[index]),
        )
        return mm(mm(G_TO_U, source_rotation), U_TO_G)

    progress(
        "Blender -> UE basis: {}; offset: {}; maximum error: {:.5f} cm"
        .format(B_TO_U, scene_offset, calibration_error)
    )

    # Independently verify moving-part metadata against the source file.
    for name, index in part_indices.items():
        metadata_position = parts[name]["location"]
        source_world_b = mv(G_TO_B, matrix_position(world_matrices[index]))
        if parts[name].get("parent") is None:
            require(
                length(sub(metadata_position, source_world_b)) * 100
                <= PIVOT_TOLERANCE_CM,
                "parts.json location disagrees with GLB for " + name,
            )
        else:
            parent_node = node_for_name(parts[name]["parent"])
            require(
                parent_index[index] == parent_node,
                "parts.json parent disagrees with GLB for " + name,
            )
            source_local_b = mv(
                G_TO_B, matrix_position(gltf_node_matrix(nodes[index]))
            )
            require(
                length(sub(metadata_position, source_local_b)) * 100
                <= PIVOT_TOLERANCE_CM,
                "Parent-space location disagrees with GLB for " + name,
            )

    for index, actor in node_actors.items():
        pivot_error = length(
            sub(xyz(actor.get_actor_location()), source_position_ue(index))
        )
        require(
            pivot_error <= PIVOT_TOLERANCE_CM,
            "Imported pivot mismatch for {}: {:.4f} cm"
            .format(node_names[index], pivot_error),
        )

    progress("Restoring the complete glTF attachment hierarchy")
    machine_root = empty_actor("MachineRoot", scene_offset)

    # Interchange may omit non-rendering source nodes.
    for index in active:
        if index not in node_actors:
            require(
                "mesh" not in nodes[index],
                "Missing imported mesh node: " + node_names[index],
            )
            node_actors[index] = empty_actor(
                node_names[index],
                source_position_ue(index),
                matrix_rotator(source_rotation_ue(index)),
            )

    for index in active:
        parent = parent_index[index]
        attach(
            node_actors[index],
            machine_root if parent is None else node_actors[parent],
        )

    mapped_paths = {actor.get_path_name() for actor in node_actors.values()}
    for actor in imported:
        if actor.get_path_name() in mapped_paths:
            continue
        cursor = actor.get_attach_parent_actor()
        found_node = False
        seen_parents = set()
        while cursor is not None:
            path = cursor.get_path_name()
            require(path not in seen_parents, "Imported attachment cycle")
            seen_parents.add(path)
            if path in mapped_paths:
                found_node = True
                break
            cursor = cursor.get_attach_parent_actor()

        if mesh_components(actor):
            require(
                found_node,
                "Unmatched imported mesh actor: " + actor.get_actor_label(),
            )
        if not found_node:
            attach(actor, machine_root)

    machine_components = []
    component_paths = set()
    for actor in descendants(machine_root):
        for component in mesh_components(actor):
            path = component.get_path_name()
            if path not in component_paths:
                component_paths.add(path)
                machine_components.append(component)

    bounds_min, bounds_max = bounds(machine_components)
    machine_center = mul(add(bounds_min, bounds_max), 0.5)
    require(
        20 < bounds_max[2] - bounds_min[2] < 200,
        "Implausible appliance height; check metre-to-centimetre conversion",
    )
    progress("Machine bounds, cm: {} .. {}".format(bounds_min, bounds_max))

    target_centers = {}
    for index in active:
        components = [
            component
            for actor in descendants(node_actors[index])
            for component in mesh_components(actor)
        ]
        if components:
            low, high = bounds(components)
            target_centers[index] = mul(add(low, high), 0.5)
        else:
            target_centers[index] = source_position_ue(index)

    progress("Creating pivot-preserving translation and rotation controls")
    controls = {}
    moving_by_actor = {
        node_actors[index].get_path_name(): name
        for name, index in part_indices.items()
    }
    moving_ancestry = {}
    for index, actor in node_actors.items():
        chain = []
        cursor = actor
        while cursor is not None:
            part_name = moving_by_actor.get(cursor.get_path_name())
            if part_name is not None:
                chain.append(part_name)
            cursor = cursor.get_attach_parent_actor()
        moving_ancestry[index] = chain

    for name, description in parts.items():
        index = part_indices[name]
        actor = node_actors[index]
        old_parent = actor.get_attach_parent_actor()
        require(old_parent is not None, "Moving part has no parent: " + name)
        pivot = xyz(actor.get_actor_location())

        parent_rotation = source_rotation_ue(parent_index[index])
        node_rotation = source_rotation_ue(index)

        anchor = empty_actor(
            name + "__ParentFrame", pivot, matrix_rotator(parent_rotation)
        )
        attach(anchor, old_parent)
        slide = empty_actor(
            name + "__Translation", pivot, matrix_rotator(parent_rotation)
        )
        attach(slide, anchor)
        basis = empty_actor(
            name + "__HingeBasis", pivot, matrix_rotator(node_rotation)
        )
        attach(basis, slide)
        spin = empty_actor(
            name + "__Rotation", pivot, matrix_rotator(node_rotation)
        )
        attach(spin, basis)
        attach(actor, spin)

        for control_actor in (slide, spin):
            control_actor.set_actor_relative_location(
                vector([0, 0, 0]), False, False
            )
            control_actor.set_actor_relative_rotation(
                unreal.Rotator(0, 0, 0), False, False
            )
            control_actor.set_actor_relative_scale3d(vector([1, 1, 1]))

        motion = description["motion"]
        translation_b = motion.get("translate", [0, 0, 0])
        parent_world = (
            identity4() if parent_index[index] is None
            else world_matrices[parent_index[index]]
        )
        translation_g = mv(B_TO_G, translation_b)
        world_translation = mul(
            mv(G_TO_U, mv(matrix_linear(parent_world), translation_g)), 100
        )
        slide_translation = mv(transpose(parent_rotation), world_translation)

        rotation = motion.get("rotate")
        degrees = rotation["degrees"] if rotation else 0.0
        axis_b = [0.0, 0.0, 0.0]
        axis_index = "XYZ".index(rotation["axis"]) if rotation else 0
        axis_b[axis_index] = 1.0
        axis_u = mv(B_TO_U, axis_b)

        # A reflection reverses axial rotation. Derive UE's Euler signs
        # using one source degree, then retain the FULL signed angle.
        # PumpFilter's -720 degrees must not collapse to zero turns.
        half = math.radians(-1.0) * 0.5
        one_degree = unreal.Quat(
            axis_u[0] * math.sin(half),
            axis_u[1] * math.sin(half),
            axis_u[2] * math.sin(half),
            math.cos(half),
        ).rotator()

        controls[name] = {
            "slide": slide,
            "spin": spin,
            "pivot": pivot,
            "translation": slide_translation,
            "world_translation": world_translation,
            "degrees": degrees,
            "rotation_per_degree": [
                one_degree.roll, one_degree.pitch, one_degree.yaw
            ],
            "world_axis": unit(mv(node_rotation, axis_u)),
        }
        require(
            length(sub(xyz(actor.get_actor_location()), pivot)) < 0.001,
            "Rig construction displaced " + name,
        )
        progress("Pivot {}: {} cm".format(name, pivot))

    progress("Building studio floor, lights, background, and fixed exposure")
    floor_material = create_material(
        "/Game/Studio/M_Floor", [0.65, 0.65, 0.65]
    )
    background_material = create_material(
        "/Game/Studio/M_Background", [300.0, 300.0, 300.0], unlit=True
    )
    glow_material = create_material(
        "/Game/Studio/M_Highlight",
        [100.0, 800.0, 1400.0],
        unlit=True,
        additive=True,
    )

    floor = spawn(
        unreal.StaticMeshActor,
        "Studio_Floor",
        [machine_center[0], machine_center[1], bounds_min[2] - 5.5],
    )
    movable(floor)
    require(
        floor.static_mesh_component.set_static_mesh(
            asset("/Engine/BasicShapes/Cube")
        ),
        "Could not assign floor mesh",
    )
    floor.set_actor_scale3d(vector([200, 200, 0.1]))
    floor.static_mesh_component.set_material(0, floor_material)

    background = spawn(
        unreal.StaticMeshActor, "Studio_Background", machine_center
    )
    movable(background)
    require(
        background.static_mesh_component.set_static_mesh(
            asset("/Engine/BasicShapes/Sphere")
        ),
        "Could not assign background mesh",
    )
    background.set_actor_scale3d(vector([300, 300, 300]))
    background.static_mesh_component.set_material(0, background_material)
    background.static_mesh_component.set_editor_property("cast_shadow", False)
    background.static_mesh_component.set_collision_enabled(
        unreal.CollisionEnabled.NO_COLLISION
    )

    sky = spawn(
        unreal.SkyLight, "Studio_SkyLight", add(machine_center, [0, 0, 200])
    )
    sky_component = sky.get_component_by_class(unreal.SkyLightComponent)
    require(sky_component is not None, "SkyLight component missing")
    sky_component.set_mobility(unreal.ComponentMobility.MOVABLE)
    sky_component.set_editor_property(
        "source_type", unreal.SkyLightSourceType.SLS_SPECIFIED_CUBEMAP
    )
    sky_component.set_editor_property(
        "cubemap", asset("/Engine/MapTemplates/Sky/DaylightAmbientCubemap")
    )
    sky_component.set_intensity(0.5)

    def rect(label, relative_blender_metres, lumens, size):
        position = add(
            machine_center, mul(mv(B_TO_U, relative_blender_metres), 100)
        )
        rotation = unreal.MathLibrary.find_look_at_rotation(
            vector(position), vector(machine_center)
        )
        light = spawn(unreal.RectLight, label, position, rotation)
        component = light.get_component_by_class(unreal.RectLightComponent)
        require(component is not None, "RectLight component missing: " + label)
        component.set_mobility(unreal.ComponentMobility.MOVABLE)
        component.set_editor_property("intensity_units", unreal.LightUnits.LUMENS)
        component.set_intensity(float(lumens))
        component.set_editor_property("source_width", float(size[0]))
        component.set_editor_property("source_height", float(size[1]))
        component.set_editor_property("attenuation_radius", 1200.0)

    rect("Studio_Key", [-1.1, -1.4, 1.6], 18000.0, [150, 150])
    rect("Studio_Fill", [1.3, -0.7, 0.9], 6500.0, [180, 180])
    rect("Studio_Rim", [0.7, 1.1, 1.5], 20000.0, [100, 160])

    pp = spawn(unreal.PostProcessVolume, "Studio_Exposure", machine_center)
    pp.set_editor_property("unbound", True)
    pp.set_editor_property("priority", 100.0)
    settings = pp.get_editor_property("settings")

    def pp_setting(name, value):
        settings.set_editor_property("override_" + name, True)
        settings.set_editor_property(name, value)

    pp_setting("auto_exposure_method", unreal.AutoExposureMethod.AEM_MANUAL)
    pp_setting("auto_exposure_apply_physical_camera_exposure", True)
    pp_setting("auto_exposure_bias", 0.0)
    pp_setting("camera_aperture", 4.0)
    pp_setting("camera_shutter_speed", 60.0)
    pp_setting("camera_iso", 200.0)
    pp_setting("bloom_intensity", 0.3)
    pp_setting("bloom_threshold", 0.2)
    pp_setting("vignette_intensity", 0.0)
    pp_setting("motion_blur_amount", 0.5)
    pp.set_editor_property("settings", settings)

    progress("Creating LevelSequence and action curves")
    sequence = create_asset(
        SEQUENCE_PATH, unreal.LevelSequence, unreal.LevelSequenceFactoryNew()
    )
    sequence.set_display_rate(unreal.FrameRate(fps, 1))
    sequence.set_tick_resolution(unreal.FrameRate(fps * 1000, 1))
    sequence.set_playback_start(0)
    sequence.set_playback_end(end_frame)
    sequence.set_work_range_start(0.0)
    sequence.set_work_range_end(end_frame / fps)
    sequence.set_view_range_start(0.0)
    sequence.set_view_range_end(end_frame / fps)

    fraction_keys = {name: {0: 0.0} for name in parts}
    current_fraction = {name: 0.0 for name in parts}
    action_ranges = {name: [] for name in parts}

    for start, finish, step in scheduled_steps:
        for action in step.get("actions", []):
            name = action["part"]
            first = start + fps
            last = first + 2 * fps
            initial = current_fraction[name]
            final = float(action["to"])
            fraction_keys[name][first] = initial
            fraction_keys[name][last] = final
            action_ranges[name].append((first, last, initial, final))
            current_fraction[name] = final

    for name in parts:
        fraction_keys[name][end_frame] = current_fraction[name]
        control = controls[name]

        slide_binding = sequence.add_possessable(control["slide"])
        slide_binding.set_display_name(name + " — parent-space translation")
        _, slide_channels = transform_channels(slide_binding, end_frame)

        spin_binding = sequence.add_possessable(control["spin"])
        spin_binding.set_display_name(name + " — unwrapped hinge/thread rotation")
        _, spin_channels = transform_channels(spin_binding, end_frame)

        for frame, fraction in sorted(fraction_keys[name].items()):
            for axis in range(3):
                add_key(
                    slide_channels[axis],
                    frame,
                    control["translation"][axis] * fraction,
                )
                add_key(
                    spin_channels[3 + axis],
                    frame,
                    control["rotation_per_degree"][axis]
                    * control["degrees"] * fraction,
                )

    def fraction_at(name, frame):
        value = 0.0
        for first, last, initial, final in action_ranges[name]:
            if frame < first:
                break
            if frame < last:
                return initial + (
                    (final - initial) * (frame - first) / (last - first)
                )
            value = final
        return value

    def target_at(target, frame):
        if target == "Machine":
            return machine_center[:]
        index = node_for_name(target)
        point = target_centers[index][:]
        # Apply inner motion first, then moving ancestors' motions.
        for name in moving_ancestry[index]:
            fraction = fraction_at(name, frame)
            control = controls[name]
            point = rotate_point(
                point,
                control["pivot"],
                control["world_axis"],
                -control["degrees"] * fraction,
            )
            point = add(point, mul(control["world_translation"], fraction))
        return point

    progress("Adding keyed emissive material overlays")
    highlight_intervals = collections.defaultdict(list)
    highlight_components = {}

    for start, finish, step in scheduled_steps:
        if not step.get("highlight"):
            continue
        actor = node_actors[node_for_name(step["highlight"])]
        components = [
            component
            for item in descendants(actor)
            for component in mesh_components(item)
        ]
        require(components, "Highlight has no meshes: " + step["highlight"])
        for component in components:
            path = component.get_path_name()
            highlight_components[path] = component
            highlight_intervals[path].append((start, finish))

    owner_bindings = {}
    for path, component in highlight_components.items():
        merged = []
        for first, last in sorted(highlight_intervals[path]):
            if merged and first <= merged[-1][1]:
                merged[-1][1] = max(last, merged[-1][1])
            else:
                merged.append([first, last])

        component.set_overlay_material(None)
        component.set_editor_property("overlay_material_max_draw_distance", 0.0)

        owner = component.get_owner()
        owner_path = owner.get_path_name()
        if owner_path not in owner_bindings:
            owner_bindings[owner_path] = sequence.add_possessable(owner)

        binding = sequence.add_possessable(component)
        binding.set_parent(owner_bindings[owner_path])
        binding.set_display_name(owner.get_actor_label() + " — highlight")

        track = binding.add_track(unreal.MovieSceneObjectPropertyTrack)
        require(track is not None, "Could not create overlay property track")
        track.set_property_name_and_path("OverlayMaterial", "OverlayMaterial")
        section = track.add_section()
        require(section is not None, "Could not create overlay section")
        section.set_range(0, end_frame)

        channels = list(section.get_all_channels())
        require(len(channels) == 1, "Expected one object-path overlay channel")
        channel = channels[0]
        channel.set_default(None)

        states = {0: None, end_frame: None}
        for first, last in merged:
            states[first] = glow_material
            states[last] = None

        for frame, material in sorted(states.items()):
            result = channel.add_key(
                time=unreal.FrameNumber(int(frame)),
                new_value=material,
            )
            require(result is not None, "Could not add highlight key")

    progress("Building camera orbit, one-second transitions, and camera cut")
    camera = spawn(unreal.CineCameraActor, "Camera_Clean", machine_center)
    movable(camera)
    cine = camera.get_cine_camera_component()
    require(cine is not None, "CineCamera component missing")

    filmback = cine.get_editor_property("filmback")
    filmback.set_editor_property("sensor_height", 24.0)
    filmback.set_editor_property("sensor_width", 24.0 * width / height)
    cine.set_editor_property("filmback", filmback)
    cine.set_editor_property("current_focal_length", 36.0)
    cine.set_editor_property("current_aperture", 4.0)
    cine.set_editor_property("constrain_aspect_ratio", True)
    cine.set_editor_property("post_process_blend_weight", 0.0)

    focus = cine.get_editor_property("focus_settings")
    focus.set_editor_property("focus_method", unreal.CameraFocusMethod.DISABLE)
    cine.set_editor_property("focus_settings", focus)

    camera_binding = sequence.add_possessable(camera)
    camera_binding.set_display_name("Clean studio camera")
    _, camera_channels = transform_channels(camera_binding, end_frame)

    cut_track = sequence.add_track(unreal.MovieSceneCameraCutTrack)
    require(cut_track is not None, "Could not create camera cut track")
    cut_section = cut_track.add_section()
    require(cut_section is not None, "Could not create camera cut section")
    cut_section.set_range(0, end_frame)

    camera_id = unreal.MovieSceneObjectBindingID()
    camera_id.set_editor_property("guid", camera_binding.get_id())
    cut_section.set_camera_binding_id(camera_id)

    def shot_position(target, distance, azimuth, elevation):
        azimuth = math.radians(azimuth)
        elevation = math.radians(elevation)
        # Blender front is -Y; viewer-right from the front is +X.
        direction_b = [
            math.sin(azimuth) * math.cos(elevation),
            -math.cos(azimuth) * math.cos(elevation),
            math.sin(elevation),
        ]
        return add(target, mul(mv(B_TO_U, direction_b), distance * 100))

    first_shot = procedure["steps"][0]["shot"]
    title_end_target = machine_center[:]
    title_end_position = shot_position(
        title_end_target,
        float(first_shot["distance"]),
        float(first_shot["azimuth"]),
        float(first_shot["elevation"]),
    )

    shot_segments = []
    previous_position = title_end_position
    previous_target = title_end_target
    for start, finish, step in scheduled_steps:
        shot = step["shot"]
        transition_end = start + fps
        destination_target = target_at(shot["target"], transition_end)
        destination_position = shot_position(
            destination_target,
            float(shot["distance"]),
            float(shot["azimuth"]),
            float(shot["elevation"]),
        )
        shot_segments.append((
            start,
            transition_end,
            previous_position[:],
            previous_target[:],
            destination_position[:],
            destination_target[:],
        ))
        previous_position = destination_position
        previous_target = destination_target

    previous_euler = None
    initial_position = None
    initial_rotation = None

    # Holds are literal camera holds after the first second of each step.
    # Later shots account for accumulated preceding part motions.
    for frame in range(end_frame + 1):
        if frame <= title_frame:
            fraction = smoothstep(frame / title_frame)
            azimuth = -40 + (float(first_shot["azimuth"]) + 40) * fraction
            target = machine_center[:]
            position = shot_position(
                target,
                float(first_shot["distance"]),
                azimuth,
                float(first_shot["elevation"]),
            )
        else:
            position = title_end_position[:]
            target = title_end_target[:]
            for start, transition_end, p0, t0, p1, t1 in shot_segments:
                if frame < start:
                    break
                if frame < transition_end:
                    fraction = smoothstep((frame - start) / fps)
                    position = lerp(p0, p1, fraction)
                    target = lerp(t0, t1, fraction)
                    break
                position, target = p1[:], t1[:]

        rotation = unreal.MathLibrary.find_look_at_rotation(
            vector(position), vector(target)
        )
        euler = [rotation.roll, rotation.pitch, rotation.yaw]
        if previous_euler is not None:
            for axis in range(3):
                euler[axis] += 360 * round(
                    (previous_euler[axis] - euler[axis]) / 360
                )
        previous_euler = euler

        for axis in range(3):
            add_key(camera_channels[axis], frame, position[axis])
            add_key(camera_channels[axis + 3], frame, euler[axis])

        if frame == 0:
            initial_position = position
            initial_rotation = rotation

    camera.set_actor_location(vector(initial_position), False, False)
    camera.set_actor_rotation(initial_rotation, False)

    progress("Creating Movie Render Queue primary configuration")
    config = create_asset(
        CONFIG_PATH,
        unreal.MoviePipelinePrimaryConfig,
        unreal.MoviePipelinePrimaryConfigFactory(),
    )
    deferred = config.find_or_add_setting_by_class(
        unreal.MoviePipelineDeferredPassBase
    )
    png = config.find_or_add_setting_by_class(
        unreal.MoviePipelineImageSequenceOutput_PNG
    )
    output = config.find_or_add_setting_by_class(
        unreal.MoviePipelineOutputSetting
    )
    aa = config.find_or_add_setting_by_class(
        unreal.MoviePipelineAntiAliasingSetting
    )
    require(
        all(item is not None for item in (deferred, png, output, aa)),
        "Could not create all MRQ settings",
    )

    frames_path = os.path.join(ROOT, "frames")
    os.makedirs(frames_path, exist_ok=True)
    require(os.path.isdir(frames_path), "Output path is not a directory")

    output.set_editor_property(
        "output_directory", unreal.DirectoryPath(frames_path + "/")
    )
    output.set_editor_property("file_name_format", "f_{frame_number}")
    output.set_editor_property("output_resolution", unreal.IntPoint(width, height))
    output.set_editor_property("zero_pad_frame_numbers", 6)
    output.set_editor_property("frame_number_offset", 0)
    output.set_editor_property("override_existing_output", True)
    output.set_editor_property("use_custom_frame_rate", True)
    output.set_editor_property("output_frame_rate", unreal.FrameRate(fps, 1))
    output.set_editor_property("use_custom_playback_range", True)
    output.set_editor_property("custom_start_frame", 0)
    output.set_editor_property("custom_end_frame", end_frame)

    aa.set_editor_property("spatial_sample_count", 1)
    aa.set_editor_property("temporal_sample_count", 4)
    aa.set_editor_property("override_anti_aliasing", True)
    aa.set_editor_property(
        "anti_aliasing_method", unreal.AntiAliasingMethod.AAM_NONE
    )
    aa.set_editor_property("engine_warm_up_count", 32)
    aa.set_editor_property("render_warm_up_count", 8)

    EAL.set_metadata_tag(config, "Spike.Map", LEVEL_PATH)
    EAL.set_metadata_tag(config, "Spike.Sequence", SEQUENCE_PATH)
    EAL.set_metadata_tag(sequence, "Spike.RenderConfig", CONFIG_PATH)

    progress("Saving every generated asset and the level")
    require(LEVELS.save_current_level(), "Could not save level")
    require(
        EAL.save_directory("/Game", only_if_is_dirty=False, recursive=True),
        "Could not save every project asset",
    )
    require(
        unreal.EditorLoadingAndSavingUtils.save_dirty_packages(True, True),
        "Dirty package save failed",
    )
    for path in (LEVEL_PATH, SEQUENCE_PATH, CONFIG_PATH):
        require(EAL.does_asset_exist(path), "Required output asset missing: " + path)

    # Creating tracks does not evaluate them: these are rest-state pivots.
    pivots = {}
    for name, index in part_indices.items():
        pivot = xyz(node_actors[index].get_actor_location())
        require(
            length(sub(pivot, controls[name]["pivot"])) < 0.001,
            "Rest pivot changed before save: " + name,
        )
        pivots[name] = pivot

    final_actors = [
        actor for actor in ACTORS.get_all_level_actors()
        if actor.get_path_name() not in existing
    ]
    result = {
        "level": LEVEL_PATH,
        "sequence": SEQUENCE_PATH,
        "render_config": CONFIG_PATH,
        "fps": fps,
        "sequence_range": {
            "start_frame": 0,
            "end_frame_exclusive": end_frame,
            "duration_seconds": end_frame / fps,
        },
        "resolution": {"width": width, "height": height},
        "actors": [
            {
                "name": actor.get_name(),
                "label": actor.get_actor_label(),
                "path": actor.get_path_name(),
            }
            for actor in sorted(final_actors, key=lambda item: item.get_name())
        ],
        "machine_bounds_cm": {
            "min": bounds_min,
            "max": bounds_max,
            "center": machine_center,
            "extent": mul(sub(bounds_max, bounds_min), 0.5),
        },
        "moving_part_pivots_cm": pivots,
        "static_catalog_parts": sorted(static_part_names),
        "coordinate_conversion": {
            "blender_to_unreal_basis": B_TO_U,
            "metres_to_centimetres": 100.0,
            "scene_offset_cm": scene_offset,
            "maximum_calibration_error_cm": calibration_error,
        },
    }

    # Never write success until every check and save has succeeded.
    atomic_json(SUCCESS, result)
    progress(
        "SUCCESS: {} actors; frames 0..{}; wrote {}"
        .format(len(final_actors), end_frame - 1, SUCCESS)
    )


try:
    main()
except Exception:
    failure = traceback.format_exc()
    for marker in (SUCCESS, SUCCESS + ".tmp"):
        if os.path.exists(marker):
            os.remove(marker)
    unreal.log_error("[SPIKE BUILD] FAILED\n" + failure)
    raise
