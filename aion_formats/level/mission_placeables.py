from dataclasses import asdict, dataclass
from pathlib import Path
import math
import re
from xml.etree import ElementTree


MISSION_REFERENCE_RE = re.compile(
    r"(?i)([A-Za-z0-9_./\\:\- ]+\.(?:cgf|cga|chr|dds|xml|lua|caf))"
)
POSITION_ATTRS = ("Pos", "Position", "Location")
ROTATION_ATTRS = ("Angles", "Rotate", "Rotation")
RUNTIME_ENTITY_CLASSES = {"Bugs", "ParticleEffect", "RandomAmbientSound", "SoundSpot"}
RUNTIME_ASSET_SEGMENTS = {"boids", "bird", "birds", "fish", "fishes", "particle", "particles", "effect", "effects", "fx", "sound", "sounds", "water"}
EXCLUDED_EXTENSIONS = {".cga", ".chr", ".dds", ".xml", ".lua", ".caf"}


@dataclass(frozen=True)
class MissionPlaceableCandidate:
    entity_id: str
    entity_name: str
    entity_class: str
    asset_path: str
    resolved_path: Path | None
    asset_exists: bool
    position: tuple[float, float, float] | None
    angles: tuple[float, float, float] | None
    classification: str
    confidence: str
    source_file: str
    element_path: str
    owner_path: str
    reference_attr: str
    warnings: tuple[str, ...]


@dataclass(frozen=True)
class MissionPlaceables:
    path: Path
    valid: bool
    reason: str
    total_references: int
    candidates: tuple[MissionPlaceableCandidate, ...]
    skipped: tuple[MissionPlaceableCandidate, ...]


def parse_mission_placeables(
    mission_path: str | Path,
    *,
    client_root: str | Path | None = None,
    level_dir: str | Path | None = None,
) -> MissionPlaceables:
    source_path = Path(mission_path)
    if not source_path.is_file():
        return MissionPlaceables(
            path=source_path,
            valid=False,
            reason="mission_mission0.xml is missing",
            total_references=0,
            candidates=(),
            skipped=(),
        )

    root = ElementTree.parse(source_path).getroot()
    client_root_path = Path(client_root) if client_root else None
    level_path = Path(level_dir) if level_dir else source_path.parent
    records = []
    skipped = []

    def visit(element, ancestors, path_parts):
        element_path = "/".join(path_parts + (element.tag,))
        owner = _nearest_transform_owner((*ancestors, _xml_node(element, element_path)))
        for attr_name, asset_ref in _references_from_attrs(element.attrib):
            candidate = _candidate_from_reference(
                source_path,
                level_path,
                client_root_path,
                element_path,
                attr_name,
                asset_ref,
                owner,
            )
            if candidate.classification == "static_placeable_cgf":
                records.append(candidate)
            else:
                skipped.append(candidate)
        next_ancestors = (*ancestors, _xml_node(element, element_path))
        for child in element:
            visit(child, next_ancestors, path_parts + (element.tag,))

    visit(root, (), ())
    return MissionPlaceables(
        path=source_path,
        valid=True,
        reason="",
        total_references=len(records) + len(skipped),
        candidates=tuple(records),
        skipped=tuple(skipped),
    )


def mission_placeables_to_dict(placeables: MissionPlaceables) -> dict:
    return {
        "path": str(placeables.path),
        "valid": placeables.valid,
        "reason": placeables.reason,
        "total_references": placeables.total_references,
        "candidates": tuple(_candidate_to_dict(candidate) for candidate in placeables.candidates),
        "skipped": tuple(_candidate_to_dict(candidate) for candidate in placeables.skipped),
    }


def mission_asset_has_runtime_segment(asset_path: str, entity_class: str = "") -> bool:
    if entity_class in RUNTIME_ENTITY_CLASSES:
        return True
    lowered = str(asset_path or "").lower().replace("\\", "/")
    segments = {
        segment
        for part in lowered.split("/")
        for segment in re.split(r"[^a-z0-9]+", part)
        if segment
    }
    return bool(segments & RUNTIME_ASSET_SEGMENTS)


def is_suspicious_static_cgf_skip(candidate: MissionPlaceableCandidate) -> bool:
    return (
        candidate.classification != "static_placeable_cgf"
        and Path(candidate.asset_path).suffix.lower() == ".cgf"
        and candidate.entity_class == "PlaceableObject"
        and candidate.position is not None
        and candidate.asset_exists
        and not mission_asset_has_runtime_segment(candidate.asset_path, candidate.entity_class)
    )


def _candidate_to_dict(candidate):
    data = asdict(candidate)
    data["resolved_path"] = str(candidate.resolved_path) if candidate.resolved_path else None
    return data


def _candidate_from_reference(
    source_path,
    level_dir,
    client_root,
    element_path,
    attr_name,
    asset_ref,
    owner,
) -> MissionPlaceableCandidate:
    owner_attrs = owner["attrs"] if owner else {}
    asset_path = _normalize(asset_ref)
    extension = Path(asset_path).suffix.lower()
    resolved_path = _resolve_asset(asset_path, level_dir, client_root)
    entity_class = _first_attr(owner_attrs, ("EntityClass",)) or ""
    position = _position_from_attrs(owner_attrs)
    angles = _first_vector(owner_attrs, ROTATION_ATTRS)
    classification, confidence, warnings = _classify(
        asset_path,
        extension,
        entity_class,
        position,
        resolved_path,
    )
    return MissionPlaceableCandidate(
        entity_id=_first_attr(owner_attrs, ("EntityId", "EntityGUID")) or "",
        entity_name=_first_attr(owner_attrs, ("Name",)) or "",
        entity_class=entity_class,
        asset_path=asset_path,
        resolved_path=resolved_path,
        asset_exists=bool(resolved_path and resolved_path.is_file()),
        position=position,
        angles=angles,
        classification=classification,
        confidence=confidence,
        source_file=source_path.name,
        element_path=element_path,
        owner_path=owner["path"] if owner else "",
        reference_attr=attr_name,
        warnings=warnings,
    )


def _classify(asset_path, extension, entity_class, position, resolved_path):
    warnings = []
    if _is_runtime_reference(asset_path, entity_class):
        return "runtime_or_unsupported_reference", "low", ("runtime boid/fx/water/sound reference",)
    if entity_class != "PlaceableObject":
        return "unsupported_entity_class", "low", (f"entity class is {entity_class or '<none>'}",)
    if extension in EXCLUDED_EXTENSIONS:
        return "unsupported_asset_type", "low", (f"unsupported asset extension {extension}",)
    if extension != ".cgf":
        return "unsupported_asset_type", "low", (f"unsupported asset extension {extension or '<none>'}",)
    if position is None:
        return "missing_position", "low", ("owner Entity has no Pos/Position/Location",)
    if not resolved_path or not resolved_path.is_file():
        return "missing_asset", "medium", ("asset does not exist under level/client root",)
    return "static_placeable_cgf", "high", warnings


def _references_from_attrs(attrs):
    refs = []
    for name, value in attrs.items():
        for match in MISSION_REFERENCE_RE.finditer(value):
            refs.append((name, match.group(1).strip().strip("\"'")))
    return tuple(refs)


def _nearest_transform_owner(nodes):
    for node in reversed(nodes):
        if _position_from_attrs(node["attrs"]) is not None:
            return node
    for node in reversed(nodes):
        if _first_attr(node["attrs"], ("EntityClass",)) is not None:
            return node
    return nodes[-1] if nodes else None


def _xml_node(element, element_path):
    return {
        "tag": element.tag,
        "path": element_path,
        "attrs": dict(element.attrib),
    }


def _position_from_attrs(attrs):
    value = _first_attr(attrs, POSITION_ATTRS)
    vector = _parse_vector(value) if value else None
    if vector and len(vector) >= 3:
        return tuple(vector[:3])
    if all(axis in attrs for axis in ("X", "Y", "Z")):
        values = (_to_float(attrs["X"]), _to_float(attrs["Y"]), _to_float(attrs["Z"]))
        if all(value is not None for value in values):
            return values
    return None


def _first_attr(attrs, names):
    lowered = {key.lower(): value for key, value in attrs.items()}
    for name in names:
        if name.lower() in lowered:
            return lowered[name.lower()]
    return None


def _first_vector(attrs, names):
    value = _first_attr(attrs, names)
    vector = _parse_vector(value) if value else None
    if vector and len(vector) >= 3:
        return tuple(vector[:3])
    return None


def _parse_vector(value):
    if not value:
        return None
    values = []
    for part in re.split(r"[,;\s]+", value.strip()):
        if not part:
            continue
        number = _to_float(part)
        if number is None:
            return None
        values.append(number)
    if not values or not all(math.isfinite(value) for value in values):
        return None
    return tuple(values)


def _to_float(value):
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _resolve_asset(asset_path, level_dir, client_root):
    if not asset_path:
        return None
    candidates = []
    relative = Path(asset_path.replace("/", "\\"))
    candidates.append(level_dir / relative)
    if client_root is not None:
        candidates.append(client_root / relative)
        candidates.append(client_root / "Levels" / relative)
    for candidate in candidates:
        if candidate.is_file():
            return candidate
    return candidates[1] if len(candidates) > 1 else candidates[0]


def _is_runtime_reference(asset_path, entity_class):
    return mission_asset_has_runtime_segment(asset_path, entity_class)


def _normalize(path):
    return str(path or "").replace("\\", "/").strip().strip("\"'").lstrip("/").lower()
