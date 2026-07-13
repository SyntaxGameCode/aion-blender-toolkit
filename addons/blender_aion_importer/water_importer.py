import math
from dataclasses import dataclass

from aion_formats.level import LevelInfo


DEFAULT_WATER_NAME = "Aion Water"
DEFAULT_WATER_XY_SCALE = 2.0


@dataclass(frozen=True)
class WaterPlaneResult:
    created: bool
    object: object | None
    mesh: object | None
    water_level: float | None
    width: float
    height: float
    xy_scale: float
    skip_reason: str | None


def create_water_plane(
    context,
    level_info: LevelInfo,
    xy_scale: float = DEFAULT_WATER_XY_SCALE,
    name: str = DEFAULT_WATER_NAME,
) -> WaterPlaneResult:
    if level_info.water_level is None:
        return _skipped_result(xy_scale, "LevelInfo WaterLevel is missing")
    if level_info.heightmap_x_size is None or level_info.heightmap_y_size is None:
        return _skipped_result(xy_scale, "LevelInfo heightmap dimensions are missing")
    if not math.isfinite(xy_scale) or xy_scale <= 0:
        raise ValueError("water XY scale must be finite and positive")
    if not math.isfinite(level_info.water_level):
        return _skipped_result(xy_scale, "LevelInfo WaterLevel is not finite")

    width = float(level_info.heightmap_x_size) * xy_scale
    height = float(level_info.heightmap_y_size) * xy_scale
    if width <= 0 or height <= 0:
        return _skipped_result(xy_scale, "LevelInfo heightmap dimensions must be positive")

    import bpy

    mesh = bpy.data.meshes.new(name)
    mesh.from_pydata(
        (
            (0.0, 0.0, 0.0),
            (width, 0.0, 0.0),
            (width, height, 0.0),
            (0.0, height, 0.0),
        ),
        (),
        ((0, 1, 2, 3),),
    )
    mesh.update(calc_edges=False)
    water_object = bpy.data.objects.new(name, mesh)
    water_object.location.z = level_info.water_level
    context.scene.collection.objects.link(water_object)

    return WaterPlaneResult(
        created=True,
        object=water_object,
        mesh=mesh,
        water_level=level_info.water_level,
        width=width,
        height=height,
        xy_scale=xy_scale,
        skip_reason=None,
    )


def _skipped_result(xy_scale: float, reason: str) -> WaterPlaneResult:
    return WaterPlaneResult(
        created=False,
        object=None,
        mesh=None,
        water_level=None,
        width=0.0,
        height=0.0,
        xy_scale=xy_scale,
        skip_reason=reason,
    )
