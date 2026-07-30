from dataclasses import dataclass
from pathlib import Path
from typing import Callable, Iterable

from aion_formats.level import (
    LIQUID_KIND_AUTO,
    LIQUID_PRESET_AUTO,
    build_liquid_surface_recipe,
    extract_liquid_references,
    parse_brush_lst,
    parse_land_map_h32,
    parse_leveldata,
    parse_objects_lst,
)

from .cga_entities_importer import (
    CgaEntitiesImportResult,
    create_cga_entities,
)
from .level_instances import (
    INVALID_BRUSH_MATRIX,
    INVALID_OBJECT_SCALE,
    PlacementSkip,
    PlacementTransformSummary,
    create_level_cgf_placement_instances,
)
from .level_jobs import collect_level_cgf_jobs
from .level_summary import LevelImportExecutionSummary
from .level_templates import LevelCgfTemplate, group_level_cgf_templates
from .liquid_surface_importer import (
    LiquidSurfaceMaterialResult,
    apply_liquid_surface_material,
    skipped_liquid_surface_result,
)
from .mission_placeables_importer import (
    MissionPlaceablesImportResult,
    create_mission_placeables,
)
from .particle_effects_importer import (
    ParticleEffectsImportResult,
    create_particle_effects,
)
from .resource_resolver import resolve_level_cgf_jobs
from .static_lights_importer import (
    DEFAULT_STATIC_LIGHT_POWER,
    STATIC_LIGHTS_MODE_POINT_LIGHT,
    StaticLightsImportResult,
    create_static_deferred_lights,
)
from .terrain_importer import DEFAULT_XY_SCALE, TerrainMeshResult, create_terrain_mesh
from .water_importer import WaterPlaneResult, create_water_plane


LEVEL_COLLECTION_NAME = "Aion Level Import"
PREVIEW_COLLECTION_NAME = "Aion Level Import Preview"


@dataclass(frozen=True)
class LevelCgfImportFailure:
    normalized_reference: str
    resolved_path: Path
    import_mode: str
    reason_code: str
    reason: str
    parser_node_count: int = 0
    parser_mesh_node_count: int = 0
    parser_material_count: int = 0
    candidate_mesh_node_count: int = 0
    parser_coverage_counts: dict | None = None
    unsupported_chunks: dict | None = None
    unused_material_fields: dict | None = None


@dataclass(frozen=True)
class LevelCgfImportSkip:
    normalized_reference: str
    resolved_path: Path
    import_mode: str
    reason_code: str
    reason: str
    parser_node_count: int = 0
    parser_mesh_node_count: int = 0
    parser_material_count: int = 0
    candidate_mesh_node_count: int = 0
    parser_coverage_counts: dict | None = None
    unsupported_chunks: dict | None = None
    unused_material_fields: dict | None = None


@dataclass(frozen=True)
class LevelTemplatePlacementStats:
    normalized_reference: str
    import_mode: str
    available_placement_count: int
    created_placement_count: int


@dataclass(frozen=True)
class LevelImportProgress:
    stage: str
    message: str
    completed: int
    total: int

    @property
    def fraction(self) -> float:
        if self.total < 1:
            return 0.0
        return min(max(self.completed / self.total, 0.0), 1.0)


@dataclass(frozen=True)
class LevelImportResult:
    level_dir: Path
    client_root: Path
    import_mode: str
    limited_preview: bool
    max_unique_cgfs: int
    max_placements_per_template: int
    resolved_job_count: int
    missing_resource_count: int
    total_template_count: int
    max_available_placements_per_template: int
    selected_template_count: int
    imported_template_count: int
    skipped_template_count: int
    failed_template_count: int
    selected_placement_count: int
    placement_objects_created: int
    object_placement_count: int
    brush_placement_count: int
    non_default_transform_count: int
    invalid_placements_skipped: int
    invalid_object_scale_count: int
    invalid_brush_matrix_count: int
    first_invalid_placement: PlacementSkip | None
    transform_summaries: tuple[PlacementTransformSummary, ...]
    per_template_placement_counts: tuple[LevelTemplatePlacementStats, ...]
    terrain_mesh_result: TerrainMeshResult | None
    water_result: WaterPlaneResult | None
    liquid_surface_result: LiquidSurfaceMaterialResult | None
    static_lights_result: StaticLightsImportResult | None
    mission_placeables_result: MissionPlaceablesImportResult | None
    particle_effects_result: ParticleEffectsImportResult | None
    cga_entities_result: CgaEntitiesImportResult | None
    summary: LevelImportExecutionSummary
    objects_created: int
    meshes_created: int
    failures: tuple[LevelCgfImportFailure, ...]
    skipped_templates: tuple[LevelCgfImportSkip, ...]


def select_level_cgf_templates(
    templates: Iterable[LevelCgfTemplate],
    max_unique_cgfs: int,
) -> tuple[LevelCgfTemplate, ...]:
    if max_unique_cgfs < 1:
        raise ValueError("max_unique_cgfs must be >= 1")

    selected = []
    for template in sorted(
        templates,
        key=lambda item: item.placement_count,
        reverse=True,
    ):
        selected.append(template)
        if len(selected) >= max_unique_cgfs:
            break

    return tuple(selected)


def import_level(
    context,
    level_dir: str | Path,
    client_root: str | Path,
    import_mode: str = "VISUAL",
    limited_preview: bool = False,
    max_unique_cgfs: int = 10,
    max_placements_per_template: int = 3,
    import_terrain: bool = False,
    import_terrain_textures: bool = False,
    import_terrain_blend_attributes: bool = False,
    import_terrain_blend_shader: bool = False,
    import_water: bool = False,
    import_textured_liquid_surface: bool = False,
    liquid_kind: str = LIQUID_KIND_AUTO,
    liquid_preset: str = LIQUID_PRESET_AUTO,
    import_static_lights: bool = False,
    static_lights_mode: str = STATIC_LIGHTS_MODE_POINT_LIGHT,
    static_lights_power: float = DEFAULT_STATIC_LIGHT_POWER,
    import_mission_placeables: bool = False,
    apply_mission_angles: bool = True,
    mission_placeables_limit: int | None = None,
    import_particle_effects: bool = False,
    import_cga_entities: bool = False,
    animate_cga_controllers: bool = False,
    apply_smoothing_groups: bool = False,
    animate_texture_sequences: bool = False,
    animate_shader_uv_scroll: bool = False,
    texture_animation_fps: int = 10,
    load_cgf: Callable | None = None,
    get_cgf_import_report: Callable | None = None,
    progress_callback: Callable[[LevelImportProgress], None] | None = None,
) -> LevelImportResult:
    if not client_root:
        raise ValueError("client_root is required for level CGF import")
    if import_mode not in {"VISUAL", "COLLISION"}:
        raise ValueError(f"unsupported import mode: {import_mode}")
    if limited_preview and max_placements_per_template < 1:
        raise ValueError("max_placements_per_template must be >= 1")
    visual_mode = import_mode == "VISUAL"
    if not visual_mode:
        import_terrain = True
        import_terrain_textures = False
        import_terrain_blend_attributes = False
        import_terrain_blend_shader = False
        import_water = False
        import_textured_liquid_surface = False
        import_static_lights = False
        import_mission_placeables = False
        import_particle_effects = False
        import_cga_entities = True
        animate_cga_controllers = False
        animate_texture_sequences = False
        animate_shader_uv_scroll = False

    if load_cgf is None:
        from . import cgf_importer
        load_cgf = cgf_importer.load
        get_cgf_import_report = cgf_importer.get_last_import_report

    level_path = Path(level_dir)
    client_root_path = Path(client_root)
    terrain_path = level_path / "terrain" / "land_map.h32"
    if import_terrain and not terrain_path.is_file():
        raise FileNotFoundError(f"terrain preview requested but file is missing: {terrain_path}")

    _emit_progress(
        progress_callback,
        stage="discover",
        message="Reading level sources",
        completed=0,
        total=1,
    )
    level_data, objects, brush = _parse_level_cgf_sources(level_path)
    jobs = collect_level_cgf_jobs(objects, brush, import_mode=import_mode)
    resolution = resolve_level_cgf_jobs(jobs.jobs, client_root_path)
    template_collection = group_level_cgf_templates(resolution.resolved)
    selected_templates = (
        select_level_cgf_templates(
            template_collection.templates,
            max_unique_cgfs,
        )
        if limited_preview
        else template_collection.templates
    )
    optional_stage_count = sum(
        (
            import_terrain,
            import_water,
            import_textured_liquid_surface,
            import_static_lights,
            import_mission_placeables,
            import_particle_effects,
            import_cga_entities,
        )
    )
    progress_total = 2 + len(selected_templates) + optional_stage_count
    progress_completed = 1
    _emit_progress(
        progress_callback,
        stage="discover",
        message=(
            f"Resolved {len(selected_templates)} of "
            f"{len(template_collection.templates)} CGF templates"
        ),
        completed=progress_completed,
        total=progress_total,
    )

    def advance_progress(stage: str, message: str) -> None:
        nonlocal progress_completed
        progress_completed += 1
        _emit_progress(
            progress_callback,
            stage=stage,
            message=message,
            completed=progress_completed,
            total=progress_total,
        )

    import bpy

    root_collection = context.scene.collection
    collection_name = (
        PREVIEW_COLLECTION_NAME
        if limited_preview
        else LEVEL_COLLECTION_NAME
    )
    preview_collection = bpy.data.collections.new(collection_name)
    root_collection.children.link(preview_collection)

    objects_before = len(bpy.data.objects)
    meshes_before = len(bpy.data.meshes)
    imported_template_count = 0
    selected_placement_count = 0
    placement_objects_created = 0
    object_placement_count = 0
    brush_placement_count = 0
    transform_summaries = []
    placement_skips = []
    per_template_placement_counts = []
    failures = []
    skipped_templates = []
    texture_sequences_applied = 0
    texture_sequences_skipped = 0
    texture_sequence_missing_frames = 0
    shader_uv_scroll_applied = 0
    shader_uv_scroll_skipped = 0
    terrain_mesh_result = None
    water_result = None
    liquid_surface_result = None
    static_lights_result = None
    mission_placeables_result = None
    particle_effects_result = None
    cga_entities_result = None

    for template_index, template in enumerate(selected_templates, start=1):
        _emit_progress(
            progress_callback,
            stage="cgf_templates",
            message=(
                f"Importing CGF template {template_index}/{len(selected_templates)}: "
                f"{template.resolved_path.name}"
            ),
            completed=progress_completed,
            total=progress_total,
        )
        collections_before = set(bpy.data.collections)
        result = load_cgf(
            context,
            str(template.resolved_path),
            import_mode=template.import_mode,
            apply_smoothing_groups=apply_smoothing_groups,
            animate_texture_sequences=animate_texture_sequences,
            animate_shader_uv_scroll=animate_shader_uv_scroll,
            texture_animation_fps=texture_animation_fps,
        )
        import_report = (
            get_cgf_import_report()
            if get_cgf_import_report is not None
            else None
        )
        if import_report is not None:
            texture_sequences_applied += getattr(import_report, "texture_sequences_applied", 0)
            texture_sequences_skipped += getattr(import_report, "texture_sequences_skipped", 0)
            texture_sequence_missing_frames += getattr(
                import_report,
                "texture_sequence_missing_frames",
                0,
            )
            shader_uv_scroll_applied += getattr(import_report, "shader_uv_scroll_applied", 0)
            shader_uv_scroll_skipped += getattr(import_report, "shader_uv_scroll_skipped", 0)

        if result != {"FINISHED"}:
            reason_code = (
                import_report.reason_code
                if import_report and import_report.reason_code
                else "unknown"
            )
            reason = (
                import_report.reason
                if import_report and import_report.reason
                else f"CGF importer returned {result}"
            )
            failure_kwargs = {
                "normalized_reference": template.normalized_reference,
                "resolved_path": template.resolved_path,
                "import_mode": template.import_mode,
                "reason_code": reason_code,
                "reason": reason,
                "parser_node_count": import_report.parser_node_count if import_report else 0,
                "parser_mesh_node_count": import_report.parser_mesh_node_count if import_report else 0,
                "parser_material_count": import_report.parser_material_count if import_report else 0,
                "candidate_mesh_node_count": (
                    import_report.candidate_mesh_node_count if import_report else 0
                ),
                "parser_coverage_counts": (
                    getattr(import_report, "parser_coverage_counts", {}) if import_report else {}
                ),
                "unsupported_chunks": (
                    getattr(import_report, "unsupported_chunks", {}) if import_report else {}
                ),
                "unused_material_fields": (
                    getattr(import_report, "unused_material_fields", {}) if import_report else {}
                ),
            }
            if _is_expected_cgf_skip(reason_code):
                skipped_templates.append(LevelCgfImportSkip(**failure_kwargs))
            else:
                failures.append(LevelCgfImportFailure(**failure_kwargs))
            advance_progress(
                "cgf_templates",
                f"Processed CGF template {template_index}/{len(selected_templates)}",
            )
            continue

        new_collections = tuple(
            collection for collection in bpy.data.collections if collection not in collections_before
        )
        imported_collection = _find_imported_template_collection(
            new_collections,
            preview_collection,
        )
        placement_limit = (
            max_placements_per_template
            if limited_preview
            else template.placement_count
        )
        instance_batch = create_level_cgf_placement_instances(
            preview_collection,
            imported_collection,
            template.placements,
            placement_limit,
        )

        imported_template_count += 1
        selected_placement_count += placement_limit
        placement_objects_created += len(instance_batch.instances)
        object_placement_count += instance_batch.object_placement_count
        brush_placement_count += instance_batch.brush_placement_count
        transform_summaries.extend(instance_batch.transform_summaries)
        placement_skips.extend(instance_batch.placement_skips)
        per_template_placement_counts.append(
            LevelTemplatePlacementStats(
                normalized_reference=template.normalized_reference,
                import_mode=template.import_mode,
                available_placement_count=template.placement_count,
                created_placement_count=len(instance_batch.instances),
            )
        )
        _detach_template_collections_from_scene(
            root_collection,
            new_collections,
        )
        advance_progress(
            "cgf_templates",
            f"Processed CGF template {template_index}/{len(selected_templates)}",
        )

    if import_terrain:
        _emit_progress(
            progress_callback,
            stage="terrain",
            message="Creating terrain",
            completed=progress_completed,
            total=progress_total,
        )
        terrain_mesh_result = create_terrain_mesh(
            context,
            parse_land_map_h32(terrain_path),
            level_data=level_data if visual_mode else None,
            client_root=client_root_path if visual_mode else None,
            import_terrain_textures=import_terrain_textures,
            import_terrain_blend_attributes=import_terrain_blend_attributes,
            import_terrain_blend_shader=import_terrain_blend_shader,
        )
        advance_progress("terrain", "Terrain created")

    if import_water:
        _emit_progress(
            progress_callback,
            stage="water",
            message="Creating water plane",
            completed=progress_completed,
            total=progress_total,
        )
        water_result = create_water_plane(
            context,
            level_data.level_info,
            xy_scale=(
                terrain_mesh_result.xy_scale
                if terrain_mesh_result is not None
                else DEFAULT_XY_SCALE
            ),
        )
        advance_progress("water", "Water plane processed")

    if import_textured_liquid_surface:
        _emit_progress(
            progress_callback,
            stage="liquid_material",
            message="Applying liquid material",
            completed=progress_completed,
            total=progress_total,
        )
        if not import_water:
            liquid_surface_result = skipped_liquid_surface_result(
                requested=True,
                selected_kind=liquid_kind,
                selected_preset=liquid_preset,
                reason="textured liquid surface requires Import Water Plane",
            )
        else:
            reference_texts = extract_liquid_references(
                (
                    level_path / "materials.xml",
                    level_path / "mission_mission0.xml",
                    level_path / "objects.lst",
                    level_path / "brush.lst",
                )
            )
            recipe = build_liquid_surface_recipe(
                client_root_path,
                level_data,
                level_dir=level_path,
                requested_kind=liquid_kind,
                requested_preset=liquid_preset,
                reference_texts=reference_texts,
            )
            liquid_surface_result = apply_liquid_surface_material(
                water_result,
                recipe,
            )
        advance_progress("liquid_material", "Liquid material processed")

    if import_static_lights:
        _emit_progress(
            progress_callback,
            stage="static_lights",
            message="Creating static lights",
            completed=progress_completed,
            total=progress_total,
        )
        static_lights_result = create_static_deferred_lights(
            context,
            level_path,
            mode=static_lights_mode,
            power=static_lights_power,
        )
        advance_progress("static_lights", "Static lights processed")

    if import_mission_placeables:
        _emit_progress(
            progress_callback,
            stage="mission_placeables",
            message="Importing mission placeables",
            completed=progress_completed,
            total=progress_total,
        )
        mission_placeables_result = create_mission_placeables(
            context,
            level_path,
            client_root_path,
            apply_angles=apply_mission_angles,
            apply_smoothing_groups=apply_smoothing_groups,
            animate_texture_sequences=animate_texture_sequences,
            animate_shader_uv_scroll=animate_shader_uv_scroll,
            texture_animation_fps=texture_animation_fps,
            limit=mission_placeables_limit,
            load_cgf=load_cgf,
            get_cgf_import_report=get_cgf_import_report,
        )
        advance_progress("mission_placeables", "Mission placeables processed")

    if import_particle_effects:
        _emit_progress(
            progress_callback,
            stage="particle_effects",
            message="Importing particle effects",
            completed=progress_completed,
            total=progress_total,
        )
        particle_effects_result = create_particle_effects(
            context,
            level_path,
            client_root_path,
            level_data=level_data,
        )
        advance_progress("particle_effects", "Particle effects processed")

    if import_cga_entities:
        _emit_progress(
            progress_callback,
            stage="cga_entities",
            message="Importing placed CGA entities",
            completed=progress_completed,
            total=progress_total,
        )
        cga_entities_result = create_cga_entities(
            context,
            level_path,
            client_root_path,
            import_mode=import_mode,
            apply_angles=True,
            apply_smoothing_groups=apply_smoothing_groups,
            animate_texture_sequences=animate_texture_sequences,
            animate_shader_uv_scroll=animate_shader_uv_scroll,
            animate_cga_controllers=animate_cga_controllers,
            texture_animation_fps=texture_animation_fps,
            load_cgf=load_cgf,
            get_cgf_import_report=get_cgf_import_report,
        )
        advance_progress("cga_entities", "CGA entities processed")

    objects_created = len(bpy.data.objects) - objects_before
    meshes_created = len(bpy.data.meshes) - meshes_before
    summary = _build_execution_summary(
        total_template_count=len(template_collection.templates),
        selected_template_count=len(selected_templates),
        imported_template_count=imported_template_count,
        failed_template_count=len(failures),
        skipped_template_count=len(skipped_templates),
        placement_objects_created=placement_objects_created,
        invalid_placements_skipped=len(placement_skips),
        invalid_object_scale_count=sum(
            skip.reason_code == INVALID_OBJECT_SCALE
            for skip in placement_skips
        ),
        invalid_brush_matrix_count=sum(
            skip.reason_code == INVALID_BRUSH_MATRIX
            for skip in placement_skips
        ),
        first_invalid_placement=placement_skips[0] if placement_skips else None,
        limited_preview=limited_preview,
        import_terrain=import_terrain,
        import_terrain_textures=import_terrain_textures,
        import_terrain_blend_attributes=import_terrain_blend_attributes,
        import_terrain_blend_shader=import_terrain_blend_shader,
        import_water=import_water,
        import_static_lights=import_static_lights,
        static_lights_mode=static_lights_mode,
        static_lights_power=static_lights_power,
        import_mission_placeables=import_mission_placeables,
        mission_placeables_result=mission_placeables_result,
        import_particle_effects=import_particle_effects,
        particle_effects_result=particle_effects_result,
        import_cga_entities=import_cga_entities,
        cga_entities_result=cga_entities_result,
        terrain_mesh_result=terrain_mesh_result,
        water_result=water_result,
        liquid_surface_result=liquid_surface_result,
        static_lights_result=static_lights_result,
        animate_texture_sequences=animate_texture_sequences,
        animate_shader_uv_scroll=animate_shader_uv_scroll,
        texture_sequences_applied=texture_sequences_applied,
        texture_sequences_skipped=texture_sequences_skipped,
        texture_sequence_missing_frames=texture_sequence_missing_frames,
        shader_uv_scroll_applied=shader_uv_scroll_applied,
        shader_uv_scroll_skipped=shader_uv_scroll_skipped,
    )

    if imported_template_count == 0:
        if preview_collection.name in root_collection.children.keys():
            root_collection.children.unlink(preview_collection)
        bpy.data.collections.remove(preview_collection)

    advance_progress("complete", "Level import complete")
    return LevelImportResult(
        level_dir=level_path,
        client_root=client_root_path,
        import_mode=import_mode,
        limited_preview=limited_preview,
        max_unique_cgfs=max_unique_cgfs,
        max_placements_per_template=max_placements_per_template,
        resolved_job_count=len(resolution.resolved),
        missing_resource_count=len(resolution.missing),
        total_template_count=len(template_collection.templates),
        max_available_placements_per_template=template_collection.max_placements_per_template,
        selected_template_count=len(selected_templates),
        imported_template_count=imported_template_count,
        failed_template_count=len(failures),
        skipped_template_count=len(skipped_templates),
        selected_placement_count=selected_placement_count,
        placement_objects_created=placement_objects_created,
        object_placement_count=object_placement_count,
        brush_placement_count=brush_placement_count,
        non_default_transform_count=sum(
            summary.is_non_default for summary in transform_summaries
        ),
        invalid_placements_skipped=len(placement_skips),
        invalid_object_scale_count=sum(
            skip.reason_code == INVALID_OBJECT_SCALE
            for skip in placement_skips
        ),
        invalid_brush_matrix_count=sum(
            skip.reason_code == INVALID_BRUSH_MATRIX
            for skip in placement_skips
        ),
        first_invalid_placement=placement_skips[0] if placement_skips else None,
        transform_summaries=tuple(transform_summaries),
        per_template_placement_counts=tuple(per_template_placement_counts),
        terrain_mesh_result=terrain_mesh_result,
        water_result=water_result,
        liquid_surface_result=liquid_surface_result,
        static_lights_result=static_lights_result,
        mission_placeables_result=mission_placeables_result,
        particle_effects_result=particle_effects_result,
        cga_entities_result=cga_entities_result,
        summary=summary,
        objects_created=objects_created,
        meshes_created=meshes_created,
        failures=tuple(failures),
        skipped_templates=tuple(skipped_templates),
    )


def _emit_progress(
    callback: Callable[[LevelImportProgress], None] | None,
    *,
    stage: str,
    message: str,
    completed: int,
    total: int,
) -> None:
    if callback is None:
        return
    callback(
        LevelImportProgress(
            stage=stage,
            message=message,
            completed=completed,
            total=total,
        )
    )


def _build_execution_summary(
    *,
    total_template_count: int,
    selected_template_count: int,
    imported_template_count: int,
    failed_template_count: int,
    skipped_template_count: int,
    placement_objects_created: int,
    invalid_placements_skipped: int,
    invalid_object_scale_count: int,
    invalid_brush_matrix_count: int,
    first_invalid_placement: PlacementSkip | None,
    limited_preview: bool,
    import_terrain: bool,
    import_terrain_textures: bool,
    import_terrain_blend_attributes: bool,
    import_terrain_blend_shader: bool,
    import_water: bool,
    import_static_lights: bool,
    static_lights_mode: str,
    static_lights_power: float,
    import_mission_placeables: bool,
    mission_placeables_result: MissionPlaceablesImportResult | None,
    import_particle_effects: bool,
    particle_effects_result: ParticleEffectsImportResult | None,
    import_cga_entities: bool,
    cga_entities_result: CgaEntitiesImportResult | None,
    terrain_mesh_result: TerrainMeshResult | None,
    water_result: WaterPlaneResult | None,
    liquid_surface_result: LiquidSurfaceMaterialResult | None,
    static_lights_result: StaticLightsImportResult | None,
    animate_texture_sequences: bool,
    animate_shader_uv_scroll: bool,
    texture_sequences_applied: int,
    texture_sequences_skipped: int,
    texture_sequence_missing_frames: int,
    shader_uv_scroll_applied: int,
    shader_uv_scroll_skipped: int,
) -> LevelImportExecutionSummary:
    terrain = terrain_mesh_result
    return LevelImportExecutionSummary(
        import_scope="limited preview" if limited_preview else "full",
        cgf_total=total_template_count,
        cgf_selected=selected_template_count,
        cgf_imported=imported_template_count,
        cgf_failed=failed_template_count,
        cgf_skipped_expected=skipped_template_count,
        placements_created=placement_objects_created,
        invalid_placements_skipped=invalid_placements_skipped,
        invalid_object_scale_count=invalid_object_scale_count,
        invalid_brush_matrix_count=invalid_brush_matrix_count,
        invalid_placement_sample=(
            f"{first_invalid_placement.source_type}[{first_invalid_placement.source_index}] "
            f"{first_invalid_placement.cgf_reference}: {first_invalid_placement.reason}"
            if first_invalid_placement
            else None
        ),
        terrain_enabled=import_terrain,
        terrain_created=terrain is not None,
        terrain_vertices=terrain.vertex_count if terrain else 0,
        terrain_faces=terrain.face_count if terrain else 0,
        terrain_materials=terrain.material_slot_count if terrain else 0,
        terrain_uv_loops=terrain.uv_loop_count if terrain else 0,
        detail_textures_total=terrain.detail_texture_count if terrain else 0,
        detail_textures_existing=terrain.existing_detail_texture_count if terrain else 0,
        detail_textures_missing=terrain.missing_detail_texture_count if terrain else 0,
        texture_preview_requested=import_terrain and import_terrain_textures,
        texture_images_loaded=terrain.texture_images_loaded if terrain else 0,
        texture_images_failed=terrain.texture_images_failed if terrain else 0,
        texture_nodes_created=terrain.texture_nodes_created if terrain else 0,
        blend_attributes_requested=(
            import_terrain and (import_terrain_blend_attributes or import_terrain_blend_shader)
        ),
        blend_attribute_layers_created=getattr(terrain, "blend_attribute_layers_created", 0) if terrain else 0,
        blend_weight_material_count=getattr(terrain, "blend_weight_material_count", 0) if terrain else 0,
        blend_boundary_sample_count=getattr(terrain, "blend_boundary_sample_count", 0) if terrain else 0,
        blend_invalid_weight_count=getattr(terrain, "blend_invalid_weight_count", 0) if terrain else 0,
        blend_shader_requested=import_terrain and import_terrain_blend_shader,
        blend_shader_graph_created=getattr(terrain, "blend_shader_graph_created", False) if terrain else False,
        blend_shader_material_count=getattr(terrain, "blend_shader_material_count", 0) if terrain else 0,
        blend_shader_included_materials=",".join(
            str(index)
            for index in (getattr(terrain, "blend_shader_included_material_indices", ()) if terrain else ())
        ),
        blend_shader_texture_images_loaded=getattr(terrain, "blend_shader_texture_images_loaded", 0) if terrain else 0,
        blend_shader_texture_images_failed=getattr(terrain, "blend_shader_texture_images_failed", 0) if terrain else 0,
        blend_shader_texture_nodes_created=getattr(terrain, "blend_shader_texture_nodes_created", 0) if terrain else 0,
        blend_shader_skipped_material_count=len(getattr(terrain, "blend_shader_skipped_material_indices", ())) if terrain else 0,
        blend_shader_skipped_sample_counts=",".join(
            f"{index}:{count}"
            for index, count in (
                getattr(terrain, "blend_shader_skipped_material_sample_counts", ())
                if terrain
                else ()
            )
        ),
        blend_shader_skipped_reasons=",".join(
            f"{index}:{reason}:{count}"
            for index, reason, count in (
                getattr(terrain, "blend_shader_skipped_material_reasons", ())
                if terrain
                else ()
            )
        ),
        blend_shader_projection_mode=getattr(terrain, "blend_shader_projection_mode", "") if terrain else "",
        blend_shader_warnings="; ".join(getattr(terrain, "blend_shader_warnings", ())) if terrain else "",
        water_enabled=import_water,
        water_created=bool(water_result and water_result.created),
        water_level=water_result.water_level if water_result else None,
        water_width=water_result.width if water_result else 0.0,
        water_height=water_result.height if water_result else 0.0,
        water_skip_reason=water_result.skip_reason if water_result else None,
        liquid_surface_requested=liquid_surface_result.requested if liquid_surface_result else False,
        liquid_surface_applied=liquid_surface_result.applied if liquid_surface_result else False,
        liquid_surface_kind=liquid_surface_result.selected_kind if liquid_surface_result else "",
        liquid_surface_inferred_kind=liquid_surface_result.inferred_kind if liquid_surface_result else "",
        liquid_surface_preset=liquid_surface_result.selected_preset if liquid_surface_result else "",
        liquid_surface_textures_loaded=liquid_surface_result.textures_loaded if liquid_surface_result else 0,
        liquid_surface_textures_used=liquid_surface_result.textures_used if liquid_surface_result else 0,
        liquid_surface_material_name=liquid_surface_result.material_name if liquid_surface_result else "",
        liquid_surface_skip_reason=liquid_surface_result.skip_reason if liquid_surface_result else None,
        liquid_surface_warnings="; ".join(liquid_surface_result.warnings) if liquid_surface_result else "",
        static_lights_enabled=import_static_lights,
        static_lights_file_found=static_lights_result.file_found if static_lights_result else False,
        static_lights_created=static_lights_result.created if static_lights_result else False,
        static_lights_count=static_lights_result.light_count if static_lights_result else 0,
        static_lights_created_count=static_lights_result.created_count if static_lights_result else 0,
        static_lights_failed_count=static_lights_result.failed_count if static_lights_result else 0,
        static_lights_mode=static_lights_result.mode if static_lights_result else static_lights_mode if import_static_lights else "",
        static_lights_power=static_lights_result.power if static_lights_result else static_lights_power if import_static_lights else 0.0,
        static_lights_skip_reason=static_lights_result.skip_reason if static_lights_result else None,
        mission_placeables_enabled=import_mission_placeables,
        mission_placeables_file_found=mission_placeables_result.file_found if mission_placeables_result else False,
        mission_placeables_created=mission_placeables_result.created_count > 0 if mission_placeables_result else False,
        mission_placeables_candidates=mission_placeables_result.candidates_count if mission_placeables_result else 0,
        mission_placeables_created_count=mission_placeables_result.created_count if mission_placeables_result else 0,
        mission_placeables_skipped_count=mission_placeables_result.skipped_count if mission_placeables_result else 0,
        mission_placeables_failed_count=mission_placeables_result.failed_count if mission_placeables_result else 0,
        mission_placeables_angles_applied_count=mission_placeables_result.angles_applied_count if mission_placeables_result else 0,
        mission_placeables_skip_reasons=_format_reason_counts(
            mission_placeables_result.skip_reasons if mission_placeables_result else {}
        ),
        mission_placeables_failure_reasons=_format_reason_counts(
            mission_placeables_result.failure_reasons if mission_placeables_result else {}
        ),
        particle_effects_enabled=import_particle_effects,
        particle_effects_files_scanned=particle_effects_result.files_scanned if particle_effects_result else 0,
        particle_effects_records_found=particle_effects_result.records_found if particle_effects_result else 0,
        particle_effects_definitions_found=particle_effects_result.definitions_found if particle_effects_result else 0,
        particle_effects_textures_resolved=particle_effects_result.textures_resolved if particle_effects_result else 0,
        particle_effects_sprites_created=particle_effects_result.sprite_visuals_created if particle_effects_result else 0,
        particle_effects_markers_created=particle_effects_result.marker_fallback_created if particle_effects_result else 0,
        particle_effects_skipped_invalid=particle_effects_result.skipped_invalid_placements if particle_effects_result else 0,
        particle_effects_unsupported_count=particle_effects_result.unsupported_effects if particle_effects_result else 0,
        particle_effects_skip_reasons=_format_reason_counts(
            particle_effects_result.skip_reasons if particle_effects_result else {}
        ),
        cga_entities_enabled=import_cga_entities,
        cga_entities_file_found=cga_entities_result.file_found if cga_entities_result else False,
        cga_entities_created=cga_entities_result.created_count > 0 if cga_entities_result else False,
        cga_entities_candidates=cga_entities_result.candidates_count if cga_entities_result else 0,
        cga_entities_created_count=cga_entities_result.created_count if cga_entities_result else 0,
        cga_entities_skipped_count=cga_entities_result.skipped_count if cga_entities_result else 0,
        cga_entities_failed_count=cga_entities_result.failed_count if cga_entities_result else 0,
        cga_entities_angles_applied_count=cga_entities_result.angles_applied_count if cga_entities_result else 0,
        cga_entities_controller_count=cga_entities_result.controller_count_total if cga_entities_result else 0,
        cga_entities_timing_present_count=cga_entities_result.timing_present_count if cga_entities_result else 0,
        cga_entities_skip_reasons=_format_reason_counts(
            cga_entities_result.skip_reasons if cga_entities_result else {}
        ),
        cga_entities_failure_reasons=_format_reason_counts(
            cga_entities_result.failure_reasons if cga_entities_result else {}
        ),
        texture_sequences_requested=animate_texture_sequences,
        texture_sequences_applied=texture_sequences_applied,
        texture_sequences_skipped=texture_sequences_skipped,
        texture_sequence_missing_frames=texture_sequence_missing_frames,
        shader_uv_scroll_requested=animate_shader_uv_scroll,
        shader_uv_scroll_applied=shader_uv_scroll_applied,
        shader_uv_scroll_skipped=shader_uv_scroll_skipped,
    )


def _format_reason_counts(reason_counts: dict) -> str:
    return ",".join(
        f"{reason}:{count}"
        for reason, count in sorted((reason_counts or {}).items())
    )


def _parse_level_cgf_sources(level_path: Path):
    leveldata_path = level_path / "leveldata.xml"
    if not leveldata_path.is_file():
        raise FileNotFoundError(f"leveldata.xml is required: {leveldata_path}")

    level_data = parse_leveldata(leveldata_path)

    objects_path = level_path / "objects.lst"
    objects = parse_objects_lst(objects_path, level_data) if objects_path.is_file() else None

    brush_path = level_path / "brush.lst"
    brush = parse_brush_lst(brush_path) if brush_path.is_file() else None

    return level_data, objects, brush


def _is_expected_cgf_skip(reason_code: str) -> bool:
    return reason_code in {"empty_mesh", "no_geometry_for_mode"}


def _detach_template_collections_from_scene(root_collection, new_collections):
    for collection in new_collections:
        if collection.name in root_collection.children.keys():
            root_collection.children.unlink(collection)


def _find_imported_template_collection(new_collections, preview_collection):
    imported = tuple(collection for collection in new_collections if collection != preview_collection)
    if len(imported) != 1:
        raise RuntimeError(f"CGF import created {len(imported)} collections; expected exactly one")
    return imported[0]
