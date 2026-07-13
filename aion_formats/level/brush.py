import struct
from dataclasses import dataclass
from pathlib import Path


BRUSH_SIGNATURE = "CRY"
BRUSH_MESH_ENTRY_SIZE = 160


@dataclass(frozen=True)
class BrushMeshEntry:
    index: int
    structure_size: int
    file_name: str
    flags: int
    bounding_box: tuple[float, float, float, float, float, float]


@dataclass(frozen=True)
class BrushNodePlacement:
    index: int
    delimiter_1: int
    node_size: int
    mesh_index: int
    mesh_file_name: str | None
    unknown_id: int
    node_flags: int
    delimiter_2: int
    transform: tuple[float, ...]
    unknown_51: int
    unknown_52: int
    unknown_53: int
    event_type: int
    unknown_6: int
    extra_bytes: bytes


@dataclass(frozen=True)
class BrushList:
    signature: str
    version: int
    mesh_block_size: int
    titles: tuple[str, ...]
    meshes: tuple[BrushMeshEntry, ...]
    nodes: tuple[BrushNodePlacement, ...]
    trailing_bytes: bytes


def _read_exact(data: bytes, offset: int, size: int, label: str) -> tuple[bytes, int]:
    end = offset + size
    if end > len(data):
        raise ValueError(f"brush.lst ended while reading {label}")
    return data[offset:end], end


def _read_uint(data: bytes, offset: int, size: int, label: str) -> tuple[int, int]:
    raw, offset = _read_exact(data, offset, size, label)
    return int.from_bytes(raw, byteorder="little"), offset


def _read_ascii(raw: bytes) -> str:
    return raw.decode("ascii").rstrip("\x00")


def parse_brush_lst(path: str | Path) -> BrushList:
    data = Path(path).read_bytes()
    offset = 0

    signature_raw, offset = _read_exact(data, offset, 3, "signature")
    signature = _read_ascii(signature_raw)
    if signature != BRUSH_SIGNATURE:
        raise ValueError(f"brush.lst signature {signature!r} does not match {BRUSH_SIGNATURE!r}")

    version, offset = _read_uint(data, offset, 4, "version")
    mesh_block_size, offset = _read_uint(data, offset, 4, "mesh block size")
    if mesh_block_size < 16:
        raise ValueError(f"brush.lst mesh block size {mesh_block_size} is smaller than 16")

    titles_count, offset = _read_uint(data, offset, 4, "titles count")
    titles = []
    for title_index in range(titles_count):
        title_size, offset = _read_uint(data, offset, 4, f"title {title_index} size")
        if title_size < 4:
            raise ValueError(f"brush.lst title {title_index} size {title_size} is smaller than 4")
        title_raw, offset = _read_exact(data, offset, title_size - 4, f"title {title_index}")
        titles.append(_read_ascii(title_raw))

    meshes_count, offset = _read_uint(data, offset, 4, "mesh count")
    meshes = []
    for mesh_index in range(meshes_count):
        mesh_raw, offset = _read_exact(data, offset, BRUSH_MESH_ENTRY_SIZE, f"mesh {mesh_index}")
        structure_size = int.from_bytes(mesh_raw[0:4], byteorder="little")
        file_name = _read_ascii(mesh_raw[4:132])
        flags = int.from_bytes(mesh_raw[132:136], byteorder="little")
        bounding_box = struct.unpack("<6f", mesh_raw[136:160])
        meshes.append(
            BrushMeshEntry(
                index=mesh_index,
                structure_size=structure_size,
                file_name=file_name,
                flags=flags,
                bounding_box=bounding_box,
            )
        )

    nodes_count, offset = _read_uint(data, offset, 4, "node count")
    nodes = []
    extra_size = 4 * (mesh_block_size - 16)
    for node_index in range(nodes_count):
        delimiter_1, offset = _read_uint(data, offset, 4, f"node {node_index} delimiter 1")
        node_size, offset = _read_uint(data, offset, 4, f"node {node_index} size")
        mesh_index, offset = _read_uint(data, offset, 4, f"node {node_index} mesh index")
        unknown_id, offset = _read_uint(data, offset, 4, f"node {node_index} unknown id")
        node_flags, offset = _read_uint(data, offset, 4, f"node {node_index} flags")
        delimiter_2, offset = _read_uint(data, offset, 4, f"node {node_index} delimiter 2")
        transform_raw, offset = _read_exact(data, offset, 48, f"node {node_index} transform")
        transform = struct.unpack("<12f", transform_raw)
        unknown_51, offset = _read_uint(data, offset, 8, f"node {node_index} unknown 51")
        unknown_52, offset = _read_uint(data, offset, 4, f"node {node_index} unknown 52")
        unknown_53, offset = _read_uint(data, offset, 4, f"node {node_index} unknown 53")
        event_type, offset = _read_uint(data, offset, 4, f"node {node_index} event type")
        unknown_6, offset = _read_uint(data, offset, 4, f"node {node_index} unknown 6")
        extra_bytes, offset = _read_exact(data, offset, extra_size, f"node {node_index} extra bytes")
        mesh_file_name = meshes[mesh_index].file_name if mesh_index < len(meshes) else None

        nodes.append(
            BrushNodePlacement(
                index=node_index,
                delimiter_1=delimiter_1,
                node_size=node_size,
                mesh_index=mesh_index,
                mesh_file_name=mesh_file_name,
                unknown_id=unknown_id,
                node_flags=node_flags,
                delimiter_2=delimiter_2,
                transform=transform,
                unknown_51=unknown_51,
                unknown_52=unknown_52,
                unknown_53=unknown_53,
                event_type=event_type,
                unknown_6=unknown_6,
                extra_bytes=extra_bytes,
            )
        )

    return BrushList(
        signature=signature,
        version=version,
        mesh_block_size=mesh_block_size,
        titles=tuple(titles),
        meshes=tuple(meshes),
        nodes=tuple(nodes),
        trailing_bytes=data[offset:],
    )
