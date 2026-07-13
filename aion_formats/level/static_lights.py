from dataclasses import asdict, dataclass
import math
import struct
from pathlib import Path


STATIC_LIGHT_RECORD_SIZE = 216
STATIC_LIGHT_NAME_SIZE = 64
STATIC_LIGHT_FLOAT_COUNT = 38


@dataclass(frozen=True)
class StaticDeferredLight:
    index: int
    name: str
    position: tuple[float, float, float]
    color_rgb: tuple[float, float, float]
    intensity: float
    radius: float
    type_or_flags: float
    cone_angle_degrees: float
    rotation_degrees: tuple[float, float, float]
    raw_fields: tuple[float, ...]


@dataclass(frozen=True)
class StaticDeferredLights:
    path: Path
    valid: bool
    reason: str
    magic: str
    version: int
    header_value_a: int
    count: int
    record_size: int
    payload_size: int
    lights: tuple[StaticDeferredLight, ...]


def parse_static_deferred_lights(path: str | Path) -> StaticDeferredLights:
    source_path = Path(path)
    data = source_path.read_bytes()
    header = _parse_header(data)
    if not header["valid"]:
        return StaticDeferredLights(
            path=source_path,
            valid=False,
            reason=header["reason"],
            magic=header.get("magic", ""),
            version=int(header.get("version", 0) or 0),
            header_value_a=int(header.get("header_value_a", 0) or 0),
            count=0,
            record_size=STATIC_LIGHT_RECORD_SIZE,
            payload_size=max(0, len(data) - 16),
            lights=(),
        )

    lights = tuple(
        _parse_record(data, index)
        for index in range(header["count"])
    )
    return StaticDeferredLights(
        path=source_path,
        valid=True,
        reason="",
        magic=header["magic"],
        version=header["version"],
        header_value_a=header["header_value_a"],
        count=header["count"],
        record_size=STATIC_LIGHT_RECORD_SIZE,
        payload_size=header["payload_size"],
        lights=lights,
    )


def static_deferred_lights_to_dict(lights: StaticDeferredLights) -> dict:
    return {
        "path": str(lights.path),
        "valid": lights.valid,
        "reason": lights.reason,
        "magic": lights.magic,
        "version": lights.version,
        "header_value_a": lights.header_value_a,
        "count": lights.count,
        "record_size": lights.record_size,
        "payload_size": lights.payload_size,
        "lights": tuple(asdict(light) for light in lights.lights),
    }


def _parse_header(data: bytes) -> dict:
    if len(data) < 16:
        return {"valid": False, "reason": "file shorter than 16-byte header"}
    magic = data[:4].decode("ascii", errors="ignore")
    version, header_value_a, count = struct.unpack_from("<III", data, 4)
    payload_size = len(data) - 16
    if magic != "AION":
        return {
            "valid": False,
            "reason": f"unexpected magic {magic!r}",
            "magic": magic,
            "version": version,
            "header_value_a": header_value_a,
        }
    if version != 1:
        return {
            "valid": False,
            "reason": f"unexpected version {version}",
            "magic": magic,
            "version": version,
            "header_value_a": header_value_a,
        }
    if count <= 0:
        return {
            "valid": False,
            "reason": "record count is not positive",
            "magic": magic,
            "version": version,
            "header_value_a": header_value_a,
        }
    if payload_size != count * STATIC_LIGHT_RECORD_SIZE:
        return {
            "valid": False,
            "reason": (
                f"payload size {payload_size} does not match "
                f"{count} records of {STATIC_LIGHT_RECORD_SIZE}"
            ),
            "magic": magic,
            "version": version,
            "header_value_a": header_value_a,
        }
    return {
        "valid": True,
        "reason": "",
        "magic": magic,
        "version": version,
        "header_value_a": header_value_a,
        "count": count,
        "payload_size": payload_size,
    }


def _parse_record(data: bytes, index: int) -> StaticDeferredLight:
    offset = 16 + index * STATIC_LIGHT_RECORD_SIZE
    record = data[offset : offset + STATIC_LIGHT_RECORD_SIZE]
    name = record[:STATIC_LIGHT_NAME_SIZE].split(b"\x00", 1)[0].decode(
        "ascii",
        errors="ignore",
    )
    values = tuple(
        _finite_float(
            struct.unpack_from(
                "<f",
                record,
                STATIC_LIGHT_NAME_SIZE + field_index * 4,
            )[0]
        )
        for field_index in range(STATIC_LIGHT_FLOAT_COUNT)
    )
    return StaticDeferredLight(
        index=index,
        name=name,
        position=(values[1], values[2], values[3]),
        color_rgb=(values[4], values[5], values[6]),
        intensity=values[7],
        radius=values[8],
        type_or_flags=values[9],
        cone_angle_degrees=values[26],
        rotation_degrees=(values[28], values[29], values[30]),
        raw_fields=values,
    )


def _finite_float(value: float) -> float:
    number = float(value)
    if not math.isfinite(number):
        raise ValueError(f"non-finite static deferred light field: {number}")
    return number
