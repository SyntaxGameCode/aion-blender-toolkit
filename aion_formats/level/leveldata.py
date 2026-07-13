from dataclasses import dataclass
from pathlib import Path
from xml.etree import ElementTree


@dataclass(frozen=True)
class LevelInfo:
    name: str | None
    heightmap_x_size: int | None
    heightmap_y_size: int | None
    heightmap_unit_size: int | None
    water_level: float | None


@dataclass(frozen=True)
class SurfaceType:
    name: str | None
    material: str | None
    detail_texture: str | None
    detail_scale_x: float | None
    detail_scale_y: float | None
    offset_u: float | None
    offset_v: float | None
    proj_axis: str | None
    project_axis: int | None
    bumpmap: str | None
    use_terrain_specular: int | None


@dataclass(frozen=True)
class LevelData:
    level_info: LevelInfo
    vegetation_files: tuple[str, ...]
    surface_types: tuple[SurfaceType, ...] = ()


def _parse_int(value: str | None) -> int | None:
    return int(value) if value not in (None, "") else None


def _parse_float(value: str | None) -> float | None:
    return float(value) if value not in (None, "") else None


def parse_leveldata(path: str | Path) -> LevelData:
    root = ElementTree.parse(path).getroot()
    level_info_element = root.find("LevelInfo")
    attrs = level_info_element.attrib if level_info_element is not None else {}

    level_info = LevelInfo(
        name=attrs.get("Name"),
        heightmap_x_size=_parse_int(attrs.get("HeightmapXSize")),
        heightmap_y_size=_parse_int(attrs.get("HeightmapYSize")),
        heightmap_unit_size=_parse_int(attrs.get("HeightmapUnitSize")),
        water_level=_parse_float(attrs.get("WaterLevel")),
    )

    vegetation_files = tuple(
        obj.attrib["FileName"]
        for obj in root.findall("./Vegetation/Object")
        if "FileName" in obj.attrib
    )

    surface_types = tuple(
        SurfaceType(
            name=surface_type.attrib.get("Name"),
            material=surface_type.attrib.get("Material"),
            detail_texture=surface_type.attrib.get("DetailTexture"),
            detail_scale_x=_parse_float(surface_type.attrib.get("DetailScaleX")),
            detail_scale_y=_parse_float(surface_type.attrib.get("DetailScaleY")),
            offset_u=_parse_float(surface_type.attrib.get("Offset_U")),
            offset_v=_parse_float(surface_type.attrib.get("Offset_V")),
            proj_axis=surface_type.attrib.get("ProjAxis"),
            project_axis=_parse_int(surface_type.attrib.get("ProjectAxis")),
            bumpmap=surface_type.attrib.get("Bumpmap"),
            use_terrain_specular=_parse_int(surface_type.attrib.get("Use_Terran_Specular")),
        )
        for surface_type in root.findall("./SurfaceTypes/SurfaceType")
    )

    return LevelData(
        level_info=level_info,
        vegetation_files=vegetation_files,
        surface_types=surface_types,
    )
