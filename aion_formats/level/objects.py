import struct
from dataclasses import dataclass
from pathlib import Path

from .leveldata import LevelData


OBJECTS_LST_HEADER = 0x10
OBJECTS_LST_RECORD_SIZE = 16


@dataclass(frozen=True)
class ObjectPlacement:
    vegetation_index: int
    vegetation_file: str | None
    raw_position: tuple[int, int, int]
    position: tuple[float, float, float]
    scale: float
    heading_raw: int
    heading_degrees: float
    unknown_byte: int


@dataclass(frozen=True)
class ObjectsList:
    header: int
    placements: tuple[ObjectPlacement, ...]
    trailing_bytes: bytes


def _position_scale(level_data: LevelData) -> float:
    heightmap_x_size = level_data.level_info.heightmap_x_size
    if not heightmap_x_size:
        raise ValueError("LevelData.level_info.heightmap_x_size is required")
    return 32768 / heightmap_x_size


def parse_objects_lst(path: str | Path, level_data: LevelData) -> ObjectsList:
    data = Path(path).read_bytes()
    if len(data) < 4:
        raise ValueError("objects.lst is too short to contain a header")

    header = int.from_bytes(data[:4], byteorder="little")
    if header != OBJECTS_LST_HEADER:
        raise ValueError(f"objects.lst header 0x{header:x} does not match 0x{OBJECTS_LST_HEADER:x}")

    magic = _position_scale(level_data)
    placements = []
    offset = 4

    while offset + OBJECTS_LST_RECORD_SIZE <= len(data):
        record = data[offset : offset + OBJECTS_LST_RECORD_SIZE]
        x_pos = int.from_bytes(record[0:2], "little")
        y_pos = int.from_bytes(record[2:4], "little")
        z_pos = int.from_bytes(record[4:6], "little")
        vegetation_index = int.from_bytes(record[6:7], "little")
        unknown_byte = int.from_bytes(record[7:8], "little")
        scale = struct.unpack("<f", record[8:12])[0]
        heading_raw = int.from_bytes(record[12:16], "little")
        heading_degrees = heading_raw * 360 / 255
        vegetation_file = (
            level_data.vegetation_files[vegetation_index]
            if vegetation_index < len(level_data.vegetation_files)
            else None
        )

        placements.append(
            ObjectPlacement(
                vegetation_index=vegetation_index,
                vegetation_file=vegetation_file,
                raw_position=(x_pos, y_pos, z_pos),
                position=(x_pos / magic, y_pos / magic, z_pos / magic),
                scale=scale,
                heading_raw=heading_raw,
                heading_degrees=heading_degrees,
                unknown_byte=unknown_byte,
            )
        )
        offset += OBJECTS_LST_RECORD_SIZE

    return ObjectsList(
        header=header,
        placements=tuple(placements),
        trailing_bytes=data[offset:],
    )
