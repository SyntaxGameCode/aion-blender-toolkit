import math
from collections import Counter
from dataclasses import dataclass

from .terrain import LandMap


@dataclass(frozen=True)
class TerrainSampleBlendWeights:
    sample_index: int
    material_index: int
    weights: tuple[tuple[int, float], ...]

    @property
    def active_material_count(self) -> int:
        return len(self.weights)


@dataclass(frozen=True)
class TerrainBlendWeights:
    radius: int
    used_material_indices: tuple[int, ...]
    samples: tuple[TerrainSampleBlendWeights, ...]
    boundary_sample_count: int
    max_active_material_count: int
    invalid_weight_count: int


def build_terrain_preview_blend_weights(
    land_map: LandMap,
    radius: int = 1,
) -> TerrainBlendWeights:
    if radius < 0:
        raise ValueError("terrain preview blend radius must be >= 0")
    if land_map.sample_count != len(land_map.samples):
        raise ValueError("LandMap sample count does not match parsed samples")
    if land_map.sample_count != land_map.width * land_map.height:
        raise ValueError("LandMap sample count does not match width * height")

    sample_weights = []
    boundary_sample_count = 0
    max_active_material_count = 0
    invalid_weight_count = 0

    for sample_index, sample in enumerate(land_map.samples):
        row, column = divmod(sample_index, land_map.width)
        neighborhood = Counter(
            land_map.samples[
                neighbor_row * land_map.width + neighbor_column
            ].color
            for neighbor_row in range(
                max(0, row - radius),
                min(land_map.height, row + radius + 1),
            )
            for neighbor_column in range(
                max(0, column - radius),
                min(land_map.width, column + radius + 1),
            )
        )
        total = sum(neighborhood.values())
        weights = tuple(
            (material_index, count / total)
            for material_index, count in sorted(neighborhood.items())
        )

        invalid_weight_count += _count_invalid_weights(weights)
        active_material_count = len(weights)
        if active_material_count > 1:
            boundary_sample_count += 1
        max_active_material_count = max(
            max_active_material_count,
            active_material_count,
        )
        sample_weights.append(
            TerrainSampleBlendWeights(
                sample_index=sample_index,
                material_index=sample.color,
                weights=weights,
            )
        )

    return TerrainBlendWeights(
        radius=radius,
        used_material_indices=tuple(
            sorted({sample.color for sample in land_map.samples})
        ),
        samples=tuple(sample_weights),
        boundary_sample_count=boundary_sample_count,
        max_active_material_count=max_active_material_count,
        invalid_weight_count=invalid_weight_count,
    )


def _count_invalid_weights(weights: tuple[tuple[int, float], ...]) -> int:
    invalid_count = sum(
        not math.isfinite(weight) or not 0.0 <= weight <= 1.0
        for _, weight in weights
    )
    if not math.isclose(
        sum(weight for _, weight in weights),
        1.0,
        rel_tol=1e-9,
        abs_tol=1e-9,
    ):
        invalid_count += 1
    return invalid_count
