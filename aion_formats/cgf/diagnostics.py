from dataclasses import dataclass, field
from collections import Counter
import os
from pathlib import Path
import re

from .texture_sequences import (
    client_root_from_path,
    detect_sequence_pattern,
    looks_fx_texture,
    resolve_texture_sequence_frames,
    sequence_base_directory,
    texture_sequence_contract,
)


CATEGORY_GEOMETRY = "geometry"
CATEGORY_MATERIAL = "material"
CATEGORY_TEXTURE = "texture"
CATEGORY_ALPHA_OPACITY = "alpha/opacity"
CATEGORY_COLLISION_NODRAW = "collision/NoDraw"
CATEGORY_HELPER_DUMMY = "helper/dummy"
CATEGORY_LIGHT = "light"
CATEGORY_ANIMATION = "animation"
CATEGORY_CONTROLLER = "controller"
CATEGORY_ANIMATED_TEXTURE = "animated_texture"
CATEGORY_TEXTURE_SEQUENCE = "texture_sequence"
CATEGORY_FX_MATERIAL = "fx_material"
CATEGORY_LIGHT_CONTROLLER = "light_controller"
CATEGORY_TRANSFORM_ANIMATION = "transform_animation"
CATEGORY_UNKNOWN_CONTROLLER = "unknown_controller"
CATEGORY_SKELETON_BONES = "skeleton/bones"
CATEGORY_PARTICLES_FX = "particles/fx"
CATEGORY_TRANSFORM = "transform"
CATEGORY_UNKNOWN = "unknown"


COVERAGE_SCENE_RELEVANT_NOW = "scene_relevant_now"
COVERAGE_SCENE_RELEVANT_LATER = "scene_relevant_later"
COVERAGE_RUNTIME_ONLY = "runtime_only_or_non_static"
COVERAGE_EXPECTED_SKIP = "expected_skip"
COVERAGE_DEBUG_NOISE = "debug_noise"
COVERAGE_UNKNOWN_NEEDS_AUDIT = "unknown_needs_audit"


PARSER_COVERAGE_TAXONOMY = (
    COVERAGE_SCENE_RELEVANT_NOW,
    COVERAGE_SCENE_RELEVANT_LATER,
    COVERAGE_RUNTIME_ONLY,
    COVERAGE_EXPECTED_SKIP,
    COVERAGE_DEBUG_NOISE,
    COVERAGE_UNKNOWN_NEEDS_AUDIT,
)


TAXONOMY = (
    CATEGORY_GEOMETRY,
    CATEGORY_MATERIAL,
    CATEGORY_TEXTURE,
    CATEGORY_ALPHA_OPACITY,
    CATEGORY_COLLISION_NODRAW,
    CATEGORY_HELPER_DUMMY,
    CATEGORY_LIGHT,
    CATEGORY_ANIMATION,
    CATEGORY_CONTROLLER,
    CATEGORY_ANIMATED_TEXTURE,
    CATEGORY_TEXTURE_SEQUENCE,
    CATEGORY_FX_MATERIAL,
    CATEGORY_LIGHT_CONTROLLER,
    CATEGORY_TRANSFORM_ANIMATION,
    CATEGORY_UNKNOWN_CONTROLLER,
    CATEGORY_SKELETON_BONES,
    CATEGORY_PARTICLES_FX,
    CATEGORY_TRANSFORM,
    CATEGORY_UNKNOWN,
)


TEXTURE_FIELD_CONTRACT = {
    "texture_diffuse": "diffuse",
    "texture_opacity": "opacity",
    "texture_bump": "bump",
    "texture_normal": "normal",
    "texture_specular": "specular",
    "texture_gloss": "gloss",
    "texture_detail": "detail",
    "texture_filter": "filter",
    "texture_ambient": "ambient",
    "texture_reflection": "reflection",
    "texture_subsurf": "subsurf",
}


FX_SEQUENCE_TERMS = (
    "lightning",
    "aura",
    "fire",
    "smoke",
    "beam",
    "glow",
    "warp",
    "fx",
    "particle",
    "trail",
)


VISUAL_SHADER_ROLES = {
    "diffuse",
    "opacity",
    "bump",
    "normal",
    "specular",
    "gloss",
    "detail",
    "reflection",
    "subsurf",
}


RAW_CONTROLLER_CHUNK_TYPES = {
    "Timing",
    "Controller",
    "VertAnim",
    "BoneAnim",
}


@dataclass
class CgfDiagnosticsCollector:
    file_path: str | None = None
    file_size: int | None = None
    parser_success: bool = False
    parser_error: str | None = None
    chunks: list[dict] = field(default_factory=list)
    skipped_ranges: list[dict] = field(default_factory=list)
    unread_ranges: list[dict] = field(default_factory=list)
    suspicious_events: list[dict] = field(default_factory=list)
    controller_chunks: list[dict] = field(default_factory=list)

    def add_chunk(self, header):
        self.chunks.append(
            {
                "chunk_id": header.get("chunk_id"),
                "chunk_type": header.get("chunk_type"),
                "version": header.get("version"),
                "offset": header.get("offset"),
                "raw_type": header.get("raw_type"),
            }
        )

    def add_controller_chunk(
        self,
        header,
        payload_offset,
        payload_size,
        prefix_hex,
        nearby_strings=(),
        decoded=None,
    ):
        category = _raw_controller_chunk_category(header.get("chunk_type"))
        record = {
            "chunk_type": header.get("chunk_type"),
            "chunk_id": header.get("chunk_id"),
            "version": header.get("version"),
            "offset": header.get("offset"),
            "raw_type": header.get("raw_type"),
            "payload_offset": int(payload_offset),
            "payload_size": int(payload_size),
            "prefix_hex": prefix_hex,
            "nearby_strings": tuple(nearby_strings),
            "category": category,
            "decoded": False,
        }
        if isinstance(decoded, dict):
            record.update(decoded)
        self.controller_chunks.append(record)

    def add_skipped_range(self, offset_start, offset_end, context, reason):
        size = int(offset_end) - int(offset_start)
        if size <= 0:
            return
        self.skipped_ranges.append(
            {
                "offset_start": int(offset_start),
                "offset_end": int(offset_end),
                "size": size,
                "context": context,
                "reason": reason,
            }
        )

    def add_unread_range(self, offset_start, offset_end, context, reason):
        size = int(offset_end) - int(offset_start)
        if size <= 0:
            return
        chunk_type = str(context or "")
        self.unread_ranges.append(
            {
                "offset_start": int(offset_start),
                "offset_end": int(offset_end),
                "size": size,
                "context": chunk_type,
                "reason": reason,
                "category": _coverage_category_for_unread_chunk(chunk_type),
                "severity": _coverage_severity_for_unread_chunk(chunk_type),
                "recommended_action": _coverage_action_for_unread_chunk(chunk_type),
            }
        )

    def add_event(
        self,
        signature,
        category,
        context="",
        detail=None,
        severity=None,
        coverage_category=None,
        recommended_action=None,
        reason=None,
    ):
        self.suspicious_events.append(
            {
                "signature": signature,
                "category": category,
                "context": context,
                "detail": detail,
                "severity": severity or _event_severity(signature, category),
                "coverage_category": coverage_category or _event_coverage_category(signature, category),
                "recommended_action": recommended_action or _event_recommended_action(signature, category),
                "reason": reason or _event_reason(signature, category),
            }
        )

    def to_dict(self, parsed=None):
        parsed = parsed if isinstance(parsed, dict) else {}
        summary = _parsed_summary(parsed)
        event_counts = Counter(event["signature"] for event in self.suspicious_events)
        chunk_counts = Counter(chunk["chunk_type"] for chunk in self.chunks)
        skipped_bytes = sum(item["size"] for item in self.skipped_ranges)
        unread_bytes = sum(item["size"] for item in self.unread_ranges)
        parser_coverage_events = _parser_coverage_events(
            self.suspicious_events,
            self.unread_ranges,
        )
        coverage_counts = Counter(event["coverage_category"] for event in parser_coverage_events)
        unsupported_counts = Counter(
            event["chunk_type"]
            for event in parser_coverage_events
            if event.get("event_type") == "unread_chunk"
        )
        unused_material_counts = Counter(
            event["field"]
            for event in parser_coverage_events
            if event.get("event_type") == "material_field"
        )
        return {
            "file_path": self.file_path,
            "file_size": self.file_size,
            "parser_success": self.parser_success,
            "parser_error": self.parser_error,
            **summary,
            "chunk_count": len(self.chunks),
            "chunk_type_counts": dict(sorted(chunk_counts.items())),
            "chunks": tuple(self.chunks),
            "controller_chunk_count": len(self.controller_chunks),
            "controller_chunks": tuple(self.controller_chunks),
            "decoded_controller_chunks": tuple(
                chunk
                for chunk in self.controller_chunks
                if chunk.get("chunk_type") == "Controller" and chunk.get("decoded")
            ),
            "timing_chunk_count": len(_timing_chunks(self.controller_chunks)),
            "timing_chunks": tuple(
                _timing_chunk_diagnostics(chunk, parsed)
                for chunk in _timing_chunks(self.controller_chunks)
            ),
            "skipped_range_count": len(self.skipped_ranges),
            "skipped_bytes": skipped_bytes,
            "skipped_ranges": tuple(self.skipped_ranges),
            "unread_range_count": len(self.unread_ranges),
            "unread_bytes": unread_bytes,
            "unread_ranges": tuple(self.unread_ranges),
            "suspicious_event_count": len(self.suspicious_events),
            "suspicious_event_counts": dict(sorted(event_counts.items())),
            "suspicious_events": tuple(self.suspicious_events),
            "parser_coverage_taxonomy": PARSER_COVERAGE_TAXONOMY,
            "parser_coverage_events": tuple(parser_coverage_events),
            "parser_coverage_counts": dict(sorted(coverage_counts.items())),
            "unsupported_chunks": dict(sorted(unsupported_counts.items())),
            "unused_material_fields": dict(sorted(unused_material_counts.items())),
            "ignored_by_design": tuple(
                event for event in parser_coverage_events
                if event.get("coverage_category") in (
                    COVERAGE_EXPECTED_SKIP,
                    COVERAGE_RUNTIME_ONLY,
                    COVERAGE_DEBUG_NOISE,
                )
            ),
            "future_feature_candidates": tuple(
                event for event in parser_coverage_events
                if event.get("coverage_category") == COVERAGE_SCENE_RELEVANT_LATER
            ),
            "expected_skips": tuple(
                event for event in parser_coverage_events
                if event.get("coverage_category") == COVERAGE_EXPECTED_SKIP
            ),
            "material_texture_contract": tuple(
                material_texture_contract(
                    material,
                    material_id=_material_id(material),
                    cgf_path=self.file_path,
                    timing=_decoded_timing_fields_for_parsed(parsed),
                )
                for material in parsed.get("all_materials") or ()
                if isinstance(material, dict)
            ),
            "taxonomy": TAXONOMY,
        }


def nearby_ascii_strings(payload, limit=8):
    strings = []
    for match in re.finditer(rb"[ -~]{4,}", payload):
        value = match.group(0).decode("ascii", errors="replace")
        if value not in strings:
            strings.append(value)
        if len(strings) >= limit:
            break
    return tuple(strings)


def _raw_controller_chunk_category(chunk_type):
    if chunk_type == "Controller":
        return CATEGORY_CONTROLLER
    if chunk_type == "Timing":
        return CATEGORY_TRANSFORM_ANIMATION
    if chunk_type in ("VertAnim", "BoneAnim"):
        return CATEGORY_ANIMATION
    return CATEGORY_UNKNOWN_CONTROLLER


def _timing_chunks(controller_chunks):
    return tuple(chunk for chunk in controller_chunks if chunk.get("chunk_type") == "Timing")


def _timing_chunk_diagnostics(raw_chunk, parsed):
    timing = parsed.get("Timing") if isinstance(parsed, dict) else None
    decoded = _decoded_timing_fields(raw_chunk, timing)
    record = {
        "chunk_type": raw_chunk.get("chunk_type"),
        "chunk_id": raw_chunk.get("chunk_id"),
        "version": raw_chunk.get("version"),
        "offset": raw_chunk.get("offset"),
        "payload_offset": raw_chunk.get("payload_offset"),
        "payload_size": raw_chunk.get("payload_size"),
        "prefix_hex": raw_chunk.get("prefix_hex"),
        "nearby_strings": raw_chunk.get("nearby_strings", ()),
        "category": CATEGORY_TRANSFORM_ANIMATION,
        "decoded": decoded is not None,
        "confidence": "high" if decoded is not None else "none",
        "raw": raw_chunk,
    }
    if decoded is not None:
        record.update(decoded)
    return record


def _decoded_timing_fields(raw_chunk, timing):
    if not isinstance(timing, dict):
        return None
    header = timing.get("header") if isinstance(timing.get("header"), dict) else {}
    if header.get("chunk_id") != raw_chunk.get("chunk_id"):
        return None
    global_range = timing.get("global_range") if isinstance(timing.get("global_range"), dict) else {}
    return {
        "name": global_range.get("name"),
        "secs_per_tick": timing.get("secs_per_tick"),
        "ticks_per_frame": timing.get("ticks_per_frame"),
        "global_range": {
            "name": global_range.get("name"),
            "start": global_range.get("start"),
            "end": global_range.get("end"),
        },
        "num_sub_ranges": timing.get("num_sub_ranges"),
        "candidate_fields": {
            "secs_per_tick": timing.get("secs_per_tick"),
            "ticks_per_frame": timing.get("ticks_per_frame"),
            "global_range_start": global_range.get("start"),
            "global_range_end": global_range.get("end"),
            "num_sub_ranges": timing.get("num_sub_ranges"),
        },
    }


def _parsed_summary(parsed):
    nodes = tuple((parsed.get("nodes") or {}).values())
    materials = tuple(parsed.get("all_materials") or ())
    mesh_nodes = tuple(node for node in nodes if node.get("mesh") is not None)
    return {
        "node_count": len(nodes),
        "material_count": len(materials),
        "mesh_count": len(mesh_nodes),
        "total_vertices": sum(
            int(node["mesh"].get("num_vertices", 0) or 0)
            for node in mesh_nodes
        ),
        "total_faces": sum(
            int(node["mesh"].get("num_faces", 0) or 0)
            for node in mesh_nodes
        ),
        "total_uvs": sum(
            int(node["mesh"].get("num_uvs", 0) or 0)
            for node in mesh_nodes
        ),
    }


def material_texture_contract(
    material,
    material_id=None,
    cgf_path=None,
    client_root=None,
    timing=None,
):
    textures = {}
    unknown_texture_fields = {}
    for field_name, value in material.items():
        if not field_name.startswith("texture_") or not isinstance(value, dict):
            continue
        normalized_name = TEXTURE_FIELD_CONTRACT.get(field_name)
        texture_info = normalize_texture_info(
            value,
            cgf_path=cgf_path,
            client_root=client_root,
            raw_field=field_name,
            normalized_role=normalized_name or "unknown",
            timing=timing,
        )
        if normalized_name:
            textures[normalized_name] = texture_info
        else:
            unknown_texture_fields[field_name] = texture_info

    flags = material.get("mtl_flag")
    flags = flags if isinstance(flags, dict) else {}
    return {
        "material_id": material_id,
        "material_name": material.get("name"),
        "mtl_type": material.get("mtl_type"),
        "mtl_flags": flags,
        "mtl_collide": material.get("mtl_collide"),
        "opacity": material.get("opacity"),
        "material_semantics": material.get("material_semantics") or {},
        "two_sided": bool(flags.get("two_sided")),
        "textures": textures,
        "unknown_texture_fields": unknown_texture_fields,
        "raw_property_keys": tuple(sorted(material)),
    }


def normalize_texture_info(
    texture,
    cgf_path=None,
    client_root=None,
    raw_field=None,
    normalized_role=None,
    timing=None,
):
    clean_name = _clean_texture_path(texture.get("name"))
    clean_long_name = _clean_texture_path(texture.get("long_name"))
    resolved_path, method = resolve_texture_path(
        clean_name,
        clean_long_name,
        cgf_path=cgf_path,
        client_root=client_root,
    )
    exists = os.path.isfile(resolved_path) if resolved_path else False
    classification = classify_texture(
        clean_name,
        clean_long_name,
        normalized_role,
        exists,
    )
    sibling_names = _texture_sibling_names(
        clean_name,
        clean_long_name,
        cgf_path=cgf_path,
        client_root=client_root,
    )
    sequence_contract = texture_sequence_contract(
        clean_name,
        clean_long_name,
        sibling_names=sibling_names,
    )
    frame_files = resolve_texture_sequence_frames(
        sequence_contract,
        clean_name,
        clean_long_name,
        cgf_path=cgf_path,
        client_root=client_root,
    )
    timing_relation = sequence_timing_relation(sequence_contract, frame_files, timing)
    recommended_action = classification["recommended_action"]
    if sequence_contract["is_sequence"] and frame_files["all_frames_exist"]:
        recommended_action = "future_animated_texture_support"
    return {
        "name": texture.get("name"),
        "long_name": texture.get("long_name"),
        "raw_field": raw_field,
        "normalized_role": normalized_role,
        "clean_name": clean_name,
        "clean_long_name": clean_long_name,
        "resolved_path": resolved_path,
        "exists": exists,
        "resolution_method": method,
        "classification": classification["classification"],
        "recommended_action": recommended_action,
        "sequence_pattern": classification["sequence_pattern"],
        "sequence_contract": sequence_contract,
        "sequence_confidence": sequence_contract["confidence"],
        "sequence_base_pattern": sequence_contract["base_pattern"],
        "sequence_start_frame": sequence_contract["start_frame"],
        "sequence_end_frame": sequence_contract["end_frame"],
        "sequence_padding": sequence_contract["padding"],
        "sequence_extension": sequence_contract["extension"],
        "sequence_frame_count": sequence_contract["frame_count_expected"],
        "frame_files": frame_files,
        "resolved_frame_files": frame_files["resolved_frame_files"],
        "missing_frame_files": frame_files["missing_frame_files"],
        "sequence_resolution_method": frame_files["resolution_method"],
        "sequence_complete": frame_files["all_frames_exist"],
        "timing_relation": timing_relation,
        "is_default_engine_texture": classification["is_default_engine_texture"],
        "is_visual_candidate": classification["is_visual_candidate"],
        "amount": texture.get("amount"),
        "texture_type": texture.get("texture_type"),
        "no_mip_map": texture.get("no_mip_map"),
        "u_tile": texture.get("u_tile"),
        "u_mirror": texture.get("u_mirror"),
        "v_tile": texture.get("v_tile"),
        "v_mirror": texture.get("v_mirror"),
        "u_off_val": texture.get("u_off_val"),
        "u_scl_val": texture.get("u_scl_val"),
        "u_rot_val": texture.get("u_rot_val"),
        "v_off_val": texture.get("v_off_val"),
        "v_scl_val": texture.get("v_scl_val"),
        "v_rot_val": texture.get("v_rot_val"),
        "w_rot_val": texture.get("w_rot_val"),
    }


def resolve_texture_path(clean_name, clean_long_name, cgf_path=None, client_root=None):
    if clean_long_name:
        root = Path(client_root).resolve() if client_root else _client_root_from_path(cgf_path)
        if root is not None:
            return (
                os.path.normcase(os.path.abspath(root / clean_long_name)),
                "long_name_client_root",
            )
    if clean_name and cgf_path:
        return (
            os.path.normcase(os.path.abspath(Path(cgf_path).resolve().parent / clean_name)),
            "local_cgf_dir",
        )
    if clean_name or clean_long_name:
        return "", "missing"
    return "", "empty"


def classify_texture(clean_name, clean_long_name, normalized_role, exists):
    texture_path = (clean_long_name or clean_name or "").lower().replace("/", "\\")
    basename = Path(texture_path).name
    is_default_engine_texture = texture_path.startswith("textures\\defaults\\")
    sequence_pattern = detect_sequence_pattern(texture_path)

    if normalized_role == "filter":
        if basename == "mrt_materialidmap.dds":
            classification = "material_id_map"
            recommended_action = "ignore_engine_map"
        elif is_default_engine_texture:
            classification = "default_engine_map"
            recommended_action = "ignore_engine_map"
        elif any(token in basename for token in ("filter", "mask", "idmap", "materialid", "matid")):
            classification = "mask_or_id_map"
            recommended_action = "diagnostics_only"
        else:
            classification = "unknown_filter_texture"
            recommended_action = "diagnostics_only"
    elif is_default_engine_texture:
        classification = "default_engine_map"
        recommended_action = "ignore_engine_map"
    elif not exists and sequence_pattern:
        classification = "fx_sequence" if _looks_fx_texture(texture_path) else "animated_texture"
        recommended_action = "requires_animation/fx_parser"
    elif not exists:
        classification = "genuinely_missing"
        recommended_action = "diagnostics_only"
    elif normalized_role == "diffuse":
        classification = "visual_diffuse"
        recommended_action = "use_now"
    elif normalized_role in ("bump", "normal"):
        classification = "normal_or_bump_map"
        recommended_action = "future_optional_shader_support"
    elif normalized_role in ("opacity", "specular", "gloss", "detail", "reflection", "subsurf"):
        classification = f"{normalized_role}_map"
        recommended_action = "future_optional_shader_support"
    else:
        classification = "unknown_texture"
        recommended_action = "diagnostics_only"

    return {
        "classification": classification,
        "recommended_action": recommended_action,
        "sequence_pattern": sequence_pattern,
        "is_default_engine_texture": is_default_engine_texture,
        "is_visual_candidate": (
            exists
            and not is_default_engine_texture
            and recommended_action in ("use_now", "future_optional_shader_support")
            and normalized_role in VISUAL_SHADER_ROLES
        ),
    }


def sequence_timing_relation(sequence_contract, frame_files, timing):
    if not sequence_contract["is_sequence"]:
        return {
            "relation": "not_sequence",
            "global_range": None,
            "ticks_per_frame": None,
            "secs_per_tick": None,
            "sequence_frame_count": 0,
            "range_end": None,
        }
    timing = timing if isinstance(timing, dict) else None
    if timing is None:
        relation = "sequence_frames_exist_with_no_timing" if frame_files["all_frames_exist"] else "sequence_frames_missing"
        return {
            "relation": relation,
            "global_range": None,
            "ticks_per_frame": None,
            "secs_per_tick": None,
            "sequence_frame_count": sequence_contract["frame_count_expected"],
            "range_end": None,
        }
    global_range = timing.get("global_range") if isinstance(timing.get("global_range"), dict) else {}
    if frame_files["all_frames_exist"]:
        relation = "sequence_frames_exist_with_global_range"
    elif frame_files["missing_frame_count"]:
        relation = "sequence_frames_missing"
    else:
        relation = "unknown"
    return {
        "relation": relation,
        "global_range": {
            "name": global_range.get("name"),
            "start": global_range.get("start"),
            "end": global_range.get("end"),
        },
        "ticks_per_frame": timing.get("ticks_per_frame"),
        "secs_per_tick": timing.get("secs_per_tick"),
        "sequence_frame_count": sequence_contract["frame_count_expected"],
        "range_end": global_range.get("end"),
    }


def _decoded_timing_fields_for_parsed(parsed):
    timing = parsed.get("Timing") if isinstance(parsed, dict) else None
    if not isinstance(timing, dict):
        return None
    global_range = timing.get("global_range") if isinstance(timing.get("global_range"), dict) else {}
    return {
        "secs_per_tick": timing.get("secs_per_tick"),
        "ticks_per_frame": timing.get("ticks_per_frame"),
        "global_range": {
            "name": global_range.get("name"),
            "start": global_range.get("start"),
            "end": global_range.get("end"),
        },
        "num_sub_ranges": timing.get("num_sub_ranges"),
    }


def _looks_fx_texture(texture_path):
    return looks_fx_texture(texture_path)


def _clean_texture_path(value):
    if not value:
        return ""
    return str(value).strip().strip("\x00").replace("/", os.sep).replace("\\", os.sep)


def _client_root_from_path(path):
    return client_root_from_path(path)


def _texture_sibling_names(clean_name, clean_long_name, cgf_path=None, client_root=None):
    directory, _method = sequence_base_directory(
        clean_name,
        clean_long_name,
        cgf_path=cgf_path,
        client_root=client_root,
    )
    if directory is None or not directory.is_dir():
        return ()
    return tuple(path.name for path in directory.iterdir() if path.is_file())


def _material_id(material):
    header = material.get("header") if isinstance(material, dict) else None
    if isinstance(header, dict):
        return header.get("chunk_id")
    return None


def _parser_coverage_events(suspicious_events, unread_ranges):
    events = []
    for item in unread_ranges:
        chunk_type = str(item.get("context") or "")
        events.append(
            {
                "event_type": "unread_chunk",
                "signature": "not_fully_read_chunk",
                "chunk_type": chunk_type,
                "category": _chunk_domain_category(chunk_type),
                "coverage_category": item.get("category") or _coverage_category_for_unread_chunk(chunk_type),
                "severity": item.get("severity") or _coverage_severity_for_unread_chunk(chunk_type),
                "reason": item.get("reason") or "chunk parser stopped before next chunk",
                "recommended_action": item.get("recommended_action") or _coverage_action_for_unread_chunk(chunk_type),
                "offset_start": item.get("offset_start"),
                "offset_end": item.get("offset_end"),
                "size": item.get("size"),
            }
        )

    for event in suspicious_events:
        signature = str(event.get("signature") or "")
        detail = event.get("detail") if isinstance(event.get("detail"), dict) else {}
        record = {
            "event_type": _coverage_event_type(signature),
            "signature": signature,
            "category": event.get("category"),
            "coverage_category": event.get("coverage_category") or _event_coverage_category(signature, event.get("category")),
            "severity": event.get("severity") or _event_severity(signature, event.get("category")),
            "context": event.get("context"),
            "field": detail.get("field") or event.get("context"),
            "reason": event.get("reason") or _event_reason(signature, event.get("category")),
            "recommended_action": event.get("recommended_action") or _event_recommended_action(signature, event.get("category")),
            "detail": event.get("detail"),
        }
        events.append(record)
    return events


def _coverage_event_type(signature):
    if signature in {
        "unused_material_texture_field",
        "material_texture_amount_not_default",
        "material_texture_transform_not_default",
        "material_texture_no_mip_map",
        "material_texture_reserved_nonzero",
        "material_self_illum_nonzero",
        "material_reserved_nonzero",
        "unknown_material_type",
    }:
        return "material_field"
    if signature in {"unsupported_chunk_parser", "animation_chunk_present"}:
        return "unsupported_chunk"
    if signature == "unsupported_chunk_padding_nonzero":
        return "chunk_padding"
    return "diagnostic_event"


def _coverage_category_for_unread_chunk(chunk_type):
    if chunk_type == "Mesh":
        return COVERAGE_SCENE_RELEVANT_NOW
    if chunk_type in {"Controller", "Timing", "VertAnim"}:
        return COVERAGE_SCENE_RELEVANT_LATER
    if chunk_type in {"BoneAnim", "BoneNameList", "BoneInitialPos", "BoneMesh"}:
        return COVERAGE_RUNTIME_ONLY
    if chunk_type in {"MeshSubsets", "SourceInfo"}:
        return COVERAGE_EXPECTED_SKIP
    return COVERAGE_UNKNOWN_NEEDS_AUDIT


def _coverage_severity_for_unread_chunk(chunk_type):
    if chunk_type == "Mesh":
        return "warning"
    if chunk_type in {"Controller", "Timing", "VertAnim"}:
        return "info"
    if chunk_type in {"BoneAnim", "BoneNameList", "BoneInitialPos", "BoneMesh"}:
        return "info"
    return "notice"


def _coverage_action_for_unread_chunk(chunk_type):
    if chunk_type == "Mesh":
        return "audit_mesh_leftover_payload"
    if chunk_type in {"Controller", "Timing", "VertAnim"}:
        return "keep_raw_metadata_for_future_animation_fx"
    if chunk_type in {"BoneAnim", "BoneNameList", "BoneInitialPos", "BoneMesh"}:
        return "ignored_by_design_for_static_import"
    if chunk_type in {"MeshSubsets", "SourceInfo"}:
        return "ignored_by_design"
    return "audit_before_silencing"


def _event_coverage_category(signature, category):
    if signature in {
        "unused_material_texture_field",
        "material_texture_amount_not_default",
        "material_texture_transform_not_default",
        "material_texture_no_mip_map",
        "material_texture_reserved_nonzero",
    }:
        return COVERAGE_SCENE_RELEVANT_LATER
    if signature in {"material_self_illum_nonzero", "visual_material_without_diffuse_texture"}:
        return COVERAGE_SCENE_RELEVANT_NOW
    if signature in {"collision_or_nodraw_material", "helper_node_ignored_by_importer"}:
        return COVERAGE_EXPECTED_SKIP
    if signature in {"animation_chunk_present", "unsupported_chunk_parser"} and category in {
        CATEGORY_ANIMATION,
        CATEGORY_CONTROLLER,
        CATEGORY_TRANSFORM_ANIMATION,
    }:
        return COVERAGE_SCENE_RELEVANT_LATER
    if signature in {"unsupported_chunk_padding_nonzero", "material_reserved_nonzero"}:
        return COVERAGE_UNKNOWN_NEEDS_AUDIT
    if signature in {"debug_done_print", "legacy_interest_message"}:
        return COVERAGE_DEBUG_NOISE
    return COVERAGE_UNKNOWN_NEEDS_AUDIT


def _event_severity(signature, category):
    coverage = _event_coverage_category(signature, category)
    if coverage == COVERAGE_SCENE_RELEVANT_NOW:
        return "warning"
    if coverage in {COVERAGE_SCENE_RELEVANT_LATER, COVERAGE_UNKNOWN_NEEDS_AUDIT}:
        return "notice"
    return "info"


def _event_recommended_action(signature, category):
    if signature == "unused_material_texture_field":
        return "classify_for_future_shader_support"
    if signature == "material_texture_amount_not_default":
        return "audit_texture_weight_semantics"
    if signature == "material_texture_transform_not_default":
        return "audit_uv_transform_semantics"
    if signature == "material_self_illum_nonzero":
        return "audit_emissive_material_support"
    if signature == "visual_material_without_diffuse_texture":
        return "diagnose_gray_material_reason"
    if signature in {"collision_or_nodraw_material", "helper_node_ignored_by_importer"}:
        return "expected_skip_summary"
    if signature == "unsupported_chunk_parser":
        return "keep_raw_metadata_or_backlog_parser"
    if signature == "animation_chunk_present":
        return "backlog_animation_or_fx_support"
    if signature in {"unsupported_chunk_padding_nonzero", "material_reserved_nonzero"}:
        return "audit_before_silencing"
    return "diagnostics_only"


def _event_reason(signature, category):
    if signature == "unused_material_texture_field":
        return "texture role is parsed but not connected by current Blender shader"
    if signature == "material_texture_amount_not_default":
        return "texture amount differs from default and may affect future shader weighting"
    if signature == "material_texture_transform_not_default":
        return "texture transform fields are parsed but not applied"
    if signature == "material_self_illum_nonzero":
        return "self illumination is parsed but not represented as emissive material"
    if signature == "collision_or_nodraw_material":
        return "collision/NoDraw material is intentionally filtered from visual import"
    if signature == "helper_node_ignored_by_importer":
        return "helper nodes are metadata/anchors and not imported by default"
    if signature == "unsupported_chunk_parser":
        return "chunk has no semantic parser in current static importer"
    if signature == "animation_chunk_present":
        return "animation/controller chunk is kept as diagnostics for future features"
    return "parser coverage diagnostic"


def _chunk_domain_category(chunk_type):
    if chunk_type in {"Mesh", "MeshSubsets", "PatchMesh", "MeshPhysicsData"}:
        return CATEGORY_GEOMETRY
    if chunk_type in {"Mtl", "MtlList", "MtlName"}:
        return CATEGORY_MATERIAL
    if chunk_type in {"Controller", "Timing"}:
        return CATEGORY_CONTROLLER
    if chunk_type in {"VertAnim", "BoneAnim", "BoneNameList", "BoneInitialPos", "BoneMesh"}:
        return CATEGORY_ANIMATION
    if chunk_type == "Light":
        return CATEGORY_LIGHT
    return CATEGORY_UNKNOWN
