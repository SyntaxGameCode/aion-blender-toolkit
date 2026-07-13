from dataclasses import dataclass


MAX_BLEND_SHADER_MATERIALS = 32
BLEND_SHADER_PROJECTION_PROJ_AXIS = "proj_axis"
BLEND_SHADER_PROJECTION_UV_MAP = "uv_map"


@dataclass(frozen=True)
class TerrainBlendShaderResult:
    enabled: bool
    graph_created: bool
    material_count: int
    included_material_indices: tuple[int, ...]
    texture_images_loaded: int
    texture_images_failed: int
    texture_nodes_created: int
    skipped_material_indices: tuple[int, ...]
    skipped_material_sample_counts: tuple[tuple[int, int], ...]
    skipped_material_reasons: tuple[tuple[int, str, int], ...]
    projection_mode: str
    warnings: tuple[str, ...]


def create_terrain_blend_shader(
    bpy,
    mesh,
    material_slots,
    *,
    material_sample_counts: dict[int, int] | None = None,
    load_textures: bool = False,
    material_limit: int = MAX_BLEND_SHADER_MATERIALS,
) -> TerrainBlendShaderResult:
    material_indices = tuple(int(index) for index in mesh.get("aion_blend_material_indices", ()))
    layer_names = tuple(
        name
        for name in str(mesh.get("aion_blend_attribute_layers", "")).split(",")
        if name
    )
    slot_by_index = {
        slot.terrain_material_index: slot
        for slot in material_slots
        if slot.surface_type is not None
    }
    sample_counts = material_sample_counts or {}
    usable_indices, skipped_materials = _classify_shader_material_indices(
        material_indices,
        slot_by_index,
        sample_counts,
        material_limit,
        load_textures,
    )
    selected_indices = usable_indices
    skipped_indices = tuple(index for index, _, _ in skipped_materials)
    skipped_sample_counts = tuple(
        (index, int(sample_counts.get(index, 0)))
        for index in skipped_indices
    )
    warnings = []

    if not layer_names:
        warnings.append("blend attributes missing")
    if not selected_indices:
        warnings.append("no supported terrain materials for blend shader")

    material = bpy.data.materials.new("Aion Terrain Blend Shader Preview")
    material.use_nodes = True
    material["aion_blend_shader_enabled"] = bool(selected_indices and layer_names)
    material["aion_blend_shader_material_count"] = len(selected_indices)
    material["aion_blend_shader_included_materials"] = ",".join(str(index) for index in selected_indices)
    material["aion_blend_attribute_layers"] = ",".join(layer_names)
    material["aion_blend_shader_skipped_materials"] = ",".join(str(index) for index in skipped_indices)
    material["aion_blend_shader_skipped_sample_counts"] = ",".join(
        f"{index}:{count}" for index, count in skipped_sample_counts
    )
    material["aion_blend_shader_skipped_reasons"] = ",".join(
        f"{index}:{reason}:{count}" for index, reason, count in skipped_materials
    )
    material["aion_blend_shader_projection"] = BLEND_SHADER_PROJECTION_PROJ_AXIS
    material["aion_blend_shader_material_details"] = _format_material_details(
        selected_indices,
        slot_by_index,
        sample_counts,
    )

    nodes = material.node_tree.nodes
    links = material.node_tree.links
    nodes.clear()

    output = nodes.new(type="ShaderNodeOutputMaterial")
    bsdf = nodes.new(type="ShaderNodeBsdfPrincipled")
    links.new(bsdf.outputs["BSDF"], output.inputs["Surface"])
    geometry = nodes.new(type="ShaderNodeNewGeometry")
    separate_xyz = nodes.new(type="ShaderNodeSeparateXYZ")
    links.new(geometry.outputs["Position"], separate_xyz.inputs["Vector"])

    texture_images_loaded = 0
    texture_images_failed = 0
    texture_nodes_created = 0
    previous_color = None

    for material_index in selected_indices:
        slot = slot_by_index[material_index]
        color_output = _create_material_color_source(
            bpy,
            nodes,
            links,
            slot,
            load_textures,
            mesh.uv_layers.active.name if mesh.uv_layers.active else "",
            separate_xyz,
        )
        texture_nodes_created += color_output.texture_nodes_created
        texture_images_loaded += color_output.texture_images_loaded
        texture_images_failed += color_output.texture_images_failed
        weight_output = _create_weight_source(
            nodes,
            links,
            material_index,
            material_indices,
            layer_names,
        )
        if previous_color is None:
            previous_color = color_output.color_socket
            continue
        mix = nodes.new(type="ShaderNodeMixRGB")
        mix.blend_type = "MIX"
        mix.use_clamp = True
        links.new(weight_output, mix.inputs["Fac"])
        links.new(previous_color, mix.inputs["Color1"])
        links.new(color_output.color_socket, mix.inputs["Color2"])
        previous_color = mix.outputs["Color"]

    graph_created = previous_color is not None and bool(layer_names)
    if graph_created:
        links.new(previous_color, bsdf.inputs["Base Color"])
    material["aion_blend_shader_warnings"] = "; ".join(warnings)
    material["aion_blend_shader_graph_created"] = graph_created
    mesh.materials.append(material)
    blend_slot_index = len(mesh.materials) - 1
    if graph_created:
        for polygon in mesh.polygons:
            polygon.material_index = blend_slot_index

    return TerrainBlendShaderResult(
        enabled=True,
        graph_created=graph_created,
        material_count=len(selected_indices),
        included_material_indices=selected_indices,
        texture_images_loaded=texture_images_loaded,
        texture_images_failed=texture_images_failed,
        texture_nodes_created=texture_nodes_created,
        skipped_material_indices=skipped_indices,
        skipped_material_sample_counts=skipped_sample_counts,
        skipped_material_reasons=skipped_materials,
        projection_mode=BLEND_SHADER_PROJECTION_PROJ_AXIS,
        warnings=tuple(warnings),
    )


@dataclass(frozen=True)
class _MaterialColorSource:
    color_socket: object
    texture_nodes_created: int = 0
    texture_images_loaded: int = 0
    texture_images_failed: int = 0


def _create_material_color_source(
    bpy,
    nodes,
    links,
    slot,
    load_textures: bool,
    uv_map_name: str,
    separate_xyz,
) -> _MaterialColorSource:
    texture_path = slot.material.get("aion_detail_texture_resolved", "") if slot.material else ""

    if load_textures and texture_path:
        texture = nodes.new(type="ShaderNodeTexImage")
        texture.label = f"Aion Terrain Surface {slot.terrain_material_index}"
        texture.name = texture.label
        vector_output = _create_projection_vector_source(
            nodes,
            links,
            slot,
            separate_xyz,
            uv_map_name,
        )
        links.new(vector_output, texture.inputs["Vector"])
        try:
            texture.image = bpy.data.images.load(texture_path, check_existing=True)
        except RuntimeError:
            return _MaterialColorSource(
                color_socket=_create_rgb_node(nodes, slot).outputs["Color"],
                texture_nodes_created=1,
                texture_images_failed=1,
            )
        return _MaterialColorSource(
            color_socket=texture.outputs["Color"],
            texture_nodes_created=1,
            texture_images_loaded=1 if texture.image is not None else 0,
        )

    return _MaterialColorSource(color_socket=_create_rgb_node(nodes, slot).outputs["Color"])


def _create_rgb_node(nodes, slot):
    rgb = nodes.new(type="ShaderNodeRGB")
    hue = (slot.terrain_material_index * 0.137) % 1.0
    rgb.outputs["Color"].default_value = (
        0.25 + hue * 0.5,
        0.55,
        0.85 - hue * 0.3,
        1.0,
    )
    return rgb


def _create_weight_source(
    nodes,
    links,
    material_index: int,
    material_indices: tuple[int, ...],
    layer_names: tuple[str, ...],
):
    packed_index = material_indices.index(material_index)
    layer_index = packed_index // 4
    channel_index = packed_index % 4
    attribute = nodes.new(type="ShaderNodeAttribute")
    attribute.attribute_name = layer_names[layer_index] if layer_index < len(layer_names) else ""
    if channel_index == 3:
        return attribute.outputs["Alpha"]
    separate = nodes.new(type="ShaderNodeSeparateColor")
    links.new(attribute.outputs["Color"], separate.inputs["Color"])
    return separate.outputs[("Red", "Green", "Blue")[channel_index]]


def _classify_shader_material_indices(
    material_indices: tuple[int, ...],
    slot_by_index: dict[int, object],
    sample_counts: dict[int, int],
    material_limit: int,
    load_textures: bool,
) -> tuple[tuple[int, ...], tuple[tuple[int, str, int], ...]]:
    included = []
    skipped = []
    for index in material_indices:
        sample_count = int(sample_counts.get(index, 0))
        if index >= MAX_BLEND_SHADER_MATERIALS:
            skipped.append((index, "out_of_range", sample_count))
        elif index not in slot_by_index:
            skipped.append((index, "missing_surface_type", sample_count))
        elif load_textures and not slot_by_index[index].material.get("aion_detail_texture_exists", False):
            skipped.append((index, "missing_texture", sample_count))
        else:
            included.append(index)
    if len(included) > material_limit:
        graph_limited = included[material_limit:]
        included = included[:material_limit]
        skipped.extend(
            (index, "graph_limit", int(sample_counts.get(index, 0)))
            for index in graph_limited
        )
    return tuple(included), tuple(skipped)


def _create_projection_vector_source(
    nodes,
    links,
    slot,
    separate_xyz,
    uv_map_name: str,
):
    surface_type = slot.surface_type
    proj_axis = (surface_type.proj_axis or "").upper() if surface_type else ""
    if proj_axis not in {"X", "Y", "Z"}:
        if uv_map_name:
            uv_map = nodes.new(type="ShaderNodeUVMap")
            uv_map.uv_map = uv_map_name
            return uv_map.outputs["UV"]
        proj_axis = "Z"

    combine = nodes.new(type="ShaderNodeCombineXYZ")
    if proj_axis == "X":
        links.new(separate_xyz.outputs["Y"], combine.inputs["X"])
        links.new(separate_xyz.outputs["Z"], combine.inputs["Y"])
    elif proj_axis == "Y":
        links.new(separate_xyz.outputs["X"], combine.inputs["X"])
        links.new(separate_xyz.outputs["Z"], combine.inputs["Y"])
    else:
        links.new(separate_xyz.outputs["Y"], combine.inputs["X"])
        links.new(separate_xyz.outputs["X"], combine.inputs["Y"])

    mapping = nodes.new(type="ShaderNodeMapping")
    mapping.inputs["Scale"].default_value = (
        _safe_surface_scale(surface_type.detail_scale_x if surface_type else None),
        _safe_surface_scale(surface_type.detail_scale_y if surface_type else None),
        1.0,
    )
    links.new(combine.outputs["Vector"], mapping.inputs["Vector"])
    return mapping.outputs["Vector"]


def _safe_surface_scale(value: float | None) -> float:
    return value if value is not None and value > 0 else 1.0


def _format_material_details(
    selected_indices: tuple[int, ...],
    slot_by_index: dict[int, object],
    sample_counts: dict[int, int],
) -> str:
    parts = []
    for index in selected_indices:
        slot = slot_by_index[index]
        surface_type = slot.surface_type
        material = slot.material
        parts.append(
            "|".join(
                (
                    str(index),
                    str(sample_counts.get(index, 0)),
                    surface_type.name or "",
                    surface_type.detail_texture or "",
                    (surface_type.proj_axis or "").upper(),
                    str(surface_type.detail_scale_x or ""),
                    str(surface_type.detail_scale_y or ""),
                    str(material.get("aion_detail_texture_exists", "")) if material else "",
                )
            )
        )
    return ";".join(parts)
