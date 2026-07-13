import math
import os
import struct

from .diagnostics import (
    CATEGORY_ANIMATION,
    CATEGORY_COLLISION_NODRAW,
    CATEGORY_GEOMETRY,
    CATEGORY_HELPER_DUMMY,
    CATEGORY_LIGHT,
    CATEGORY_MATERIAL,
    CATEGORY_TEXTURE,
    CATEGORY_TRANSFORM,
    CATEGORY_UNKNOWN,
    CgfDiagnosticsCollector,
    RAW_CONTROLLER_CHUNK_TYPES,
    nearby_ascii_strings,
)


_ACTIVE_DIAGNOSTICS_COLLECTOR = None


class ParseError(ValueError):
    def __init__(self, message, offset=None, context=""):
        self.offset = offset
        self.context = context
        detail = message
        if context:
            detail = f"{context}: {detail}"
        if offset is not None:
            detail = f"{detail} at offset {offset}"
        super().__init__(detail)


def _read_exact(stream, size, context):
    offset = stream.tell()
    data = stream.read(size)
    if len(data) != size:
        raise ParseError(
            f"expected {size} bytes, got {len(data)}",
            offset=offset,
            context=context,
        )
    return data


def read_u8(stream, context="u8"):
    return int.from_bytes(_read_exact(stream, 1, context), byteorder="little")


def read_u32(stream, context="u32"):
    return int.from_bytes(_read_exact(stream, 4, context), byteorder="little")


def read_f32(stream, context="f32"):
    return struct.unpack("<f", _read_exact(stream, 4, context))[0]


def read_bool8(stream, context="bool8"):
    return bool.from_bytes(_read_exact(stream, 1, context), byteorder="little")


def read_ascii_bytes(stream, size, context="ascii"):
    return _read_exact(stream, size, context).decode("ascii")


def _active_collector():
    return _ACTIVE_DIAGNOSTICS_COLLECTOR


class _DiagnosticsScope:
    def __init__(self, collector):
        self.collector = collector
        self.previous_collector = None

    def __enter__(self):
        global _ACTIVE_DIAGNOSTICS_COLLECTOR
        self.previous_collector = _ACTIVE_DIAGNOSTICS_COLLECTOR
        _ACTIVE_DIAGNOSTICS_COLLECTOR = self.collector
        return self.collector

    def __exit__(self, exc_type, exc_value, traceback):
        global _ACTIVE_DIAGNOSTICS_COLLECTOR
        _ACTIVE_DIAGNOSTICS_COLLECTOR = self.previous_collector
        return False


def _emit_parser_event(
    signature,
    category,
    context="",
    detail=None,
    severity=None,
    coverage_category=None,
    recommended_action=None,
    reason=None,
):
    collector = _active_collector()
    if collector is not None:
        collector.add_event(
            signature,
            category,
            context=context,
            detail=detail,
            severity=severity,
            coverage_category=coverage_category,
            recommended_action=recommended_action,
            reason=reason,
        )


def remove_items(d, r_items):
    for k, v in d.copy().items():
        if isinstance(v, dict) and k not in r_items:
            remove_items(v, r_items)
        else:
            if k in r_items:
                d.pop(k)


CHUNK_TYPE_NAMES = {
    0: "ANY",
    0xCCCC0000: "Mesh",
    0xCCCC0001: "Helper",
    0xCCCC0002: "VertAnim",
    0xCCCC0003: "BoneAnim",
    0xCCCC0004: "GeomNameList",
    0xCCCC0005: "BoneNameList",
    0xCCCC0006: "MtlList",
    0xCCCC0007: "MRM",
    0xCCCC0008: "SceneProps",
    0xCCCC0009: "Light",
    0xCCCC000A: "PatchMesh",
    0xCCCC000B: "Node",
    0xCCCC000C: "Mtl",
    0xCCCC000D: "Controller",
    0xCCCC000E: "Timing",
    0xCCCC000F: "BoneMesh",
    0xCCCC0010: "BoneLightBinding",
    0xCCCC0011: "MeshMorphTarget",
    0xCCCC0012: "BoneInitialPos",
    0xCCCC0013: "SourceInfo",
    0xCCCC0014: "MtlName",
    0xCCCC0015: "ExportFlags",
    0xCCCC0016: "DataStream",
    0xCCCC0017: "MeshSubsets",
    0xCCCC0018: "MeshPhysicsData",
}

dict_chunk_type = {hex(raw_type): name for raw_type, name in CHUNK_TYPE_NAMES.items()}


def get_header(stream):
    raw_type = hex(read_u32(stream, "chunk raw type"))
    return {"chunk_type": dict_chunk_type.get(raw_type, "Unknown"),
            "raw_type": raw_type,
            "version": hex(read_u32(stream, "chunk version")),
            "offset": read_u32(stream, "chunk offset"),
            "chunk_id": read_u32(stream, "chunk id")}


def get_chunk(chunk_type, byte_data, offset):
    parser = CHUNK_PARSERS.get(chunk_type)
    if parser is None:
        return None
    return parser(byte_data, offset)


def read_vertices(stream, vertices_count):
    position = []
    normal = []

    for i in range(vertices_count):
        position.append([read_f32(stream, "vertex x") / 100,
                         read_f32(stream, "vertex y") / 100,
                         read_f32(stream, "vertex z") / 100])
        normal.append([read_f32(stream, "normal x"),
                       read_f32(stream, "normal y"),
                       read_f32(stream, "normal z")])

    return {"position": position,
            "normal": normal}


def read_faces(stream, vertices_count):
    fp = []
    mat = []
    smoothing_group = []
    for i in range(vertices_count):
        fp.append([read_u32(stream, "face vertex 0"),
                   read_u32(stream, "face vertex 1"),
                   read_u32(stream, "face vertex 2")])

        mat.append(read_u32(stream, "face material"))

        smoothing_group.append(read_u32(stream, "face smoothing group"))

    return {"v": fp,
            "material": mat,
            "smoothing_group": smoothing_group}


def read_uvs(stream, vertices_count):
    uv = []
    for i in range(vertices_count):
        uv.append([read_f32(stream, "uv u"),
                   read_f32(stream, "uv v")])

    return {"uvs": uv}


def read_uvfaces(stream, vertices_count):
    uv = []
    for i in range(vertices_count):
        uv.append([read_u32(stream, "face uv 0"),
                   read_u32(stream, "face uv 1"),
                   read_u32(stream, "face uv 2")])

    return {"face_uvs": uv}


def read_string(stream):
    string_val = ''.join(iter(lambda: stream.read(1).decode('ascii'), '\x00'))
    return string_val


def read_string_per(stream):
    str_ = ''
    nums = 0
    for i in range(128):
        char = stream.read(1)
        nums = nums + 1
        if char == b'\x00':
            break
        try:
            str_ = str_ + char.decode('utf-8')
        except UnicodeDecodeError:
            continue

    stream.read(128 - nums)

    return str_


def read_array(stream, size):
    list_ = []
    for i in range(size):
        list_.append(read_f32(stream, "float array"))
    return list_


def read_matrix44(m_list):
    return (
        (m_list[0], m_list[1], m_list[2], m_list[3]),
        (m_list[4], m_list[5], m_list[6], m_list[7]),
        (m_list[8], m_list[9], m_list[10], m_list[11]),
        (m_list[12] / 100, m_list[13] / 100, m_list[14] / 100, m_list[15]),
    )


def check_if_not_null(stream, size):
    for i in range(size):
        short_byte = int.from_bytes(_read_exact(stream, 2, "reserved u16"), byteorder='little')
        if short_byte != 0:
            _emit_parser_event(
                "material_reserved_nonzero",
                CATEGORY_MATERIAL,
                context="mtl_type_2_padding",
                detail={"value": short_byte, "index": i},
            )


def check_for_null(stream, size, chunk_type):
    for i in range(size):
        if _read_exact(stream, 1, "reserved byte") != b'\x00':
            _emit_parser_event(
                "unsupported_chunk_padding_nonzero",
                _chunk_category(chunk_type),
                context=chunk_type,
                detail={"index": i},
            )


def check_for_null_textures(stream, size, chunk_type):
    for i in range(size):
        temp = _read_exact(stream, 1, "texture reserved byte")
        if temp != b'\x00' and temp != b'\xff':
            _emit_parser_event(
                "material_texture_padding_nonzero",
                CATEGORY_TEXTURE,
                context=chunk_type,
                detail={"index": i, "value_hex": temp.hex()},
            )


def de_bi_op(mtl_flags):
    values = {"wire": 0,
              "two_sided": 0,
              "facemap": 0,
              "faceted": 0,
              "additive": 0,
              "substractive": 0,
              "cry_shader": 0,
              "physicalize": 0,
              "additive_decal": 0,
              "use_glossiness": 0}

    if mtl_flags >= 512:
        values["use_glossiness"] = 1
        mtl_flags = mtl_flags - 512

    if mtl_flags >= 256:
        values["additive_decal"] = 1
        mtl_flags = mtl_flags - 256

    if mtl_flags >= 128:
        values["physicalize"] = 1
        mtl_flags = mtl_flags - 128

    if mtl_flags >= 64:
        values["cry_shader"] = 1
        mtl_flags = mtl_flags - 64

    if mtl_flags >= 32:
        values["substractive"] = 1
        mtl_flags = mtl_flags - 32

    if mtl_flags >= 16:
        values["additive"] = 1
        mtl_flags = mtl_flags - 16

    if mtl_flags >= 8:
        values["faceted"] = 1
        mtl_flags = mtl_flags - 8

    if mtl_flags >= 4:
        values["facemap"] = 1
        mtl_flags = mtl_flags - 4

    if mtl_flags >= 2:
        values["two_sided"] = 1
        mtl_flags = mtl_flags - 2

    if mtl_flags >= 1:
        values["wire"] = 1

    return values

# Световые эффекты (нихуя не понятно

def build_material_semantics(material):
    name = str(material.get("name") or "")
    flags = material.get("mtl_flag") if isinstance(material.get("mtl_flag"), dict) else {}
    shader_name, material_template, display_name = _split_material_name_semantics(name)

    blend_mode = "unknown_not_decoded"
    alpha_mode = "unknown_not_decoded"
    sources = []

    if flags.get("additive"):
        blend_mode = "additive"
        sources.append("mtl_flag.additive")
    elif flags.get("additive_decal"):
        blend_mode = "additive_decal"
        sources.append("mtl_flag.additive_decal")
    elif flags.get("substractive"):
        blend_mode = "subtractive"
        sources.append("mtl_flag.substractive")

    opacity_texture = material.get("texture_opacity")
    if isinstance(opacity_texture, dict) and (
        opacity_texture.get("long_name") or opacity_texture.get("name")
    ):
        alpha_mode = "texture_opacity"
        if blend_mode == "unknown_not_decoded":
            blend_mode = "alpha_blend"
        sources.append("texture_opacity")

    opacity = material.get("opacity")
    if isinstance(opacity, (int, float)) and opacity < 1.0:
        alpha_mode = "scalar_opacity"
        if blend_mode == "unknown_not_decoded":
            blend_mode = "alpha_blend"
        sources.append("opacity")

    self_illum = material.get("self_illum")
    emissive = bool(isinstance(self_illum, (int, float)) and self_illum > 0.0)
    if emissive:
        sources.append("self_illum")

    if shader_name:
        sources.append("material_name.shader")
    if material_template:
        sources.append("material_name.template")

    return {
        "display_name": display_name,
        "shader_name": shader_name,
        "material_template": material_template,
        "blend_mode": blend_mode,
        "alpha_mode": alpha_mode,
        "emissive": emissive,
        "self_illum": self_illum,
        "two_sided": bool(flags.get("two_sided")),
        "physicalized": bool(flags.get("physicalize")),
        "cry_shader": bool(flags.get("cry_shader")),
        "material_flags_raw": material.get("mtl_flag_raw"),
        "source": tuple(sources) if sources else ("parsed_material_defaults",),
    }


def _split_material_name_semantics(name):
    display_name = name
    shader_name = ""
    material_template = ""
    if "/" in display_name:
        display_name, material_template = display_name.rsplit("/", 1)
    if "(" in display_name and ")" in display_name:
        before, rest = display_name.split("(", 1)
        shader_name = rest.split(")", 1)[0].strip()
        display_name = before.strip()
    return shader_name, material_template.strip(), display_name.strip()

def get_mesh_subsets_chunk(stream, offset):
    stream.seek(offset)

    header = get_header(stream)

    return {"header": header}

def get_mesh_chunk(stream, offset):
    mesh_chunk_dict = {}

    stream.seek(offset)

    header = get_header(stream)
    has_vertex_weights = read_bool8(stream, "mesh has vertex weights")
    has_vertex_colors = read_bool8(stream, "mesh has vertex colors")
    reserved_1 = read_ascii_bytes(stream, 2, "mesh reserved")
    num_vertices = read_u32(stream, "mesh num vertices")
    num_uvs = read_u32(stream, "mesh num uvs")
    num_faces = read_u32(stream, "mesh num faces")
    vert_anim = read_u32(stream, "mesh vert anim id")

    vertices = read_vertices(stream, num_vertices)
    faces = read_faces(stream, num_faces)

    if num_uvs > 0:
        uvs = read_uvs(stream, num_uvs)
        uv_faces = read_uvfaces(stream, num_faces)  # как и было, но только при num_uvs>0
    else:
        uvs = {"num_uvs": 0, "uvs": []}
        uv_faces = {"face_uvs": []}

    if has_vertex_colors:
        colors_vertx = []
        for vrt in range(num_vertices):
            colors_vertx.append({"r": read_u8(stream, "vertex color r"),
                                 "g": read_u8(stream, "vertex color g"),
                                 "b": read_u8(stream, "vertex color b")})

    mesh_chunk_dict.update({"header": header})
    mesh_chunk_dict.update({"has_vertex_weights": has_vertex_weights})
    mesh_chunk_dict.update({"has_vertex_colors": has_vertex_colors})
    mesh_chunk_dict.update({"reserved_1": reserved_1})
    mesh_chunk_dict.update({"num_vertices": num_vertices})
    mesh_chunk_dict.update({"num_uvs": num_uvs})
    mesh_chunk_dict.update({"num_faces": num_faces})
    mesh_chunk_dict.update({"vert_anim": vert_anim})
    mesh_chunk_dict.update({"vertices": vertices})
    mesh_chunk_dict.update({"faces": faces})
    mesh_chunk_dict.update({"uvs": uvs})
    mesh_chunk_dict.update({"uv_faces": uv_faces})

    return mesh_chunk_dict


def get_source_info_chunk(stream, offset):
    stream.seek(offset)
    return {"header": "",
            "source_file": read_string(stream),
            "date": read_string(stream),
            "author": read_string(stream)}


def get_timing_chunk(stream, offset):
    stream.seek(offset)
    return {"header": get_header(stream),
            "secs_per_tick": read_f32(stream, "timing secs per tick"),
            "ticks_per_frame": read_u32(stream, "timing ticks per frame"),
            "global_range": {"name": read_ascii_bytes(stream, 32, "timing range name").rstrip('\x00'),
                             "start": read_u32(stream, "timing range start"),
                             "end": read_u32(stream, "timing range end")},
            "num_sub_ranges": read_u32(stream, "timing sub range count")}


def get_node_chunk(stream, offset):
    node_dict = {}
    children_ids = []

    stream.seek(offset)

    header = get_header(stream)
    node_dict.update({"header": header})

    node_name = read_ascii_bytes(stream, 64, "node name").rstrip('\x00')
    node_dict.update({"name": node_name})

    node_dict.update({"object_id": read_u32(stream, "node object id")})  # Mesh or Helper
    node_dict.update({"parent_id": read_u32(stream, "node parent id")})

    num_children = read_u32(stream, "node children count")

    node_dict.update({"num_children": num_children})
    node_dict.update({"material_id": read_u32(stream, "node material id")})
    is_group_head = read_u8(stream, "node is group head")
    node_dict.update({"is_group_head": is_group_head})
    is_group_member = read_u8(stream, "node is group member")
    node_dict.update({"is_group_member": is_group_member})

    reserved_1 = read_ascii_bytes(stream, 2, "node reserved")
    node_dict.update({"reserved_1": reserved_1})

    node_dict.update({"transform": read_array(stream, 16)})

    position = {"x": read_f32(stream, "node position x") / 100,
                "y": read_f32(stream, "node position y") / 100,
                "z": read_f32(stream, "node position z") / 100}
    node_dict.update({"position": position})

    rotation = {"x": read_f32(stream, "node rotation x"),
                "y": read_f32(stream, "node rotation y"),
                "z": read_f32(stream, "node rotation z"),
                "w": read_f32(stream, "node rotation w")}
    node_dict.update({"rotation": rotation})

    scale = {"x": read_f32(stream, "node scale x"),
             "y": read_f32(stream, "node scale y"),
             "z": read_f32(stream, "node scale z")}

    node_dict.update({"scale": scale})

    pos_ctrl_id = read_u32(stream, "node position controller id")
    rot_ctrl_id = read_u32(stream, "node rotation controller id")
    scl_ctrl_id = read_u32(stream, "node scale controller id")

    node_dict.update({"pos_ctrl_id": pos_ctrl_id})
    node_dict.update({"rot_ctrl_id": rot_ctrl_id})
    node_dict.update({"scl_ctrl_id": scl_ctrl_id})

    string_len = read_u32(stream, "node property string length")
    strings_properties = read_ascii_bytes(stream, string_len, "node property string")
    strings_properties = strings_properties.split("\r\n")

    props = {}

    # for prop in strings_properties:
    #     if prop != "":
    #         pr = prop.split(" = ")
    #         props.update({pr[0]: pr[1] if pr[1] != '<None>' else None})

    node_dict.update({"strings_properties": props})

    if num_children > 0:
        for i in range(num_children):
            children_ids.append(read_u32(stream, "node child id"))

    return node_dict


def get_helper_chunk(stream, offset):
    stream.seek(offset)
    header = get_header(stream)
    helper_type = read_u32(stream, "helper type")
    position = {"x": read_f32(stream, "helper position x") / 100,
                "y": read_f32(stream, "helper position y") / 100,
                "z": read_f32(stream, "helper position z") / 100}
    return {"header": header,
            "helper_type": helper_type,
            "position": position}


def get_texture(stream, text_txt):
    texture_dict = {}
    ignoring_texture = ['default_normalmap_ddn','mrt_materialidmap']
    long_name = read_ascii_bytes(stream, 128, "texture path").rstrip('\x00')
    name = long_name.split("\\")[-1]
    if (len(long_name) > 0 and text_txt != ""
            and 'default_normalmap_ddn' not in name
            and 'mrt_materialidmap' not in name):
        _emit_parser_event(
            "unused_material_texture_field",
            CATEGORY_TEXTURE,
            context=text_txt,
            detail={"field": text_txt, "texture": long_name},
        )

    texture_dict.update({"long_name": long_name})
    texture_dict.update({"name": name})

    # 80
    texture_type = read_u8(stream, "texture type")
    # "0": "NORMAL"
    # "1": "ENVIRONMENT"
    # "2": "SCREENENVIRONMENT"
    # "3": "CUBIC"
    # "4": "AUTOCUBIC"

    texture_dict.update({"texture_type": texture_type})

    no_mip_map = read_u8(stream, "texture no mip map")
    if no_mip_map > 0:
        _emit_parser_event(
            "material_texture_no_mip_map",
            CATEGORY_TEXTURE,
            context=text_txt,
            detail={"field": text_txt, "value": no_mip_map, "texture": long_name},
        )

    texture_dict.update({"no_mip_map": no_mip_map})

    amount = read_u8(stream, "texture amount")
    if len(long_name) > 0 and amount != 100:
        _emit_parser_event(
            "material_texture_amount_not_default",
            CATEGORY_TEXTURE,
            context=text_txt,
            detail={"field": text_txt, "amount": amount, "texture": long_name},
        )

    texture_dict.update({"amount": amount})

    check_for_null(stream, 32, "TextureMap reserved1-2")
    # self.reserved1 = int.from_bytes(stream.read(1), byteorder='little')
    # self.reserved2 = int.from_bytes(stream.read(31), byteorder='little')

    u_tile = read_bool8(stream, "texture u tile")
    u_mirror = read_bool8(stream, "texture u mirror")
    v_tile = read_bool8(stream, "texture v tile")
    v_mirror = read_bool8(stream, "texture v mirror")

    reserved_3 = read_u8(stream, "texture reserved 3")
    if reserved_3 > 0:
        _emit_parser_event(
            "material_texture_reserved_nonzero",
            CATEGORY_TEXTURE,
            context=text_txt,
            detail={"field": text_txt, "value": reserved_3, "texture": long_name},
        )

    ref_update = read_u32(stream, "texture ref update")
    ref_size = read_u32(stream, "texture ref size")
    ref_blur = read_f32(stream, "texture ref blur")

    # Texture position values
    u_off_val = read_f32(stream, "texture u offset")
    u_scl_val = read_f32(stream, "texture u scale")
    u_rot_val = read_f32(stream, "texture u rotation")
    v_off_val = read_f32(stream, "texture v offset")
    v_scl_val = read_f32(stream, "texture v scale")
    v_rot_val = read_f32(stream, "texture v rotation")
    w_rot_val = read_f32(stream, "texture w rotation")
    transform_values = {
        "u_off_val": u_off_val,
        "u_scl_val": u_scl_val,
        "u_rot_val": u_rot_val,
        "v_off_val": v_off_val,
        "v_scl_val": v_scl_val,
        "v_rot_val": v_rot_val,
        "w_rot_val": w_rot_val,
    }
    non_default_transform_values = {
        key: value
        for key, value in transform_values.items()
        if (
            (key in {"u_scl_val", "v_scl_val"} and value not in (0.0, 1.0))
            or (key not in {"u_scl_val", "v_scl_val"} and value > 0)
        )
    }
    if non_default_transform_values:
        _emit_parser_event(
            "material_texture_transform_not_default",
            CATEGORY_TEXTURE,
            context=text_txt,
            detail={
                "field": text_txt,
                "texture": long_name,
                "values": non_default_transform_values,
            },
        )
    # 80
    u_off_ctrl = read_u32(stream, "texture u offset controller")
    u_scl_ctrl = read_u32(stream, "texture u scale controller")
    u_rot_ctrl = read_u32(stream, "texture u rotation controller")
    v_off_ctrl = read_u32(stream, "texture v offset controller")
    v_scl_ctrl = read_u32(stream, "texture v scale controller")
    v_rot_ctrl = read_u32(stream, "texture v rotation controller")
    w_rot_ctrl = read_u32(stream, "texture w rotation controller")

    texture_dict.update({"u_tile": u_tile})
    texture_dict.update({"u_mirror": u_mirror})
    texture_dict.update({"v_tile": v_tile})
    texture_dict.update({"v_mirror": v_mirror})
    texture_dict.update({"ref_update": ref_update})
    texture_dict.update({"ref_size": ref_size})
    texture_dict.update({"ref_blur": ref_blur})
    texture_dict.update({"u_off_val": u_off_val})
    texture_dict.update({"u_scl_val": u_scl_val})
    texture_dict.update({"u_rot_val": u_rot_val})
    texture_dict.update({"v_off_val": v_off_val})
    texture_dict.update({"v_scl_val": v_scl_val})
    texture_dict.update({"v_rot_val": v_rot_val})
    texture_dict.update({"w_rot_val": w_rot_val})

    return texture_dict


def get_mtl_chunk(stream, offset):
    mtl_dict = {}
    stream.seek(offset)

    header = get_header(stream)
    mtl_dict.update({"header": header})

    name = read_string_per(stream)
    mtl_dict.update({"name": name})

    mtl_type = read_u32(stream, "material type")
    mtl_dict.update({"mtl_type": mtl_type})
    if mtl_type == 1:
        diffuse_color = {"r": read_u8(stream, "material diffuse r"),
                         "g": read_u8(stream, "material diffuse g"),
                         "b": read_u8(stream, "material diffuse b")}
        mtl_dict.update({"diffuse_color": diffuse_color})

        specular_color = {"r": read_u8(stream, "material specular r"),
                          "g": read_u8(stream, "material specular g"),
                          "b": read_u8(stream, "material specular b")}
        mtl_dict.update({"specular_color": specular_color})

        ambient_color = {"r": read_u8(stream, "material ambient r"),
                         "g": read_u8(stream, "material ambient g"),
                         "b": read_u8(stream, "material ambient b")}
        mtl_dict.update({"ambient_color": ambient_color})

        check_for_null(stream, 3, "MtlChunk")  # Unknown.

        specular_level = read_f32(stream, "material specular level")
        mtl_dict.update({"specular_level": specular_level})

        specular_shininess = read_f32(stream, "material specular shininess")
        mtl_dict.update({"specular_shininess": specular_shininess})

        self_illum = read_f32(stream, "material self illum")
        mtl_dict.update({"self_illum": self_illum})
        if self_illum > 0:
            _emit_parser_event(
                "material_self_illum_nonzero",
                CATEGORY_MATERIAL,
                context=name,
                detail={"material": name, "self_illum": self_illum},
            )

        opacity = read_f32(stream, "material opacity")
        mtl_dict.update({"opacity": opacity})

        check_for_null(stream, 8, "MtlChunk2")  # Unknown.

        texture_ambient = get_texture(stream, "texture_ambient")
        mtl_dict.update({"texture_ambient": texture_ambient})

        mtl_dict.update({"texture_diffuse": get_texture(stream, "")})

        texture_specular = get_texture(stream, "texture_specular")
        mtl_dict.update({"texture_specular": texture_specular})

        texture_opacity = get_texture(stream, "texture_opacity")
        mtl_dict.update({"texture_opacity": texture_opacity})

        # выдавливание есть в Bu_ru_StainedGlassWall_02b.cgf
        texture_bump = get_texture(stream, "")
        mtl_dict.update({"texture_bump": texture_bump})

        texture_gloss = get_texture(stream, "texture_gloss")
        mtl_dict.update({"texture_gloss": texture_gloss})

        # Какое-то свечение текстуры. Пример: bu_ru_wall_01a_02_matid.dds
        texture_filter = get_texture(stream, "")
        mtl_dict.update({"texture_filter": texture_filter})

        # self.texture_cubemap = TextureMap(stream)

        texture_reflection = get_texture(stream, "texture_reflection")
        mtl_dict.update({"texture_reflection": texture_reflection})

        texture_subsurf = get_texture(stream, "texture_subsurf")
        mtl_dict.update({"texture_subsurf": texture_subsurf})

        texture_detail = get_texture(stream, "texture_detail")
        mtl_dict.update({"texture_detail": texture_detail})

    elif mtl_type == 2:
        multi_mtl_counts = read_u32(stream, "multi material count")
        mtl_dict.update({"multi_mtl_counts": multi_mtl_counts})
        check_if_not_null(stream, 1196)
    else:
        _emit_parser_event(
            "unknown_material_type",
            CATEGORY_MATERIAL,
            context=str(mtl_type),
            detail={"mtl_type": mtl_type},
        )

    mtl_flag_raw = read_u32(stream, "material flags")
    mtl_dict.update({"mtl_flag_raw": mtl_flag_raw})
    mtl_flag = de_bi_op(mtl_flag_raw)
    mtl_dict.update({"mtl_flag": mtl_flag})
    mtl_dict.update({"mtl_collide": read_f32(stream, "material collide")})

    dyn_static_friction = read_f32(stream, "material static friction")
    dyn_sliding_friction = read_f32(stream, "material sliding friction")
    mtl_dict.update({"dyn_static_friction": dyn_static_friction})
    mtl_dict.update({"dyn_sliding_friction": dyn_sliding_friction})

    if mtl_type == 2:
        multi_mtl_ids = []
        for i in range(multi_mtl_counts):
            multi_mtl_ids.append(read_u32(stream, "multi material id"))
        mtl_dict.update({"multi_mtl_ids": multi_mtl_ids})

    mtl_dict.update({"material_semantics": build_material_semantics(mtl_dict)})

    return mtl_dict


CHUNK_PARSERS = {
    "Mesh": get_mesh_chunk,
    "MeshSubsets": get_mesh_subsets_chunk,
    "SourceInfo": get_source_info_chunk,
    "Timing": get_timing_chunk,
    "Node": get_node_chunk,
    "Mtl": get_mtl_chunk,
    "Helper": get_helper_chunk,
}


def check_chunk_remains(stream, next_chunk_pos, chunk_type):
    current_poss = stream.tell()
    if current_poss != next_chunk_pos and chunk_type != "MeshSubsets" and chunk_type != "SourceInfo":
        if chunk_type == "Node":
            check_for_null(stream, next_chunk_pos - current_poss, chunk_type)


def is_physical_node(node, all_mats):
    # быстро фикс lf4
    if node.get("material") is None:
        return False
    if node["material"]["mtl_collide"] == 1.0:
        return True
    elif node["material"].get("multi_mtl_ids") is not None:
        phys_mat_counts = 0
        for mlt_id in node["material"]["multi_mtl_ids"]:
            for ml in all_mats:
                if ml["header"]["chunk_id"] == mlt_id:
                    if ml["mtl_collide"] == 1.0:
                        phys_mat_counts = phys_mat_counts + 1
        if len(node["material"]["multi_mtl_ids"]) == phys_mat_counts:
            return True
    return False


def get_cgf(file_stream, diagnostics=False, file_path=None):
    collector = _new_diagnostics_collector(file_stream, diagnostics, file_path)
    with _DiagnosticsScope(collector):
        return _parse_cgf(file_stream, collector)


def _parse_cgf(file_stream, collector):
    cgf_dict = {}

    signature = ''.join(iter(lambda: file_stream.read(1).decode('ascii'), '\x00'))
    cgf_dict.update({"signature": signature})

    _read_exact(file_stream, 1, "signature terminator")  # null symbol

    type_of_file = hex(read_u32(file_stream, "cgf file type"))
    if type_of_file == "0xffff0001":
        return _finish_with_error({"error": "Animation data"}, collector, "Animation data")
    elif type_of_file != "0xffff0000":
        return _finish_with_error({"error": "Wrong filetype"}, collector, "Wrong filetype")

    cgf_version = hex(read_u32(file_stream, "cgf version"))
    cgf_dict.update({"version": cgf_version})

    offset = read_u32(file_stream, "chunk table offset")

    # Переходим к таблице данных чанках
    file_stream.seek(offset)

    num_of_chunks = read_u32(file_stream, "chunk count")
    chunk_headers = []
    for i in range(num_of_chunks):
        header = get_header(file_stream)
        chunk_headers.append(header)
        if collector is not None:
            collector.add_chunk(header)
            if header["chunk_type"] == "Unknown":
                collector.add_event(
                    "unknown_chunk_type",
                    CATEGORY_UNKNOWN,
                    context=f"chunk_id={header['chunk_id']}",
                    detail=header,
                )
    if collector is not None:
        _record_raw_controller_chunks(collector, file_stream, chunk_headers)

    nodes = {}
    mtls_chunk = {}
    meshs_chunk = {}
    helpers_chunk = {}

    mlts_ = []

    cgf_dict = {"nodes": {}, "all_nodes": {}}

    file_stream.seek(0)
    for chunk_data in chunk_headers:
        before_chunk = file_stream.tell()
        chunk = get_chunk(chunk_data["chunk_type"], file_stream, chunk_data["offset"])
        if collector is not None and chunk is None:
            collector.add_event(
                "unsupported_chunk_parser",
                _chunk_category(chunk_data["chunk_type"]),
                context=chunk_data["chunk_type"],
                detail=chunk_data,
            )

        if chunk_data["chunk_id"] < (len(chunk_headers) - 1):
            check_chunk_remains(file_stream, chunk_headers[int(chunk_data["chunk_id"] + 1)]["offset"],
                                chunk_data["chunk_type"])

        if collector is not None:
            _record_chunk_unread_range(collector, file_stream, chunk_data, chunk_headers, before_chunk)

        if chunk_data["chunk_type"] == "Node":
            nodes.update({chunk_data["chunk_id"]: chunk})
        elif chunk_data["chunk_type"] == "Mtl":
            mtls_chunk.update({chunk_data["chunk_id"]: chunk})
        elif chunk_data["chunk_type"] == "Mesh":
            meshs_chunk.update({chunk_data["chunk_id"]: chunk})
        elif chunk_data["chunk_type"] == "Helper":
            helpers_chunk.update({chunk_data["chunk_id"]: chunk})
        else:
            cgf_dict.update({chunk_data["chunk_type"]: chunk})

    for node in nodes.values():
        if meshs_chunk.get(node["object_id"]) is not None:
            node.update({"mesh": meshs_chunk[node["object_id"]]})
            node.pop("object_id")
        elif helpers_chunk.get(node["object_id"]) is not None:
            node.update({"helper": helpers_chunk[node["object_id"]]})
            node.pop("object_id")

        if node.get("mesh") is not None:
            cgf_dict["nodes"].update({node["header"]["chunk_id"]: node})

        cgf_dict["all_nodes"].update({node["header"]["chunk_id"]: node})

        # Если у ноды есть материал, добавляет его к ноде.
        if node["material_id"] != 4294967295:
            nodes_mat = mtls_chunk[node["material_id"]]
            node.update({"material": nodes_mat})

    # Собираем все материалы в отдельный список
    for mlt in mtls_chunk.values():
        if mlt.get("multi_mtl_ids") is None:
            mlts_.append(mlt)

    cgf_dict.update({"all_materials": mlts_})

    if collector is not None:
        _analyze_diagnostics(collector, cgf_dict, nodes, mtls_chunk)
        collector.parser_success = True
        cgf_dict["_diagnostics"] = collector.to_dict(cgf_dict)

    return cgf_dict


def _new_diagnostics_collector(file_stream, diagnostics, file_path):
    if not diagnostics:
        return None
    collector = CgfDiagnosticsCollector(file_path=str(file_path) if file_path else None)
    try:
        current = file_stream.tell()
        file_stream.seek(0, os.SEEK_END)
        collector.file_size = file_stream.tell()
        file_stream.seek(current)
    except (AttributeError, OSError):
        collector.file_size = None
    return collector


def _finish_with_error(cgf_dict, collector, error):
    if collector is not None:
        collector.parser_error = error
        cgf_dict["_diagnostics"] = collector.to_dict(cgf_dict)
    return cgf_dict


def _record_chunk_unread_range(collector, stream, chunk_data, chunk_headers, before_chunk):
    current = stream.tell()
    expected_end = _next_chunk_offset(chunk_data, chunk_headers)
    if expected_end is not None and current < expected_end:
        collector.add_unread_range(
            current,
            expected_end,
            chunk_data["chunk_type"],
            "chunk_parser_stopped_before_next_chunk",
        )
    elif expected_end is not None and current > expected_end:
        collector.add_event(
            "seek_beyond_expected_boundary",
            _chunk_category(chunk_data["chunk_type"]),
            context=chunk_data["chunk_type"],
            detail={
                "chunk_id": chunk_data.get("chunk_id"),
                "offset_before": before_chunk,
                "current": current,
                "expected_end": expected_end,
            },
        )


def _record_raw_controller_chunks(collector, stream, chunk_headers):
    current = stream.tell()
    for chunk_data in chunk_headers:
        if chunk_data["chunk_type"] not in RAW_CONTROLLER_CHUNK_TYPES:
            continue
        offset = int(chunk_data["offset"])
        expected_end = _next_chunk_offset(chunk_data, chunk_headers) or collector.file_size
        if expected_end is None:
            expected_end = offset
        payload_offset = min(offset + 16, expected_end)
        payload_size = max(0, int(expected_end) - payload_offset)
        stream.seek(payload_offset)
        payload = stream.read(payload_size)
        collector.add_controller_chunk(
            chunk_data,
            payload_offset=payload_offset,
            payload_size=payload_size,
            prefix_hex=payload[:16].hex(),
            nearby_strings=nearby_ascii_strings(payload),
            decoded=_decode_controller_payload(chunk_data, payload),
        )
    stream.seek(current)


def _decode_controller_payload(header, payload):
    if header.get("chunk_type") != "Controller":
        return None
    if len(payload) < 16:
        return {
            "decoded": False,
            "decode_reason": "payload_too_short",
            "controller_component": "unknown",
        }

    controller_type, key_count, flags, controller_id = struct.unpack_from("<IIII", payload, 0)
    component = _controller_component(controller_type)
    decoded = {
        "controller_type": int(controller_type),
        "controller_id": int(controller_id),
        "controller_key_count": int(key_count),
        "controller_flags": int(flags),
        "controller_component": component,
        "decoded": False,
    }
    if key_count < 1:
        decoded["decode_reason"] = "no_keys"
        return decoded

    data_size = len(payload) - 16
    if data_size <= 0 or data_size % key_count != 0:
        decoded["decode_reason"] = "unsupported_key_stride"
        decoded["controller_key_stride"] = None
        return decoded

    stride = data_size // key_count
    decoded["controller_key_stride"] = int(stride)
    if controller_type == 10:
        return _decode_rotation_axis_angle_controller(payload, decoded, key_count, stride)
    if controller_type in (6, 9):
        return _decode_vector3_controller(payload, decoded, key_count, stride)

    decoded["decode_reason"] = "unsupported_controller_type"
    return decoded


def _controller_component(controller_type):
    if controller_type == 10:
        return "rotation_axis_angle"
    if controller_type == 9:
        return "position_vector3"
    if controller_type == 6:
        return "scale_vector3"
    return "unknown"


def _finite_values(values):
    return all(math.isfinite(float(value)) for value in values)


def _decode_rotation_axis_angle_controller(payload, decoded, key_count, stride):
    if stride != 40:
        decoded["decode_reason"] = "unsupported_rotation_key_stride"
        return decoded

    keys = []
    valid = True
    for index in range(key_count):
        offset = 16 + index * stride
        time_ticks = struct.unpack_from("<I", payload, offset)[0]
        axis_x, axis_y, axis_z, angle = struct.unpack_from("<ffff", payload, offset + 4)
        axis_length = math.sqrt(axis_x * axis_x + axis_y * axis_y + axis_z * axis_z)
        finite = _finite_values((axis_x, axis_y, axis_z, angle))
        if not finite or (axis_length <= 0.0 and abs(angle) > 1.0e-6):
            valid = False
        keys.append(
            {
                "time_ticks": int(time_ticks),
                "axis": (float(axis_x), float(axis_y), float(axis_z)),
                "axis_length": float(axis_length),
                "angle_radians": float(angle),
            }
        )

    decoded["controller_keys"] = tuple(keys)
    decoded["decoded"] = bool(valid)
    decoded["decode_reason"] = "decoded" if valid else "invalid_rotation_axis_angle"
    decoded["confidence"] = "high" if valid else "low"
    return decoded


def _decode_vector3_controller(payload, decoded, key_count, stride):
    if stride < 16 or stride % 4 != 0:
        decoded["decode_reason"] = "unsupported_vector3_key_stride"
        return decoded

    keys = []
    valid = True
    for index in range(key_count):
        offset = 16 + index * stride
        time_ticks = struct.unpack_from("<I", payload, offset)[0]
        value = struct.unpack_from("<fff", payload, offset + 4)
        if not _finite_values(value):
            valid = False
        keys.append(
            {
                "time_ticks": int(time_ticks),
                "value": tuple(float(component) for component in value),
            }
        )
    decoded["controller_keys"] = tuple(keys)
    decoded["decoded"] = bool(valid)
    decoded["decode_reason"] = "decoded" if valid else "invalid_vector3_values"
    decoded["confidence"] = "medium" if valid else "low"
    return decoded


def _next_chunk_offset(chunk_data, chunk_headers):
    current_offset = chunk_data.get("offset")
    later_offsets = sorted(
        header["offset"]
        for header in chunk_headers
        if header.get("offset") is not None and header["offset"] > current_offset
    )
    return later_offsets[0] if later_offsets else None


def _analyze_diagnostics(collector, parsed, nodes, mtls_chunk):
    material_ids = set(mtls_chunk)
    material_names = {}
    for material_id, material in mtls_chunk.items():
        if material is None:
            continue
        material_name = material.get("name")
        if material_name:
            material_names.setdefault(material_name, []).append(material_id)
        if _mtl_collide_value(material) > 0 or "nodraw" in str(material_name).lower():
            collector.add_event(
                "collision_or_nodraw_material",
                CATEGORY_COLLISION_NODRAW,
                context=str(material_name),
                detail={"material_id": material_id},
            )
        for key, value in material.items():
            if key.startswith("texture_") and isinstance(value, dict):
                long_name = value.get("long_name")
                texture_name = value.get("name")
                if long_name and key != "texture_diffuse":
                    collector.add_event(
                        "non_diffuse_texture_field_present",
                        CATEGORY_TEXTURE,
                        context=key,
                        detail={"material": material_name, "texture": long_name},
                    )
                if texture_name and not long_name:
                    collector.add_event(
                        "texture_name_without_long_name",
                        CATEGORY_TEXTURE,
                        context=key,
                        detail={"material": material_name, "texture": texture_name},
                    )
    for material_name, ids in material_names.items():
        if len(ids) > 1:
            collector.add_event(
                "duplicate_material_name",
                CATEGORY_MATERIAL,
                context=str(material_name),
                detail={"material_ids": tuple(ids)},
            )

    for node_id, node in nodes.items():
        if node is None:
            continue
        material_id = node.get("material_id")
        if material_id != 4294967295 and material_id not in material_ids:
            collector.add_event(
                "invalid_node_material_ref",
                CATEGORY_MATERIAL,
                context=str(node.get("name")),
                detail={"node_id": node_id, "material_id": material_id},
            )
        if node.get("mesh") is None and node.get("helper") is None:
            collector.add_event(
                "node_transform_without_mesh_or_helper",
                CATEGORY_TRANSFORM,
                context=str(node.get("name")),
                detail={"node_id": node_id},
            )
        if node.get("helper") is not None:
            collector.add_event(
                "helper_node_ignored_by_importer",
                CATEGORY_HELPER_DUMMY,
                context=str(node.get("name")),
                detail={"node_id": node_id},
            )
        if node.get("mesh") is not None and material_id == 4294967295:
            collector.add_event(
                "mesh_node_without_material",
                CATEGORY_MATERIAL,
                context=str(node.get("name")),
                detail={"node_id": node_id},
            )
        mesh = node.get("mesh")
        material = node.get("material")
        if mesh is not None and isinstance(material, dict):
            has_texture = bool(
                ((material.get("texture_diffuse") or {}).get("name"))
                or ((material.get("texture_diffuse") or {}).get("long_name"))
            )
            if has_texture and not mesh.get("uvs", {}).get("uvs"):
                collector.add_event(
                    "textured_material_without_uvs",
                    CATEGORY_GEOMETRY,
                    context=str(node.get("name")),
                    detail={"node_id": node_id},
                )
            if not has_texture and _mtl_collide_value(material) <= 0:
                collector.add_event(
                    "visual_material_without_diffuse_texture",
                    CATEGORY_TEXTURE,
                    context=str(material.get("name")),
                    detail={"node_id": node_id},
                )

    for chunk_type in parsed:
        if chunk_type == "Light":
            collector.add_event("light_chunk_present", CATEGORY_LIGHT, context="Light")
        elif chunk_type in ("VertAnim", "BoneAnim", "Controller", "Timing"):
            collector.add_event("animation_chunk_present", CATEGORY_ANIMATION, context=chunk_type)


def _chunk_category(chunk_type):
    if chunk_type in ("Mesh", "MeshSubsets", "PatchMesh", "MeshPhysicsData"):
        return CATEGORY_GEOMETRY
    if chunk_type in ("Mtl", "MtlList", "MtlName"):
        return CATEGORY_MATERIAL
    if chunk_type == "Helper":
        return CATEGORY_HELPER_DUMMY
    if chunk_type == "Light":
        return CATEGORY_LIGHT
    if chunk_type in ("VertAnim", "BoneAnim", "Controller", "Timing"):
        return CATEGORY_ANIMATION
    return CATEGORY_UNKNOWN


def _mtl_collide_value(material):
    try:
        return float(material.get("mtl_collide", 0.0) or 0.0)
    except (TypeError, ValueError):
        return 0.0
