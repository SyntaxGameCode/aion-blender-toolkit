import math
from dataclasses import dataclass
from pathlib import Path


LAND_MAP_BYTES_PER_SAMPLE = 3
LAND_MAP_HEIGHT_SCALE = 32


@dataclass(frozen=True)
class LandMapSample:
    height_raw: int
    height: float
    color: int


@dataclass(frozen=True)
class LandMap:
    width: int
    height: int
    sample_count: int
    bytes_per_sample: int
    height_scale: int
    samples: tuple[LandMapSample, ...]
    min_height: float
    max_height: float
    trailing_bytes: bytes


def parse_land_map_h32(path: str | Path) -> LandMap:
    data = Path(path).read_bytes()
    sample_count, remainder = divmod(len(data), LAND_MAP_BYTES_PER_SAMPLE)
    if remainder:
        raise ValueError("land_map.h32 size is not divisible by 3 bytes per sample")

    width = int(math.sqrt(sample_count))
    if width * width != sample_count:
        raise ValueError(f"land_map.h32 sample count {sample_count} is not a square grid")

    samples = []
    for offset in range(0, sample_count * LAND_MAP_BYTES_PER_SAMPLE, LAND_MAP_BYTES_PER_SAMPLE):
        height_raw = int.from_bytes(data[offset : offset + 2], byteorder="little")
        color = int.from_bytes(data[offset + 2 : offset + 3], byteorder="little")
        samples.append(
            LandMapSample(
                height_raw=height_raw,
                height=height_raw / LAND_MAP_HEIGHT_SCALE,
                color=color,
            )
        )

    heights = tuple(sample.height for sample in samples)
    return LandMap(
        width=width,
        height=width,
        sample_count=sample_count,
        bytes_per_sample=LAND_MAP_BYTES_PER_SAMPLE,
        height_scale=LAND_MAP_HEIGHT_SCALE,
        samples=tuple(samples),
        min_height=min(heights) if heights else 0.0,
        max_height=max(heights) if heights else 0.0,
        trailing_bytes=data[sample_count * LAND_MAP_BYTES_PER_SAMPLE :],
    )
