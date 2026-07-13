from __future__ import annotations

import re
from dataclasses import asdict, dataclass
from pathlib import Path


UNKNOWN_NOT_DECODED = "unknown_not_decoded"


@dataclass(frozen=True)
class ClientShaderSemantics:
    shader_name: str
    resolved_shader_name: str
    definition_path: str
    include_paths: tuple[str, ...]
    blend_mode: str
    blend_equation: str
    alpha_mode: str
    sort_mode: str
    cull_mode: str
    two_sided: bool
    no_auto_depth_write: bool
    uv_scroll_confirmed: bool
    uv_scroll_source: str
    uv_scroll_param: str
    uv_scroll_speed_x: float | None
    uv_scroll_speed_y: float | None
    uv_scroll_target_slot: str
    uv_scroll_target_layer: str
    uv_scroll_static_mask_slot: str
    alpha_source: str
    color_formula: str
    shader_layers: tuple[dict[str, str], ...]
    semantics_source: tuple[str, ...]

    def to_dict(self):
        return asdict(self)


def resolve_client_shader_semantics(client_root, shader_name):
    shader_name = str(shader_name or "").strip()
    if not shader_name or not client_root:
        return None

    shaders_root = Path(client_root) / "Shaders"
    if not shaders_root.is_dir():
        return None

    shader_block = _find_shader_block(shaders_root, shader_name)
    if shader_block is None:
        return None

    definition_path, resolved_shader_name, block = shader_block
    include_paths = _resolve_includes(definition_path, block)
    include_text = "\n".join(_read_text(path) for path in include_paths)
    combined_text = f"{block}\n{include_text}"

    blend_equation = _first_blend_equation(combined_text)
    sort_mode = _first_param_value(block, "Sort")
    cull_mode = _first_param_value(combined_text, "Cull")
    no_auto_depth_write = bool(re.search(r"\bNoAutoDepthWrite\b", combined_text, re.IGNORECASE))
    shader_layers = _shader_layers(combined_text)
    uv_scroll = _texshift_uv_scroll(combined_text, shader_layers)
    return ClientShaderSemantics(
        shader_name=shader_name,
        resolved_shader_name=resolved_shader_name,
        definition_path=str(definition_path),
        include_paths=tuple(str(path) for path in include_paths),
        blend_mode=_blend_mode_from_equation(blend_equation),
        blend_equation=blend_equation,
        alpha_mode=UNKNOWN_NOT_DECODED,
        sort_mode=sort_mode,
        cull_mode=cull_mode,
        two_sided=_two_sided_from_cull(cull_mode),
        no_auto_depth_write=no_auto_depth_write,
        uv_scroll_confirmed=uv_scroll["confirmed"],
        uv_scroll_source=uv_scroll["source"],
        uv_scroll_param=uv_scroll["param"],
        uv_scroll_speed_x=uv_scroll["speed_x"],
        uv_scroll_speed_y=uv_scroll["speed_y"],
        uv_scroll_target_slot=uv_scroll["target_slot"],
        uv_scroll_target_layer=uv_scroll["target_layer"],
        uv_scroll_static_mask_slot=uv_scroll["static_mask_slot"],
        alpha_source=uv_scroll["alpha_source"],
        color_formula=uv_scroll["color_formula"],
        shader_layers=shader_layers,
        semantics_source=tuple(
            source
            for source in (
                "client_shader.definition",
                "client_shader.include" if include_paths else "",
                "client_shader.blend" if blend_equation else "",
                "client_shader.cull" if cull_mode else "",
                "client_shader.no_auto_depth_write" if no_auto_depth_write else "",
                "client_shader.uv_scroll" if uv_scroll["confirmed"] else "",
            )
            if source
        ),
    )


def _find_shader_block(shaders_root, shader_name):
    wanted = shader_name.lower()
    for shader_file in _shader_definition_files(shaders_root):
        text = _read_text(shader_file)
        for match in re.finditer(r"Shader\s+'([^']+)'\s*(?P<body>[{(])", text, re.IGNORECASE):
            name = match.group(1).strip()
            if name.lower() != wanted:
                continue
            opener = match.group("body")
            closer = "}" if opener == "{" else ")"
            start = match.start()
            end = _matching_block_end(text, match.end() - 1, opener, closer)
            return shader_file, name, text[start:end]
    return None


def _shader_definition_files(shaders_root):
    subdirs = (
        shaders_root / "HWScripts" / "Techniques" / "materialShaders",
        shaders_root / "HWScripts" / "Techniques" / "systemShaders",
        shaders_root / "MRT" / "DX9" / "HWScripts" / "Techniques" / "materialShaders",
        shaders_root / "MRT" / "DX9" / "HWScripts" / "Techniques" / "systemShaders",
    )
    for subdir in subdirs:
        if subdir.is_dir():
            yield from sorted(subdir.glob("*.csl"))


def _resolve_includes(definition_path, block):
    paths = []
    for include in re.findall(r'#include\s+["<]([^">]+)[">]', block, re.IGNORECASE):
        include_path = (definition_path.parent / include.replace("\\", "/")).resolve()
        if include_path.is_file():
            paths.append(include_path)
    return tuple(paths)


def _read_text(path):
    try:
        return Path(path).read_text(encoding="utf-8", errors="replace")
    except OSError:
        return ""


def _matching_block_end(text, opener_index, opener, closer):
    depth = 0
    for index in range(opener_index, len(text)):
        char = text[index]
        if char == opener:
            depth += 1
        elif char == closer:
            depth -= 1
            if depth == 0:
                return index + 1
    return len(text)


def _first_blend_equation(text):
    match = re.search(r"\bBlend\s*(?:\(\s*)?'?([A-Za-z0-9_]+\s+[A-Za-z0-9_]+)'?", text, re.IGNORECASE)
    return " ".join(match.group(1).upper().split()) if match else ""


def _blend_mode_from_equation(blend_equation):
    if blend_equation == "ONE ONE":
        return "additive"
    if blend_equation in {
        "SRCALPHA INVSRCALPHA",
        "SRC_ALPHA INV_SRC_ALPHA",
        "SRC_ALPHA ONE_MINUS_SRC_ALPHA",
        "SRCALPHA ONEMINUSSRCALPHA",
    }:
        return "alpha_blend"
    return UNKNOWN_NOT_DECODED if not blend_equation else "unknown_blend_equation"


def _first_param_value(text, name):
    match = re.search(rf"\b{name}\s*=\s*([A-Za-z0-9_]+)", text, re.IGNORECASE)
    return match.group(1) if match else ""


def _two_sided_from_cull(cull_mode):
    return str(cull_mode or "").lower() in {"none", "twosided", "two_sided"}


def _shader_layers(text):
    layers = []
    for match in re.finditer(
        r"\bLayer\s+'?(\d+)'?\s*(?P<body>[{(])",
        text,
        re.IGNORECASE,
    ):
        opener = match.group("body")
        closer = "}" if opener == "{" else ")"
        body = text[match.end() - 1 : _matching_block_end(text, match.end() - 1, opener, closer)]
        map_match = re.search(r"\bMap\s*=\s*(\$[A-Za-z0-9_]+)", body, re.IGNORECASE)
        if map_match:
            layers.append(
                {
                    "layer": match.group(1),
                    "map": map_match.group(1),
                }
            )
    return tuple(layers)


def _texshift_uv_scroll(text, shader_layers):
    speed_x = _public_float_value(text, "shiftspeedX")
    speed_y = _public_float_value(text, "shiftspeedY")
    texshift_body = ""
    for texshift_match in re.finditer(r"\bCGVPParam\s*(?P<body>[{(])", text, re.IGNORECASE):
        opener = texshift_match.group("body")
        closer = "}" if opener == "{" else ")"
        body = text[
            texshift_match.end() - 1 : _matching_block_end(
                text,
                texshift_match.end() - 1,
                opener,
                closer,
            )
        ]
        if re.search(r"\bName\s*=\s*TexShift\b", body, re.IGNORECASE):
            texshift_body = body
            break

    has_texshift = bool(texshift_body)
    has_time = len(re.findall(r"\bComp\s+'time\s+1'", texshift_body, re.IGNORECASE)) >= 2
    has_speed_users = bool(
        re.search(r"\bUser\s+'shiftspeedX'", texshift_body, re.IGNORECASE)
        and re.search(r"\bUser\s+'shiftspeedY'", texshift_body, re.IGNORECASE)
    )
    resolved_shader_name = _shader_name(text)
    shader_name_normalized = resolved_shader_name.lower()
    diffuse_layer = next((layer for layer in shader_layers if layer["map"].lower() == "$diffuse"), None)
    has_mask_layer = any(layer["map"].lower() == "$maskmap" for layer in shader_layers)
    target_slot = "diffuse" if diffuse_layer else ""
    target_layer = diffuse_layer["layer"] if diffuse_layer else ""
    confirmed_common = (
        has_texshift
        and has_time
        and has_speed_users
        and speed_x is not None
        and speed_y is not None
        and target_slot == "diffuse"
    )
    is_opacity_shift_layer = shader_name_normalized == "aion_bg_opacityshiftlayer"
    is_opacity_shift = shader_name_normalized == "aion_bg_opacityshift"
    confirmed_layer = confirmed_common and is_opacity_shift_layer and has_mask_layer
    confirmed_single = confirmed_common and is_opacity_shift and not has_mask_layer
    confirmed = confirmed_layer or confirmed_single
    alpha_source = ""
    color_formula = ""
    static_mask_slot = ""
    if confirmed_layer:
        alpha_source = "diffuse_alpha_multiply_mask_alpha_multiply_opacity"
        color_formula = "ambient_times_diffuse_times_4_plus_mask_rgb"
        static_mask_slot = "mask_map"
    elif confirmed_single:
        alpha_source = "diffuse_alpha_multiply_opacity"
        color_formula = "ambient_times_diffuse_times_4"
    return {
        "confirmed": confirmed,
        "source": "external_shader_sot" if confirmed else "",
        "param": "TexShift" if has_texshift else "",
        "speed_x": speed_x,
        "speed_y": speed_y,
        "target_slot": target_slot if confirmed else "",
        "target_layer": target_layer if confirmed else "",
        "static_mask_slot": static_mask_slot if confirmed else "",
        "alpha_source": alpha_source if confirmed else "",
        "color_formula": color_formula if confirmed else "",
    }


def _public_float_value(text, name):
    match = re.search(
        rf"\bfloat\s+'{re.escape(name)}'\s*\(\s*([-+]?\d+(?:\.\d+)?)\s*\)",
        text,
        re.IGNORECASE,
    )
    return float(match.group(1)) if match else None


def _shader_name(text):
    match = re.search(r"\bShader\s+'([^']+)'", text, re.IGNORECASE)
    return match.group(1).strip() if match else ""
