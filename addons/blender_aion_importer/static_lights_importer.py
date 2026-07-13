from dataclasses import dataclass
import math
from pathlib import Path

from aion_formats.level import parse_static_deferred_lights


STATIC_LIGHTS_COLLECTION_NAME = "AION Static Deferred Lights"
STATIC_LIGHTS_COORDINATE_VARIANT = "raw"
STATIC_LIGHTS_MODE_EMPTY = "EMPTY"
STATIC_LIGHTS_MODE_POINT_LIGHT = "POINT_LIGHT"
STATIC_LIGHTS_MODES = (STATIC_LIGHTS_MODE_EMPTY, STATIC_LIGHTS_MODE_POINT_LIGHT)
DEFAULT_STATIC_LIGHT_POWER = 800.0


@dataclass(frozen=True)
class StaticLightsImportResult:
    requested: bool
    file_found: bool
    parsed: bool
    created: bool
    mode: str
    power: float
    light_count: int
    created_count: int
    failed_count: int
    skip_reason: str | None
    collection_name: str
    coordinate_variant: str


def create_static_deferred_lights(
    context,
    level_dir: str | Path,
    mode: str = STATIC_LIGHTS_MODE_POINT_LIGHT,
    power: float = DEFAULT_STATIC_LIGHT_POWER,
) -> StaticLightsImportResult:
    level_path = Path(level_dir)
    source_path = level_path / "staticdeferredlights.lst"
    if mode not in STATIC_LIGHTS_MODES:
        raise ValueError(f"unsupported static lights mode: {mode}")
    if power <= 0 or not math.isfinite(float(power)):
        raise ValueError("static light power must be finite and positive")
    if not source_path.is_file():
        return _result(
            requested=True,
            file_found=False,
            parsed=False,
            created=False,
            mode=mode,
            power=power,
            skip_reason="static_lights_missing",
        )

    parsed = parse_static_deferred_lights(source_path)
    if not parsed.valid:
        return _result(
            requested=True,
            file_found=True,
            parsed=False,
            created=False,
            mode=mode,
            power=power,
            skip_reason=parsed.reason or "static_lights_invalid",
        )

    import bpy

    collection = bpy.data.collections.new(STATIC_LIGHTS_COLLECTION_NAME)
    context.scene.collection.children.link(collection)
    created_count = 0
    failed_count = 0
    for light in parsed.lights:
        try:
            obj = _create_light_object(bpy, light, source_path, mode, power)
        except (TypeError, ValueError):
            failed_count += 1
            continue
        collection.objects.link(obj)
        created_count += 1

    return _result(
        requested=True,
        file_found=True,
        parsed=True,
        created=created_count > 0,
        mode=mode,
        power=power,
        light_count=parsed.count,
        created_count=created_count,
        failed_count=failed_count,
        skip_reason=None if created_count > 0 else "static_lights_no_valid_records",
    )


def _create_light_object(bpy, light, source_path, mode, power):
    position = _raw_position(light.position)
    if mode == STATIC_LIGHTS_MODE_POINT_LIGHT:
        light_data = bpy.data.lights.new(light.name or f"AION Static Light {light.index}", type="POINT")
        light_data.color = _clamped_rgb(light.color_rgb)
        light_data.energy = _light_energy(light, power)
        light_data.shadow_soft_size = max(0.01, float(light.radius))
        if hasattr(light_data, "use_shadow"):
            light_data.use_shadow = False
        obj = bpy.data.objects.new(light.name or light_data.name, light_data)
    else:
        obj = bpy.data.objects.new(light.name or f"AION Static Light {light.index}", None)
        obj.empty_display_type = "SPHERE"
        obj.empty_display_size = max(0.25, min(float(light.radius), 60.0) * 0.1)

    obj.location = position
    _assign_custom_properties(obj, light, source_path, mode, power)
    return obj


def _assign_custom_properties(obj, light, source_path, mode, power):
    obj["aion_static_deferred_light"] = True
    obj["aion_static_deferred_light_mode"] = mode
    obj["aion_source_file"] = str(source_path)
    obj["aion_coordinate_variant"] = STATIC_LIGHTS_COORDINATE_VARIANT
    obj["aion_raw_position"] = tuple(float(value) for value in light.position)
    obj["aion_rgb"] = tuple(float(value) for value in light.color_rgb)
    obj["aion_intensity"] = float(light.intensity)
    obj["aion_radius"] = float(light.radius)
    obj["aion_type_or_flags"] = float(light.type_or_flags)
    obj["aion_cone_angle_degrees"] = float(light.cone_angle_degrees)
    obj["aion_rotation_degrees"] = tuple(float(value) for value in light.rotation_degrees)
    obj["aion_static_light_power"] = float(power)


def _raw_position(position):
    values = tuple(float(value) for value in position)
    if len(values) != 3 or not all(math.isfinite(value) for value in values):
        raise ValueError(f"invalid static light position: {position}")
    return values


def _clamped_rgb(rgb):
    values = tuple(float(value) for value in rgb)
    if len(values) != 3 or not all(math.isfinite(value) for value in values):
        raise ValueError(f"invalid static light color: {rgb}")
    return tuple(max(0.0, min(1.0, value)) for value in values)


def _light_energy(light, power):
    intensity = float(light.intensity)
    if not math.isfinite(intensity):
        intensity = 1.0
    return max(1.0, float(power) * max(0.0, intensity))


def _result(
    *,
    requested,
    file_found,
    parsed,
    created,
    mode,
    power,
    light_count=0,
    created_count=0,
    failed_count=0,
    skip_reason=None,
):
    return StaticLightsImportResult(
        requested=bool(requested),
        file_found=bool(file_found),
        parsed=bool(parsed),
        created=bool(created),
        mode=mode,
        power=float(power),
        light_count=int(light_count),
        created_count=int(created_count),
        failed_count=int(failed_count),
        skip_reason=skip_reason,
        collection_name=STATIC_LIGHTS_COLLECTION_NAME,
        coordinate_variant=STATIC_LIGHTS_COORDINATE_VARIANT,
    )
