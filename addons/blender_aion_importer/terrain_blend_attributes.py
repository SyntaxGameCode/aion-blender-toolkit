import math
from array import array
from dataclasses import dataclass

from aion_formats.level import TerrainBlendWeights


ATTRIBUTE_NAME_PREFIX = "AION_BlendWeights_"
MATERIALS_PER_ATTRIBUTE = 4


@dataclass(frozen=True)
class TerrainBlendAttributeResult:
    attribute_layers_created: int
    material_count: int
    layer_names: tuple[str, ...]


def create_terrain_blend_attributes(
    mesh,
    blend_weights: TerrainBlendWeights,
) -> TerrainBlendAttributeResult:
    material_indices = blend_weights.used_material_indices
    layer_names = []

    for layer_index, start in enumerate(
        range(0, len(material_indices), MATERIALS_PER_ATTRIBUTE)
    ):
        layer_material_indices = material_indices[start : start + MATERIALS_PER_ATTRIBUTE]
        layer_name = f"{ATTRIBUTE_NAME_PREFIX}{layer_index}"
        attribute = mesh.color_attributes.new(
            name=layer_name,
            type="FLOAT_COLOR",
            domain="CORNER",
        )
        colors = _pack_loop_colors(
            mesh,
            blend_weights,
            layer_material_indices,
        )
        attribute.data.foreach_set("color", colors)
        layer_names.append(layer_name)

    mesh["aion_blend_material_indices"] = list(material_indices)
    mesh["aion_blend_attribute_layers"] = ",".join(layer_names)
    mesh["aion_blend_radius"] = blend_weights.radius

    return TerrainBlendAttributeResult(
        attribute_layers_created=len(layer_names),
        material_count=len(material_indices),
        layer_names=tuple(layer_names),
    )


def _pack_loop_colors(
    mesh,
    blend_weights: TerrainBlendWeights,
    layer_material_indices: tuple[int, ...],
) -> array:
    sample_colors = array("f")
    for sample in blend_weights.samples:
        weight_by_material = dict(sample.weights)
        color = tuple(
            weight_by_material.get(material_index, 0.0)
            for material_index in layer_material_indices
        )
        sample_colors.extend(color)
        sample_colors.extend((0.0,) * (MATERIALS_PER_ATTRIBUTE - len(color)))

    loop_colors = array("f")
    for loop in mesh.loops:
        color_offset = loop.vertex_index * MATERIALS_PER_ATTRIBUTE
        loop_colors.extend(
            sample_colors[color_offset : color_offset + MATERIALS_PER_ATTRIBUTE]
        )

    if len(loop_colors) != len(mesh.loops) * MATERIALS_PER_ATTRIBUTE:
        raise ValueError("terrain blend color count does not match mesh loop count")
    if not all(math.isfinite(value) and 0.0 <= value <= 1.0 for value in loop_colors):
        raise ValueError("terrain blend color attributes contain invalid weights")
    return loop_colors
