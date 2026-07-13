from dataclasses import dataclass
from pathlib import Path

from aion_formats.level import (
    parse_brush_lst,
    parse_land_map_h32,
    parse_leveldata,
    parse_objects_lst,
)

from .level_jobs import collect_level_cgf_jobs
from .level_templates import group_level_cgf_templates
from .resource_resolver import resolve_level_cgf_jobs


@dataclass(frozen=True)
class LevelImportExecutionSummary:
    import_scope: str
    cgf_total: int
    cgf_selected: int
    cgf_imported: int
    cgf_failed: int
    cgf_skipped_expected: int
    placements_created: int
    invalid_placements_skipped: int
    invalid_object_scale_count: int
    invalid_brush_matrix_count: int
    invalid_placement_sample: str | None
    terrain_enabled: bool
    terrain_created: bool
    terrain_vertices: int
    terrain_faces: int
    terrain_materials: int
    terrain_uv_loops: int
    detail_textures_total: int
    detail_textures_existing: int
    detail_textures_missing: int
    texture_preview_requested: bool
    texture_images_loaded: int
    texture_images_failed: int
    texture_nodes_created: int
    blend_attributes_requested: bool
    blend_attribute_layers_created: int
    blend_weight_material_count: int
    blend_boundary_sample_count: int
    blend_invalid_weight_count: int
    blend_shader_requested: bool
    blend_shader_graph_created: bool
    blend_shader_material_count: int
    blend_shader_included_materials: str
    blend_shader_texture_images_loaded: int
    blend_shader_texture_images_failed: int
    blend_shader_texture_nodes_created: int
    blend_shader_skipped_material_count: int
    blend_shader_skipped_sample_counts: str
    blend_shader_skipped_reasons: str
    blend_shader_projection_mode: str
    blend_shader_warnings: str
    water_enabled: bool
    water_created: bool
    water_level: float | None
    water_width: float
    water_height: float
    water_skip_reason: str | None
    liquid_surface_requested: bool = False
    liquid_surface_applied: bool = False
    liquid_surface_kind: str = ""
    liquid_surface_inferred_kind: str = ""
    liquid_surface_preset: str = ""
    liquid_surface_textures_loaded: int = 0
    liquid_surface_textures_used: int = 0
    liquid_surface_material_name: str = ""
    liquid_surface_skip_reason: str | None = None
    liquid_surface_warnings: str = ""
    static_lights_enabled: bool = False
    static_lights_file_found: bool = False
    static_lights_created: bool = False
    static_lights_count: int = 0
    static_lights_created_count: int = 0
    static_lights_failed_count: int = 0
    static_lights_mode: str = ""
    static_lights_power: float = 0.0
    static_lights_skip_reason: str | None = None
    mission_placeables_enabled: bool = False
    mission_placeables_file_found: bool = False
    mission_placeables_created: bool = False
    mission_placeables_candidates: int = 0
    mission_placeables_created_count: int = 0
    mission_placeables_skipped_count: int = 0
    mission_placeables_failed_count: int = 0
    mission_placeables_angles_applied_count: int = 0
    mission_placeables_skip_reasons: str = ""
    mission_placeables_failure_reasons: str = ""
    particle_effects_enabled: bool = False
    particle_effects_files_scanned: int = 0
    particle_effects_records_found: int = 0
    particle_effects_definitions_found: int = 0
    particle_effects_textures_resolved: int = 0
    particle_effects_sprites_created: int = 0
    particle_effects_markers_created: int = 0
    particle_effects_skipped_invalid: int = 0
    particle_effects_unsupported_count: int = 0
    particle_effects_skip_reasons: str = ""
    cga_entities_enabled: bool = False
    cga_entities_file_found: bool = False
    cga_entities_created: bool = False
    cga_entities_candidates: int = 0
    cga_entities_created_count: int = 0
    cga_entities_skipped_count: int = 0
    cga_entities_failed_count: int = 0
    cga_entities_angles_applied_count: int = 0
    cga_entities_controller_count: int = 0
    cga_entities_timing_present_count: int = 0
    cga_entities_skip_reasons: str = ""
    cga_entities_failure_reasons: str = ""
    texture_sequences_requested: bool = False
    texture_sequences_applied: int = 0
    texture_sequences_skipped: int = 0
    texture_sequence_missing_frames: int = 0
    shader_uv_scroll_requested: bool = False
    shader_uv_scroll_applied: int = 0
    shader_uv_scroll_skipped: int = 0


def format_level_import_report(summary: LevelImportExecutionSummary) -> str:
    terrain_state = "created" if summary.terrain_created else (
        "requested" if summary.terrain_enabled else "off"
    )
    texture_state = "on" if summary.texture_preview_requested else "off"
    blend_state = "on" if summary.blend_attributes_requested else "off"
    blend_shader_state = "created" if summary.blend_shader_graph_created else (
        "requested" if summary.blend_shader_requested else "off"
    )
    blend_shader_warning = (
        f", warnings={summary.blend_shader_warnings}"
        if summary.blend_shader_warnings
        else ""
    )
    blend_shader_skipped_samples = (
        f", skipped_samples={summary.blend_shader_skipped_sample_counts}"
        if summary.blend_shader_skipped_sample_counts
        else ""
    )
    blend_shader_skipped_reasons = (
        f", skipped_reasons={summary.blend_shader_skipped_reasons}"
        if summary.blend_shader_skipped_reasons
        else ""
    )
    water_state = "created" if summary.water_created else (
        "requested" if summary.water_enabled else "off"
    )
    water_reason = (
        f", reason={summary.water_skip_reason}"
        if summary.water_skip_reason
        else ""
    )
    liquid_state = "applied" if summary.liquid_surface_applied else (
        "requested" if summary.liquid_surface_requested else "off"
    )
    liquid_reason = (
        f", reason={summary.liquid_surface_skip_reason}"
        if summary.liquid_surface_skip_reason
        else ""
    )
    liquid_warnings = (
        f", warnings={summary.liquid_surface_warnings}"
        if summary.liquid_surface_warnings
        else ""
    )
    static_lights_state = "created" if summary.static_lights_created else (
        "requested" if summary.static_lights_enabled else "off"
    )
    static_lights_reason = (
        f", reason={summary.static_lights_skip_reason}"
        if summary.static_lights_skip_reason
        else ""
    )
    mission_placeables_state = "created" if summary.mission_placeables_created else (
        "requested" if summary.mission_placeables_enabled else "off"
    )
    mission_placeables_skip_reasons = (
        f", skip_reasons={summary.mission_placeables_skip_reasons}"
        if summary.mission_placeables_skip_reasons
        else ""
    )
    mission_placeables_failure_reasons = (
        f", failure_reasons={summary.mission_placeables_failure_reasons}"
        if summary.mission_placeables_failure_reasons
        else ""
    )
    particle_effects_state = (
        "created"
        if summary.particle_effects_sprites_created or summary.particle_effects_markers_created
        else ("requested" if summary.particle_effects_enabled else "off")
    )
    particle_effects_skip_reasons = (
        f", skip_reasons={summary.particle_effects_skip_reasons}"
        if summary.particle_effects_skip_reasons
        else ""
    )
    cga_entities_state = "created" if summary.cga_entities_created else (
        "requested" if summary.cga_entities_enabled else "off"
    )
    cga_entities_skip_reasons = (
        f", skip_reasons={summary.cga_entities_skip_reasons}"
        if summary.cga_entities_skip_reasons
        else ""
    )
    cga_entities_failure_reasons = (
        f", failure_reasons={summary.cga_entities_failure_reasons}"
        if summary.cga_entities_failure_reasons
        else ""
    )
    texture_sequence_state = "on" if summary.texture_sequences_requested else "off"
    shader_uv_scroll_state = "on" if summary.shader_uv_scroll_requested else "off"
    invalid_sample = (
        f", sample={summary.invalid_placement_sample}"
        if summary.invalid_placement_sample
        else ""
    )
    warnings = []
    if summary.cgf_failed:
        warnings.append(f"cgf_failed={summary.cgf_failed}")
    if summary.invalid_placements_skipped:
        warnings.append(f"invalid_placements={summary.invalid_placements_skipped}")
    if summary.texture_images_failed:
        warnings.append(f"terrain_texture_failures={summary.texture_images_failed}")
    if summary.blend_shader_texture_images_failed:
        warnings.append(f"blend_shader_texture_failures={summary.blend_shader_texture_images_failed}")
    if summary.liquid_surface_skip_reason:
        warnings.append(f"liquid_surface={summary.liquid_surface_skip_reason}")
    if summary.static_lights_failed_count:
        warnings.append(f"static_lights_failed={summary.static_lights_failed_count}")
    if summary.mission_placeables_failed_count:
        warnings.append(f"mission_placeables_failed={summary.mission_placeables_failed_count}")
    if summary.cga_entities_failed_count:
        warnings.append(f"cga_entities_failed={summary.cga_entities_failed_count}")
    warning_text = ", ".join(warnings) if warnings else "none"
    return (
        "Aion level import: "
        f"scope={summary.import_scope}; "
        f"Geometry: CGF total={summary.cgf_total}, selected={summary.cgf_selected}, "
        f"imported={summary.cgf_imported}, skipped={summary.cgf_skipped_expected}, "
        f"failed={summary.cgf_failed}; "
        f"Collision: placements={summary.placements_created}, "
        f"invalid skipped={summary.invalid_placements_skipped} "
        f"(object scale={summary.invalid_object_scale_count}, "
        f"brush matrix={summary.invalid_brush_matrix_count}{invalid_sample}); "
        f"Terrain: terrain {terrain_state} "
        f"({summary.terrain_vertices} vertices, {summary.terrain_faces} faces, "
        f"{summary.terrain_materials} materials, {summary.terrain_uv_loops} UV loops); "
        f"detail textures {summary.detail_textures_existing}/{summary.detail_textures_total} existing"
        f" ({summary.detail_textures_missing} missing); "
        f"texture preview {texture_state} "
        f"({summary.texture_images_loaded} loaded, {summary.texture_images_failed} failed, "
        f"{summary.texture_nodes_created} nodes); "
        f"blend attributes {blend_state} "
        f"({summary.blend_attribute_layers_created} layers, "
        f"{summary.blend_weight_material_count} materials, "
        f"{summary.blend_boundary_sample_count} boundary samples, "
        f"{summary.blend_invalid_weight_count} invalid); "
        f"blend shader {blend_shader_state} "
        f"({summary.blend_shader_material_count} materials, "
        f"included={summary.blend_shader_included_materials or '-'}, "
        f"projection={summary.blend_shader_projection_mode or '-'}, "
        f"{summary.blend_shader_texture_images_loaded} images loaded, "
        f"{summary.blend_shader_texture_images_failed} image failures, "
        f"{summary.blend_shader_texture_nodes_created} texture nodes, "
        f"{summary.blend_shader_skipped_material_count} skipped"
        f"{blend_shader_skipped_samples}"
        f"{blend_shader_skipped_reasons}"
        f"{blend_shader_warning}); "
        f"water {water_state} "
        f"(level={summary.water_level}, size={summary.water_width}x{summary.water_height}"
        f"{water_reason}); "
        f"World: liquid surface {liquid_state} "
        f"(kind={summary.liquid_surface_kind or '-'}, "
        f"inferred={summary.liquid_surface_inferred_kind or '-'}, "
        f"preset={summary.liquid_surface_preset or '-'}, "
        f"textures={summary.liquid_surface_textures_used}/{summary.liquid_surface_textures_loaded} used"
        f"{liquid_reason}{liquid_warnings}); "
        f"static lights {static_lights_state} "
        f"(file={'yes' if summary.static_lights_file_found else 'no'}, "
        f"mode={summary.static_lights_mode or '-'}, "
        f"power={summary.static_lights_power}, "
        f"created={summary.static_lights_created_count}/{summary.static_lights_count}, "
        f"failed={summary.static_lights_failed_count}"
        f"{static_lights_reason}); "
        f"Dynamic: mission placeables {mission_placeables_state} "
        f"(file={'yes' if summary.mission_placeables_file_found else 'no'}, "
        f"created={summary.mission_placeables_created_count}/{summary.mission_placeables_candidates}, "
        f"skipped={summary.mission_placeables_skipped_count}, "
        f"failed={summary.mission_placeables_failed_count}, "
        f"angles={summary.mission_placeables_angles_applied_count}"
        f"{mission_placeables_skip_reasons}"
        f"{mission_placeables_failure_reasons}); "
        f"particle effects {particle_effects_state} "
        f"(files={summary.particle_effects_files_scanned}, "
        f"records={summary.particle_effects_records_found}, "
        f"defs={summary.particle_effects_definitions_found}, "
        f"textures={summary.particle_effects_textures_resolved}, "
        f"sprites={summary.particle_effects_sprites_created}, "
        f"markers={summary.particle_effects_markers_created}, "
        f"invalid={summary.particle_effects_skipped_invalid}, "
        f"unsupported={summary.particle_effects_unsupported_count}"
        f"{particle_effects_skip_reasons}); "
        f"CGA entities {cga_entities_state} "
        f"(file={'yes' if summary.cga_entities_file_found else 'no'}, "
        f"created={summary.cga_entities_created_count}/{summary.cga_entities_candidates}, "
        f"skipped={summary.cga_entities_skipped_count}, "
        f"failed={summary.cga_entities_failed_count}, "
        f"angles={summary.cga_entities_angles_applied_count}, "
        f"controllers={summary.cga_entities_controller_count}, "
        f"timing={summary.cga_entities_timing_present_count}"
        f"{cga_entities_skip_reasons}"
        f"{cga_entities_failure_reasons}); "
        f"texture sequences {texture_sequence_state} "
        f"({summary.texture_sequences_applied} applied, "
        f"{summary.texture_sequences_skipped} skipped, "
        f"{summary.texture_sequence_missing_frames} missing frames); "
        f"shader UV scroll {shader_uv_scroll_state} "
        f"({summary.shader_uv_scroll_applied} applied, "
        f"{summary.shader_uv_scroll_skipped} skipped); "
        f"Warnings: {warning_text}"
    )


@dataclass(frozen=True)
class LevelImportSummary:
    level_dir: Path
    import_mode: str
    vegetation_count: int
    object_count: int | None
    brush_mesh_count: int | None
    brush_node_count: int | None
    terrain_width: int | None
    terrain_height: int | None
    terrain_sample_count: int | None
    cgf_job_count: int
    object_job_count: int
    brush_job_count: int
    unresolved_reference_count: int
    resource_resolution_enabled: bool
    resolved_cgf_job_count: int
    missing_cgf_resource_count: int
    unique_template_count: int
    max_placements_per_template: int
    top_repeated_templates: tuple[tuple[str, int], ...]
    missing_optional_files: tuple[str, ...]


def summarize_level_folder(
    level_dir: str | Path,
    import_mode: str = "VISUAL",
    client_root: str | Path | None = None,
) -> LevelImportSummary:
    level_path = Path(level_dir)
    leveldata_path = level_path / "leveldata.xml"
    if not leveldata_path.is_file():
        raise FileNotFoundError(f"leveldata.xml is required: {leveldata_path}")

    level_data = parse_leveldata(leveldata_path)
    missing_optional_files = []

    objects_path = level_path / "objects.lst"
    if objects_path.is_file():
        objects = parse_objects_lst(objects_path, level_data)
        object_count = len(objects.placements)
    else:
        objects = None
        object_count = None
        missing_optional_files.append("objects.lst")

    brush_path = level_path / "brush.lst"
    if brush_path.is_file():
        brush = parse_brush_lst(brush_path)
        brush_mesh_count = len(brush.meshes)
        brush_node_count = len(brush.nodes)
    else:
        brush = None
        brush_mesh_count = None
        brush_node_count = None
        missing_optional_files.append("brush.lst")

    land_map_path = level_path / "terrain" / "land_map.h32"
    if land_map_path.is_file():
        land_map = parse_land_map_h32(land_map_path)
        terrain_width = land_map.width
        terrain_height = land_map.height
        terrain_sample_count = land_map.sample_count
    else:
        terrain_width = None
        terrain_height = None
        terrain_sample_count = None
        missing_optional_files.append("terrain/land_map.h32")

    cgf_jobs = collect_level_cgf_jobs(objects, brush, import_mode=import_mode)
    resource_resolution = resolve_level_cgf_jobs(cgf_jobs.jobs, client_root)
    template_collection = group_level_cgf_templates(resource_resolution.resolved)
    top_repeated_templates = tuple(
        (template.normalized_reference, template.placement_count)
        for template in sorted(
            template_collection.templates,
            key=lambda template: template.placement_count,
            reverse=True,
        )[:5]
    )

    return LevelImportSummary(
        level_dir=level_path,
        import_mode=import_mode,
        vegetation_count=len(level_data.vegetation_files),
        object_count=object_count,
        brush_mesh_count=brush_mesh_count,
        brush_node_count=brush_node_count,
        terrain_width=terrain_width,
        terrain_height=terrain_height,
        terrain_sample_count=terrain_sample_count,
        cgf_job_count=len(cgf_jobs.jobs),
        object_job_count=len(cgf_jobs.object_jobs),
        brush_job_count=len(cgf_jobs.brush_jobs),
        unresolved_reference_count=len(cgf_jobs.unresolved),
        resource_resolution_enabled=resource_resolution.enabled,
        resolved_cgf_job_count=len(resource_resolution.resolved),
        missing_cgf_resource_count=len(resource_resolution.missing),
        unique_template_count=len(template_collection.templates),
        max_placements_per_template=template_collection.max_placements_per_template,
        top_repeated_templates=top_repeated_templates,
        missing_optional_files=tuple(missing_optional_files),
    )
