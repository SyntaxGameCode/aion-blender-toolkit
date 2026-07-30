bl_info = {
    "name": "Aion Importer",
    "author": "Aion Blender Toolkit",
    "version": (0, 4, 32),
    "blender": (4, 0, 0),
    "location": "File > Import",
    "description": "Import Aion CGF assets",
    "category": "Import-Export",
}

__version__ = ".".join(str(part) for part in bl_info["version"])

import sys
from pathlib import Path


_VENDOR_DIR = Path(__file__).resolve().parent / "_vendor"
_REPO_AION_FORMATS_DIR = Path(__file__).resolve().parents[2] / "aion_formats"


def _is_relative_to(path, parent):
    try:
        path.resolve().relative_to(parent.resolve())
    except ValueError:
        return False
    return True


def _drop_cached_aion_formats():
    for module_name in list(sys.modules):
        if module_name == "aion_formats" or module_name.startswith("aion_formats."):
            sys.modules.pop(module_name, None)


if _VENDOR_DIR.is_dir():
    _drop_cached_aion_formats()
    if str(_VENDOR_DIR) not in sys.path:
        sys.path.insert(0, str(_VENDOR_DIR))
else:
    _loaded_aion_formats = sys.modules.get("aion_formats")
    _loaded_file = getattr(_loaded_aion_formats, "__file__", None)
    if _loaded_file and not _is_relative_to(Path(_loaded_file), _REPO_AION_FORMATS_DIR):
        _drop_cached_aion_formats()

import bpy

from .operators.import_cgf import AION_OT_import_cgf
from .operators.import_level import AION_OT_import_level_folder


def menu_func_import(self, context):
    self.layout.operator(AION_OT_import_cgf.bl_idname, text="Aion CGF (.cgf)")
    self.layout.operator(AION_OT_import_level_folder.bl_idname, text="Aion Level Folder")


classes = (AION_OT_import_cgf, AION_OT_import_level_folder)


def register():
    for cls in classes:
        bpy.utils.register_class(cls)
    bpy.types.TOPBAR_MT_file_import.append(menu_func_import)


def unregister():
    try:
        bpy.types.TOPBAR_MT_file_import.remove(menu_func_import)
    except ValueError:
        pass
    for cls in reversed(classes):
        try:
            bpy.utils.unregister_class(cls)
        except RuntimeError as exc:
            if "missing bl_rna" not in str(exc):
                raise


if __name__ == "__main__":
    register()
