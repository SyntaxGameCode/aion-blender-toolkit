from collections import Counter
from dataclasses import dataclass
import math
from pathlib import Path

from aion_formats.cgf.texture_sequences import resolve_texture_sequence
from aion_formats.level import (
    EntityContextParticleEffect,
    parse_entitycontext_particle_effects,
    resolve_particle_effect_definition,
)


PARTICLE_EFFECTS_COLLECTION_NAME = "Aion Particle Effects"
PARTICLE_EFFECTS_COORDINATE_VARIANT = "raw_xyz"
PARTICLE_EFFECTS_EXPERIMENTAL = True


@dataclass(frozen=True)
class ParticleEffectImportStatus:
    effect_name: str
    entity_name: str
    source_file: str
    record_index: int
    position: tuple[float, float, float] | None
    definition_found: bool
    effect_library: str
    texture_path: str
    texture_exists: bool
    emitter_name: str
    emitter_record_index: int
    visual_status: str
    object_name: str
    reason: str


@dataclass(frozen=True)
class ParticleEffectsImportResult:
    requested: bool
    files_scanned: int
    records_found: int
    definitions_found: int
    textures_resolved: int
    sprite_visuals_created: int
    marker_fallback_created: int
    skipped_invalid_placements: int
    unsupported_effects: int
    collection_name: str
    coordinate_variant: str
    statuses: tuple[ParticleEffectImportStatus, ...]
    skip_reasons: dict


def create_particle_effects(
    context,
    level_dir: str | Path,
    client_root: str | Path,
    *,
    level_data=None,
    sprite_size: float = 2.0,
) -> ParticleEffectsImportResult:
    level_path = Path(level_dir)
    client_root_path = Path(client_root)
    if sprite_size <= 0 or not math.isfinite(float(sprite_size)):
        raise ValueError("particle sprite size must be finite and positive")

    parsed = parse_entitycontext_particle_effects(level_path, level_data=level_data)
    import bpy

    collection = bpy.data.collections.new(PARTICLE_EFFECTS_COLLECTION_NAME)
    context.scene.collection.children.link(collection)
    material_cache = {}
    statuses = []
    skip_reasons = Counter()
    definitions_found = 0
    textures_resolved = 0
    sprite_count = 0
    marker_count = 0
    unsupported_count = 0

    for record in parsed.records:
        definition = resolve_particle_effect_definition(client_root_path, record.effect_name)
        if definition.definition_found:
            definitions_found += 1
        texture_refs = _existing_textures(definition.texture_references)
        if texture_refs:
            textures_resolved += len(texture_refs)
            for layer_index, texture_ref in enumerate(texture_refs):
                obj, visual_status, reason = _create_sprite_object(
                    bpy,
                    record,
                    definition,
                    texture_ref,
                    material_cache,
                    client_root=client_root_path,
                    sprite_size=sprite_size,
                    layer_index=layer_index,
                    layer_count=len(texture_refs),
                )
                if obj is not None:
                    sprite_count += 1
                else:
                    obj = _create_marker_object(bpy, record, definition, texture_ref, visual_status, reason)
                    marker_count += 1
                    skip_reasons[reason or visual_status] += 1
                collection.objects.link(obj)
                statuses.append(
                    _status_from_object(
                        record,
                        definition,
                        texture_ref,
                        visual_status,
                        obj.name,
                        reason,
                    )
                )
        else:
            texture_ref = _first_texture(definition.texture_references)
            visual_status = "marker_no_texture"
            reason = "no_existing_particle_texture"
            obj = _create_marker_object(bpy, record, definition, texture_ref, visual_status, reason)
            marker_count += 1
            unsupported_count += 1
            skip_reasons[reason] += 1

            collection.objects.link(obj)
            statuses.append(
                _status_from_object(
                    record,
                    definition,
                    texture_ref,
                    visual_status,
                    obj.name,
                    reason,
                )
            )

    return ParticleEffectsImportResult(
        requested=True,
        files_scanned=parsed.files_scanned,
        records_found=parsed.records_found,
        definitions_found=definitions_found,
        textures_resolved=textures_resolved,
        sprite_visuals_created=sprite_count,
        marker_fallback_created=marker_count,
        skipped_invalid_placements=parsed.skipped_invalid_positions,
        unsupported_effects=unsupported_count,
        collection_name=PARTICLE_EFFECTS_COLLECTION_NAME,
        coordinate_variant=PARTICLE_EFFECTS_COORDINATE_VARIANT,
        statuses=tuple(statuses),
        skip_reasons=dict(skip_reasons),
    )


def _create_sprite_object(
    bpy,
    record,
    definition,
    texture_ref,
    material_cache,
    *,
    client_root,
    sprite_size,
    layer_index,
    layer_count,
):
    try:
        material = _particle_material(bpy, texture_ref, material_cache, definition, client_root=client_root)
    except RuntimeError as exc:
        return None, "marker_texture_load_failed", f"texture_load_failed:{exc}"

    half = float(sprite_size) * 0.5
    mesh = bpy.data.meshes.new(f"AION_ParticleEffect_{record.record_index:04d}_Mesh")
    mesh.from_pydata(
        [(-half, 0.0, -half), (half, 0.0, -half), (half, 0.0, half), (-half, 0.0, half)],
        [],
        [(0, 1, 2, 3)],
    )
    mesh.update()
    uv_layer = mesh.uv_layers.new(name="AION_ParticleUV")
    for loop, uv in zip(uv_layer.data, ((0.0, 0.0), (1.0, 0.0), (1.0, 1.0), (0.0, 1.0))):
        loop.uv = uv
    mesh.materials.append(material)
    obj = bpy.data.objects.new(_object_name(record, layer_index=layer_index, layer_count=layer_count), mesh)
    obj.location = _raw_position(record.position)
    _assign_custom_properties(obj, record, definition, texture_ref, "sprite_texture", "")
    obj["aion_particle_layer_index"] = int(layer_index)
    obj["aion_particle_layer_count"] = int(layer_count)
    return obj, "sprite_texture", ""


def _create_marker_object(bpy, record, definition, texture_ref, visual_status, reason):
    obj = bpy.data.objects.new(_object_name(record), None)
    obj.empty_display_type = "PLAIN_AXES"
    obj.empty_display_size = 1.0
    obj.location = _raw_position(record.position)
    _assign_custom_properties(obj, record, definition, texture_ref, visual_status, reason)
    return obj


def _particle_material(bpy, texture_ref, material_cache, definition, *, client_root):
    sequence = resolve_texture_sequence(
        {"name": texture_ref.texture_path, "long_name": texture_ref.texture_path},
        cgf_path=definition.library_path,
        client_root=client_root,
        fps=10,
    )
    key = (str(texture_ref.resolved_path), bool(sequence.is_sequence), sequence.frame_count)
    cached = material_cache.get(key)
    if cached is not None:
        return cached

    image = bpy.data.images.load(
        str(sequence.frame_paths[0] if sequence.is_sequence else texture_ref.resolved_path),
        check_existing=not sequence.is_sequence,
    )
    if sequence.is_sequence:
        image.source = "SEQUENCE"
        image.filepath = sequence.frame_paths[0]
        image.filepath_raw = sequence.frame_paths[0]
    material = bpy.data.materials.new(f"AION Particle {Path(texture_ref.texture_path).stem}")
    material.use_nodes = True
    material.blend_method = "BLEND"
    if hasattr(material, "use_screen_refraction"):
        material.use_screen_refraction = False
    nodes = material.node_tree.nodes
    bsdf = nodes.get("Principled BSDF")
    texture = nodes.new(type="ShaderNodeTexImage")
    texture.name = "AION Particle Texture"
    texture.image = image
    image_user = getattr(texture, "image_user", None)
    if sequence.is_sequence and image_user is not None:
        image_user.frame_start = 1
        image_user.frame_duration = int(sequence.effective_frame_count)
        image_user.frame_offset = int(sequence.blender_frame_offset)
        image_user.use_cyclic = True
        image_user.use_auto_refresh = True
    if bsdf is not None:
        material.node_tree.links.new(texture.outputs["Color"], bsdf.inputs["Base Color"])
        if "Alpha" in texture.outputs and "Alpha" in bsdf.inputs:
            material.node_tree.links.new(texture.outputs["Alpha"], bsdf.inputs["Alpha"])
    material["aion_particle_texture"] = texture_ref.texture_path
    material["aion_particle_texture_exists"] = bool(texture_ref.exists)
    material["aion_particle_emitter_name"] = texture_ref.emitter_name
    material["aion_particle_emitter_record_index"] = int(texture_ref.emitter_record_index)
    material["aion_particle_blend_semantics"] = "unknown_not_decoded"
    material["aion_particle_size_semantics"] = "unknown_not_decoded"
    material["aion_particle_orientation_semantics"] = "unknown_not_decoded"
    material["aion_particle_texture_sequence_enabled"] = bool(sequence.is_sequence)
    material["aion_particle_texture_sequence_frame_count"] = int(sequence.frame_count)
    material["aion_particle_texture_sequence_skip_reason"] = sequence.skip_reason
    material_cache[key] = material
    return material


def _existing_textures(texture_references):
    return tuple(texture for texture in texture_references if texture.exists)


def _first_texture(texture_references):
    return texture_references[0] if texture_references else None


def _first_existing_texture(texture_references):
    for texture in texture_references:
        if texture.exists:
            return texture
    return None


def _assign_custom_properties(obj, record, definition, texture_ref, visual_status, reason):
    obj["aion_entity_type"] = "ParticleEffect"
    obj["aion_effect_name"] = record.effect_name
    obj["aion_effect_library"] = str(definition.library_path) if definition.library_path else ""
    obj["aion_effect_definition_found"] = bool(definition.definition_found)
    obj["aion_particle_texture"] = texture_ref.texture_path if texture_ref else ""
    obj["aion_particle_texture_exists"] = bool(texture_ref and texture_ref.exists)
    obj["aion_particle_emitter_name"] = texture_ref.emitter_name if texture_ref else ""
    obj["aion_particle_emitter_record_index"] = int(texture_ref.emitter_record_index) if texture_ref else -1
    obj["aion_particle_emitter_record_offset"] = int(texture_ref.emitter_record_offset) if texture_ref else -1
    obj["aion_particle_prt_record_layout"] = definition.record_layout
    obj["aion_particle_selected_record_count"] = int(definition.selected_record_count)
    obj["aion_particle_blend_semantics"] = "unknown_not_decoded"
    obj["aion_particle_size_semantics"] = "unknown_not_decoded"
    obj["aion_particle_orientation_semantics"] = "billboard_preview_no_prt_orientation_decoded"
    obj["aion_particle_visual_status"] = visual_status
    obj["aion_particle_import_experimental"] = PARTICLE_EFFECTS_EXPERIMENTAL
    obj["aion_entitycontext_source"] = record.source_file
    obj["aion_entitycontext_record_index"] = int(record.record_index)
    obj["aion_entity_name"] = record.entity_name
    obj["aion_raw_position"] = tuple(float(value) for value in record.position)
    obj["aion_coordinate_variant"] = PARTICLE_EFFECTS_COORDINATE_VARIANT
    obj["aion_particle_reason"] = reason
    obj["aion_raw_position_candidates"] = ";".join(
        ",".join(f"{float(value):.6g}" for value in candidate)
        for candidate in record.raw_position_candidates[:4]
    )
    obj["aion_particle_warnings"] = ";".join(record.warnings)


def _status_from_object(record, definition, texture_ref, visual_status, object_name, reason):
    return ParticleEffectImportStatus(
        effect_name=record.effect_name,
        entity_name=record.entity_name,
        source_file=record.source_file,
        record_index=record.record_index,
        position=tuple(record.position) if record.position else None,
        definition_found=definition.definition_found,
        effect_library=str(definition.library_path) if definition.library_path else "",
        texture_path=texture_ref.texture_path if texture_ref else "",
        texture_exists=bool(texture_ref and texture_ref.exists),
        emitter_name=texture_ref.emitter_name if texture_ref else "",
        emitter_record_index=int(texture_ref.emitter_record_index) if texture_ref else -1,
        visual_status=visual_status,
        object_name=object_name,
        reason=reason,
    )


def _raw_position(position):
    values = tuple(float(value) for value in position)
    if len(values) != 3 or not all(math.isfinite(value) for value in values):
        raise ValueError(f"invalid particle effect position: {position}")
    return values


def _object_name(record: EntityContextParticleEffect, *, layer_index=0, layer_count=1) -> str:
    base = record.entity_name or record.effect_name.split(".")[-1] or "ParticleEffect"
    suffix = f"_L{layer_index:02d}" if layer_count > 1 else ""
    return f"AION_ParticleEffect_{record.record_index:04d}_{base}{suffix}"
