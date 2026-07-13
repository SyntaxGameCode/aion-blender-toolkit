from dataclasses import dataclass


@dataclass(frozen=True)
class TerrainTextureNodeResult:
    texture_load_requested: bool
    texture_images_loaded: int
    texture_images_failed: int
    texture_nodes_created: int


def create_terrain_texture_nodes(bpy, materials) -> TerrainTextureNodeResult:
    images_loaded = 0
    images_failed = 0
    nodes_created = 0

    for material in materials:
        texture_path = material.get("aion_detail_texture_resolved")
        if not texture_path or not material.get("aion_detail_texture_exists"):
            continue

        material.use_nodes = True
        nodes = material.node_tree.nodes
        links = material.node_tree.links
        bsdf = nodes.get("Principled BSDF")
        if bsdf is None:
            bsdf = nodes.new(type="ShaderNodeBsdfPrincipled")
        output = nodes.get("Material Output")
        if output is None:
            output = nodes.new(type="ShaderNodeOutputMaterial")
        links.new(bsdf.outputs["BSDF"], output.inputs["Surface"])

        texture_node = nodes.new(type="ShaderNodeTexImage")
        texture_node.label = "Aion Detail Texture Preview"
        texture_node.name = "Aion Detail Texture Preview"
        nodes_created += 1

        try:
            texture_node.image = bpy.data.images.load(texture_path, check_existing=True)
        except RuntimeError as exc:
            images_failed += 1
            material["aion_detail_texture_load_error"] = str(exc)
            continue

        if texture_node.image is not None:
            images_loaded += 1
            material["aion_detail_texture_image"] = texture_node.image.name

        if "Base Color" in bsdf.inputs:
            links.new(texture_node.outputs["Color"], bsdf.inputs["Base Color"])

    return TerrainTextureNodeResult(
        texture_load_requested=True,
        texture_images_loaded=images_loaded,
        texture_images_failed=images_failed,
        texture_nodes_created=nodes_created,
    )
