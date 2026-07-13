from dataclasses import dataclass

from aion_formats.level import (
    LIQUID_KIND_LAVA,
    LIQUID_PRESET_LAVA_EMISSIVE,
    LIQUID_PRESET_NORMAL,
    LIQUID_PRESET_TRANSPARENT,
    LiquidSurfaceRecipe,
)


@dataclass(frozen=True)
class LiquidSurfaceMaterialResult:
    requested: bool
    applied: bool
    selected_kind: str
    inferred_kind: str
    selected_preset: str
    textures_loaded: int
    textures_used: int
    material_name: str
    skip_reason: str | None
    warnings: tuple[str, ...] = ()


def apply_liquid_surface_material(water_result, recipe: LiquidSurfaceRecipe, *, alpha: float = 0.35, tile_scale: float = 32.0):
    if water_result is None or not water_result.created or water_result.object is None or water_result.mesh is None:
        return LiquidSurfaceMaterialResult(
            requested=True,
            applied=False,
            selected_kind=recipe.selected_kind,
            inferred_kind=recipe.inferred_kind,
            selected_preset=recipe.selected_preset,
            textures_loaded=0,
            textures_used=0,
            material_name="",
            skip_reason="liquid surface material requested but water/liquid plane was not created",
            warnings=recipe.warnings,
        )

    material, report = _create_liquid_material(
        recipe,
        alpha=alpha,
        tile_scale=tile_scale,
    )
    water_result.mesh.materials.clear()
    water_result.mesh.materials.append(material)
    water_result.object["aion_liquid_kind"] = recipe.selected_kind
    water_result.object["aion_liquid_inferred_kind"] = recipe.inferred_kind
    water_result.object["aion_liquid_preset"] = recipe.selected_preset
    water_result.object["aion_liquid_textures_loaded"] = report["textures_loaded"]
    water_result.object["aion_liquid_textures_used"] = report["textures_used"]
    water_result.object["aion_liquid_level"] = water_result.water_level
    water_result.object["aion_liquid_width"] = water_result.width
    water_result.object["aion_liquid_height"] = water_result.height
    material["aion_liquid_kind"] = recipe.selected_kind
    material["aion_liquid_inferred_kind"] = recipe.inferred_kind
    material["aion_liquid_preset"] = recipe.selected_preset
    material["aion_liquid_textures_loaded"] = report["textures_loaded"]
    material["aion_liquid_textures_used"] = report["textures_used"]
    return LiquidSurfaceMaterialResult(
        requested=True,
        applied=True,
        selected_kind=recipe.selected_kind,
        inferred_kind=recipe.inferred_kind,
        selected_preset=recipe.selected_preset,
        textures_loaded=report["textures_loaded"],
        textures_used=report["textures_used"],
        material_name=material.name,
        skip_reason=None,
        warnings=recipe.warnings,
    )


def skipped_liquid_surface_result(*, requested, selected_kind="", inferred_kind="", selected_preset="", reason=None):
    return LiquidSurfaceMaterialResult(
        requested=requested,
        applied=False,
        selected_kind=selected_kind,
        inferred_kind=inferred_kind,
        selected_preset=selected_preset,
        textures_loaded=0,
        textures_used=0,
        material_name="",
        skip_reason=reason,
    )


def _create_liquid_material(recipe: LiquidSurfaceRecipe, *, alpha: float, tile_scale: float):
    import bpy

    material = bpy.data.materials.new(f"AION_Liquid_{recipe.selected_kind.lower()}_{recipe.selected_preset.lower()}")
    material.use_nodes = True
    material.blend_method = "BLEND"
    material.show_transparent_back = True
    tree = material.node_tree
    nodes = tree.nodes
    links = tree.links
    for node in tuple(nodes):
        nodes.remove(node)
    output = nodes.new("ShaderNodeOutputMaterial")
    mapping = nodes.new("ShaderNodeMapping")
    tex_coord = nodes.new("ShaderNodeTexCoord")
    mapping.inputs["Scale"].default_value = (float(tile_scale), float(tile_scale), 1.0)
    links.new(tex_coord.outputs["UV"], mapping.inputs["Vector"])
    loaded = _load_candidates(recipe.candidates)
    used = []
    if recipe.selected_kind == LIQUID_KIND_LAVA or recipe.selected_preset == LIQUID_PRESET_LAVA_EMISSIVE:
        used.extend(_wire_lava(nodes, links, mapping, output, loaded, recipe.selected_preset))
    else:
        used.extend(_wire_water(nodes, links, mapping, output, loaded, recipe.selected_preset, alpha))
    return material, {
        "textures_loaded": len(loaded),
        "textures_used": len({item["candidate"].texture for item in used}),
    }


def _load_candidates(candidates):
    import bpy

    loaded = []
    for candidate in candidates:
        if not candidate.exists:
            continue
        try:
            image = bpy.data.images.load(candidate.resolved_path, check_existing=True)
        except RuntimeError:
            continue
        loaded.append({"candidate": candidate, "image": image})
    return loaded


def _wire_water(nodes, links, mapping, output, loaded, preset, alpha):
    bsdf = nodes.new("ShaderNodeBsdfPrincipled")
    bsdf.inputs["Alpha"].default_value = max(0.0, min(1.0, float(alpha)))
    bsdf.inputs["Base Color"].default_value = (0.08, 0.32, 0.42, max(0.0, min(1.0, float(alpha))))
    bsdf.inputs["Roughness"].default_value = 0.18
    links.new(bsdf.outputs["BSDF"], output.inputs["Surface"])
    used = []
    texture = _first_loaded(loaded, roles=("diffuse_base", "caustics", "reflection"), kinds=("WATER", "SWAMP", "MAGIC", "UNKNOWN"))
    if texture:
        tex = nodes.new("ShaderNodeTexImage")
        tex.image = texture["image"]
        links.new(mapping.outputs["Vector"], tex.inputs["Vector"])
        links.new(tex.outputs["Color"], bsdf.inputs["Base Color"])
        used.append(texture)
    if preset == LIQUID_PRESET_NORMAL:
        normal_texture = _first_loaded(loaded, roles=("normal_bump",), kinds=("WATER", "SWAMP", "MAGIC", "UNKNOWN"))
        if normal_texture:
            normal_texture["image"].colorspace_settings.name = "Non-Color"
            tex = nodes.new("ShaderNodeTexImage")
            tex.image = normal_texture["image"]
            normal = nodes.new("ShaderNodeNormalMap")
            normal.inputs["Strength"].default_value = 0.25
            links.new(mapping.outputs["Vector"], tex.inputs["Vector"])
            links.new(tex.outputs["Color"], normal.inputs["Color"])
            links.new(normal.outputs["Normal"], bsdf.inputs["Normal"])
            used.append(normal_texture)
    if preset == LIQUID_PRESET_TRANSPARENT:
        bsdf.inputs["Alpha"].default_value = min(bsdf.inputs["Alpha"].default_value, 0.35)
    return used


def _wire_lava(nodes, links, mapping, output, loaded, preset):
    texture = _first_loaded(loaded, roles=("emission_glow", "diffuse_base", "caustics"), kinds=("LAVA", "UNKNOWN"))
    emission = nodes.new("ShaderNodeEmission")
    emission.inputs["Color"].default_value = (1.0, 0.22, 0.02, 1.0)
    emission.inputs["Strength"].default_value = 4.0 if preset == LIQUID_PRESET_LAVA_EMISSIVE else 2.0
    links.new(emission.outputs["Emission"], output.inputs["Surface"])
    if not texture:
        return []
    tex = nodes.new("ShaderNodeTexImage")
    tex.image = texture["image"]
    links.new(mapping.outputs["Vector"], tex.inputs["Vector"])
    links.new(tex.outputs["Color"], emission.inputs["Color"])
    return [texture]


def _first_loaded(loaded, *, roles, kinds):
    for kind in kinds:
        for role in roles:
            for item in loaded:
                candidate = item["candidate"]
                if candidate.role == role and candidate.liquid_kind == kind:
                    return item
    for role in roles:
        for item in loaded:
            if item["candidate"].role == role:
                return item
    return None
