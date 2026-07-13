from dataclasses import dataclass
import os
import math
import hashlib

import bpy
from mathutils import Matrix

from aion_formats.cgf import get_cgf
from aion_formats.cgf.shader_semantics import resolve_client_shader_semantics
from aion_formats.cgf.texture_sequences import (
    UNKNOWN_NOT_DECODED,
    resolve_texture_sequence,
)


_MAT_CACHE = {}
_LAST_IMPORT_REPORT = None
_TEXTURE_SEQUENCE_STATS = None
_SHADER_UV_SCROLL_STATS = None


MISSING_FILE = "missing_file"
PARSE_ERROR = "parse_error"
EMPTY_MESH = "empty_mesh"
NO_GEOMETRY_FOR_MODE = "no_geometry_for_mode"
IMPORT_EXCEPTION = "import_exception"
UNSUPPORTED = "unsupported"
UNKNOWN = "unknown"


@dataclass(frozen=True)
class CgfImportReport:
    filepath: str
    import_mode: str
    result: str
    reason_code: str | None
    reason: str | None
    file_exists: bool
    parser_node_count: int
    parser_mesh_node_count: int
    parser_material_count: int
    candidate_mesh_node_count: int
    objects_created: int
    parser_coverage_counts: dict
    unsupported_chunks: dict
    unused_material_fields: dict
    texture_sequences_requested: bool = False
    texture_sequences_applied: int = 0
    texture_sequences_skipped: int = 0
    texture_sequence_missing_frames: int = 0
    shader_uv_scroll_requested: bool = False
    shader_uv_scroll_applied: int = 0
    shader_uv_scroll_skipped: int = 0
    source_extension: str = ""
    cga_static_import: bool = False
    cga_controller_count: int = 0
    cga_timing_present: bool = False
    cga_animation_status: str = ""
    cga_controller_animation_requested: bool = False
    cga_controller_animations_applied: int = 0


def get_last_import_report():
    return _LAST_IMPORT_REPORT


def read_matrix44(matrix_values):
    return (
        tuple(matrix_values[0:4]),
        tuple(matrix_values[4:8]),
        tuple(matrix_values[8:12]),
        (
            matrix_values[12] / 100,
            matrix_values[13] / 100,
            matrix_values[14] / 100,
            matrix_values[15],
        ),
    )


def _mode_allows(is_collide, import_mode, has_visual_surface=False):
    if import_mode == "COLLISION":
        return is_collide
    if import_mode != "VISUAL":
        raise ValueError(f"unsupported import mode: {import_mode}")
    return (not is_collide) or has_visual_surface


def _node_id(node):
    header = node.get("header") if isinstance(node, dict) else None
    if isinstance(header, dict):
        return header.get("chunk_id")
    return None


def _parent_id(node):
    parent_id = node.get("parent_id") if isinstance(node, dict) else None
    if parent_id in (None, -1, 0xFFFFFFFF):
        return None
    return parent_id


def _local_node_matrix(node):
    return Matrix(read_matrix44(node["transform"])).transposed()


def _composed_node_matrix(node, all_nodes):
    chain = []
    current = node
    seen = set()
    while isinstance(current, dict):
        current_id = _node_id(current)
        if current_id in seen:
            break
        if current_id is not None:
            seen.add(current_id)
        chain.append(current)
        parent_id = _parent_id(current)
        if parent_id is None:
            break
        current = all_nodes.get(parent_id)
        if current is None:
            break

    matrix = Matrix.Identity(4)
    for chain_node in reversed(chain):
        matrix = matrix @ _local_node_matrix(chain_node)
    return matrix


def _set_import_report(
    *,
    filepath,
    import_mode,
    result,
    reason_code=None,
    reason=None,
    file_exists=False,
    parser_node_count=0,
    parser_mesh_node_count=0,
    parser_material_count=0,
    candidate_mesh_node_count=0,
    objects_created=0,
    parser_coverage_counts=None,
    unsupported_chunks=None,
    unused_material_fields=None,
    texture_sequences_requested=False,
    texture_sequences_applied=0,
    texture_sequences_skipped=0,
    texture_sequence_missing_frames=0,
    shader_uv_scroll_requested=False,
    shader_uv_scroll_applied=0,
    shader_uv_scroll_skipped=0,
    source_extension="",
    cga_static_import=False,
    cga_controller_count=0,
    cga_timing_present=False,
    cga_animation_status="",
    cga_controller_animation_requested=False,
    cga_controller_animations_applied=0,
):
    global _LAST_IMPORT_REPORT
    _LAST_IMPORT_REPORT = CgfImportReport(
        filepath=str(filepath or ""),
        import_mode=import_mode,
        result=result,
        reason_code=reason_code,
        reason=reason,
        file_exists=bool(file_exists),
        parser_node_count=int(parser_node_count),
        parser_mesh_node_count=int(parser_mesh_node_count),
        parser_material_count=int(parser_material_count),
        candidate_mesh_node_count=int(candidate_mesh_node_count),
        objects_created=int(objects_created),
        parser_coverage_counts=dict(parser_coverage_counts or {}),
        unsupported_chunks=dict(unsupported_chunks or {}),
        unused_material_fields=dict(unused_material_fields or {}),
        texture_sequences_requested=bool(texture_sequences_requested),
        texture_sequences_applied=int(texture_sequences_applied),
        texture_sequences_skipped=int(texture_sequences_skipped),
        texture_sequence_missing_frames=int(texture_sequence_missing_frames),
        shader_uv_scroll_requested=bool(shader_uv_scroll_requested),
        shader_uv_scroll_applied=int(shader_uv_scroll_applied),
        shader_uv_scroll_skipped=int(shader_uv_scroll_skipped),
        source_extension=str(source_extension or ""),
        cga_static_import=bool(cga_static_import),
        cga_controller_count=int(cga_controller_count or 0),
        cga_timing_present=bool(cga_timing_present),
        cga_animation_status=str(cga_animation_status or ""),
        cga_controller_animation_requested=bool(cga_controller_animation_requested),
        cga_controller_animations_applied=int(cga_controller_animations_applied or 0),
    )
    return _LAST_IMPORT_REPORT


def _cancel(filepath, import_mode, reason_code, reason, **report_counts):
    _set_import_report(
        filepath=filepath,
        import_mode=import_mode,
        result="CANCELLED",
        reason_code=reason_code,
        reason=reason,
        **report_counts,
    )
    return {"CANCELLED"}


def _diagnostics_report_counts(cgf_file):
    diagnostics = cgf_file.get("_diagnostics") if isinstance(cgf_file, dict) else None
    if not isinstance(diagnostics, dict):
        return {}
    return {
        "parser_coverage_counts": diagnostics.get("parser_coverage_counts") or {},
        "unsupported_chunks": diagnostics.get("unsupported_chunks") or {},
        "unused_material_fields": diagnostics.get("unused_material_fields") or {},
    }


def _source_extension(filepath):
    return os.path.splitext(str(filepath or ""))[1].lower().lstrip(".")


def _cga_metadata_counts(cgf_file):
    diagnostics = cgf_file.get("_diagnostics") if isinstance(cgf_file, dict) else None
    unsupported = diagnostics.get("unsupported_chunks") if isinstance(diagnostics, dict) else {}
    timing_count = diagnostics.get("timing_chunk_count") if isinstance(diagnostics, dict) else 0
    controller_count = unsupported.get("Controller", 0) if isinstance(unsupported, dict) else 0
    return int(controller_count or 0), bool(timing_count)


def _cga_report_counts(
    filepath,
    cgf_file,
    *,
    animation_requested=False,
    animations_applied=0,
):
    extension = _source_extension(filepath)
    is_cga = extension == "cga"
    controller_count, timing_present = _cga_metadata_counts(cgf_file) if is_cga else (0, False)
    animation_status = ""
    if is_cga:
        animation_status = (
            "controller_decoded"
            if int(animations_applied or 0) > 0
            else "controller_not_decoded"
        )
    return {
        "source_extension": extension,
        "cga_static_import": is_cga,
        "cga_controller_count": controller_count,
        "cga_timing_present": timing_present,
        "cga_animation_status": animation_status,
        "cga_controller_animation_requested": bool(animation_requested),
        "cga_controller_animations_applied": int(animations_applied or 0),
    }


def _assign_cga_static_metadata(
    obj,
    filepath,
    cgf_file,
    *,
    animation_requested=False,
    animations_applied=0,
    animation_status=None,
):
    if _source_extension(filepath) != "cga":
        return
    controller_count, timing_present = _cga_metadata_counts(cgf_file)
    obj["aion_source_filepath"] = str(filepath)
    obj["aion_source_extension"] = ".cga"
    obj["aion_cga_static_import"] = True
    obj["aion_cga_controller_count"] = controller_count
    obj["aion_cga_timing_present"] = timing_present
    obj["aion_cga_animation_status"] = animation_status or (
        "controller_decoded" if animations_applied else "controller_not_decoded"
    )
    obj["aion_cga_controller_animation_requested"] = bool(animation_requested)
    obj["aion_cga_controller_animations_applied"] = int(animations_applied or 0)


def _decoded_cga_controllers(cgf_file):
    diagnostics = cgf_file.get("_diagnostics") if isinstance(cgf_file, dict) else None
    chunks = diagnostics.get("decoded_controller_chunks") if isinstance(diagnostics, dict) else ()
    controllers = {}
    for chunk in chunks or ():
        controller_id = chunk.get("controller_id", chunk.get("chunk_id"))
        if controller_id is None:
            continue
        controllers[int(controller_id)] = chunk
    return controllers


def _timing_frame_scale(cgf_file):
    diagnostics = cgf_file.get("_diagnostics") if isinstance(cgf_file, dict) else None
    timing_chunks = diagnostics.get("timing_chunks") if isinstance(diagnostics, dict) else ()
    if not timing_chunks:
        return 1.0, None
    timing = timing_chunks[0]
    ticks_per_frame = timing.get("ticks_per_frame") or 0
    if ticks_per_frame <= 0:
        return 1.0, timing
    return 1.0 / float(ticks_per_frame), timing


def _cga_controller_axis_to_blender(axis):
    return (
        -float(axis[0]),
        -float(axis[1]),
        -float(axis[2]),
    )


def _axis_angle_quaternion(axis, angle):
    x = float(axis[0])
    y = float(axis[1])
    z = float(axis[2])
    length = math.sqrt(x * x + y * y + z * z)
    if length <= 0.0:
        return (1.0, 0.0, 0.0, 0.0)
    half_angle = float(angle) * 0.5
    scale = math.sin(half_angle) / length
    return (math.cos(half_angle), x * scale, y * scale, z * scale)


def _quat_multiply(left, right):
    lw, lx, ly, lz = (float(value) for value in left)
    rw, rx, ry, rz = (float(value) for value in right)
    return (
        lw * rw - lx * rx - ly * ry - lz * rz,
        lw * rx + lx * rw + ly * rz - lz * ry,
        lw * ry - lx * rz + ly * rw + lz * rx,
        lw * rz + lx * ry - ly * rx + lz * rw,
    )


def _quat_conjugate(quat):
    w, x, y, z = (float(value) for value in quat)
    return (w, -x, -y, -z)


def _quat_rotate_vector(quat, vector):
    rotated = _quat_multiply(
        _quat_multiply(quat, (0.0, float(vector[0]), float(vector[1]), float(vector[2]))),
        _quat_conjugate(quat),
    )
    return rotated[1:4]


def _vector_length(vector):
    return math.sqrt(sum(float(value) * float(value) for value in vector))


def _normalized_vector(vector):
    length = _vector_length(vector)
    if length <= 0.0:
        return None
    return tuple(float(value) / length for value in vector)


def _vector_dot(left, right):
    return sum(float(left[index]) * float(right[index]) for index in range(3))


def _node_bbox_extents(node):
    vertices = (
        (node.get("mesh") or {})
        .get("vertices", {})
        .get("position")
        or ()
    )
    if not vertices:
        return None
    mins = [min(vertex[index] for vertex in vertices) for index in range(3)]
    maxs = [max(vertex[index] for vertex in vertices) for index in range(3)]
    return tuple(float(maxs[index] - mins[index]) for index in range(3))


def _flat_axis_vector_from_extents(extents):
    if not extents:
        return None
    max_extent = max(extents)
    min_extent = min(extents)
    if max_extent <= 0.0 or min_extent / max_extent > 0.6:
        return None
    axis = min(range(3), key=lambda index: extents[index])
    return (
        1.0 if axis == 0 else 0.0,
        1.0 if axis == 1 else 0.0,
        1.0 if axis == 2 else 0.0,
    )


def _controller_composition_for_node(node, keys):
    if len(keys) < 2:
        return "controller_replaces_local_rotation", None
    first_key = keys[0]
    first_axis = first_key.get("axis")
    first_angle = first_key.get("angle_radians")
    if first_axis is None or first_angle is None:
        return "controller_replaces_local_rotation", None
    bind_quaternion = _axis_angle_quaternion(
        _cga_controller_axis_to_blender(first_axis),
        first_angle,
    )
    flat_axis = _flat_axis_vector_from_extents(_node_bbox_extents(node))
    if flat_axis is None:
        return "controller_replaces_local_rotation", None
    bind_flat_axis = _normalized_vector(_quat_rotate_vector(bind_quaternion, flat_axis))
    if bind_flat_axis is None:
        return "controller_replaces_local_rotation", None

    for key in keys[1:]:
        angle = key.get("angle_radians")
        axis = key.get("axis")
        if axis is None or angle is None:
            continue
        if abs(float(angle) - float(first_angle)) <= 1.0e-6:
            continue
        blender_axis = _normalized_vector(_cga_controller_axis_to_blender(axis))
        if blender_axis is None:
            continue
        alignment = abs(_vector_dot(bind_flat_axis, blender_axis))
        if alignment >= 0.98:
            return "parent_axis_delta_then_bind", bind_flat_axis
    return "controller_replaces_local_rotation", None


def _controller_key_quaternion(key, *, first_key, bind_quaternion, composition):
    axis = key.get("axis")
    angle = key.get("angle_radians")
    if axis is None or angle is None:
        return None
    blender_axis = _cga_controller_axis_to_blender(axis)
    if composition == "parent_axis_delta_then_bind":
        first_angle = float(first_key.get("angle_radians") or 0.0)
        delta_quaternion = _axis_angle_quaternion(blender_axis, float(angle) - first_angle)
        return _quat_multiply(delta_quaternion, bind_quaternion)
    return _axis_angle_quaternion(blender_axis, angle)


def _apply_cga_controller_animation(obj, node, filepath, cgf_file, *, enabled=False):
    if not enabled or _source_extension(filepath) != "cga":
        return 0
    rot_ctrl_id = node.get("rot_ctrl_id")
    if rot_ctrl_id in (None, 0xFFFFFFFF):
        return 0
    parent_id = _parent_id(node)
    if parent_id is not None:
        obj["aion_cga_animation_status"] = "controller_skipped_parented_node"
        return 0

    controller = _decoded_cga_controllers(cgf_file).get(int(rot_ctrl_id))
    if not controller or controller.get("controller_component") != "rotation_axis_angle":
        return 0
    keys = tuple(controller.get("controller_keys") or ())
    if len(keys) < 2:
        return 0

    first_key = keys[0]
    first_axis = first_key.get("axis")
    first_angle = first_key.get("angle_radians")
    if first_axis is None or first_angle is None:
        return 0
    bind_quaternion = _axis_angle_quaternion(
        _cga_controller_axis_to_blender(first_axis),
        first_angle,
    )
    composition, spin_axis = _controller_composition_for_node(node, keys)
    frame_scale, timing = _timing_frame_scale(cgf_file)
    obj.rotation_mode = "QUATERNION"
    inserted_keys = 0
    max_frame = 0.0
    first_quaternion = None
    first_axis_raw = None
    first_axis_blender = None
    for key in keys:
        axis = key.get("axis")
        angle = key.get("angle_radians")
        time_ticks = key.get("time_ticks")
        if axis is None or angle is None or time_ticks is None:
            continue
        frame = 1.0 + float(time_ticks) * frame_scale
        blender_axis = _cga_controller_axis_to_blender(axis)
        quaternion = _controller_key_quaternion(
            key,
            first_key=first_key,
            bind_quaternion=bind_quaternion,
            composition=composition,
        )
        if quaternion is None:
            continue
        obj.rotation_quaternion = quaternion
        obj.keyframe_insert(data_path="rotation_quaternion", frame=frame)
        if first_quaternion is None:
            first_quaternion = tuple(float(value) for value in obj.rotation_quaternion)
            first_axis_raw = tuple(float(value) for value in axis)
            first_axis_blender = tuple(float(value) for value in blender_axis)
        max_frame = max(max_frame, frame)
        inserted_keys += 1

    if inserted_keys < 2:
        obj.animation_data_clear()
        return 0

    if first_quaternion is not None:
        obj.rotation_quaternion = first_quaternion

    obj["aion_cga_animation_status"] = "controller_decoded"
    obj["aion_controller_target_node"] = str(node.get("name") or "")
    obj["aion_controller_id"] = int(rot_ctrl_id)
    obj["aion_controller_type"] = str(controller.get("controller_component") or "")
    obj["aion_controller_axis_raw"] = first_axis_raw or ()
    obj["aion_controller_axis_blender"] = first_axis_blender or ()
    obj["aion_controller_spin_axis_blender"] = tuple(spin_axis) if spin_axis else ()
    obj["aion_controller_basis_source"] = (
        "flat_geometry_axis_alignment"
        if composition == "parent_axis_delta_then_bind"
        else "bind_pose_preservation"
    )
    obj["aion_controller_space"] = (
        "parent_axis_delta"
        if composition == "parent_axis_delta_then_bind"
        else "absolute_local_rotation"
    )
    obj["aion_controller_composition"] = composition
    obj["aion_controller_delta_from_key0"] = composition == "parent_axis_delta_then_bind"
    obj["aion_bind_rotation_preserved"] = True
    obj["aion_parented_animation_status"] = "not_parented"
    obj["aion_controller_key_count"] = int(len(keys))
    obj["aion_controller_time_range_ticks"] = (
        int(keys[0].get("time_ticks", 0)),
        int(keys[-1].get("time_ticks", 0)),
    )
    obj["aion_controller_frame_range"] = (1.0, float(max_frame))
    obj["aion_controller_loop"] = "unknown"
    obj["aion_controller_timing_ticks_per_frame"] = (
        int(timing.get("ticks_per_frame"))
        if isinstance(timing, dict) and timing.get("ticks_per_frame")
        else 0
    )
    return 1


def get_mat(
    mat_data,
    aion_path,
    *,
    animate_texture_sequences=False,
    texture_animation_fps=10,
    animate_shader_uv_scroll=False,
    shader_uv_scroll_context=None,
):
    name = mat_data.get("name", "AION_MAT")
    tex_info = mat_data.get("texture_diffuse") or {}
    tex_name = tex_info.get("name") or ""
    tex_long_name = tex_info.get("long_name") or ""
    tex_filepath = _resolved_texture_path(aion_path, tex_info)
    sequence = (
        resolve_texture_sequence(
            tex_info,
            cgf_path=aion_path,
            client_root=_client_root_from_aion_path(aion_path),
            fps=texture_animation_fps,
        )
        if animate_texture_sequences and tex_info
        else None
    )
    cache_key = _material_cache_key(
        mat_data,
        aion_path,
        tex_filepath,
        animate_texture_sequences=animate_texture_sequences,
        texture_animation_fps=texture_animation_fps,
        sequence_source=sequence.source_texture if sequence else "",
        animate_shader_uv_scroll=animate_shader_uv_scroll,
        shader_uv_scroll_context=shader_uv_scroll_context,
    )
    material_name = _material_datablock_name(name, cache_key)
    cached = _live_material(cache_key, material_name)
    if cached is not None:
        _record_cached_texture_sequence(cached, sequence)
        _record_cached_shader_uv_scroll(cached)
        return cached

    mat = bpy.data.materials.new(material_name)
    mat["aion_material_name"] = name
    mat["aion_material_cache_key"] = cache_key
    mat["aion_material_cache_hash"] = _short_hash(cache_key)
    mat["aion_diffuse_texture"] = tex_name
    mat["aion_diffuse_texture_long_name"] = tex_long_name
    mat["aion_diffuse_texture_resolved"] = tex_filepath
    mat["aion_diffuse_texture_exists"] = os.path.isfile(tex_filepath)
    mat["aion_material_collision"] = _mtl_collide_value(mat_data)
    external_semantics = _store_material_semantics_metadata(mat, mat_data, aion_path)
    mat.use_nodes = True

    tree = mat.node_tree
    nodes = tree.nodes
    links = tree.links

    bsdf = nodes.get("Principled BSDF")
    alpha_in = bsdf.inputs.get("Alpha") if bsdf else None

    tex = None

    if tex_name and bsdf:
        if sequence and sequence.is_sequence:
            tex = _create_texture_sequence_node(
                nodes,
                mat,
                sequence,
                mat_data.get("material_semantics") or {},
            )
            if tex is not None:
                if not mat.get("aion_texture_sequence_alpha_enabled", False):
                    links.new(bsdf.inputs["Base Color"], tex.outputs["Color"])
                _record_texture_sequence_applied(cache_key)
            else:
                _record_texture_sequence_skipped(sequence)
        elif sequence and sequence.skip_reason:
            _record_texture_sequence_skipped(sequence)

        if tex is None and os.path.isfile(tex_filepath):
            tex = nodes.new("ShaderNodeTexImage")
            tex.image = bpy.data.images.load(tex_filepath, check_existing=True)

            links.new(bsdf.inputs["Base Color"], tex.outputs["Color"])

    if float(mat_data.get("mtl_collide", 0.0) or 0.0) > 0.0:
        mat.blend_method = "OPAQUE"
        mat.diffuse_color[3] = 1.0
        if alpha_in:
            alpha_in.default_value = 1.0
        mat["aion_scalar_opacity_applied"] = False
    else:
        opacity = _scalar_opacity(mat_data)
        if opacity is not None:
            mat.diffuse_color[3] = opacity
            mat.blend_method = "BLEND"
            mat["aion_scalar_opacity"] = opacity
            mat["aion_scalar_opacity_applied"] = True
            if alpha_in:
                alpha_in.default_value = opacity
                if tex is not None:
                    multiply = nodes.new("ShaderNodeMath")
                    multiply.operation = "MULTIPLY"
                    multiply.inputs[1].default_value = opacity
                    links.new(multiply.inputs[0], tex.outputs["Alpha"])
                    links.new(alpha_in, multiply.outputs["Value"])
                    mat["aion_scalar_opacity_mode"] = "texture_alpha_multiply"
                else:
                    mat["aion_scalar_opacity_mode"] = "bsdf_alpha"
        elif tex is not None and not mat.get("aion_texture_sequence_enabled", False):
            if alpha_in:
                links.new(alpha_in, tex.outputs["Alpha"])
            mat["aion_scalar_opacity_applied"] = False
        else:
            mat["aion_scalar_opacity_applied"] = False

    sequence_alpha_enabled = str(mat.get("aion_texture_sequence_alpha_strategy", "")) == "image_alpha"
    external_additive_enabled = _external_shader_blend_mode(mat) == "additive"
    uv_scroll_applied = False
    if animate_shader_uv_scroll and _mtl_collide_value(mat_data) <= 0.0 and tex is not None:
        uv_scroll_applied = _configure_shader_uv_scroll_material(
            mat,
            mat_data,
            aion_path,
            external_semantics,
            tex,
            alpha_in,
            texture_animation_fps,
            shader_uv_scroll_context,
        )
    elif animate_shader_uv_scroll:
        _record_shader_uv_scroll_skipped()

    if (
        _mtl_collide_value(mat_data) <= 0.0
        and tex is not None
        and _scalar_opacity(mat_data) is None
        and external_additive_enabled
    ):
        _configure_external_additive_material(mat, tex)
    elif (
        _mtl_collide_value(mat_data) <= 0.0
        and tex is not None
        and _scalar_opacity(mat_data) is None
        and sequence_alpha_enabled
    ):
        _configure_texture_sequence_fx_material(mat, tex)
    elif (
        _mtl_collide_value(mat_data) <= 0.0
        and tex is not None
        and _scalar_opacity(mat_data) is None
        and not mat.get("aion_texture_sequence_enabled", False)
        and not uv_scroll_applied
    ):
        amount = tex_info.get("amount", 1)
        if amount == 0:
            if alpha_in:
                alpha_in.default_value = 0.0
            mat.blend_method = "BLEND"
        else:
            mat.blend_method = "CLIP"

    _MAT_CACHE[cache_key] = mat.name
    return mat


def _scalar_opacity(mat_data):
    try:
        opacity = float(mat_data.get("opacity"))
    except (TypeError, ValueError):
        return None
    if math.isfinite(opacity) and 0.0 <= opacity < 1.0:
        return opacity
    return None


def _store_material_semantics_metadata(mat, mat_data, aion_path):
    semantics = mat_data.get("material_semantics")
    semantics = semantics if isinstance(semantics, dict) else {}
    shader_name = semantics.get("shader_name", "")
    mat["aion_material_shader_name"] = shader_name
    mat["aion_material_alpha_mode"] = semantics.get("alpha_mode", "")
    mat["aion_material_blend_mode"] = semantics.get("blend_mode", "")
    mat["aion_material_emissive"] = bool(semantics.get("emissive", False))
    mat["aion_material_semantics_source"] = ",".join(semantics.get("source") or ())
    external_semantics = resolve_client_shader_semantics(
        _client_root_from_aion_path(aion_path),
        shader_name,
    )
    if external_semantics is not None:
        shader_semantics = external_semantics.to_dict()
        mat["aion_external_shader_name"] = shader_semantics["resolved_shader_name"]
        mat["aion_external_shader_definition"] = shader_semantics["definition_path"]
        mat["aion_external_shader_includes"] = "\n".join(shader_semantics["include_paths"])
        mat["aion_external_shader_blend_mode"] = shader_semantics["blend_mode"]
        mat["aion_external_shader_blend_equation"] = shader_semantics["blend_equation"]
        mat["aion_external_shader_alpha_mode"] = shader_semantics["alpha_mode"]
        mat["aion_external_shader_sort"] = shader_semantics["sort_mode"]
        mat["aion_external_shader_cull"] = shader_semantics["cull_mode"]
        mat["aion_external_shader_two_sided"] = bool(shader_semantics["two_sided"])
        mat["aion_external_shader_no_auto_depth_write"] = bool(
            shader_semantics["no_auto_depth_write"]
        )
        mat["aion_external_shader_uv_scroll_confirmed"] = bool(
            shader_semantics["uv_scroll_confirmed"]
        )
        mat["aion_external_shader_uv_scroll_source"] = shader_semantics["uv_scroll_source"]
        mat["aion_external_shader_uv_scroll_param"] = shader_semantics["uv_scroll_param"]
        if shader_semantics["uv_scroll_speed_x"] is not None:
            mat["aion_external_shader_uv_scroll_speed_x"] = shader_semantics[
                "uv_scroll_speed_x"
            ]
        if shader_semantics["uv_scroll_speed_y"] is not None:
            mat["aion_external_shader_uv_scroll_speed_y"] = shader_semantics[
                "uv_scroll_speed_y"
            ]
        mat["aion_external_shader_uv_scroll_target_slot"] = shader_semantics[
            "uv_scroll_target_slot"
        ]
        mat["aion_external_shader_uv_scroll_target_layer"] = shader_semantics[
            "uv_scroll_target_layer"
        ]
        mat["aion_external_shader_uv_scroll_static_mask_slot"] = shader_semantics[
            "uv_scroll_static_mask_slot"
        ]
        mat["aion_external_shader_alpha_source"] = shader_semantics["alpha_source"]
        mat["aion_external_shader_color_formula"] = shader_semantics["color_formula"]
        mat["aion_external_shader_layers"] = "\n".join(
            f"{layer.get('layer', '')}:{layer.get('map', '')}"
            for layer in shader_semantics["shader_layers"]
        )
        mat["aion_external_shader_semantics_source"] = ",".join(
            shader_semantics["semantics_source"]
        )
        if shader_semantics["two_sided"]:
            mat.use_backface_culling = False
            mat["aion_material_two_sided"] = True
            mat["aion_material_two_sided_source"] = "external_shader_sot"
    return external_semantics


def _configure_shader_uv_scroll_material(
    mat,
    mat_data,
    aion_path,
    external_semantics,
    diffuse_node,
    alpha_in,
    texture_animation_fps,
    shader_uv_scroll_context,
):
    if external_semantics is None or not external_semantics.uv_scroll_confirmed:
        _record_shader_uv_scroll_skipped()
        return False
    if external_semantics.uv_scroll_target_slot != "diffuse":
        _record_shader_uv_scroll_skipped()
        return False

    mask_info = None
    mask_path = ""
    if external_semantics.uv_scroll_static_mask_slot == "mask_map":
        mask_info = mat_data.get("texture_opacity")
        mask_path = _resolved_texture_path(aion_path, mask_info)
        if not mask_path or not os.path.isfile(mask_path):
            mat["aion_uv_scroll_enabled"] = False
            mat["aion_uv_scroll_skip_reason"] = "mask_texture_missing"
            _record_shader_uv_scroll_skipped()
            return False
    elif external_semantics.uv_scroll_static_mask_slot:
        _record_shader_uv_scroll_skipped()
        return False

    tree = mat.node_tree
    if tree is None:
        _record_shader_uv_scroll_skipped()
        return False
    nodes = tree.nodes
    links = tree.links

    scroll_tex_coord = nodes.new("ShaderNodeTexCoord")
    scroll_mapping = nodes.new("ShaderNodeMapping")
    scroll_tex_coord.name = "AION_TexShift_TextureCoordinate"
    scroll_mapping.name = "AION_TexShift_DiffuseMapping"
    diffuse_transform = _apply_texture_transform(
        scroll_mapping,
        mat_data.get("texture_diffuse"),
    )

    _replace_input_links(links, diffuse_node.inputs["Vector"])
    links.new(scroll_mapping.inputs["Vector"], scroll_tex_coord.outputs["UV"])
    links.new(diffuse_node.inputs["Vector"], scroll_mapping.outputs["Vector"])

    bsdf = nodes.get("Principled BSDF")
    base_color_in = bsdf.inputs.get("Base Color") if bsdf else None
    mask_tex = None
    if mask_path:
        mask_image = bpy.data.images.load(mask_path, check_existing=True)
        mask_tex_coord = nodes.new("ShaderNodeTexCoord")
        mask_mapping = nodes.new("ShaderNodeMapping")
        mask_tex = nodes.new("ShaderNodeTexImage")
        mask_tex_coord.name = "AION_MaskMap_TextureCoordinate"
        mask_mapping.name = "AION_TexShift_MaskMapMapping"
        mask_tex.name = "AION_TexShift_MaskMap"
        mask_tex.image = mask_image
        mask_transform = _apply_texture_transform(
            mask_mapping,
            mask_info,
        )
        links.new(mask_mapping.inputs["Vector"], mask_tex_coord.outputs["UV"])
        links.new(mask_tex.inputs["Vector"], mask_mapping.outputs["Vector"])
    else:
        mask_transform = _texture_transform_values(None)

    if base_color_in is not None and mask_tex is not None:
        _replace_input_links(links, base_color_in)
        add_color = nodes.new("ShaderNodeMixRGB")
        add_color.name = "AION_OpacityShift_ColorAdd"
        add_color.blend_type = "ADD"
        add_color.inputs["Factor"].default_value = 1.0
        links.new(add_color.inputs["Color1"], diffuse_node.outputs["Color"])
        links.new(add_color.inputs["Color2"], mask_tex.outputs["Color"])
        links.new(base_color_in, add_color.outputs["Color"])

    if alpha_in is not None:
        _replace_input_links(links, alpha_in)
        opacity = _scalar_opacity(mat_data)
        alpha_output = diffuse_node.outputs["Alpha"]
        if mask_tex is not None:
            diffuse_mask_multiply = nodes.new("ShaderNodeMath")
            diffuse_mask_multiply.operation = "MULTIPLY"
            diffuse_mask_multiply.name = "AION_OpacityShift_DiffuseAlphaMaskAlpha"
            links.new(diffuse_mask_multiply.inputs[0], diffuse_node.outputs["Alpha"])
            links.new(diffuse_mask_multiply.inputs[1], mask_tex.outputs["Alpha"])
            alpha_output = diffuse_mask_multiply.outputs["Value"]
        if opacity is not None:
            opacity_multiply = nodes.new("ShaderNodeMath")
            opacity_multiply.operation = "MULTIPLY"
            opacity_multiply.name = "AION_OpacityShift_OpacityMultiply"
            opacity_multiply.inputs[1].default_value = opacity
            links.new(opacity_multiply.inputs[0], alpha_output)
            links.new(alpha_in, opacity_multiply.outputs["Value"])
            mat["aion_uv_scroll_alpha_source"] = external_semantics.alpha_source
        else:
            links.new(alpha_in, alpha_output)
            mat["aion_uv_scroll_alpha_source"] = (
                "diffuse_alpha_multiply_mask_alpha"
                if mask_tex is not None
                else "diffuse_alpha"
            )

    blender_speed_x, blender_speed_y = _blender_uv_scroll_speed(
        float(external_semantics.uv_scroll_speed_x or 0.0),
        float(external_semantics.uv_scroll_speed_y or 0.0),
        shader_uv_scroll_context,
    )
    _animate_mapping_location(
        scroll_mapping,
        blender_speed_x,
        blender_speed_y,
        _scene_fps(),
        base_x=diffuse_transform["u_offset"],
        base_y=diffuse_transform["v_offset"],
    )
    mat.blend_method = "BLEND"
    if hasattr(mat, "surface_render_method"):
        mat.surface_render_method = "BLENDED"
    mat.show_transparent_back = True
    mat["aion_shader_layer_diffuse_slot"] = "texture_diffuse"
    mat["aion_shader_layer_mask_slot"] = "texture_opacity" if mask_path else ""
    mat["aion_uv_scroll_enabled"] = True
    mat["aion_uv_scroll_source"] = "external_shader_sot"
    mat["aion_uv_scroll_param"] = external_semantics.uv_scroll_param
    mat["aion_uv_scroll_speed_x"] = float(external_semantics.uv_scroll_speed_x or 0.0)
    mat["aion_uv_scroll_speed_y"] = float(external_semantics.uv_scroll_speed_y or 0.0)
    mat["aion_uv_scroll_raw_speed_x"] = float(external_semantics.uv_scroll_speed_x or 0.0)
    mat["aion_uv_scroll_raw_speed_y"] = float(external_semantics.uv_scroll_speed_y or 0.0)
    mat["aion_uv_scroll_blender_speed_x"] = blender_speed_x
    mat["aion_uv_scroll_blender_speed_y"] = blender_speed_y
    mat["aion_uv_scroll_effective_speed_x"] = blender_speed_x
    mat["aion_uv_scroll_effective_speed_y"] = blender_speed_y
    mat["aion_uv_scroll_sign_y"] = float(
        (shader_uv_scroll_context or {}).get("sign_y", 1.0)
    )
    mat["aion_uv_scroll_sign_source"] = str(
        (shader_uv_scroll_context or {}).get("sign_source", "raw_shader_uv")
    )
    mat["aion_uv_scroll_target_slot"] = external_semantics.uv_scroll_target_slot
    mat["aion_uv_scroll_target_layer"] = external_semantics.uv_scroll_target_layer
    mat["aion_uv_scroll_static_mask_slot"] = external_semantics.uv_scroll_static_mask_slot
    mat["aion_uv_scroll_mapping_method"] = "driver_frame_over_scene_fps"
    mat["aion_uv_scroll_time_source"] = "scene_frame_over_scene_fps"
    mat["aion_uv_scroll_speed_units"] = "shader_uv_units_per_second"
    mat["aion_uv_scroll_sign_convention"] = str(
        (shader_uv_scroll_context or {}).get("sign_convention", "raw_shader_uv")
    )
    mat["aion_uv_scroll_unit_status"] = str(
        (shader_uv_scroll_context or {}).get("unit_status", "sot_raw_sign")
    )
    mat["aion_uv_scroll_mask_texture"] = mask_info.get("name") if isinstance(mask_info, dict) else ""
    mat["aion_uv_scroll_mask_texture_resolved"] = mask_path
    mat["aion_uv_scroll_mask_texture_exists"] = bool(mask_path)
    mat["aion_uv_scroll_diffuse_node"] = diffuse_node.name
    mat["aion_uv_scroll_color_formula"] = external_semantics.color_formula
    _store_texture_transform_metadata(mat, "diffuse", diffuse_transform)
    _store_texture_transform_metadata(mat, "mask", mask_transform)
    mat["aion_material_alpha_formula"] = mat.get("aion_uv_scroll_alpha_source", external_semantics.alpha_source)
    opacity = _scalar_opacity(mat_data)
    mat["aion_material_opacity_source"] = "material_scalar_opacity" if opacity is not None else "texture_alpha"
    mat["aion_material_effective_opacity"] = float(opacity) if opacity is not None else 1.0
    _record_shader_uv_scroll_applied(mat.get("aion_material_cache_key", ""))
    return True


def _blender_uv_scroll_speed(speed_x, speed_y, shader_uv_scroll_context=None):
    context = shader_uv_scroll_context if isinstance(shader_uv_scroll_context, dict) else {}
    sign_y = context.get("sign_y", 1.0)
    try:
        sign_y = float(sign_y)
    except (TypeError, ValueError):
        sign_y = 1.0
    if not math.isfinite(sign_y) or sign_y == 0.0:
        sign_y = 1.0
    return float(speed_x), float(speed_y) * sign_y


def _animate_mapping_location(mapping_node, speed_x, speed_y, fps, *, base_x=0.0, base_y=0.0):
    fps = float(fps or 10)
    if fps <= 0.0:
        fps = 10.0
    location = mapping_node.inputs["Location"]
    location.default_value[0] = float(base_x)
    location.default_value[1] = float(base_y)
    driver_x = location.driver_add("default_value", 0).driver
    driver_x.type = "SCRIPTED"
    driver_x.expression = _driver_linear_expression(float(base_x), speed_x, fps)
    driver_y = location.driver_add("default_value", 1).driver
    driver_y.type = "SCRIPTED"
    driver_y.expression = _driver_linear_expression(float(base_y), speed_y, fps)


def _driver_linear_expression(base_value, speed, fps):
    step = float(speed) / float(fps)
    if abs(base_value) <= 1e-12:
        return f"frame*{step:.12g}"
    if step >= 0:
        return f"{base_value:.12g}+frame*{step:.12g}"
    return f"{base_value:.12g}-frame*{abs(step):.12g}"


def _scene_fps():
    scene = bpy.context.scene if bpy.context else None
    fps = getattr(getattr(scene, "render", None), "fps", 0) if scene else 0
    try:
        fps = float(fps)
    except (TypeError, ValueError):
        fps = 0.0
    return fps if fps > 0.0 else 24.0


def _apply_texture_transform(mapping_node, texture_info):
    transform = _texture_transform_values(texture_info)
    mapping_node.inputs["Location"].default_value[0] = transform["u_offset"]
    mapping_node.inputs["Location"].default_value[1] = transform["v_offset"]
    mapping_node.inputs["Scale"].default_value[0] = transform["u_scale"]
    mapping_node.inputs["Scale"].default_value[1] = transform["v_scale"]
    return transform


def _texture_transform_values(texture_info):
    if not isinstance(texture_info, dict):
        return {
            "u_offset": 0.0,
            "v_offset": 0.0,
            "u_scale": 1.0,
            "v_scale": 1.0,
            "u_rotation": 0.0,
            "v_rotation": 0.0,
            "w_rotation": 0.0,
            "amount": 100.0,
        }
    return {
        "u_offset": _texture_float(texture_info.get("u_off_val"), 0.0),
        "v_offset": _texture_float(texture_info.get("v_off_val"), 0.0),
        "u_scale": _texture_scale(texture_info.get("u_scl_val")),
        "v_scale": _texture_scale(texture_info.get("v_scl_val")),
        "u_rotation": _texture_float(texture_info.get("u_rot_val"), 0.0),
        "v_rotation": _texture_float(texture_info.get("v_rot_val"), 0.0),
        "w_rotation": _texture_float(texture_info.get("w_rot_val"), 0.0),
        "amount": _texture_float(texture_info.get("amount"), 100.0),
    }


def _texture_float(value, default):
    try:
        result = float(value)
    except (TypeError, ValueError):
        return float(default)
    return result if math.isfinite(result) else float(default)


def _texture_scale(value):
    scale = _texture_float(value, 1.0)
    return scale if scale != 0.0 else 1.0


def _store_texture_transform_metadata(mat, prefix, transform):
    for key, value in transform.items():
        mat[f"aion_uv_scroll_{prefix}_texture_{key}"] = float(value)
    mat[f"aion_uv_scroll_{prefix}_texture_transform_applied"] = bool(
        abs(transform["u_offset"]) > 1e-12
        or abs(transform["v_offset"]) > 1e-12
        or abs(transform["u_scale"] - 1.0) > 1e-12
        or abs(transform["v_scale"] - 1.0) > 1e-12
    )
    mat[f"aion_uv_scroll_{prefix}_texture_rotation_status"] = (
        "metadata_only_not_applied"
        if (
            abs(transform["u_rotation"]) > 1e-12
            or abs(transform["v_rotation"]) > 1e-12
            or abs(transform["w_rotation"]) > 1e-12
        )
        else "none"
    )


def _replace_input_links(links, socket):
    for link in tuple(socket.links):
        links.remove(link)


def _create_texture_sequence_node(nodes, mat, sequence, material_semantics=None):
    frame_paths = tuple(sequence.frame_paths)
    if not frame_paths:
        return None
    first_frame = frame_paths[0]
    if not os.path.isfile(first_frame):
        return None
    try:
        image = bpy.data.images.load(first_frame, check_existing=False)
    except RuntimeError:
        return None
    image.name = f"AION_TextureSequence_{os.path.basename(first_frame)}"
    image.filepath = first_frame
    image.filepath_raw = first_frame
    image.source = "SEQUENCE"
    image_channels = int(getattr(image, "channels", 0) or 0)
    alpha_strategy, alpha_strategy_source = _texture_sequence_alpha_strategy(
        material_semantics or {},
    )
    alpha_enabled = alpha_strategy != UNKNOWN_NOT_DECODED
    tex = nodes.new("ShaderNodeTexImage")
    tex.image = image
    image_user = getattr(tex, "image_user", None)
    effective_frame_count = int(sequence.effective_frame_count)
    frame_offset = int(sequence.blender_frame_offset)
    if image_user is not None:
        image_user.frame_start = 1
        image_user.frame_duration = effective_frame_count
        image_user.frame_offset = frame_offset
        image_user.use_cyclic = True
        image_user.use_auto_refresh = True
    _fit_scene_timing_to_sequence(effective_frame_count, sequence.fps)

    mat["aion_texture_sequence_enabled"] = True
    mat["aion_texture_sequence_frame_count"] = sequence.frame_count
    mat["aion_texture_sequence_fps"] = sequence.fps
    mat["aion_texture_sequence_source"] = sequence.source_texture
    mat["aion_texture_sequence_missing_frames"] = sequence.missing_frame_count
    mat["aion_texture_sequence_confidence"] = sequence.confidence
    mat["aion_texture_sequence_first_frame"] = first_frame
    mat["aion_texture_sequence_last_frame"] = frame_paths[-1]
    mat["aion_texture_sequence_frame_paths"] = "\n".join(frame_paths)
    mat["aion_texture_sequence_frame_start_index"] = (
        -1 if sequence.frame_start_index is None else int(sequence.frame_start_index)
    )
    mat["aion_texture_sequence_frame_end_index"] = (
        -1 if sequence.frame_end_index is None else int(sequence.frame_end_index)
    )
    mat["aion_texture_sequence_effective_frame_count"] = effective_frame_count
    mat["aion_texture_sequence_blender_frame_offset"] = frame_offset
    mat["aion_texture_sequence_image_channels"] = image_channels
    mat["aion_texture_sequence_alpha_enabled"] = alpha_enabled
    mat["aion_texture_sequence_alpha_strategy"] = alpha_strategy
    mat["aion_texture_sequence_alpha_strategy_source"] = alpha_strategy_source
    return tex


def _texture_sequence_alpha_strategy(material_semantics):
    alpha_mode = str(material_semantics.get("alpha_mode") or "")
    blend_mode = str(material_semantics.get("blend_mode") or "")
    if alpha_mode in {"texture_opacity", "scalar_opacity"}:
        return "image_alpha", f"cgf_material_semantics:{alpha_mode}"
    if blend_mode in {"additive", "additive_decal", "subtractive", "alpha_blend"}:
        return "image_alpha", f"cgf_material_semantics:{blend_mode}"

    return UNKNOWN_NOT_DECODED, "unknown_not_decoded"


def _external_shader_blend_mode(mat):
    return str(mat.get("aion_external_shader_blend_mode", ""))


def _configure_external_additive_material(mat, tex):
    tree = mat.node_tree
    if tree is None:
        return
    nodes = tree.nodes
    links = tree.links
    output = nodes.get("Material Output")
    if output is None:
        output = nodes.new("ShaderNodeOutputMaterial")

    surface = output.inputs.get("Surface")
    if surface is not None:
        for link in tuple(surface.links):
            links.remove(link)

    transparent = nodes.new("ShaderNodeBsdfTransparent")
    emission = nodes.new("ShaderNodeEmission")
    add = nodes.new("ShaderNodeAddShader")
    emission.inputs["Strength"].default_value = 2.0

    links.new(emission.inputs["Color"], tex.outputs["Color"])
    links.new(add.inputs[0], transparent.outputs["BSDF"])
    links.new(add.inputs[1], emission.outputs["Emission"])
    if surface is not None:
        links.new(surface, add.outputs["Shader"])

    mat.blend_method = "BLEND"
    if hasattr(mat, "surface_render_method"):
        mat.surface_render_method = "BLENDED"
    mat.show_transparent_back = True
    if hasattr(mat, "use_screen_refraction"):
        mat.use_screen_refraction = False
    mat["aion_material_blend_mode"] = "additive"
    mat["aion_material_blend_source"] = "external_shader_sot"
    mat["aion_external_shader_blend_expr"] = mat.get("aion_external_shader_blend_equation", "")
    mat["aion_texture_sequence_alpha_enabled"] = False
    mat["aion_texture_sequence_alpha_strategy"] = "not_used_additive_blend"
    mat["aion_texture_sequence_alpha_strategy_source"] = "external_shader_sot_blend_one_one"
    mat["aion_external_shader_additive_graph"] = "transparent_bsdf+emission_bsdf+add_shader"


def _configure_texture_sequence_fx_material(mat, tex):
    tree = mat.node_tree
    if tree is None:
        return
    nodes = tree.nodes
    links = tree.links
    output = nodes.get("Material Output")
    if output is None:
        output = nodes.new("ShaderNodeOutputMaterial")

    surface = output.inputs.get("Surface")
    if surface is not None:
        for link in tuple(surface.links):
            links.remove(link)

    transparent = nodes.new("ShaderNodeBsdfTransparent")
    emission = nodes.new("ShaderNodeEmission")
    mix = nodes.new("ShaderNodeMixShader")
    emission.inputs["Strength"].default_value = 2.0

    links.new(emission.inputs["Color"], tex.outputs["Color"])
    links.new(mix.inputs["Fac"], tex.outputs["Alpha"])
    mat["aion_texture_sequence_alpha_factor_source"] = "image_alpha"
    links.new(mix.inputs[1], transparent.outputs["BSDF"])
    links.new(mix.inputs[2], emission.outputs["Emission"])
    if surface is not None:
        links.new(surface, mix.outputs["Shader"])

    mat.blend_method = "BLEND"
    mat.show_transparent_back = True
    if hasattr(mat, "use_screen_refraction"):
        mat.use_screen_refraction = False
    mat["aion_texture_sequence_alpha_mode"] = "transparent_emission_mix"
    mat["aion_texture_sequence_fx_graph"] = "transparent_bsdf+emission_bsdf+mix_shader"

def _fit_scene_timing_to_sequence(frame_count, fps):
    scene = getattr(bpy.context, "scene", None)
    if scene is None or frame_count <= 1:
        return
    scene.frame_start = 1
    if scene.frame_end in (0, 1, 250) or scene.frame_end < frame_count:
        scene.frame_end = frame_count
    fps = int(fps or 10)
    if fps > 0:
        scene.render.fps = fps


def _resolved_texture_path(aion_path, texture_info):
    if not isinstance(texture_info, dict):
        return ""
    texture_name = _clean_texture_path(texture_info.get("name"))
    texture_long_name = _clean_texture_path(texture_info.get("long_name"))
    if texture_long_name:
        client_root = _client_root_from_aion_path(aion_path)
        if client_root is not None:
            return os.path.normcase(os.path.abspath(os.path.join(client_root, texture_long_name)))
    if texture_name:
        return os.path.normcase(os.path.abspath(os.path.join(aion_path, texture_name)))
    return ""


def _clean_texture_path(texture_path):
    if not texture_path:
        return ""
    return str(texture_path).strip().strip("\x00").replace("/", os.sep).replace("\\", os.sep)


def _client_root_from_aion_path(aion_path):
    parts = os.path.abspath(aion_path).split(os.sep)
    for index, part in enumerate(parts):
        if part.lower() in ("levels", "objects", "effects", "textures"):
            if index == 0:
                return None
            return os.sep.join(parts[:index])
    return None


def _material_cache_key(
    mat_data,
    aion_path,
    tex_filepath,
    *,
    animate_texture_sequences=False,
    texture_animation_fps=10,
    sequence_source="",
    animate_shader_uv_scroll=False,
    shader_uv_scroll_context=None,
):
    flags = mat_data.get("mtl_flag")
    if isinstance(flags, dict):
        flags_key = tuple(sorted((str(key), int(bool(value))) for key, value in flags.items()))
    else:
        flags_key = ()
    key_parts = (
        os.path.normcase(os.path.abspath(aion_path)),
        str(mat_data.get("name", "AION_MAT")),
        str(tex_filepath),
        repr(mat_data.get("opacity")),
        repr(_mtl_collide_value(mat_data)),
        repr(mat_data.get("mtl_type")),
        repr(flags_key),
        repr(bool(animate_texture_sequences)),
        repr(int(texture_animation_fps)),
        str(sequence_source),
        repr(bool(animate_shader_uv_scroll)),
        repr(_shader_uv_scroll_cache_context(shader_uv_scroll_context)),
    )
    return "|".join(key_parts)


def _shader_uv_scroll_cache_context(shader_uv_scroll_context):
    if not isinstance(shader_uv_scroll_context, dict):
        return ()
    return (
        ("sign_y", float(shader_uv_scroll_context.get("sign_y", 1.0))),
        ("sign_source", str(shader_uv_scroll_context.get("sign_source", ""))),
    )


def _reset_texture_sequence_stats(requested):
    global _TEXTURE_SEQUENCE_STATS
    _TEXTURE_SEQUENCE_STATS = {
        "requested": bool(requested),
        "applied_keys": set(),
        "skipped": 0,
        "missing_frames": 0,
    }


def _reset_shader_uv_scroll_stats(requested):
    global _SHADER_UV_SCROLL_STATS
    _SHADER_UV_SCROLL_STATS = {
        "requested": bool(requested),
        "applied_keys": set(),
        "skipped": 0,
    }


def _record_texture_sequence_applied(cache_key):
    if _TEXTURE_SEQUENCE_STATS is not None:
        _TEXTURE_SEQUENCE_STATS["applied_keys"].add(cache_key)


def _record_cached_texture_sequence(mat, sequence):
    if _TEXTURE_SEQUENCE_STATS is None:
        return
    if mat.get("aion_texture_sequence_enabled"):
        _TEXTURE_SEQUENCE_STATS["applied_keys"].add(mat.get("aion_material_cache_key", ""))
    elif sequence and sequence.skip_reason:
        _record_texture_sequence_skipped(sequence)


def _record_texture_sequence_skipped(sequence):
    if _TEXTURE_SEQUENCE_STATS is None:
        return
    _TEXTURE_SEQUENCE_STATS["skipped"] += 1
    _TEXTURE_SEQUENCE_STATS["missing_frames"] += int(sequence.missing_frame_count or 0)


def _texture_sequence_report_counts():
    if _TEXTURE_SEQUENCE_STATS is None:
        return {}
    return {
        "texture_sequences_requested": bool(_TEXTURE_SEQUENCE_STATS["requested"]),
        "texture_sequences_applied": len(_TEXTURE_SEQUENCE_STATS["applied_keys"]),
        "texture_sequences_skipped": int(_TEXTURE_SEQUENCE_STATS["skipped"]),
        "texture_sequence_missing_frames": int(_TEXTURE_SEQUENCE_STATS["missing_frames"]),
    }


def _record_shader_uv_scroll_applied(cache_key):
    if _SHADER_UV_SCROLL_STATS is not None:
        _SHADER_UV_SCROLL_STATS["applied_keys"].add(cache_key)


def _record_cached_shader_uv_scroll(mat):
    if _SHADER_UV_SCROLL_STATS is None:
        return
    if mat.get("aion_uv_scroll_enabled"):
        _SHADER_UV_SCROLL_STATS["applied_keys"].add(mat.get("aion_material_cache_key", ""))


def _record_shader_uv_scroll_skipped():
    if _SHADER_UV_SCROLL_STATS is not None:
        _SHADER_UV_SCROLL_STATS["skipped"] += 1


def _shader_uv_scroll_report_counts():
    if _SHADER_UV_SCROLL_STATS is None:
        return {}
    return {
        "shader_uv_scroll_requested": bool(_SHADER_UV_SCROLL_STATS["requested"]),
        "shader_uv_scroll_applied": len(_SHADER_UV_SCROLL_STATS["applied_keys"]),
        "shader_uv_scroll_skipped": int(_SHADER_UV_SCROLL_STATS["skipped"]),
    }


def _short_hash(value):
    return hashlib.sha1(value.encode("utf-8")).hexdigest()[:10]


def _material_datablock_name(name, cache_key):
    readable = str(name or "AION_MAT").replace("/", "_").replace("\\", "_")
    return f"{readable[:48]}#{_short_hash(cache_key)}"


def _live_material(cache_key, material_name):
    cached_name = _MAT_CACHE.get(cache_key)
    if cached_name:
        cached = bpy.data.materials.get(cached_name)
        if cached is not None and cached.get("aion_material_cache_key") == cache_key:
            return cached

    current = bpy.data.materials.get(material_name)
    if current is not None and current.get("aion_material_cache_key") == cache_key:
        _MAT_CACHE[cache_key] = current.name
        return current

    return None


def _safe_uv_idx(face_uvidx, uv_len):
    if face_uvidx is None or face_uvidx is Ellipsis:
        return 0
    if isinstance(face_uvidx, str) and face_uvidx.strip() == "...":
        return 0
    try:
        idx = int(face_uvidx)
    except (TypeError, ValueError):
        return 0
    return idx if 0 <= idx < uv_len else 0


def _mtl_collide_value(mat_data):
    value = mat_data.get("mtl_collide", 0.0) if isinstance(mat_data, dict) else 0.0
    try:
        return float(value or 0.0)
    except (TypeError, ValueError):
        return 0.0


def _mat_is_collide_by_id(mat_id, materials):
    return 0 <= mat_id < len(materials) and _mtl_collide_value(materials[mat_id]) > 0.0


def _mat_has_visual_surface(mat_data):
    if not isinstance(mat_data, dict):
        return False
    flags = mat_data.get("mtl_flag")
    no_draw = bool(flags.get("no_draw")) if isinstance(flags, dict) else False
    name = str(mat_data.get("name") or "").lower()
    if no_draw or "nodraw" in name or "no draw" in name:
        return False
    try:
        opacity = float(mat_data.get("opacity", 1.0))
    except (TypeError, ValueError):
        opacity = 1.0
    if math.isfinite(opacity) and opacity <= 0.0:
        return False
    texture = mat_data.get("texture_diffuse")
    if isinstance(texture, dict) and (texture.get("name") or texture.get("long_name")):
        return True
    return False


def _mat_has_visual_surface_by_id(mat_id, materials):
    return 0 <= mat_id < len(materials) and _mat_has_visual_surface(materials[mat_id])


def _shader_uv_scroll_context_for_material(verts_loc, verts_tex, faces, faces_m, uv_faces, mat_id):
    samples = []
    if not verts_loc or not verts_tex or not faces or not uv_faces:
        return _raw_shader_uv_scroll_context()
    uv_len = len(verts_tex)
    for face_index, face in enumerate(faces):
        if face_index >= len(faces_m) or faces_m[face_index] != mat_id:
            continue
        if face_index >= len(uv_faces):
            continue
        uv_face = uv_faces[face_index]
        for vertex_index, uv_index in zip(face, uv_face):
            if not isinstance(vertex_index, int):
                continue
            if vertex_index < 0 or vertex_index >= len(verts_loc):
                continue
            uv = verts_tex[_safe_uv_idx(uv_index, uv_len)]
            x, y, z = verts_loc[vertex_index]
            samples.append((float(x), float(y), float(z), float(uv[0]), float(uv[1])))
    if not samples:
        return _raw_shader_uv_scroll_context()

    x_extent = _extent(sample[0] for sample in samples)
    y_extent = _extent(sample[1] for sample in samples)
    z_extent = _extent(sample[2] for sample in samples)
    v_extent = _extent(sample[4] for sample in samples)
    horizontal_extent = max(x_extent, y_extent)
    if z_extent > horizontal_extent and v_extent > 1.0:
        return {
            "sign_y": -1.0,
            "sign_source": "vertical_geometry_uv_v",
            "sign_convention": "cryengine_vertical_texcoord_to_blender_uv",
            "unit_status": "sot_sign_converted",
            "z_extent": z_extent,
            "horizontal_extent": horizontal_extent,
            "uv_v_extent": v_extent,
        }
    context = _raw_shader_uv_scroll_context()
    context.update(
        {
            "z_extent": z_extent,
            "horizontal_extent": horizontal_extent,
            "uv_v_extent": v_extent,
        }
    )
    return context


def _raw_shader_uv_scroll_context():
    return {
        "sign_y": 1.0,
        "sign_source": "raw_shader_uv",
        "sign_convention": "raw_shader_uv",
        "unit_status": "sot_raw_sign",
    }


def _extent(values):
    values = tuple(float(value) for value in values)
    if not values:
        return 0.0
    return max(values) - min(values)


def create_mesh(
    node,
    materials,
    aion_path,
    mat_info,
    import_mode="VISUAL",
    apply_smoothing_groups=False,
    animate_texture_sequences=False,
    texture_animation_fps=10,
    animate_shader_uv_scroll=False,
):
    mesh_chunk = node["mesh"]

    verts_loc = mesh_chunk["vertices"]["position"]
    verts_tex = mesh_chunk["uvs"]["uvs"]
    faces = mesh_chunk["faces"]["v"]
    faces_m = mesh_chunk["faces"]["material"]
    smoothing_groups = mesh_chunk["faces"]["smoothing_group"]
    uv_faces = mesh_chunk["uv_faces"]["face_uvs"]

    is_multi = mat_info.get("mtl_type") == 2

    if is_multi and import_mode in ("VISUAL", "COLLISION"):
        new_faces = []
        new_faces_m = []
        new_smoothing_groups = []
        new_uv_faces = []
        has_uv_faces = isinstance(uv_faces, list)

        for index, face in enumerate(faces):
            mat_id = faces_m[index] if index < len(faces_m) else 0
            is_collide = _mat_is_collide_by_id(mat_id, materials)
            has_visual_surface = _mat_has_visual_surface_by_id(mat_id, materials)

            if not _mode_allows(is_collide, import_mode, has_visual_surface):
                continue

            new_faces.append(face)
            new_faces_m.append(mat_id)
            new_smoothing_groups.append(
                smoothing_groups[index] if index < len(smoothing_groups) else 0
            )
            if has_uv_faces and index < len(uv_faces):
                new_uv_faces.append(uv_faces[index])

        if not new_faces:
            return None

        faces = new_faces
        faces_m = new_faces_m
        smoothing_groups = new_smoothing_groups
        uv_faces = new_uv_faces

    mesh = bpy.data.meshes.new(node["name"])
    mesh.from_pydata(verts_loc, [], faces)

    if verts_tex and mesh.polygons:
        mesh.uv_layers.new()

    use_mat_ids = []
    mat_slot_by_id = {}

    def slot_for(mat_id):
        slot = mat_slot_by_id.get(mat_id)
        if slot is None:
            slot = len(use_mat_ids)
            use_mat_ids.append(mat_id)
            mat_slot_by_id[mat_id] = slot
        return slot

    for blender_poly, mat_id in zip(mesh.polygons, faces_m):
        blender_poly.material_index = slot_for(mat_id)

    if apply_smoothing_groups:
        for blender_poly, smoothing_group in zip(mesh.polygons, smoothing_groups):
            if smoothing_group != 0:
                blender_poly.use_smooth = True
        mesh["aion_smoothing_groups_applied"] = True
    else:
        mesh["aion_smoothing_groups_applied"] = False

    if verts_tex and uv_faces and mesh.uv_layers.active:
        uv_layer = mesh.uv_layers.active
        flat_uv = [0.0] * (len(mesh.loops) * 2)
        uv_len = len(verts_tex)

        for uv_face, blender_poly in zip(uv_faces, mesh.polygons):
            for face_uvidx, loop_index in zip(uv_face, blender_poly.loop_indices):
                uv = verts_tex[_safe_uv_idx(face_uvidx, uv_len)]
                base = loop_index * 2
                flat_uv[base] = uv[0]
                flat_uv[base + 1] = uv[1]

        uv_layer.data.foreach_set("uv", flat_uv)

    if mat_info.get("mtl_type") == 1:
        shader_uv_scroll_context = _shader_uv_scroll_context_for_material(
            verts_loc,
            verts_tex,
            faces,
            faces_m,
            uv_faces,
            0,
        )
        material = get_mat(
            mat_info,
            aion_path,
            animate_texture_sequences=animate_texture_sequences,
            texture_animation_fps=texture_animation_fps,
            animate_shader_uv_scroll=animate_shader_uv_scroll,
            shader_uv_scroll_context=shader_uv_scroll_context,
        )
        _tag_fx_mesh_geometry_source(material)
        mesh.materials.append(material)
    elif mat_info.get("mtl_type") == 2:
        for mat_id in use_mat_ids:
            shader_uv_scroll_context = _shader_uv_scroll_context_for_material(
                verts_loc,
                verts_tex,
                faces,
                faces_m,
                uv_faces,
                mat_id,
            )
            material = get_mat(
                materials[mat_id],
                aion_path,
                animate_texture_sequences=animate_texture_sequences,
                texture_animation_fps=texture_animation_fps,
                animate_shader_uv_scroll=animate_shader_uv_scroll,
                shader_uv_scroll_context=shader_uv_scroll_context,
            )
            _tag_fx_mesh_geometry_source(material)
            mesh.materials.append(material)

    mesh.update(calc_edges=False)
    return bpy.data.objects.new(mesh.name, mesh)


def _tag_fx_mesh_geometry_source(material):
    if material.get("aion_external_shader_blend_mode") != "additive":
        return
    material["aion_fx_geometry_source"] = "cgf_mesh"
    material["aion_fx_generated_billboard"] = False
    material["aion_fx_billboard_semantics_source"] = UNKNOWN_NOT_DECODED


def _is_collision_node(node, materials):
    mat = node.get("material") if isinstance(node.get("material"), dict) else {}

    if _mtl_collide_value(mat) > 0.0:
        return True

    if mat.get("mtl_type") == 2:
        for mat_id in mat.get("multi_mtl_ids") or []:
            if _mat_is_collide_by_id(mat_id, materials):
                return True

    return False


def _node_has_visual_surface(node, materials):
    mat = node.get("material") if isinstance(node.get("material"), dict) else {}
    if _mat_has_visual_surface(mat):
        return True
    if mat.get("mtl_type") == 2:
        return any(
            _mat_has_visual_surface_by_id(mat_id, materials)
            for mat_id in mat.get("multi_mtl_ids") or []
        )
    return False


def load(
    context,
    filepath,
    import_mode="VISUAL",
    apply_smoothing_groups=False,
    animate_texture_sequences=False,
    texture_animation_fps=10,
    animate_shader_uv_scroll=False,
    animate_cga_controllers=False,
):
    if import_mode not in {"VISUAL", "COLLISION"}:
        raise ValueError(f"unsupported import mode: {import_mode}")
    visual_mode = import_mode == "VISUAL"
    if not visual_mode:
        animate_texture_sequences = False
        animate_shader_uv_scroll = False
        animate_cga_controllers = False

    _reset_texture_sequence_stats(animate_texture_sequences)
    _reset_shader_uv_scroll_stats(animate_shader_uv_scroll)
    if not filepath or not os.path.isfile(filepath):
        return _cancel(
            filepath,
            import_mode,
            MISSING_FILE,
            f"file does not exist: {filepath}",
            file_exists=False,
            **_cga_report_counts(
                filepath,
                {},
                animation_requested=animate_cga_controllers,
            ),
            **_texture_sequence_report_counts(),
            **_shader_uv_scroll_report_counts(),
        )

    file_name = bpy.path.basename(filepath)
    aion_path = os.path.dirname(filepath)

    with open(filepath, "rb") as file_stream:
        cgf_file = get_cgf(file_stream, diagnostics=True, file_path=filepath)

    if not isinstance(cgf_file, dict):
        return _cancel(
            filepath,
            import_mode,
            PARSE_ERROR,
            f"expected parser dict result, got {type(cgf_file).__name__}",
            file_exists=True,
            **_cga_report_counts(
                filepath,
                {},
                animation_requested=animate_cga_controllers,
            ),
            **_texture_sequence_report_counts(),
            **_shader_uv_scroll_report_counts(),
        )

    err = cgf_file.get("error") if isinstance(cgf_file, dict) else None
    if err:
        return _cancel(
            filepath,
            import_mode,
            PARSE_ERROR,
            str(err),
            file_exists=True,
            **_diagnostics_report_counts(cgf_file),
            **_cga_report_counts(
                filepath,
                cgf_file,
                animation_requested=animate_cga_controllers,
            ),
            **_texture_sequence_report_counts(),
            **_shader_uv_scroll_report_counts(),
        )

    materials = cgf_file.get("all_materials", [])
    nodes = tuple((cgf_file.get("nodes") or {}).values())
    all_nodes = cgf_file.get("all_nodes") or cgf_file.get("nodes") or {}
    parser_mesh_node_count = sum(node.get("mesh") is not None for node in nodes)

    root_collection = context.scene.collection
    cgf_collection = bpy.data.collections.new(name=file_name)
    objects_created = 0
    candidate_mesh_node_count = 0
    cga_controller_animations_applied = 0

    for node in nodes:
        mesh_chunk = node.get("mesh")
        if not mesh_chunk:
            continue

        mat_info = node.get("material") if isinstance(node.get("material"), dict) else {}
        is_multi = mat_info.get("mtl_type") == 2

        if not is_multi:
            is_collide = _is_collision_node(node, materials)
            if not _mode_allows(
                is_collide,
                import_mode,
                _node_has_visual_surface(node, materials),
            ):
                continue

        candidate_mesh_node_count += 1
        obj = create_mesh(
            node,
            materials,
            aion_path,
            mat_info,
            import_mode=import_mode,
            apply_smoothing_groups=apply_smoothing_groups,
            animate_texture_sequences=animate_texture_sequences,
            texture_animation_fps=texture_animation_fps,
            animate_shader_uv_scroll=animate_shader_uv_scroll,
        )
        if obj is None:
            continue

        obj.matrix_world = _composed_node_matrix(node, all_nodes)
        animation_applied = _apply_cga_controller_animation(
            obj,
            node,
            filepath,
            cgf_file,
            enabled=animate_cga_controllers,
        )
        cga_controller_animations_applied += animation_applied
        _assign_cga_static_metadata(
            obj,
            filepath,
            cgf_file,
            animation_requested=animate_cga_controllers,
            animations_applied=animation_applied,
        )
        cgf_collection.objects.link(obj)
        objects_created += 1

    if objects_created == 0:
        bpy.data.collections.remove(cgf_collection)
        if parser_mesh_node_count == 0:
            reason_code = EMPTY_MESH
            reason = "parser returned no mesh nodes"
        elif candidate_mesh_node_count == 0:
            reason_code = NO_GEOMETRY_FOR_MODE
            reason = f"no mesh nodes matched import mode {import_mode}"
        else:
            reason_code = EMPTY_MESH
            reason = "mesh nodes produced no Blender objects"
        return _cancel(
            filepath,
            import_mode,
            reason_code,
            reason,
            file_exists=True,
            parser_node_count=len(nodes),
            parser_mesh_node_count=parser_mesh_node_count,
            parser_material_count=len(materials),
            candidate_mesh_node_count=candidate_mesh_node_count,
            objects_created=objects_created,
            **_diagnostics_report_counts(cgf_file),
            **_cga_report_counts(
                filepath,
                cgf_file,
                animation_requested=animate_cga_controllers,
                animations_applied=cga_controller_animations_applied,
            ),
            **_texture_sequence_report_counts(),
            **_shader_uv_scroll_report_counts(),
        )

    root_collection.children.link(cgf_collection)
    if _source_extension(filepath) == "cga":
        controller_count, timing_present = _cga_metadata_counts(cgf_file)
        cgf_collection["aion_source_extension"] = ".cga"
        cgf_collection["aion_cga_static_import"] = True
        cgf_collection["aion_cga_controller_count"] = controller_count
        cgf_collection["aion_cga_timing_present"] = timing_present
        cgf_collection["aion_cga_animation_status"] = (
            "controller_decoded"
            if cga_controller_animations_applied
            else "controller_not_decoded"
        )
        cgf_collection["aion_cga_controller_animation_requested"] = bool(
            animate_cga_controllers
        )
        cgf_collection["aion_cga_controller_animations_applied"] = int(
            cga_controller_animations_applied
        )
    _set_import_report(
        filepath=filepath,
        import_mode=import_mode,
        result="FINISHED",
        file_exists=True,
        parser_node_count=len(nodes),
        parser_mesh_node_count=parser_mesh_node_count,
        parser_material_count=len(materials),
        candidate_mesh_node_count=candidate_mesh_node_count,
        objects_created=objects_created,
        **_diagnostics_report_counts(cgf_file),
        **_cga_report_counts(
            filepath,
            cgf_file,
            animation_requested=animate_cga_controllers,
            animations_applied=cga_controller_animations_applied,
        ),
        **_texture_sequence_report_counts(),
        **_shader_uv_scroll_report_counts(),
    )
    return {"FINISHED"}
