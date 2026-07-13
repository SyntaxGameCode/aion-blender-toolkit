import math
from dataclasses import dataclass

from .level_jobs import SOURCE_BRUSH, SOURCE_OBJECT, LevelCgfJob


INVALID_OBJECT_SCALE = "invalid_object_scale"
INVALID_OBJECT_TRANSFORM = "invalid_object_transform"
INVALID_BRUSH_MATRIX = "invalid_brush_matrix"
UNSUPPORTED_SOURCE_TYPE = "unsupported_source_type"


class InvalidPlacementError(ValueError):
    def __init__(self, reason_code: str, message: str):
        super().__init__(message)
        self.reason_code = reason_code


@dataclass(frozen=True)
class PlacementSkip:
    source_type: str
    source_index: int
    cgf_reference: str
    reason_code: str
    reason: str


@dataclass(frozen=True)
class PlacementTransformSummary:
    source_type: str
    source_index: int
    matrix_values: tuple[float, ...]
    translation: tuple[float, float, float]
    scale: float | None
    heading_degrees: float | None
    is_non_default: bool


@dataclass(frozen=True)
class PlacementInstanceBatch:
    instances: tuple
    transform_summaries: tuple[PlacementTransformSummary, ...]
    object_placement_count: int
    brush_placement_count: int
    placement_skips: tuple[PlacementSkip, ...]
    invalid_placements_skipped: int
    invalid_object_scale_count: int
    invalid_brush_matrix_count: int


def create_level_cgf_placement_instances(
    target_collection,
    template_collection,
    placements: tuple[LevelCgfJob, ...],
    max_placements: int,
) -> PlacementInstanceBatch:
    if max_placements < 1:
        raise ValueError("max_placements must be >= 1")

    import bpy

    instances = []
    summaries = []
    placement_skips = []
    for placement in placements[:max_placements]:
        try:
            matrix = _placement_matrix(placement)
        except InvalidPlacementError as exc:
            placement_skips.append(
                PlacementSkip(
                    source_type=placement.source_type,
                    source_index=placement.source_index,
                    cgf_reference=placement.cgf_reference,
                    reason_code=exc.reason_code,
                    reason=str(exc),
                )
            )
            continue
        summary = _summarize_transform(placement, matrix)
        instance = bpy.data.objects.new(
            f"{template_collection.name}_{placement.source_type}_{placement.source_index}",
            None,
        )
        instance.instance_type = "COLLECTION"
        instance.instance_collection = template_collection
        instance.matrix_world = matrix
        target_collection.objects.link(instance)
        instances.append(instance)
        summaries.append(summary)

    return PlacementInstanceBatch(
        instances=tuple(instances),
        transform_summaries=tuple(summaries),
        object_placement_count=sum(
            summary.source_type == SOURCE_OBJECT for summary in summaries
        ),
        brush_placement_count=sum(
            summary.source_type == SOURCE_BRUSH for summary in summaries
        ),
        placement_skips=tuple(placement_skips),
        invalid_placements_skipped=len(placement_skips),
        invalid_object_scale_count=sum(
            skip.reason_code == INVALID_OBJECT_SCALE
            for skip in placement_skips
        ),
        invalid_brush_matrix_count=sum(
            skip.reason_code == INVALID_BRUSH_MATRIX
            for skip in placement_skips
        ),
    )


def _placement_matrix(placement: LevelCgfJob):
    from mathutils import Matrix

    if placement.source_type == SOURCE_OBJECT:
        if placement.position is None or placement.scale is None or placement.heading_degrees is None:
            raise InvalidPlacementError(
                INVALID_OBJECT_TRANSFORM,
                "object placement requires position, scale, and heading",
            )
        if not math.isfinite(placement.scale) or placement.scale <= 0:
            raise InvalidPlacementError(
                INVALID_OBJECT_SCALE,
                f"object placement scale must be finite and positive: {placement.scale}",
            )
        if not all(math.isfinite(value) for value in placement.position):
            raise InvalidPlacementError(
                INVALID_OBJECT_TRANSFORM,
                f"object placement position must be finite: {placement.position}",
            )
        if not math.isfinite(placement.heading_degrees):
            raise InvalidPlacementError(
                INVALID_OBJECT_TRANSFORM,
                f"object placement heading must be finite: {placement.heading_degrees}",
            )

        sot_matrix = (
            Matrix.Translation(placement.position)
            @ Matrix.Rotation(math.radians(placement.heading_degrees), 4, "Z")
            @ Matrix.Scale(placement.scale, 4)
        )
        return sot_matrix

    if placement.source_type == SOURCE_BRUSH:
        if placement.transform is None or len(placement.transform) != 12:
            raise InvalidPlacementError(
                INVALID_BRUSH_MATRIX,
                "brush placement requires a 12-value transform",
            )
        if not all(math.isfinite(value) for value in placement.transform):
            raise InvalidPlacementError(
                INVALID_BRUSH_MATRIX,
                "brush placement matrix contains NaN or infinity",
            )

        sot_matrix = Matrix(
            (
                placement.transform[0:4],
                placement.transform[4:8],
                placement.transform[8:12],
                (0.0, 0.0, 0.0, 1.0),
            )
        )
        return sot_matrix

    raise InvalidPlacementError(
        UNSUPPORTED_SOURCE_TYPE,
        f"unsupported placement source type: {placement.source_type}",
    )


def _summarize_transform(placement: LevelCgfJob, matrix) -> PlacementTransformSummary:
    matrix_values = tuple(float(value) for row in matrix for value in row)
    if len(matrix_values) != 16:
        raise ValueError(f"placement matrix must contain 16 values, got {len(matrix_values)}")
    if not all(math.isfinite(value) for value in matrix_values):
        raise ValueError("placement matrix contains NaN or infinity")

    identity = (
        1.0, 0.0, 0.0, 0.0,
        0.0, 1.0, 0.0, 0.0,
        0.0, 0.0, 1.0, 0.0,
        0.0, 0.0, 0.0, 1.0,
    )
    return PlacementTransformSummary(
        source_type=placement.source_type,
        source_index=placement.source_index,
        matrix_values=matrix_values,
        translation=(matrix_values[3], matrix_values[7], matrix_values[11]),
        scale=placement.scale,
        heading_degrees=placement.heading_degrees,
        is_non_default=any(
            not math.isclose(value, identity_value, rel_tol=1e-9, abs_tol=1e-9)
            for value, identity_value in zip(matrix_values, identity)
        ),
    )
