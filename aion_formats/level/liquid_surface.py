from collections import Counter
from dataclasses import dataclass
from pathlib import Path
import re

from .leveldata import LevelData


LIQUID_KIND_AUTO = "AUTO"
LIQUID_KIND_WATER = "WATER"
LIQUID_KIND_LAVA = "LAVA"
LIQUID_KIND_UNKNOWN = "UNKNOWN"

LIQUID_PRESET_AUTO = "AUTO"
LIQUID_PRESET_NORMAL = "NORMAL"
LIQUID_PRESET_TRANSPARENT = "TRANSPARENT"
LIQUID_PRESET_LAVA_EMISSIVE = "LAVA_EMISSIVE"


_KIND_KEYWORDS = {
    LIQUID_KIND_LAVA: ("lava", "magma", "molten", "volcano"),
    "ACID": ("acid", "toxic", "poison"),
    "SWAMP": ("swamp",),
    "MAGIC": ("magic", "abyss"),
    LIQUID_KIND_WATER: ("water", "ocean", "sea", "river", "lake", "wave", "foam", "caustic", "shore"),
}
_DEFAULT_TEXTURE_CANDIDATES = (
    "textures/defaults/default_water_wave.dds",
    "textures/defaults/default_water_wave_mask.dds",
    "textures/defaults/mrt_oceannormal_ddn.dds",
    "textures/defaults/mrt_oceansunbump.dds",
    "textures/defaults/caustics_sampler.dds",
    "textures/defaults/Default_ReflectionMap.dds",
)
_REFERENCE_RE = re.compile(
    rb"(?i)([A-Za-z0-9_./\\:\- ]+\.(?:cgf|cga|chr|dds|xml|lua|caf|st5|lst|bin|tmp|uvs|ctc))"
)


@dataclass(frozen=True)
class LiquidTextureCandidate:
    texture: str
    resolved_path: str
    exists: bool
    source: str
    liquid_kind: str
    confidence: str
    role: str
    visual_candidate: bool


@dataclass(frozen=True)
class LiquidSurfaceRecipe:
    requested_kind: str
    inferred_kind: str
    selected_kind: str
    requested_preset: str
    selected_preset: str
    candidates: tuple[LiquidTextureCandidate, ...]
    warnings: tuple[str, ...] = ()


def infer_liquid_kind_from_text(text: str) -> tuple[str, tuple[str, ...], str]:
    normalized = _normalize(text)
    matches = {
        kind: tuple(keyword for keyword in keywords if keyword in normalized)
        for kind, keywords in _KIND_KEYWORDS.items()
    }
    matches = {kind: keywords for kind, keywords in matches.items() if keywords}
    if not matches:
        return LIQUID_KIND_UNKNOWN, (), "none"
    for kind in (LIQUID_KIND_LAVA, "ACID", "SWAMP", LIQUID_KIND_WATER, "MAGIC"):
        if kind in matches:
            confidence = "high" if kind in {LIQUID_KIND_LAVA, LIQUID_KIND_WATER, "ACID"} else "medium"
            return kind, matches[kind], confidence
    return LIQUID_KIND_UNKNOWN, (), "low"


def classify_liquid_texture_role(texture_ref: str) -> tuple[str, str, str, bool]:
    normalized = _normalize(texture_ref)
    name = Path(normalized).name
    liquid_kind, _keywords, confidence = infer_liquid_kind_from_text(normalized)
    if "normal" in name or "ddn" in name or "bump" in name:
        role = "normal_bump"
    elif "mask" in name:
        role = "mask"
    elif "caustic" in name:
        role = "caustics"
    elif "reflection" in name or "reflect" in name:
        role = "reflection"
    elif "foam" in name:
        role = "foam"
    elif any(term in name for term in ("emissive", "glow", "fire", "lava", "magma", "molten")):
        role = "emission_glow" if liquid_kind == LIQUID_KIND_LAVA else "diffuse_base"
    elif "volcano" in name:
        role = "diffuse_base"
    elif any(term in name for term in ("wave", "water", "river", "ocean", "lake", "sea")):
        role = "diffuse_base"
    else:
        role = "unknown"
    visual_candidate = role in {"diffuse_base", "caustics", "foam", "reflection", "emission_glow"}
    return liquid_kind, confidence, role, visual_candidate


def infer_liquid_kind(level_data: LevelData, reference_texts: tuple[str, ...] = ()) -> str:
    evidence = []
    for surface in level_data.surface_types:
        evidence.extend(
            str(value)
            for value in (surface.name, surface.material, surface.detail_texture, surface.bumpmap)
            if value
        )
    evidence.extend(reference_texts)
    counts = Counter(infer_liquid_kind_from_text(value)[0] for value in evidence)
    counts.pop(LIQUID_KIND_UNKNOWN, None)
    if not counts:
        return LIQUID_KIND_WATER if level_data.level_info.water_level is not None else LIQUID_KIND_UNKNOWN
    return counts.most_common(1)[0][0]


def extract_liquid_references(paths: tuple[str | Path, ...]) -> tuple[str, ...]:
    references = []
    seen = set()
    for path_like in paths:
        path = Path(path_like)
        if not path.is_file():
            continue
        content = path.read_bytes()
        for match in _REFERENCE_RE.findall(content):
            text = match.decode("utf-8", errors="ignore").strip().strip("\"'")
            kind = infer_liquid_kind_from_text(text)[0]
            if kind == LIQUID_KIND_UNKNOWN:
                continue
            key = _normalize(text)
            if key not in seen:
                seen.add(key)
                references.append(text)
    return tuple(references)


def build_liquid_surface_recipe(
    client_root: str | Path,
    level_data: LevelData,
    *,
    level_dir: str | Path | None = None,
    requested_kind: str = LIQUID_KIND_AUTO,
    requested_preset: str = LIQUID_PRESET_AUTO,
    reference_texts: tuple[str, ...] = (),
) -> LiquidSurfaceRecipe:
    requested_kind = (requested_kind or LIQUID_KIND_AUTO).upper()
    requested_preset = (requested_preset or LIQUID_PRESET_AUTO).upper()
    inferred_kind = infer_liquid_kind(level_data, reference_texts)
    selected_kind = inferred_kind if requested_kind == LIQUID_KIND_AUTO else requested_kind
    if selected_kind not in {LIQUID_KIND_WATER, LIQUID_KIND_LAVA, LIQUID_KIND_UNKNOWN}:
        selected_kind = LIQUID_KIND_UNKNOWN
    selected_preset = _select_preset(selected_kind, requested_preset)
    candidates = resolve_liquid_texture_candidates(
        client_root,
        level_data,
        level_dir=level_dir,
        requested_kind=selected_kind,
    )
    warnings = ()
    if selected_kind == LIQUID_KIND_LAVA and not any(
        candidate.exists and candidate.liquid_kind == LIQUID_KIND_LAVA for candidate in candidates
    ):
        warnings = ("lava selected but no existing lava texture candidates were resolved",)
    return LiquidSurfaceRecipe(
        requested_kind=requested_kind,
        inferred_kind=inferred_kind,
        selected_kind=selected_kind,
        requested_preset=requested_preset,
        selected_preset=selected_preset,
        candidates=candidates,
        warnings=warnings,
    )


def resolve_liquid_texture_candidates(
    client_root: str | Path,
    level_data: LevelData,
    *,
    level_dir: str | Path | None = None,
    requested_kind: str = LIQUID_KIND_AUTO,
) -> tuple[LiquidTextureCandidate, ...]:
    client_root_path = Path(client_root)
    candidates = []
    seen = set()
    for texture_ref in _DEFAULT_TEXTURE_CANDIDATES:
        _append_candidate(candidates, seen, client_root_path, texture_ref, "default_candidate")
    for surface in level_data.surface_types:
        for value in (surface.detail_texture, surface.bumpmap, surface.material, surface.name):
            if value and infer_liquid_kind_from_text(value)[0] != LIQUID_KIND_UNKNOWN:
                _append_candidate(candidates, seen, client_root_path, value, "leveldata_surface_type")
    if level_dir:
        references = extract_liquid_references(
            (
                Path(level_dir) / "materials.xml",
                Path(level_dir) / "mission_mission0.xml",
                Path(level_dir) / "objects.lst",
                Path(level_dir) / "brush.lst",
            )
        )
        for reference in references:
            if Path(reference).suffix.lower() == ".dds":
                _append_candidate(candidates, seen, client_root_path, reference, "level_reference")
    requested_kind = (requested_kind or LIQUID_KIND_AUTO).upper()
    if requested_kind in {LIQUID_KIND_WATER, LIQUID_KIND_LAVA}:
        candidates = [
            candidate for candidate in candidates
            if candidate.liquid_kind in {requested_kind, LIQUID_KIND_UNKNOWN}
            or candidate.source == "default_candidate"
        ]
    return tuple(candidates)


def liquid_surface_recipe_to_dict(recipe: LiquidSurfaceRecipe) -> dict:
    return {
        "requested_kind": recipe.requested_kind,
        "inferred_kind": recipe.inferred_kind,
        "selected_kind": recipe.selected_kind,
        "requested_preset": recipe.requested_preset,
        "selected_preset": recipe.selected_preset,
        "warnings": recipe.warnings,
        "candidates": tuple(candidate.__dict__ for candidate in recipe.candidates),
    }


def _append_candidate(candidates, seen, client_root: Path, texture_ref: str, source: str):
    normalized = str(texture_ref).strip().strip("\x00").replace("\\", "/")
    if not normalized or "." not in Path(normalized).name:
        return
    key = normalized.lower()
    if key in seen:
        return
    seen.add(key)
    liquid_kind, confidence, role, visual_candidate = classify_liquid_texture_role(normalized)
    candidates.append(
        LiquidTextureCandidate(
            texture=normalized,
            resolved_path=str(client_root / normalized),
            exists=(client_root / normalized).is_file(),
            source=source,
            liquid_kind=liquid_kind,
            confidence=confidence,
            role=role,
            visual_candidate=visual_candidate,
        )
    )


def _select_preset(selected_kind: str, requested_preset: str) -> str:
    if requested_preset != LIQUID_PRESET_AUTO:
        return requested_preset
    if selected_kind == LIQUID_KIND_LAVA:
        return LIQUID_PRESET_LAVA_EMISSIVE
    return LIQUID_PRESET_NORMAL


def _normalize(value: str) -> str:
    return str(value or "").strip().strip("\x00").replace("\\", "/").lower()
