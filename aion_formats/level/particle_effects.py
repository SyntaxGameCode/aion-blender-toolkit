from dataclasses import asdict, dataclass
from pathlib import Path
import math
import re
import struct


PRINTABLE_RE = re.compile(rb"[ -~]{4,}")
PARTICLE_CLASS = "ParticleEffect"
ENTITY_CLASS_NAMES = {
    "BasicEntity",
    "Bugs",
    "Chair",
    "DeferredLight",
    "Fish",
    "Milestone",
    "ParticleEffect",
    "PlaceableObject",
    "RandomAmbientSound",
    "SoundSpot",
    "client_npc",
}
EFFECT_NAME_RE = re.compile(r"^[A-Za-z0-9_]+(?:\.[A-Za-z0-9_\-/\[\]]+){2,}$")
TEXTURE_RE = re.compile(r"(?i)([A-Za-z0-9_./\\:\- ]+\.dds)")
PRT_HEADER_SIZE = 15
PRT_RECORD_SIZE = 2187


@dataclass(frozen=True)
class EntityContextParticleEffect:
    entity_name: str
    effect_name: str
    position: tuple[float, float, float] | None
    source_file: str
    record_index: int
    entity_offset: int
    effect_offset: int
    raw_position_candidates: tuple[tuple[float, float, float], ...]
    warnings: tuple[str, ...]


@dataclass(frozen=True)
class EntityContextParticleEffects:
    files_scanned: int
    records_found: int
    valid_records: int
    skipped_invalid_positions: int
    records: tuple[EntityContextParticleEffect, ...]
    warnings: tuple[str, ...]


@dataclass(frozen=True)
class ParticleTextureReference:
    texture_path: str
    resolved_path: Path | None
    exists: bool
    emitter_name: str = ""
    emitter_record_index: int = -1
    emitter_record_offset: int = -1


@dataclass(frozen=True)
class PrtEmitterRecord:
    record_index: int
    record_offset: int
    emitter_name: str
    texture_path: str
    sound_path: str
    texture_reference: ParticleTextureReference | None


@dataclass(frozen=True)
class PrtEffectDefinition:
    effect_name: str
    library_path: Path
    definition_found: bool
    effect_offset: int
    texture_references: tuple[ParticleTextureReference, ...]
    emitter_records: tuple[PrtEmitterRecord, ...]
    record_layout: str
    selected_record_count: int
    raw_nearby_strings: tuple[str, ...]
    warnings: tuple[str, ...]


def parse_entitycontext_particle_effects(
    level_dir: str | Path,
    *,
    level_data=None,
    source_names: tuple[str, ...] = ("entitycontexts.lst", "entitycontexts2.lst"),
) -> EntityContextParticleEffects:
    level_path = Path(level_dir)
    x_max, y_max = _level_xy_bounds(level_data)
    records = []
    warnings = []
    files_scanned = 0
    skipped_invalid_positions = 0

    for source_name in source_names:
        source_path = level_path / source_name
        if not source_path.is_file():
            continue
        files_scanned += 1
        parsed, skipped = _parse_entitycontext_file(
            source_path,
            x_max=x_max,
            y_max=y_max,
            start_index=len(records),
        )
        records.extend(parsed)
        skipped_invalid_positions += skipped

    return EntityContextParticleEffects(
        files_scanned=files_scanned,
        records_found=len(records) + skipped_invalid_positions,
        valid_records=len(records),
        skipped_invalid_positions=skipped_invalid_positions,
        records=tuple(records),
        warnings=tuple(warnings),
    )


def resolve_particle_effect_definition(
    client_root: str | Path,
    effect_name: str,
) -> PrtEffectDefinition:
    client_root_path = Path(client_root)
    library_path = particle_effect_library_path(client_root_path, effect_name)
    if library_path is None or not library_path.is_file():
        return PrtEffectDefinition(
            effect_name=effect_name,
            library_path=library_path or client_root_path / "effects" / "prt" / "<unknown>.prt",
            definition_found=False,
            effect_offset=-1,
            texture_references=(),
            emitter_records=(),
            record_layout="missing",
            selected_record_count=0,
            raw_nearby_strings=(),
            warnings=("prt_library_missing",),
        )
    return parse_prt_effect_definition(library_path, effect_name, client_root=client_root_path)


def parse_prt_effect_definition(
    library_path: str | Path,
    effect_name: str,
    *,
    client_root: str | Path | None = None,
    window_bytes: int = 8192,
) -> PrtEffectDefinition:
    source_path = Path(library_path)
    data = source_path.read_bytes()
    encoded = effect_name.encode("latin1", errors="ignore")
    offset = data.find(encoded)
    if offset < 0:
        return PrtEffectDefinition(
            effect_name=effect_name,
            library_path=source_path,
            definition_found=False,
            effect_offset=-1,
            texture_references=(),
            emitter_records=(),
            record_layout="fixed_2187" if _has_fixed_prt_record_layout(data) else "unknown",
            selected_record_count=0,
            raw_nearby_strings=(),
            warnings=("effect_definition_missing",),
        )
    client_root_path = Path(client_root) if client_root else None
    record_layout = "unknown"
    selected_records = ()
    texture_refs = ()
    warnings = []
    if _has_fixed_prt_record_layout(data):
        record_layout = "fixed_2187"
        records = _parse_prt_records(data, client_root_path)
        selected_records = _select_effect_records(records, effect_name)
        texture_refs = tuple(
            record.texture_reference
            for record in selected_records
            if record.texture_reference is not None
        )
        if selected_records and selected_records[0].emitter_name == effect_name and not selected_records[0].texture_path:
            warnings.append("prt_child_emitters_selected_from_fixed_records")
    if not texture_refs:
        start = max(0, offset - 1024)
        end = min(len(data), offset + window_bytes)
        strings = tuple(_decode_printable(match.group(0)) for match in PRINTABLE_RE.finditer(data[start:end]))
        texture_paths = []
        for value in strings:
            for match in TEXTURE_RE.finditer(value):
                texture_paths.append(_normalize_path(match.group(1)))
        texture_refs = tuple(
            _texture_reference(path, client_root_path)
            for path in _unique(texture_paths)
        )
        if not selected_records:
            warnings.append("prt_texture_refs_from_string_window")
    else:
        strings = tuple(
            value
            for record in selected_records
            for value in (record.emitter_name, record.texture_path, record.sound_path)
            if value
        )
    return PrtEffectDefinition(
        effect_name=effect_name,
        library_path=source_path,
        definition_found=True,
        effect_offset=offset,
        texture_references=texture_refs,
        emitter_records=selected_records,
        record_layout=record_layout,
        selected_record_count=len(selected_records),
        raw_nearby_strings=strings[:32],
        warnings=tuple(warnings),
    )


def particle_effects_to_dict(parsed: EntityContextParticleEffects) -> dict:
    return {
        "files_scanned": parsed.files_scanned,
        "records_found": parsed.records_found,
        "valid_records": parsed.valid_records,
        "skipped_invalid_positions": parsed.skipped_invalid_positions,
        "records": tuple(asdict(record) for record in parsed.records),
        "warnings": parsed.warnings,
    }


def prt_effect_definition_to_dict(definition: PrtEffectDefinition) -> dict:
    data = asdict(definition)
    data["library_path"] = str(definition.library_path)
    data["texture_references"] = tuple(
        {
            "texture_path": texture.texture_path,
            "resolved_path": str(texture.resolved_path) if texture.resolved_path else None,
            "exists": texture.exists,
            "emitter_name": texture.emitter_name,
            "emitter_record_index": texture.emitter_record_index,
            "emitter_record_offset": texture.emitter_record_offset,
        }
        for texture in definition.texture_references
    )
    data["emitter_records"] = tuple(
        {
            "record_index": record.record_index,
            "record_offset": record.record_offset,
            "emitter_name": record.emitter_name,
            "texture_path": record.texture_path,
            "sound_path": record.sound_path,
        }
        for record in definition.emitter_records
    )
    return data


def particle_effect_library_path(client_root: str | Path, effect_name: str) -> Path | None:
    if not effect_name or "." not in effect_name:
        return None
    library_name = effect_name.split(".", 1)[0]
    return Path(client_root) / "effects" / "prt" / f"{library_name}.prt"


def _parse_entitycontext_file(source_path: Path, *, x_max, y_max, start_index):
    data = source_path.read_bytes()
    strings = [
        (match.start(), _decode_printable(match.group(0)))
        for match in PRINTABLE_RE.finditer(data)
    ]
    records = []
    skipped_invalid_positions = 0
    for index, (class_offset, value) in enumerate(strings):
        if value != PARTICLE_CLASS:
            continue
        next_class_offset = _next_entity_class_offset(strings, index + 1, len(data))
        entity_name = strings[index + 1][1] if index + 1 < len(strings) else ""
        entity_name_end = strings[index + 1][0] + len(entity_name) if index + 1 < len(strings) else class_offset
        effect_offset, effect_name = _find_effect_name(strings, index + 1, next_class_offset)
        if not effect_name:
            skipped_invalid_positions += 1
            continue
        candidates = _position_candidates(
            data,
            entity_name_end,
            effect_offset,
            x_max=x_max,
            y_max=y_max,
        )
        position = candidates[0] if candidates else None
        warnings = []
        if position is None:
            warnings.append("missing_or_out_of_bounds_position")
            skipped_invalid_positions += 1
            continue
        warnings.append("rotation_not_decoded")
        records.append(
            EntityContextParticleEffect(
                entity_name=entity_name,
                effect_name=effect_name,
                position=position,
                source_file=source_path.name,
                record_index=start_index + len(records),
                entity_offset=class_offset,
                effect_offset=effect_offset,
                raw_position_candidates=tuple(candidates[:8]),
                warnings=tuple(warnings),
            )
        )
    return records, skipped_invalid_positions


def _find_effect_name(strings, start_index, stop_offset):
    for offset, value in strings[start_index:]:
        if offset >= stop_offset:
            break
        if "\\" in value or "/" in value or value.lower().endswith((".cgf", ".cga", ".dds", ".ogg")):
            continue
        if EFFECT_NAME_RE.match(value):
            return offset, value
    return -1, ""


def _next_entity_class_offset(strings, start_index, default):
    for offset, value in strings[start_index:]:
        if value in ENTITY_CLASS_NAMES:
            return offset
    return default


def _position_candidates(data, start_offset, stop_offset, *, x_max, y_max):
    if stop_offset <= start_offset:
        stop_offset = min(len(data), start_offset + 256)
    stop_offset = min(len(data), stop_offset)
    candidates = []
    for offset in range(start_offset, max(start_offset, stop_offset - 12) + 1):
        try:
            values = struct.unpack_from("<fff", data, offset)
        except struct.error:
            break
        if _is_plausible_position(values, x_max=x_max, y_max=y_max):
            candidates.append(tuple(float(value) for value in values))
    scored = [
        (candidate, _position_score(candidate, x_max=x_max, y_max=y_max))
        for candidate in candidates
    ]
    return [
        candidate
        for candidate, score in sorted(scored, key=lambda item: item[1], reverse=True)
        if score >= 5.0
    ]


def _is_plausible_position(values, *, x_max, y_max):
    if len(values) != 3 or not all(math.isfinite(value) for value in values):
        return False
    x, y, z = values
    margin = 64.0
    return (
        -margin <= x <= x_max + margin
        and -margin <= y <= y_max + margin
        and -1000.0 <= z <= 5000.0
    )


def _position_score(values, *, x_max, y_max):
    x, y, z = values
    score = 0.0
    if 0.0 <= x <= x_max:
        score += 1.0
    if 0.0 <= y <= y_max:
        score += 1.0
    if -100.0 <= z <= 500.0:
        score += 2.0
    if abs(x) > 16.0:
        score += 2.0
    if abs(y) > 16.0:
        score += 2.0
    if abs(z) > 1.0:
        score += 1.0
    if abs(x) < 1.0 and abs(y) < 1.0:
        score -= 4.0
    return score


def _level_xy_bounds(level_data):
    info = getattr(level_data, "level_info", None)
    x_size = float(getattr(info, "heightmap_x_size", 1024) or 1024)
    y_size = float(getattr(info, "heightmap_y_size", 1024) or 1024)
    return x_size * 2.0, y_size * 2.0


def _parse_prt_records(data: bytes, client_root: Path | None):
    records = []
    count = (len(data) - PRT_HEADER_SIZE) // PRT_RECORD_SIZE
    for index in range(count):
        offset = PRT_HEADER_SIZE + index * PRT_RECORD_SIZE
        record = data[offset : offset + PRT_RECORD_SIZE]
        emitter_name = _decode_c_string(record[0:64])
        texture_path = _normalize_path(_decode_c_string(record[64:256]))
        sound_path = _normalize_path(_decode_c_string(record[2094:]))
        texture_reference = (
            _texture_reference(
                texture_path,
                client_root,
                emitter_name=emitter_name,
                emitter_record_index=index,
                emitter_record_offset=offset,
            )
            if texture_path
            else None
        )
        records.append(
            PrtEmitterRecord(
                record_index=index,
                record_offset=offset,
                emitter_name=emitter_name,
                texture_path=texture_path,
                sound_path=sound_path,
                texture_reference=texture_reference,
            )
        )
    return tuple(records)


def _select_effect_records(records, effect_name):
    for index, record in enumerate(records):
        if record.emitter_name != effect_name:
            continue
        if record.texture_path:
            return (record,)
        selected = [record]
        for child in records[index + 1 :]:
            if not child.texture_path:
                break
            selected.append(child)
        return tuple(selected)
    return ()


def _has_fixed_prt_record_layout(data: bytes):
    return len(data) >= PRT_HEADER_SIZE and (len(data) - PRT_HEADER_SIZE) % PRT_RECORD_SIZE == 0


def _decode_c_string(value: bytes):
    return _decode_printable(value.split(b"\0", 1)[0]).strip()


def _texture_reference(
    texture_path,
    client_root,
    *,
    emitter_name="",
    emitter_record_index=-1,
    emitter_record_offset=-1,
):
    resolved = _resolve_texture_path(texture_path, client_root)
    return ParticleTextureReference(
        texture_path=texture_path,
        resolved_path=resolved,
        exists=bool(resolved and resolved.is_file()),
        emitter_name=emitter_name,
        emitter_record_index=emitter_record_index,
        emitter_record_offset=emitter_record_offset,
    )


def _resolve_texture_path(texture_path, client_root):
    if client_root is None or not texture_path:
        return None
    path = Path(texture_path.replace("/", "\\").lstrip("\\/"))
    if path.is_absolute():
        return path
    return client_root / path


def _decode_printable(value):
    return value.decode("latin1", errors="ignore").strip("\x00")


def _normalize_path(value):
    return str(value or "").strip().strip("\"'").replace("/", "\\")


def _unique(values):
    seen = set()
    result = []
    for value in values:
        lowered = value.lower()
        if lowered in seen:
            continue
        seen.add(lowered)
        result.append(value)
    return tuple(result)
