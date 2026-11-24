# /home/peder/spike/build.py
#
# Run:
# /home/peder/UE/Engine/Binaries/Linux/UnrealEditor-Cmd \
#   /home/peder/spike/Spike.uproject \
#   -run=pythonscript -script=/home/peder/spike/build.py \
#   -unattended -nosplash -stdout -FullStdOutLogOutput

import unreal
import collections
import itertools
import json
import math
import os
import re
import struct
import traceback
import unicodedata


ROOT = "/home/peder/spike"
INPUT = ROOT + "/input"
SUCCESS = ROOT + "/build_ok.json"

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
DISPLAY = unreal.SequenceTimeUnit.DISPLAY_RATE

# Blender -> glTF, for Blender's standard glTF export:
# (x, y, z) -> (x, z, -y).
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

KEEP_ALIVE = []


def progress(message):
    print("[SPIKE BUILD] " + message, flush=True)
    unreal.log("[SPIKE BUILD] " + message)


def require(condition, message):
    if not condition:
        raise RuntimeError(message)


def read_json(name):
    path = INPUT + "/" + name
    require(os.path.isfile(path), "Missing input: " + path)
    with open(path, "r", encoding="utf-8") as handle:
        return json.load(handle)


def normalized(value):
    value = unicodedata.normalize("NFKD", str(value))
    return re.sub(r"[^a-z0-9]", "", value.lower())


def vector(values):
    return unreal.Vector(*[float(x) for x in values])


def xyz(value):
    return [float(value.x), float(value.y), float(value.z)]


def add(a, b):
    return [a[i] + b[i] for i in range(3)]


def sub(a, b):
    return [a[i] - b[i] for i in range(3)]


def mul(a, scalar):
    return [x * scalar for x in a]


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


def determinant3(m):
    return dot(m[0], cross(m[1], m[2]))


def rotation_basis(matrix, description):
    """Remove positive scale; reject shear or mirrored local frames."""
    columns = transpose(matrix_linear(matrix))
    columns = [unit(column) for column in columns]
    require(
        max(abs(dot(columns[i], columns[j]))
            for i in range(3) for j in range(i + 1, 3)) < 1e-4,
        description + ": sheared transform cannot define an orthogonal hinge frame",
    )
    result = transpose(columns)
    require(
        determinant3(result) > 0.999,
        description + ": mirrored node transform; apply negative scale in Blender",
    )
    return result


def quaternion_matrix(q):
    x, y, z, w = q
    size = math.sqrt(x*x + y*y + z*z + w*w)
    require(size > 1e-12, "Invalid glTF quaternion")
    x, y, z, w = [v / size for v in (x, y, z, w)]
    return [
        [1 - 2*(y*y + z*z), 2*(x*y - z*w), 2*(x*z + y*w)],
        [2*(x*y + z*w), 1 - 2*(x*x + z*z), 2*(y*z - x*w)],
        [2*(x*z - y*w), 2*(y*z + x*w), 1 - 2*(x*x + y*y)],
    ]


def matrix_rotator(m):
    """A conventional rotation matrix -> UE quaternion -> UE Rotator."""
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
        return [[float(values[column * 4 + row])
                 for column in range(4)] for row in range(4)]

    result = identity4()
    r = quaternion_matrix(node.get("rotation", [0, 0, 0, 1]))
    scale = node.get("scale", [1, 1, 1])
    position = node.get("translation", [0, 0, 0])
    for row in range(3):
        for column in range(3):
            result[row][column] = r[row][column] * scale[column]
        result[row][3] = position[row]
    return result


def asset(path):
    result = unreal.load_asset(path)
    require(result is not None, "Could not load asset: " + path)
    return result


def create_asset(path, asset_class, factory):
    folder, name = path.rsplit("/", 1)
    require(EAL.make_directory(folder), "Cannot create asset folder: " + folder)
    result = TOOLS.create_asset(name, folder, asset_class, factory)
    require(result is not None, "Could not create asset: " + path)
    return result


def spawn(actor_class, label, location, rotation=None):
    actor = ACTORS.spawn_actor_from_class(
        actor_class,
        vector(location),
        rotation or unreal.Rotator(0, 0, 0),
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
    # A meshless StaticMeshActor supplies a reliable native root component,
    # including when running without the interactive editor.
    result = spawn(unreal.StaticMeshActor, label, position, rotation)
    movable(result)
    component = result.static_mesh_component
    component.set_collision_enabled(unreal.CollisionEnabled.NO_COLLISION)
    component.set_editor_property("cast_shadow", False)
    return result


def mesh_components(actor):
    return [
        c for c in actor.get_components_by_class(unreal.StaticMeshComponent)
        if c.get_editor_property("static_mesh") is not None
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
        xyz(transform.transform_location(vector(p)))
        for p in itertools.product(
            (low[0], high[0]), (low[1], high[1]), (low[2], high[2])
        )
    ]
    return (
        [min(p[i] for p in points) for i in range(3)],
        [max(p[i] for p in points) for i in range(3)],
    )


def bounds(components):
    require(components, "No renderable mesh components in bounds query")
    boxes = [component_bounds(c) for c in components]
    low = [min(box[0][i] for box in boxes) for i in range(3)]
    high = [max(box[1][i] for box in boxes) for i in range(3)]
    return low, high


def material_constant(material, value, property_name):
    if isinstance(value, (tuple, list)):
        expression = unreal.MaterialEditingLibrary.create_material_expression(
            material, unreal.MaterialExpressionConstant3Vector, -300, 0
        )
        expression.set_editor_property(
            "constant", unreal.LinearColor(*value, 1.0)
        )
    else:
        expression = unreal.MaterialEditingLibrary.create_material_expression(
            material, unreal.MaterialExpressionConstant, -300, 120
        )
        expression.set_editor_property("r", float(value))
    require(expression is not None, "Material expression creation failed")
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
        material_constant(material, color, unreal.MaterialProperty.MP_EMISSIVE_COLOR)
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
    channel.add_key(
        time=unreal.FrameNumber(int(frame)),
        new_value=float(value),
        time_unit=DISPLAY,
        interpolation=LINEAR,
    )


def transform_channels(sequence, binding, end_frame):
    track = binding.add_track(unreal.MovieScene3DTransformTrack)
    require(track is not None, "Could not create transform track")
    section = track.add_section()
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
    """Rodrigues rotation, conventional right-handed mathematical angle."""
    angle = math.radians(degrees)
    p = sub(point, pivot)
    c, s = math.cos(angle), math.sin(angle)
    rotated = add(
        add(mul(p, c), mul(cross(axis, p), s)),
        mul(axis, dot(axis, p) * (1 - c)),
    )
    return add(pivot, rotated)


def main():
    if os.path.exists(SUCCESS):
        os.remove(SUCCESS)

    progress("Reading and validating inputs")
    parts = read_json("parts.json")
    procedure = read_json("procedure.json")
    timing = read_json("timing.json")
    render = read_json("render.json")
    glb_path = INPUT + "/EW7F7649U2.glb"
    require(os.path.isfile(glb_path), "Missing " + glb_path)
    gltf = read_glb(glb_path)

    fps = int(timing["fps"])
    require(fps > 0 and fps == timing["fps"], "fps must be a positive integer")
    width, height = int(render["width"]), int(render["height"])
    require(width > 0 and height > 0, "Invalid output resolution")
    require(len(procedure["steps"]) == len(timing["steps"]), "Step count mismatch")

    end_frame = math.ceil((float(timing["total"]) + 1.0) * fps)
    title_frame = round(float(timing["title_seconds"]) * fps)
    require(0 < title_frame < end_frame, "Invalid title duration")

    scheduled_steps = []
    previous_end = title_frame
    for number, (step, clock) in enumerate(
        zip(procedure["steps"], timing["steps"]), 1
    ):
        start = round(float(clock["start"]) * fps)
        finish = round((float(clock["start"]) + float(clock["length"])) * fps)
        require(start >= previous_end, "Overlapping step {}".format(number))
        require(finish > start and finish <= end_frame, "Invalid step range")
        require(start + fps <= finish, "A shot transition requires one second")
        if step.get("actions"):
            require(start + 3 * fps <= finish, "An action requires three seconds")
        for action in step.get("actions", []):
            require(action["part"] in parts, "Unknown action part")
            require(0 <= float(action["to"]) <= 1, "Action fraction outside [0, 1]")
        shot = step["shot"]
        require(float(shot["distance"]) > 0, "Non-positive shot distance")
        scheduled_steps.append((start, finish, step))
        previous_end = finish

    # Read only the active glTF scene.
    nodes = gltf["nodes"]
    scene = gltf["scenes"][gltf.get("scene", 0)]
    parent_index = {}
    world_matrices = {}
    active = []
    visiting = set()

    def visit(index, parent, parent_world):
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
        i: nodes[i].get("name", "GLTF_Node_{}".format(i)) for i in active
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
    # These folders are owned by this build script.
    for folder in (
        "/Game/Machine", "/Game/Seq", "/Game/Render", "/Game/Studio"
    ):
        if EAL.does_directory_exist(folder):
            require(EAL.delete_directory(folder), "Cannot replace " + folder)
        require(EAL.make_directory(folder), "Cannot create " + folder)

    require(EAL.make_directory("/Game/Maps"), "Cannot create Maps folder")
    if EAL.does_asset_exist(LEVEL_PATH):
        require(EAL.delete_asset(LEVEL_PATH), "Cannot replace " + LEVEL_PATH)
    require(LEVELS.new_level(LEVEL_PATH), "Could not create new level")

    existing = {a.get_path_name() for a in ACTORS.get_all_level_actors()}

    progress("Importing glTF scene with unbaked, separate static meshes")
    # Persist an explicit pipeline copy so the build does not depend on saved
    # interactive import-dialog settings.
    pipeline_source = "/Interchange/Pipelines/DefaultSceneAssetsPipeline"
    scene_pipeline_path = "/Interchange/Pipelines/DefaultSceneLevelPipeline"
    asset(pipeline_source)
    scene_pipeline = asset(scene_pipeline_path)

    pipeline = EAL.duplicate_asset(
        pipeline_source, "/Game/Machine/SpikeSceneAssetsPipeline"
    )
    require(pipeline is not None, "Could not duplicate scene import pipeline")
    pipeline.get_editor_property("common_meshes_properties").set_editor_property(
        "bake_meshes", False
    )
    mesh_pipeline = pipeline.get_editor_property("mesh_pipeline")
    mesh_pipeline.set_editor_property("combine_static_meshes", False)
    mesh_pipeline.set_editor_property("import_static_meshes", True)
    KEEP_ALIVE.extend([pipeline, scene_pipeline])

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
    KEEP_ALIVE.extend([source, parameters])

    # import_scene is the synchronous scene-import entry point.
    require(
        manager.import_scene("/Game/Machine", source, parameters),
        "Interchange scene import failed",
    )

    imported = [
        a for a in ACTORS.get_all_level_actors()
        if a.get_path_name() not in existing
    ]
    require(imported, "Scene import spawned no actors")
    require(any(mesh_components(a) for a in imported), "Scene import has no meshes")
    for actor in imported:
        movable(actor)

    # Match source nodes to scene actors. Actor labels are preferred. A mesh-name
    # fallback is allowed only when it is unambiguous.
    node_actors = {}
    used = set()

    for index in active:
        key = normalized(node_names[index])
        candidates = [
            a for a in imported
            if normalized(a.get_actor_label()) == key
            and a.get_path_name() not in used
        ]
        require(len(candidates) <= 1, "Duplicate imported label: " + node_names[index])
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
                normalized(c.get_editor_property("static_mesh").get_name()) in keys
                for c in mesh_components(actor)
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
            source_position = mv(
                G_TO_B, matrix_position(world_matrices[index])
            )
            pairs.append((
                source_position,
                xyz(node_actors[index].get_actor_location()),
            ))
    require(len(pairs) >= 3, "Need at least three imported moving-part pivots")

    # Blender and UE are both Z-up, but opposite handedness. Test every
    # horizontal signed-axis permutation with determinant -1. Translation
    # accommodates a common importer scene-root offset; scale MUST be 100.
    candidates = []
    for swap in (False, True):
        for sx, sy in itertools.product((-1.0, 1.0), repeat=2):
            c = (
                [[0, sx, 0], [sy, 0, 0], [0, 0, 1]]
                if swap else
                [[sx, 0, 0], [0, sy, 0], [0, 0, 1]]
            )
            if determinant3(c) > -0.999:
                continue
            offsets = [sub(u, mul(mv(c, b), 100.0)) for b, u in pairs]
            offset = [
                sum(p[i] for p in offsets) / len(offsets) for i in range(3)
            ]
            error = max(
                length(sub(add(mul(mv(c, b), 100), offset), u))
                for b, u in pairs
            )
            candidates.append((error, c, offset))

    candidates.sort(key=lambda item: item[0])
    error, B_TO_U, scene_offset = candidates[0]
    require(
        error <= PIVOT_TOLERANCE_CM,
        "Importer pivot check failed: {:.4f} cm error. "
        "Meshes may have baked transforms or the exporter used another basis."
        .format(error),
    )
    require(
        candidates[1][0] > PIVOT_TOLERANCE_CM,
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
            matrix, "glTF node " + ("scene" if index is None else node_names[index])
        )
        return mm(mm(G_TO_U, source_rotation), U_TO_G)

    progress("Blender -> UE basis: {}; offset: {}; maximum error: {:.5f} cm"
             .format(B_TO_U, scene_offset, error))

    # Validate metadata locations independently of the fit.
    for name, index in part_indices.items():
        metadata_position = [float(x) for x in parts[name]["location"]]
        source_world_b = mv(G_TO_B, matrix_position(world_matrices[index]))
        if parts[name].get("parent") is None:
            require(
                length(sub(metadata_position, source_world_b)) * 100
                <= PIVOT_TOLERANCE_CM,
                "parts.json location disagrees with GLB for " + name,
            )
        else:
            parent_name = parts[name]["parent"]
            parent_node = node_for_name(parent_name)
            require(
                parent_index[index] == parent_node,
                "Explicit parts.json parent must match the GLB parent: " + name,
            )
            source_local_b = mv(
                G_TO_B, matrix_position(gltf_node_matrix(nodes[index]))
            )
            require(
                length(sub(metadata_position, source_local_b)) * 100
                <= PIVOT_TOLERANCE_CM,
                "Parent-space location disagrees with GLB for " + name,
            )

    # Validate all represented node pivots, not only the calibration points.
    for index, actor in node_actors.items():
        pivot_error = length(
            sub(xyz(actor.get_actor_location()), source_position_ue(index))
        )
        require(
            pivot_error <= PIVOT_TOLERANCE_CM,
            "Imported pivot mismatch for {}: {:.4f} cm"
            .format(node_names[index], pivot_error),
        )

    progress("Restoring complete node attachment hierarchy")
    machine_root = empty_actor("MachineRoot", scene_offset)

    # Interchange may omit empty glTF nodes. Supply native-root actors for them.
    for index in active:
        if index not in node_actors:
            require("mesh" not in nodes[index], "A mesh node was not imported")
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

    mapped_paths = {a.get_path_name() for a in node_actors.values()}
    for actor in imported:
        if actor.get_path_name() in mapped_paths:
            continue
        # Keep importer-created primitive actors beneath their source node.
        cursor = actor.get_attach_parent_actor()
        found_node = False
        while cursor is not None:
            if cursor.get_path_name() in mapped_paths:
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
            if component.get_path_name() not in component_paths:
                component_paths.add(component.get_path_name())
                machine_components.append(component)
    require(machine_components, "Machine hierarchy contains no meshes")

    bounds_min, bounds_max = bounds(machine_components)
    machine_center = mul(add(bounds_min, bounds_max), 0.5)
    require(
        20 < bounds_max[2] - bounds_min[2] < 200,
        "Implausible appliance height; check metre-to-centimetre conversion",
    )

    # Cache original centres before inserting control actors.
    target_centers = {}
    for index in active:
        components = [
            c for actor in descendants(node_actors[index])
            for c in mesh_components(actor)
        ]
        if components:
            lo, hi = bounds(components)
            target_centers[index] = mul(add(lo, hi), 0.5)
        else:
            target_centers[index] = source_position_ue(index)

    progress("Creating pivot-preserving translation and spin controls")
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
        # Inner to outer: useful for analytically moving a rest-space point.
        moving_ancestry[index] = chain

    for name, description in parts.items():
        index = part_indices[name]
        actor = node_actors[index]
        old_parent = actor.get_attach_parent_actor()
        require(old_parent is not None, "Moving part has no machine parent")
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

        # The animated controls start with identity relative transforms.
        slide.set_actor_relative_location(vector([0, 0, 0]), False, False)
        slide.set_actor_relative_rotation(unreal.Rotator(0, 0, 0), False, False)
        slide.set_actor_relative_scale3d(vector([1, 1, 1]))
        spin.set_actor_relative_location(vector([0, 0, 0]), False, False)
        spin.set_actor_relative_rotation(unreal.Rotator(0, 0, 0), False, False)
        spin.set_actor_relative_scale3d(vector([1, 1, 1]))

        motion = description["motion"]
        translation_b = [float(v) for v in motion.get("translate", [0, 0, 0])]
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
        degrees = float(rotation["degrees"]) if rotation else 0.0
        axis_b = [0.0, 0.0, 0.0]
        axis_b["XYZ".index(rotation["axis"].upper()) if rotation else 0] = 1.0
        axis_u = mv(B_TO_U, axis_b)

        # A reflection changes the sign of an axial rotation. Obtain UE's
        # Roll/Pitch/Yaw sign convention from a one-degree quaternion.
        half = math.radians(-1.0) * 0.5
        one_degree = unreal.Quat(
            axis_u[0] * math.sin(half),
            axis_u[1] * math.sin(half),
            axis_u[2] * math.sin(half),
            math.cos(half),
        ).rotator()
        rotation_per_degree = [
            one_degree.roll, one_degree.pitch, one_degree.yaw
        ]

        world_axis = unit(mv(node_rotation, axis_u))
        controls[name] = {
            "slide": slide,
            "spin": spin,
            "pivot": pivot,
            "translation": slide_translation,
            "world_translation": world_translation,
            "degrees": degrees,
            "rotation_per_degree": rotation_per_degree,
            "world_axis": world_axis,
        }

        require(
            length(sub(xyz(actor.get_actor_location()), pivot)) < 0.001,
            "Rig construction displaced " + name,
        )

    progress("Building clean studio")
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
        floor.static_mesh_component.set_static_mesh(asset("/Engine/BasicShapes/Cube")),
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
        unreal.SkyLight, "Studio_SkyLight",
        add(machine_center, [0, 0, 200])
    )
    sky_component = sky.get_component_by_class(unreal.SkyLightComponent)
    sky_component.set_mobility(unreal.ComponentMobility.MOVABLE)
    sky_component.set_editor_property(
        "source_type", unreal.SkyLightSourceType.SLS_SPECIFIED_CUBEMAP
    )
    sky_component.set_editor_property(
        "cubemap",
        asset("/Engine/MapTemplates/Sky/DaylightAmbientCubemap"),
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
        component.set_mobility(unreal.ComponentMobility.MOVABLE)
        component.set_editor_property("intensity_units", unreal.LightUnits.LUMENS)
        component.set_intensity(lumens)
        component.set_editor_property("source_width", float(size[0]))
        component.set_editor_property("source_height", float(size[1]))
        component.set_editor_property("attenuation_radius", 1200.0)
        return light

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
    pp_setting("motion_blur_amount", 0.0)
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

    # Fraction curves are explicitly held until each action begins.
    fraction_keys = {name: {0: 0.0} for name in parts}
    current_fraction = {name: 0.0 for name in parts}
    action_ranges = {name: [] for name in parts}

    for start, finish, step in scheduled_steps:
        action_names = [a["part"] for a in step.get("actions", [])]
        require(
            len(action_names) == len(set(action_names)),
            "A step contains multiple simultaneous actions for the same part",
        )
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
        _, slide_channels = transform_channels(sequence, slide_binding, end_frame)

        spin_binding = sequence.add_possessable(control["spin"])
        spin_binding.set_display_name(name + " — unbounded hinge/thread rotation")
        _, spin_channels = transform_channels(sequence, spin_binding, end_frame)

        for frame, fraction in sorted(fraction_keys[name].items()):
            for axis in range(3):
                add_key(
                    slide_channels[axis], frame,
                    control["translation"][axis] * fraction,
                )
                add_key(
                    spin_channels[3 + axis], frame,
                    control["rotation_per_degree"][axis]
                    * control["degrees"] * fraction,
                )

    def fraction_at(name, frame):
        value = 0.0
        for first, last, initial, final in action_ranges[name]:
            if frame < first:
                break
            if frame < last:
                return initial + (final - initial) * (frame - first) / (last - first)
            value = final
        return value

    def target_at(target, frame):
        if target == "Machine":
            return machine_center[:]
        index = node_for_name(target)
        point = target_centers[index][:]
        # Apply inner motion first; outer moving parents then carry it along.
        for name in moving_ancestry[index]:
            fraction = fraction_at(name, frame)
            control = controls[name]
            point = rotate_point(
                point, control["pivot"], control["world_axis"],
                -control["degrees"] * fraction,
            )
            point = add(point, mul(control["world_translation"], fraction))
        return point

    progress("Adding animated emissive overlays")
    # Union intervals per component, so overlapping group/child highlights do
    # not reset each other. The underlying imported materials remain untouched.
    highlight_intervals = collections.defaultdict(list)
    highlight_components = {}

    for start, finish, step in scheduled_steps:
        if not step.get("highlight"):
            continue
        actor = node_actors[node_for_name(step["highlight"])]
        components = [
            component for item in descendants(actor)
            for component in mesh_components(item)
        ]
        require(components, "Highlight has no meshes: " + step["highlight"])
        for component in components:
            path = component.get_path_name()
            highlight_components[path] = component
            highlight_intervals[path].append((start, finish))

    owner_bindings = {}
    for path, component in highlight_components.items():
        intervals = sorted(highlight_intervals[path])
        merged = []
        for first, last in intervals:
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
            channel.add_key(
                time=unreal.FrameNumber(frame),
                new_value=material,
                time_unit=DISPLAY,
            )

    progress("Building camera orbit, shot transitions, and camera cuts")
    camera = spawn(
        unreal.CineCameraActor, "Camera_Clean", machine_center
    )
    movable(camera)
    cine = camera.get_cine_camera_component()
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
    _, camera_channels = transform_channels(sequence, camera_binding, end_frame)

    cut_track = sequence.add_track(unreal.MovieSceneCameraCutTrack)
    require(cut_track is not None, "Could not create camera cut track")
    cut_section = cut_track.add_section()
    cut_section.set_range(0, end_frame)
    camera_id = unreal.MovieSceneObjectBindingID()
    camera_id.set_editor_property("guid", camera_binding.get_id())
    cut_section.set_camera_binding_id(camera_id)

    def shot_position(target, distance, azimuth, elevation):
        azimuth, elevation = math.radians(azimuth), math.radians(elevation)
        # Blender front is -Y. +X is the viewer's right in a front view.
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
            start, transition_end,
            previous_position[:], previous_target[:],
            destination_position[:], destination_target[:],
        ))
        previous_position = destination_position
        previous_target = destination_target

    previous_euler = None
    initial_position = None
    initial_rotation = None

    for frame in range(end_frame + 1):
        if frame <= title_frame:
            fraction = smoothstep(frame / title_frame)
            azimuth = -40 + (float(first_shot["azimuth"]) + 40) * fraction
            target = machine_center[:]
            position = shot_position(
                target, float(first_shot["distance"]), azimuth,
                float(first_shot["elevation"]),
            )
        else:
            position, target = title_end_position[:], title_end_target[:]
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
            initial_position, initial_rotation = position, rotation

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

    os.makedirs(ROOT + "/frames", exist_ok=True)
    output.set_editor_property(
        "output_directory", unreal.DirectoryPath(ROOT + "/frames/")
    )
    output.set_editor_property("file_name_format", "f_{frame_number}")
    output.set_editor_property(
        "output_resolution", unreal.IntPoint(width, height)
    )
    output.set_editor_property("zero_pad_frame_numbers", 6)
    output.set_editor_property("frame_number_offset", 0)
    output.set_editor_property("override_existing_output", True)
    output.set_editor_property("use_custom_frame_rate", True)
    output.set_editor_property("output_frame_rate", unreal.FrameRate(fps, 1))
    output.set_editor_property("use_custom_playback_range", True)
    output.set_editor_property("custom_start_frame", 0)
    # MRQ's custom end frame is exclusive, matching Sequencer playback.
    output.set_editor_property("custom_end_frame", end_frame)

    aa.set_editor_property("spatial_sample_count", 1)
    aa.set_editor_property("temporal_sample_count", 4)
    aa.set_editor_property("override_anti_aliasing", True)
    aa.set_editor_property("anti_aliasing_method", unreal.AntiAliasingMethod.AAM_NONE)
    aa.set_editor_property("engine_warm_up_count", 32)
    aa.set_editor_property("render_warm_up_count", 8)

    # Leave useful associations on the configuration without creating or
    # executing a render job.
    EAL.set_metadata_tag(config, "Spike.Map", LEVEL_PATH)
    EAL.set_metadata_tag(config, "Spike.Sequence", SEQUENCE_PATH)
    EAL.set_metadata_tag(sequence, "Spike.RenderConfig", CONFIG_PATH)

    progress("Saving all assets and level")
    require(LEVELS.save_current_level(), "Could not save level")
    require(
        EAL.save_directory("/Game", only_if_is_dirty=False, recursive=True),
        "Could not save every project asset",
    )
    require(
        unreal.EditorLoadingAndSavingUtils.save_dirty_packages(True, True),
        "Dirty package save failed",
    )

    # Actors are still at the rest pose: sequence construction never evaluates
    # or leaves the editor world at an animated frame.
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
            for actor in sorted(final_actors, key=lambda a: a.get_name())
        ],
        "machine_bounds_cm": {
            "min": bounds_min,
            "max": bounds_max,
            "center": machine_center,
            "extent": mul(sub(bounds_max, bounds_min), 0.5),
        },
        "moving_part_pivots_cm": pivots,
        "coordinate_conversion": {
            "blender_to_unreal_basis": B_TO_U,
            "metres_to_centimetres": 100.0,
            "scene_offset_cm": scene_offset,
            "maximum_calibration_error_cm": error,
        },
    }

    temporary = SUCCESS + ".tmp"
    with open(temporary, "w", encoding="utf-8") as handle:
        json.dump(result, handle, indent=2, ensure_ascii=False)
        handle.write("\n")
        handle.flush()
        os.fsync(handle.fileno())
    os.replace(temporary, SUCCESS)

    progress(
        "SUCCESS: {} actors; frames 0..{}; wrote {}"
        .format(len(final_actors), end_frame - 1, SUCCESS)
    )


try:
    main()
except Exception:
    if os.path.exists(SUCCESS):
        os.remove(SUCCESS)
    unreal.log_error("[SPIKE BUILD] FAILED\n" + traceback.format_exc())
    raise
