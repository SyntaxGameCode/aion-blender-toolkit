import colorsys
import math
from collections import Counter
from dataclasses import dataclass
from pathlib import Path, PureWindowsPath

from aion_formats.level import (
    LandMap,
    LevelData,
    SurfaceType,
    TerrainMaterialInventory,
    build_terrain_preview_blend_weights,
    build_terrain_material_inventory,
)

from .terrain_blend_attributes import (
    TerrainBlendAttributeResult,
    create_terrain_blend_attributes,
)
from .terrain_blend_nodes import (
    TerrainBlendShaderResult,
    create_terrain_blend_shader,
)
from .terrain_textures import resolve_terrain_detail_texture
from .terrain_material_nodes import TerrainTextureNodeResult, create_terrain_texture_nodes


DEFAULT_TERRAIN_NAME = "Aion Terrain"
DEFAULT_XY_SCALE = 2.0


@dataclass(frozen=True)
class TerrainMeshResult:
    object: object
    mesh: object
    width: int
    height: int
    vertex_count: int
    face_count: int
    min_height: float
    max_height: float
    xy_scale: float
    material_slot_count: int = 0
    assigned_material_index_count: int = 0
    uv_layer_count: int = 0
    uv_loop_count: int = 0
    image_count_delta: int = 0
    detail_texture_count: int = 0
    resolved_detail_texture_count: int = 0
    existing_detail_texture_count: int = 0
    missing_detail_texture_count: int = 0
    texture_load_requested: bool = False
    texture_images_loaded: int = 0
    texture_images_failed: int = 0
    texture_nodes_created: int = 0
    blend_attributes_requested: bool = False
    blend_attribute_layers_created: int = 0
    blend_weight_material_count: int = 0
    blend_boundary_sample_count: int = 0
    blend_invalid_weight_count: int = 0
    blend_shader_enabled: bool = False
    blend_shader_graph_created: bool = False
    blend_shader_material_count: int = 0
    blend_shader_included_material_indices: tuple[int, ...] = ()
    blend_shader_texture_images_loaded: int = 0
    blend_shader_texture_images_failed: int = 0
    blend_shader_texture_nodes_created: int = 0
    blend_shader_skipped_material_indices: tuple[int, ...] = ()
    blend_shader_skipped_material_sample_counts: tuple[tuple[int, int], ...] = ()
    blend_shader_skipped_material_reasons: tuple[tuple[int, str, int], ...] = ()
    blend_shader_projection_mode: str = ""
    blend_shader_warnings: tuple[str, ...] = ()


@dataclass(frozen=True)
class TerrainMaterialSlot:
    terrain_material_index: int
    slot_index: int
    name: str
    surface_type: SurfaceType | None
    material: object | None = None


def build_terrain_geometry(
    land_map: LandMap,
    xy_scale: float = DEFAULT_XY_SCALE,
) -> tuple[tuple[tuple[float, float, float], ...], tuple[tuple[int, int, int, int], ...]]:
    if land_map.sample_count != land_map.width * land_map.height:
        raise ValueError("LandMap sample count does not match width * height")
    if not math.isfinite(xy_scale) or xy_scale <= 0:
        raise ValueError("terrain XY scale must be finite and positive")

    vertices = tuple(
        (
            float(index // land_map.width) * xy_scale,
            float(index % land_map.width) * xy_scale,
            sample.height,
        )
        for index, sample in enumerate(land_map.samples)
    )
    if not all(math.isfinite(value) for vertex in vertices for value in vertex):
        raise ValueError("terrain geometry contains NaN or infinity")

    faces = tuple(
        (
            row * land_map.width + column,
            (row + 1) * land_map.width + column,
            (row + 1) * land_map.width + column + 1,
            row * land_map.width + column + 1,
        )
        for row in range(land_map.height - 1)
        for column in range(land_map.width - 1)
    )
    return vertices, faces


def create_terrain_mesh(
    context,
    land_map: LandMap,
    level_data: LevelData | None = None,
    client_root: str | Path | None = None,
    import_terrain_textures: bool = False,
    import_terrain_blend_attributes: bool = False,
    import_terrain_blend_shader: bool = False,
    name: str = DEFAULT_TERRAIN_NAME,
    xy_scale: float = DEFAULT_XY_SCALE,
) -> TerrainMeshResult:
    import bpy

    images_before = len(bpy.data.images)
    vertices, faces = build_terrain_geometry(land_map, xy_scale=xy_scale)
    mesh = bpy.data.meshes.new(name)
    mesh.from_pydata(vertices, (), faces)
    mesh.update(calc_edges=False)

    material_slots = ()
    assigned_material_index_count = 0
    texture_node_result = TerrainTextureNodeResult(
        texture_load_requested=False,
        texture_images_loaded=0,
        texture_images_failed=0,
        texture_nodes_created=0,
    )
    blend_weights = None
    blend_attribute_result = TerrainBlendAttributeResult(
        attribute_layers_created=0,
        material_count=0,
        layer_names=(),
    )
    if import_terrain_blend_attributes or import_terrain_blend_shader:
        blend_weights = build_terrain_preview_blend_weights(land_map, radius=1)
        blend_attribute_result = create_terrain_blend_attributes(mesh, blend_weights)
    blend_shader_result = TerrainBlendShaderResult(
        enabled=False,
        graph_created=False,
        material_count=0,
        included_material_indices=(),
        texture_images_loaded=0,
        texture_images_failed=0,
        texture_nodes_created=0,
        skipped_material_indices=(),
        skipped_material_sample_counts=(),
        skipped_material_reasons=(),
        projection_mode="",
        warnings=(),
    )

    if level_data is not None:
        inventory = build_terrain_material_inventory(land_map, level_data)
        material_slots = _create_terrain_materials(bpy, mesh, inventory, client_root)
        assigned_material_index_count = _assign_face_material_indices(
            mesh,
            land_map,
            material_slots,
        )
        _assign_preview_uvs(mesh, land_map, material_slots)
        if import_terrain_textures:
            texture_node_result = create_terrain_texture_nodes(bpy, mesh.materials)
        if import_terrain_blend_shader:
            blend_shader_result = create_terrain_blend_shader(
                bpy,
                mesh,
                material_slots,
                material_sample_counts=_terrain_material_sample_counts(land_map),
                load_textures=import_terrain_textures,
            )

    terrain_object = bpy.data.objects.new(name, mesh)
    terrain_object["aion_blend_shader_enabled"] = blend_shader_result.enabled
    terrain_object["aion_blend_shader_material_count"] = blend_shader_result.material_count
    terrain_object["aion_blend_shader_included_materials"] = ",".join(
        str(index) for index in blend_shader_result.included_material_indices
    )
    terrain_object["aion_blend_attribute_layers"] = ",".join(blend_attribute_result.layer_names)
    terrain_object["aion_blend_shader_skipped_materials"] = ",".join(
        str(index) for index in blend_shader_result.skipped_material_indices
    )
    terrain_object["aion_blend_shader_skipped_sample_counts"] = ",".join(
        f"{index}:{count}"
        for index, count in blend_shader_result.skipped_material_sample_counts
    )
    terrain_object["aion_blend_shader_skipped_reasons"] = ",".join(
        f"{index}:{reason}:{count}"
        for index, reason, count in blend_shader_result.skipped_material_reasons
    )
    terrain_object["aion_blend_shader_projection"] = blend_shader_result.projection_mode
    terrain_object["aion_blend_shader_warnings"] = "; ".join(blend_shader_result.warnings)
    context.scene.collection.objects.link(terrain_object)
    return TerrainMeshResult(
        object=terrain_object,
        mesh=mesh,
        width=land_map.width,
        height=land_map.height,
        vertex_count=len(vertices),
        face_count=len(faces),
        min_height=land_map.min_height,
        max_height=land_map.max_height,
        xy_scale=xy_scale,
        material_slot_count=len(material_slots),
        assigned_material_index_count=assigned_material_index_count,
        uv_layer_count=len(mesh.uv_layers),
        uv_loop_count=len(mesh.uv_layers.active.data) if mesh.uv_layers.active else 0,
        image_count_delta=len(bpy.data.images) - images_before,
        detail_texture_count=_count_materials_with_property(mesh, "aion_detail_texture"),
        resolved_detail_texture_count=_count_materials_with_property(mesh, "aion_detail_texture_resolved"),
        existing_detail_texture_count=_count_materials_with_existing_detail_texture(mesh, True),
        missing_detail_texture_count=_count_materials_with_existing_detail_texture(mesh, False),
        texture_load_requested=texture_node_result.texture_load_requested,
        texture_images_loaded=texture_node_result.texture_images_loaded,
        texture_images_failed=texture_node_result.texture_images_failed,
        texture_nodes_created=texture_node_result.texture_nodes_created,
        blend_attributes_requested=import_terrain_blend_attributes or import_terrain_blend_shader,
        blend_attribute_layers_created=blend_attribute_result.attribute_layers_created,
        blend_weight_material_count=blend_attribute_result.material_count,
        blend_boundary_sample_count=blend_weights.boundary_sample_count if blend_weights else 0,
        blend_invalid_weight_count=blend_weights.invalid_weight_count if blend_weights else 0,
        blend_shader_enabled=blend_shader_result.enabled,
        blend_shader_graph_created=blend_shader_result.graph_created,
        blend_shader_material_count=blend_shader_result.material_count,
        blend_shader_included_material_indices=blend_shader_result.included_material_indices,
        blend_shader_texture_images_loaded=blend_shader_result.texture_images_loaded,
        blend_shader_texture_images_failed=blend_shader_result.texture_images_failed,
        blend_shader_texture_nodes_created=blend_shader_result.texture_nodes_created,
        blend_shader_skipped_material_indices=blend_shader_result.skipped_material_indices,
        blend_shader_skipped_material_sample_counts=blend_shader_result.skipped_material_sample_counts,
        blend_shader_skipped_material_reasons=blend_shader_result.skipped_material_reasons,
        blend_shader_projection_mode=blend_shader_result.projection_mode,
        blend_shader_warnings=blend_shader_result.warnings,
    )


def _create_terrain_materials(
    bpy,
    mesh,
    inventory: TerrainMaterialInventory,
    client_root: str | Path | None,
) -> tuple[TerrainMaterialSlot, ...]:
    slots = []
    for usage in inventory.used_material_indices:
        material_name = _terrain_material_name(usage.index, usage.surface_type)
        material = bpy.data.materials.new(material_name)
        material.use_nodes = False
        material.node_tree.nodes.clear()
        material.diffuse_color = _terrain_material_color(usage.index)
        material["aion_terrain_material_index"] = usage.index
        if usage.surface_type is not None:
            material["aion_surface_name"] = usage.surface_type.name or ""
            texture_ref = resolve_terrain_detail_texture(
                client_root,
                usage.surface_type.detail_texture,
            )
            material["aion_detail_texture"] = texture_ref.raw_path
            material["aion_detail_texture_normalized"] = texture_ref.normalized_relative_path
            material["aion_detail_texture_resolved"] = texture_ref.resolved_path or ""
            material["aion_detail_texture_exists"] = texture_ref.exists
        else:
            material["aion_surface_missing"] = True

        slot = TerrainMaterialSlot(
            terrain_material_index=usage.index,
            slot_index=len(mesh.materials),
            name=material_name,
            surface_type=usage.surface_type,
            material=material,
        )
        mesh.materials.append(material)
        slots.append(slot)

    return tuple(slots)


def _assign_face_material_indices(
    mesh,
    land_map: LandMap,
    material_slots: tuple[TerrainMaterialSlot, ...],
) -> int:
    slot_by_terrain_index = {
        slot.terrain_material_index: slot.slot_index
        for slot in material_slots
    }
    assigned_indices = set()
    for row in range(land_map.height - 1):
        for column in range(land_map.width - 1):
            polygon_index = row * (land_map.width - 1) + column
            sample_index = row * land_map.width + column
            terrain_material_index = land_map.samples[sample_index].color
            slot_index = slot_by_terrain_index.get(terrain_material_index)
            if slot_index is not None:
                mesh.polygons[polygon_index].material_index = slot_index
                assigned_indices.add(slot_index)

    return len(assigned_indices)


def _assign_preview_uvs(
    mesh,
    land_map: LandMap,
    material_slots: tuple[TerrainMaterialSlot, ...],
) -> None:
    slot_by_terrain_index = {
        slot.terrain_material_index: slot
        for slot in material_slots
    }
    uv_layer = mesh.uv_layers.new(name="Aion Terrain Preview UV")
    for row in range(land_map.height - 1):
        for column in range(land_map.width - 1):
            polygon_index = row * (land_map.width - 1) + column
            sample_index = row * land_map.width + column
            terrain_material_index = land_map.samples[sample_index].color
            slot = slot_by_terrain_index.get(terrain_material_index)
            surface_type = slot.surface_type if slot is not None else None

            polygon = mesh.polygons[polygon_index]
            for loop_index, vertex_index in zip(polygon.loop_indices, polygon.vertices):
                vertex_column = vertex_index % land_map.width
                vertex_row = vertex_index // land_map.width
                uv_layer.data[loop_index].uv = _preview_uv_for_grid(
                    vertex_column,
                    vertex_row,
                    surface_type,
                )


def _preview_uv_for_grid(
    column: int,
    row: int,
    surface_type: SurfaceType | None,
) -> tuple[float, float]:
    scale_x = surface_type.detail_scale_x if surface_type and surface_type.detail_scale_x is not None else 1.0
    scale_y = surface_type.detail_scale_y if surface_type and surface_type.detail_scale_y is not None else 1.0
    offset_u = surface_type.offset_u if surface_type and surface_type.offset_u is not None else 0.0
    offset_v = surface_type.offset_v if surface_type and surface_type.offset_v is not None else 0.0
    return (
        float(column) * scale_x + offset_u,
        float(row) * scale_y + offset_v,
    )


def _terrain_material_name(index: int, surface_type: SurfaceType | None) -> str:
    label = None
    if surface_type is not None:
        label = surface_type.name or (
            PureWindowsPath(surface_type.detail_texture).name
            if surface_type.detail_texture
            else None
        )
    return f"Terrain Surface {index}: {label or 'Unknown'}"


def _terrain_material_color(index: int) -> tuple[float, float, float, float]:
    hue = (index * 0.137) % 1.0
    red, green, blue = colorsys.hsv_to_rgb(hue, 0.45, 0.85)
    return (red, green, blue, 1.0)


def _count_materials_with_property(mesh, property_name: str) -> int:
    return sum(1 for material in mesh.materials if bool(material.get(property_name)))


def _count_materials_with_existing_detail_texture(mesh, exists: bool) -> int:
    return sum(
        1
        for material in mesh.materials
        if bool(material.get("aion_detail_texture")) and material.get("aion_detail_texture_exists") is exists
    )


def _terrain_material_sample_counts(land_map: LandMap) -> dict[int, int]:
    return dict(Counter(sample.color for sample in land_map.samples))
