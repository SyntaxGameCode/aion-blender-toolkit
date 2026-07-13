from pathlib import Path

import bpy
from bpy.props import BoolProperty, EnumProperty, FloatProperty, IntProperty, StringProperty
from bpy_extras.io_utils import ImportHelper

from aion_formats.level import (
    LIQUID_KIND_AUTO,
    LIQUID_KIND_LAVA,
    LIQUID_KIND_UNKNOWN,
    LIQUID_KIND_WATER,
    LIQUID_PRESET_AUTO,
    LIQUID_PRESET_LAVA_EMISSIVE,
    LIQUID_PRESET_NORMAL,
    LIQUID_PRESET_TRANSPARENT,
)

from ..level_importer import import_level
from ..level_summary import format_level_import_report
from ..static_lights_importer import (
    DEFAULT_STATIC_LIGHT_POWER,
    STATIC_LIGHTS_MODE_EMPTY,
    STATIC_LIGHTS_MODE_POINT_LIGHT,
)


class AION_OT_import_level_folder(bpy.types.Operator, ImportHelper):
    bl_idname = "import_scene.aion_level_folder"
    bl_label = "Import Aion Level Folder"
    bl_description = "Import an unpacked Aion level locally"
    bl_options = {"PRESET", "UNDO"}

    filename_ext = ""
    use_filter_folder = True
    filter_glob: StringProperty(default="", options={"HIDDEN"})

    import_mode: EnumProperty(
        name="Import Mode",
        description="What to import from resolved level CGF references",
        items=(
            ("VISUAL", "Visual", "Import visual level content"),
            ("COLLISION", "Collision", "Import terrain heightfield and collision geometry only"),
        ),
        default="VISUAL",
    )

    client_root: StringProperty(
        name="Client Root",
        description="Required unpacked Aion client root for resolving level CGF and terrain texture references",
        subtype="DIR_PATH",
        default="",
    )

    limited_preview: BoolProperty(
        name="Limited Preview (Debug)",
        description="Apply template and placement limits for bounded debugging and smoke tests",
        default=False,
    )

    max_unique_cgfs: IntProperty(
        name="Preview Max Unique CGFs",
        description="Maximum unique CGF templates imported only in limited preview mode",
        default=10,
        min=1,
    )

    max_placements_per_template: IntProperty(
        name="Preview Placements per Template",
        description="Maximum placements per template created only in limited preview mode",
        default=3,
        min=1,
    )

    import_terrain: BoolProperty(
        name="Import Terrain Preview",
        description="Create a terrain mesh preview from terrain/land_map.h32",
        default=True,
    )

    import_terrain_textures: BoolProperty(
        name="Load Terrain Texture Preview",
        description="Explicitly load resolved terrain detail DDS files into simple material texture nodes",
        default=True,
    )

    import_terrain_blend_attributes: BoolProperty(
        name="Store Blend Weights (Advanced)",
        description="Store preview terrain material weights as Blender color attributes without shader blending",
        default=False,
    )

    import_terrain_blend_shader: BoolProperty(
        name="Terrain Blend Shader Preview (Experimental)",
        description="Create an experimental terrain material that reads AION_BlendWeights color attributes",
        default=True,
    )

    import_water: BoolProperty(
        name="Import Water Plane",
        description="Create a simple water plane from LevelInfo WaterLevel and heightmap dimensions",
        default=True,
    )

    import_textured_liquid_surface: BoolProperty(
        name="Import Textured Liquid Surface",
        description="Apply optional water/lava preview material to the imported liquid plane",
        default=True,
    )

    liquid_kind: EnumProperty(
        name="Liquid Kind",
        description="Select the liquid material family or infer it from level data",
        items=(
            (LIQUID_KIND_AUTO, "Auto", "Infer water/lava from level data and texture references"),
            (LIQUID_KIND_WATER, "Water", "Use water-like liquid material selection"),
            (LIQUID_KIND_LAVA, "Lava", "Use lava-like emissive liquid material selection"),
            (LIQUID_KIND_UNKNOWN, "Unknown", "Use fallback liquid material selection"),
        ),
        default=LIQUID_KIND_AUTO,
    )

    liquid_preset: EnumProperty(
        name="Liquid Preset",
        description="Choose a simple liquid material preset",
        items=(
            (LIQUID_PRESET_AUTO, "Auto", "Choose a conservative preset from liquid kind"),
            (LIQUID_PRESET_NORMAL, "Normal", "Water-style material with diffuse/normal candidates"),
            (LIQUID_PRESET_TRANSPARENT, "Transparent", "More transparent water-style material"),
            (LIQUID_PRESET_LAVA_EMISSIVE, "Lava Emissive", "Emissive lava-style material"),
        ),
        default=LIQUID_PRESET_AUTO,
    )

    import_static_lights: BoolProperty(
        name="Import Static Lights",
        description="Create optional point lights from staticdeferredlights.lst using confirmed raw coordinates",
        default=True,
    )

    static_lights_mode: EnumProperty(
        name="Static Lights Mode",
        description="Preview staticdeferredlights.lst as markers or Blender point lights",
        items=(
            (
                STATIC_LIGHTS_MODE_POINT_LIGHT,
                "Point Lights",
                "Create conservative Blender point lights",
            ),
            (
                STATIC_LIGHTS_MODE_EMPTY,
                "Markers",
                "Create non-rendering empty markers",
            ),
        ),
        default=STATIC_LIGHTS_MODE_POINT_LIGHT,
    )

    static_lights_power: FloatProperty(
        name="Static Light Power",
        description="Energy assigned to each imported static deferred point light",
        default=DEFAULT_STATIC_LIGHT_POWER,
        min=1.0,
        soft_max=5000.0,
    )

    import_mission_placeables: BoolProperty(
        name="Import Mission Placeables",
        description="Import high-confidence static PlaceableObject CGF references from mission_mission0.xml",
        default=True,
    )

    apply_mission_angles: BoolProperty(
        name="Apply Mission Angles",
        description="Apply Entity.Angles rotation for imported mission PlaceableObject previews",
        default=True,
    )

    import_particle_effects: BoolProperty(
        name="Import Particle Effects (Experimental, Heavy)",
        description="Create experimental ParticleEffect markers/sprites from entitycontexts*.lst and matching .prt libraries",
        default=False,
    )

    import_cga_entities: BoolProperty(
        name="Import CGA Entities (Experimental)",
        description="Import static mesh content from BasicEntity .cga references",
        default=True,
    )

    animate_cga_controllers: BoolProperty(
        name="Animate CGA Controllers (Experimental)",
        description="Apply decoded CGA rotation controller keyframes for imported CGA entities",
        default=True,
    )

    apply_smoothing_groups: BoolProperty(
        name="Apply CGF Smoothing Groups (Experimental)",
        description="Set imported CGF polygons smooth when the parsed face smoothing group is nonzero",
        default=False,
    )

    animate_texture_sequences: BoolProperty(
        name="Animate Texture Sequences",
        description="Use confirmed diffuse texture frame sequences as Blender image sequences for imported CGFs",
        default=True,
    )

    animate_shader_uv_scroll: BoolProperty(
        name="Animate Shader UV Scroll",
        description="Use confirmed client shader TexShift semantics to animate supported imported CGF material UVs",
        default=True,
    )

    texture_animation_fps: IntProperty(
        name="Texture Sequence FPS",
        description="Playback FPS for imported texture image sequences; shader UV scroll uses shader speed and scene time",
        default=10,
        min=1,
        max=60,
    )

    def execute(self, context):
        if not self.client_root:
            self.report({"ERROR"}, "Aion level import requires an unpacked Client Root")
            return {"CANCELLED"}

        visual_mode = self.import_mode == "VISUAL"
        effective_import_terrain = self.import_terrain if visual_mode else True
        effective_import_terrain_textures = (
            visual_mode and effective_import_terrain and self.import_terrain_textures
        )
        effective_import_terrain_blend_attributes = (
            visual_mode and effective_import_terrain and self.import_terrain_blend_attributes
        )
        effective_import_terrain_blend_shader = (
            visual_mode and effective_import_terrain and self.import_terrain_blend_shader
        )
        effective_import_water = visual_mode and self.import_water
        effective_import_textured_liquid_surface = (
            effective_import_water and self.import_textured_liquid_surface
        )
        effective_import_static_lights = visual_mode and self.import_static_lights
        effective_import_mission_placeables = visual_mode and self.import_mission_placeables
        effective_import_particle_effects = visual_mode and self.import_particle_effects
        effective_import_cga_entities = visual_mode and self.import_cga_entities
        effective_animate_cga_controllers = (
            effective_import_cga_entities and self.animate_cga_controllers
        )
        effective_animate_texture_sequences = visual_mode and self.animate_texture_sequences
        effective_animate_shader_uv_scroll = visual_mode and self.animate_shader_uv_scroll
        terrain_path = Path(self.filepath) / "terrain" / "land_map.h32"
        if effective_import_terrain and not terrain_path.is_file():
            self.report({"ERROR"}, f"Terrain preview file is missing: {terrain_path}")
            return {"CANCELLED"}

        result = import_level(
            context,
            self.filepath,
            self.client_root,
            import_mode=self.import_mode,
            limited_preview=self.limited_preview,
            max_unique_cgfs=self.max_unique_cgfs,
            max_placements_per_template=self.max_placements_per_template,
            import_terrain=effective_import_terrain,
            import_terrain_textures=effective_import_terrain_textures,
            import_terrain_blend_attributes=effective_import_terrain_blend_attributes,
            import_terrain_blend_shader=effective_import_terrain_blend_shader,
            import_water=effective_import_water,
            import_textured_liquid_surface=effective_import_textured_liquid_surface,
            liquid_kind=self.liquid_kind,
            liquid_preset=self.liquid_preset,
            import_static_lights=effective_import_static_lights,
            static_lights_mode=self.static_lights_mode,
            static_lights_power=self.static_lights_power,
            import_mission_placeables=effective_import_mission_placeables,
            apply_mission_angles=self.apply_mission_angles,
            import_particle_effects=effective_import_particle_effects,
            import_cga_entities=effective_import_cga_entities,
            animate_cga_controllers=effective_animate_cga_controllers,
            apply_smoothing_groups=self.apply_smoothing_groups,
            animate_texture_sequences=effective_animate_texture_sequences,
            animate_shader_uv_scroll=effective_animate_shader_uv_scroll,
            texture_animation_fps=self.texture_animation_fps,
        )

        failure_samples = _format_cgf_issues(result.failures)
        skip_samples = _format_cgf_issues(result.skipped_templates)
        water_failure = (
            f", water={result.water_result.skip_reason}"
            if result.water_result and result.water_result.skip_reason
            else ""
        )
        if (
            result.imported_template_count == 0
            and result.terrain_mesh_result is None
            and not (result.water_result and result.water_result.created)
            and not (result.liquid_surface_result and result.liquid_surface_result.applied)
            and not (result.static_lights_result and result.static_lights_result.created)
            and not (
                result.mission_placeables_result
                and result.mission_placeables_result.created_count
            )
            and not (
                result.particle_effects_result
                and (
                    result.particle_effects_result.sprite_visuals_created
                    or result.particle_effects_result.marker_fallback_created
                )
            )
            and not (
                result.cga_entities_result
                and result.cga_entities_result.created_count
            )
        ):
            self.report(
                {"ERROR"},
                "Aion level import failed: "
                f"selected={result.selected_template_count}, failed={result.failed_template_count}"
                f", skipped={result.skipped_template_count}"
                f"{failure_samples}{skip_samples}{water_failure}",
            )
            return {"CANCELLED"}

        report_type = (
            {"WARNING"}
            if result.failed_template_count
            or (effective_import_water and not result.summary.water_created)
            or (
                effective_import_textured_liquid_surface
                and result.liquid_surface_result
                and not result.liquid_surface_result.applied
            )
            or (
                effective_import_static_lights
                and result.static_lights_result
                and result.static_lights_result.failed_count
            )
            or (
                effective_import_mission_placeables
                and result.mission_placeables_result
                and result.mission_placeables_result.failed_count
            )
            or (
                effective_import_cga_entities
                and result.cga_entities_result
                and result.cga_entities_result.failed_count
            )
            else {"INFO"}
        )
        self.report(
            report_type,
            format_level_import_report(result.summary) + failure_samples + skip_samples,
        )
        return {"FINISHED"}

    def draw(self, context):
        layout = self.layout
        layout.use_property_split = True
        layout.use_property_decorate = False
        layout.prop(self, "import_mode")
        layout.prop(self, "client_root")
        if self.import_mode != "VISUAL":
            return
        layout.prop(self, "import_water")
        if self.import_water:
            layout.prop(self, "import_textured_liquid_surface")
            if self.import_textured_liquid_surface:
                layout.prop(self, "liquid_kind")
                layout.prop(self, "liquid_preset")
        layout.prop(self, "import_static_lights")
        if self.import_static_lights:
            layout.prop(self, "static_lights_mode")
            layout.prop(self, "static_lights_power")
        layout.prop(self, "import_mission_placeables")
        if self.import_mission_placeables:
            layout.prop(self, "apply_mission_angles")
        layout.prop(self, "import_particle_effects")
        layout.prop(self, "import_cga_entities")
        if self.import_cga_entities:
            layout.prop(self, "animate_cga_controllers")
        layout.prop(self, "animate_texture_sequences")
        layout.prop(self, "animate_shader_uv_scroll")
        if self.animate_texture_sequences:
            layout.prop(self, "texture_animation_fps")


def _format_cgf_issues(issues, limit=3):
    if not issues:
        return ""
    samples = "; ".join(
        f"{issue.resolved_path.name}:{issue.reason_code}"
        for issue in issues[:limit]
    )
    more = f"; +{len(issues) - limit} more" if len(issues) > limit else ""
    label = "failures" if issues[0].__class__.__name__.endswith("Failure") else "skips"
    return f"; {label}={samples}{more}"
