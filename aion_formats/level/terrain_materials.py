from collections import Counter
from dataclasses import dataclass

from .leveldata import LevelData, SurfaceType
from .terrain import LandMap


@dataclass(frozen=True)
class TerrainMaterialUsage:
    index: int
    sample_count: int
    surface_type: SurfaceType | None


@dataclass(frozen=True)
class TerrainMaterialInventory:
    total_samples: int
    used_material_indices: tuple[TerrainMaterialUsage, ...]
    known_material_indices: tuple[int, ...]
    out_of_range_indices: tuple[int, ...]
    unused_surface_type_indices: tuple[int, ...]
    dominant_index: int | None


def build_terrain_material_inventory(
    land_map: LandMap,
    level_data: LevelData,
) -> TerrainMaterialInventory:
    if land_map.sample_count != len(land_map.samples):
        raise ValueError("LandMap sample count does not match parsed samples")

    counts = Counter(sample.color for sample in land_map.samples)
    surface_count = len(level_data.surface_types)

    used_material_indices = tuple(
        TerrainMaterialUsage(
            index=index,
            sample_count=counts[index],
            surface_type=level_data.surface_types[index] if 0 <= index < surface_count else None,
        )
        for index in sorted(counts)
    )
    known_material_indices = tuple(
        usage.index for usage in used_material_indices if usage.surface_type is not None
    )
    out_of_range_indices = tuple(
        usage.index for usage in used_material_indices if usage.surface_type is None
    )
    unused_surface_type_indices = tuple(
        index for index in range(surface_count) if index not in counts
    )
    dominant_index = (
        min(counts, key=lambda index: (-counts[index], index))
        if counts
        else None
    )

    return TerrainMaterialInventory(
        total_samples=land_map.sample_count,
        used_material_indices=used_material_indices,
        known_material_indices=known_material_indices,
        out_of_range_indices=out_of_range_indices,
        unused_surface_type_indices=unused_surface_type_indices,
        dominant_index=dominant_index,
    )
