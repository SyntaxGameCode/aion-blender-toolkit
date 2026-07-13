from dataclasses import dataclass
import os
from pathlib import Path
import re


FX_SEQUENCE_TERMS = (
    "lightning",
    "aura",
    "fire",
    "flame",
    "smoke",
    "beam",
    "glow",
    "warp",
    "fx",
    "particle",
    "trail",
)

IMAGE_ALPHA = "image_alpha"
UNKNOWN_NOT_DECODED = "unknown_not_decoded"


@dataclass(frozen=True)
class TextureSequencePattern:
    is_sequence: bool
    confidence: str
    pattern_type: str
    prefix: str
    placeholder: str
    start_frame: int | None
    end_frame: int | None
    padding: int | None
    extension: str

    @property
    def frame_count_expected(self):
        if not self.is_sequence or self.start_frame is None or self.end_frame is None:
            return 0
        if self.end_frame < self.start_frame:
            return 0
        return self.end_frame - self.start_frame + 1


@dataclass(frozen=True)
class TextureSequenceResolution:
    is_sequence: bool
    source_texture: str
    frame_paths: tuple[str, ...]
    frame_count: int
    missing_frame_count: int
    fps: int
    confidence: str
    skip_reason: str
    frame_start_index: int | None = None
    frame_end_index: int | None = None

    @property
    def complete(self):
        return self.is_sequence and self.frame_count > 1 and self.missing_frame_count == 0

    @property
    def effective_frame_count(self):
        return self.frame_count

    @property
    def blender_frame_offset(self):
        if self.frame_start_index is None:
            return 0
        return int(self.frame_start_index) - 1


def parse_texture_sequence_pattern(texture_path):
    normalized = _normalize_texture_path(texture_path)
    basename = Path(normalized).name
    if not basename:
        return TextureSequencePattern(False, "", "", "", "", None, None, None, "")

    hash_range = re.match(
        r"^(?P<prefix>.*?)(?P<placeholder>##|%0?\d*d)(?P<start>\d{1,4})-(?P<end>\d{1,4})(?P<extension>\.[^.]+)$",
        basename,
        flags=re.IGNORECASE,
    )
    if hash_range:
        placeholder = hash_range.group("placeholder")
        start_text = hash_range.group("start")
        end_text = hash_range.group("end")
        return TextureSequencePattern(
            True,
            "confirmed_hash_range" if placeholder == "##" else "confirmed_printf_range",
            "hash_numeric_range" if placeholder == "##" else "printf_numeric_range",
            hash_range.group("prefix"),
            placeholder,
            int(start_text),
            int(end_text),
            _sequence_padding(placeholder, start_text, end_text),
            hash_range.group("extension").lower(),
        )

    numeric_suffix = re.match(
        r"^(?P<prefix>.*?[_-])(?P<frame>\d{2,4})(?P<extension>\.[^.]+)$",
        basename,
        flags=re.IGNORECASE,
    )
    if numeric_suffix:
        frame_text = numeric_suffix.group("frame")
        confidence = "loose_fx_name_candidate" if looks_fx_texture(basename) else "numeric_sequence_candidate"
        return TextureSequencePattern(
            True,
            confidence,
            "numeric_suffix",
            numeric_suffix.group("prefix"),
            frame_text,
            int(frame_text),
            int(frame_text),
            len(frame_text),
            numeric_suffix.group("extension").lower(),
        )

    return TextureSequencePattern(False, "", "", "", "", None, None, None, Path(basename).suffix.lower())


def sequence_frame_names(pattern, *, sibling_names=()):
    if not pattern.is_sequence:
        return ()
    if pattern.confidence in {"numeric_sequence_candidate", "loose_fx_name_candidate"}:
        inferred = _infer_numeric_sibling_range(pattern, sibling_names)
        if inferred:
            start_frame, end_frame = inferred
        else:
            start_frame = pattern.start_frame
            end_frame = pattern.end_frame
    else:
        start_frame = pattern.start_frame
        end_frame = pattern.end_frame
    if start_frame is None or end_frame is None or end_frame < start_frame:
        return ()
    return tuple(
        f"{pattern.prefix}{frame:0{pattern.padding}d}{pattern.extension}"
        for frame in range(start_frame, end_frame + 1)
    )


def texture_sequence_contract(clean_name="", clean_long_name="", *, sibling_names=()):
    texture_path = (clean_long_name or clean_name or "").replace("/", os.sep).replace("\\", os.sep)
    pattern = parse_texture_sequence_pattern(texture_path)
    names = sequence_frame_names(pattern, sibling_names=sibling_names)
    return {
        "is_sequence": pattern.is_sequence,
        "confidence": pattern.confidence,
        "pattern_type": pattern.pattern_type,
        "prefix": pattern.prefix,
        "placeholder": pattern.placeholder,
        "start_frame": pattern.start_frame,
        "end_frame": _end_frame_from_names(pattern, names),
        "padding": pattern.padding,
        "extension": pattern.extension,
        "frame_count_expected": len(names),
        "frame_name_examples": tuple(list(names[:3]) + list(names[-1:])) if names else (),
        "base_pattern": _base_pattern(pattern),
    }


def resolve_texture_sequence_frames(
    sequence_contract,
    clean_name="",
    clean_long_name="",
    *,
    cgf_path=None,
    client_root=None,
):
    if not sequence_contract["is_sequence"]:
        return {
            "expected_frame_count": 0,
            "existing_frame_count": 0,
            "missing_frame_count": 0,
            "resolved_frame_files": (),
            "missing_frame_files": (),
            "first_existing_frame": "",
            "first_missing_frame": "",
            "all_frames_exist": False,
            "resolution_method": "not_sequence",
            "frame_name_examples": (),
        }

    directory, method = sequence_base_directory(
        clean_name,
        clean_long_name,
        cgf_path=cgf_path,
        client_root=client_root,
    )
    names = tuple(sequence_contract.get("frame_name_examples") or ())
    all_names = _all_names_from_contract(sequence_contract)
    if all_names:
        names = all_names
    existing = []
    missing = []
    for name in names:
        path = directory / name if directory is not None else None
        if path is not None and path.is_file():
            existing.append(str(path))
        else:
            missing.append(str(path) if path is not None else name)
    return {
        "expected_frame_count": len(names),
        "existing_frame_count": len(existing),
        "missing_frame_count": len(missing),
        "resolved_frame_files": tuple(existing),
        "missing_frame_files": tuple(missing),
        "first_existing_frame": existing[0] if existing else "",
        "first_missing_frame": missing[0] if missing else "",
        "all_frames_exist": bool(names) and not missing,
        "resolution_method": method,
        "frame_name_examples": tuple(list(names[:3]) + list(names[-1:])) if names else (),
    }


def resolve_texture_sequence(
    texture_info,
    *,
    cgf_path=None,
    client_root=None,
    fps=10,
    min_existing_ratio=1.0,
):
    clean_name, clean_long_name = _texture_info_names(texture_info)
    source_texture = clean_long_name or clean_name
    if not source_texture:
        return TextureSequenceResolution(
            is_sequence=False,
            source_texture="",
            frame_paths=(),
            frame_count=0,
            missing_frame_count=0,
            fps=_safe_fps(fps),
            confidence="",
            skip_reason="missing_texture",
            frame_start_index=None,
            frame_end_index=None,
        )

    contract = texture_sequence_contract(clean_name=clean_name, clean_long_name=clean_long_name)
    if not _is_supported_product_sequence(contract):
        return TextureSequenceResolution(
            is_sequence=False,
            source_texture=source_texture,
            frame_paths=(),
            frame_count=0,
            missing_frame_count=0,
            fps=_safe_fps(fps),
            confidence=contract.get("confidence") or "",
            skip_reason="unsupported_or_unconfirmed_pattern",
            frame_start_index=contract.get("start_frame"),
            frame_end_index=contract.get("end_frame"),
        )

    frames = resolve_texture_sequence_frames(
        contract,
        clean_name=clean_name,
        clean_long_name=clean_long_name,
        cgf_path=cgf_path,
        client_root=client_root,
    )
    expected = int(frames.get("expected_frame_count") or 0)
    existing = int(frames.get("existing_frame_count") or 0)
    missing = int(frames.get("missing_frame_count") or 0)
    if expected <= 1:
        skip_reason = "sequence_needs_multiple_frames"
    elif existing <= 1:
        skip_reason = "not_enough_existing_frames"
    elif expected and existing / expected < float(min_existing_ratio):
        skip_reason = "incomplete_sequence"
    else:
        skip_reason = ""

    return TextureSequenceResolution(
        is_sequence=not skip_reason,
        source_texture=source_texture,
        frame_paths=tuple(frames.get("resolved_frame_files") or ()),
        frame_count=existing,
        missing_frame_count=missing,
        fps=_safe_fps(fps),
        confidence=contract.get("confidence") or "",
        skip_reason=skip_reason,
        frame_start_index=contract.get("start_frame"),
        frame_end_index=contract.get("end_frame"),
    )


def detect_sequence_pattern(texture_path):
    if not texture_path:
        return ""
    basename = Path(str(texture_path).lower().replace("/", "\\")).name
    patterns = []
    if "##" in basename:
        patterns.append("hash_sequence")
    if re.search(r"\d{1,3}-\d{1,3}", basename):
        patterns.append("numeric_range")
    if re.search(r"[_-]\d{2,4}(?:\.[^.]+)?$", basename):
        patterns.append("numeric_suffix")
    if looks_fx_texture(basename):
        patterns.append("fx_term")
    return "+".join(patterns)


def looks_fx_texture(texture_path):
    return any(term in str(texture_path).lower() for term in FX_SEQUENCE_TERMS)


def sequence_base_directory(clean_name, clean_long_name, cgf_path=None, client_root=None):
    if clean_long_name:
        root = Path(client_root).resolve() if client_root else client_root_from_path(cgf_path)
        if root is not None:
            return root / Path(_normalize_texture_path(clean_long_name)).parent, "long_name_client_root"
    if clean_name and cgf_path:
        return Path(cgf_path).resolve().parent, "local_cgf_dir"
    return None, "missing"


def client_root_from_path(path):
    if not path:
        return None
    parts = Path(path).resolve().parts
    root_markers = {"levels", "effects", "objects", "textures"}
    for index, part in enumerate(parts):
        if part.lower() in root_markers:
            if index == 0:
                return None
            return Path(*parts[:index])
    return None


def _normalize_texture_path(value):
    return str(value or "").strip().strip("\x00").replace("/", os.sep).replace("\\", os.sep)


def _texture_info_names(texture_info):
    if not isinstance(texture_info, dict):
        return "", ""
    return (
        _normalize_texture_path(texture_info.get("name")),
        _normalize_texture_path(texture_info.get("long_name")),
    )


def _is_supported_product_sequence(contract):
    return contract.get("confidence") in {"confirmed_hash_range", "confirmed_printf_range"}


def _safe_fps(value):
    try:
        fps = int(value)
    except (TypeError, ValueError):
        return 10
    return min(60, max(1, fps))


def _sequence_padding(placeholder, start_text, end_text):
    if placeholder.startswith("%"):
        match = re.match(r"%0?(?P<padding>\d*)d", placeholder, flags=re.IGNORECASE)
        if match and match.group("padding"):
            return int(match.group("padding"))
    return max(2 if placeholder == "##" else 0, len(start_text), len(end_text))


def _infer_numeric_sibling_range(pattern, sibling_names):
    if not sibling_names:
        return None
    frame_re = re.compile(
        rf"^{re.escape(pattern.prefix)}(?P<frame>\d{{{pattern.padding}}}){re.escape(pattern.extension)}$",
        flags=re.IGNORECASE,
    )
    frames = sorted(
        int(match.group("frame"))
        for name in sibling_names
        for match in (frame_re.match(str(name)),)
        if match
    )
    if not frames:
        return None
    return frames[0], frames[-1]


def _end_frame_from_names(pattern, names):
    if not names:
        return pattern.end_frame
    last = Path(names[-1]).name
    match = re.match(
        rf"^{re.escape(pattern.prefix)}(?P<frame>\d{{{pattern.padding}}}){re.escape(pattern.extension)}$",
        last,
        flags=re.IGNORECASE,
    )
    return int(match.group("frame")) if match else pattern.end_frame


def _base_pattern(pattern):
    if not pattern.is_sequence:
        return ""
    if pattern.confidence in {"confirmed_hash_range", "confirmed_printf_range"}:
        return f"{pattern.prefix}{pattern.placeholder}{pattern.start_frame:0{pattern.padding}d}-{pattern.end_frame:0{pattern.padding}d}{pattern.extension}"
    return f"{pattern.prefix}{'#' * max(1, pattern.padding)}{pattern.extension}"


def _all_names_from_contract(contract):
    if not contract.get("is_sequence"):
        return ()
    start_frame = contract.get("start_frame")
    end_frame = contract.get("end_frame")
    padding = contract.get("padding")
    prefix = contract.get("prefix")
    extension = contract.get("extension")
    if None in (start_frame, end_frame, padding) or not prefix or not extension:
        return ()
    if end_frame < start_frame:
        return ()
    return tuple(
        f"{prefix}{frame:0{padding}d}{extension}"
        for frame in range(start_frame, end_frame + 1)
    )
