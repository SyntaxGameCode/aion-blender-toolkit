import bpy
from bpy.props import BoolProperty, EnumProperty, IntProperty, StringProperty
from bpy_extras.io_utils import ImportHelper

from ..cgf_importer import get_last_import_report, load


class AION_OT_import_cgf(bpy.types.Operator, ImportHelper):
    bl_idname = "import_scene.aion_cgf"
    bl_label = "Import Aion CGF/CGA"
    bl_description = "Import a single Aion CGF or static CGA file"
    bl_options = {"PRESET", "UNDO"}

    filename_ext = ".cgf"
    filter_glob: StringProperty(
        default="*.cgf;*.cga",
        options={"HIDDEN"},
        maxlen=255,
    )

    import_mode: EnumProperty(
        name="Import Mode",
        description="What to import from CGF",
        items=(
            ("VISUAL", "Visual", "Import visual geometry and optional visual material animation"),
            ("COLLISION", "Collision", "Import collision geometry only"),
        ),
        default="VISUAL",
    )

    apply_smoothing_groups: BoolProperty(
        name="Apply CGF Smoothing Groups (Experimental)",
        description="Set Blender polygons smooth when the parsed CGF face smoothing group is nonzero",
        default=False,
    )

    animate_texture_sequences: BoolProperty(
        name="Animate Texture Sequences",
        description="Use confirmed diffuse texture frame sequences as Blender image sequences",
        default=True,
    )

    animate_shader_uv_scroll: BoolProperty(
        name="Animate Shader UV Scroll",
        description="Use confirmed client shader TexShift semantics to animate supported material UVs",
        default=True,
    )

    animate_cga_controllers: BoolProperty(
        name="Animate CGA Controllers (Experimental)",
        description="Apply decoded CGA rotation controller keyframes when controller data is understood",
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
        visual_mode = self.import_mode == "VISUAL"
        result = load(
            context,
            self.filepath,
            import_mode=self.import_mode,
            apply_smoothing_groups=self.apply_smoothing_groups,
            animate_texture_sequences=visual_mode and self.animate_texture_sequences,
            animate_shader_uv_scroll=visual_mode and self.animate_shader_uv_scroll,
            animate_cga_controllers=visual_mode and self.animate_cga_controllers,
            texture_animation_fps=self.texture_animation_fps,
        )
        if result == {"FINISHED"}:
            self.report({"INFO"}, "Aion CGF import finished")
        else:
            report = get_last_import_report()
            reason = report.reason_code if report and report.reason_code else "unknown"
            self.report({"ERROR"}, f"Aion CGF import did not finish: {reason}")
        return result

    def draw(self, context):
        layout = self.layout
        layout.use_property_split = True
        layout.use_property_decorate = False
        layout.prop(self, "import_mode")
        layout.prop(self, "apply_smoothing_groups")
        if self.import_mode != "VISUAL":
            return
        layout.prop(self, "animate_texture_sequences")
        layout.prop(self, "animate_shader_uv_scroll")
        layout.prop(self, "animate_cga_controllers")
        if self.animate_texture_sequences:
            layout.prop(self, "texture_animation_fps")
