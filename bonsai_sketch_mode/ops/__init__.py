# Bonsai Sketch Mode - direct-modelling interaction for Bonsai
# Copyright (C) 2026 Innovations & Integrations
#
# This program is free software: you can redistribute it and/or modify
# it under the terms of the GNU General Public License as published by
# the Free Software Foundation, either version 3 of the License, or
# (at your option) any later version.
#
# This program is distributed in the hope that it will be useful,
# but WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
# GNU General Public License for more details.
#
# You should have received a copy of the GNU General Public License
# along with this program.  If not, see <http://www.gnu.org/licenses/>.

"""Sketch Mode's modal tools.

Each module here is one tool. They register even when Bonsai's polyline engine
is missing -- their poll methods return False in that case, so the toolbar
shows them greyed out with a reason rather than the tool silently vanishing.
"""

from __future__ import annotations

import bpy

from .eraser import BONSAI_SKETCH_MODE_OT_eraser
from .importer import (
    BONSAI_SKETCH_MODE_OT_import_cad,
    BONSAI_SKETCH_MODE_OT_stand_up,
    BONSAI_SKETCH_MODE_MT_sketch,
    sketch_menu_entry,
    menu_entry,
    object_menu_entry,
)
from .line import BONSAI_SKETCH_MODE_OT_line
from .camera import (
    BONSAI_SKETCH_MODE_OT_camera_from_view,
    BONSAI_SKETCH_MODE_OT_camera_two_point,
)
from .offset import BONSAI_SKETCH_MODE_OT_offset
from .drawing_project import BONSAI_SKETCH_MODE_OT_build_drawing_project
from .pushpull import BONSAI_SKETCH_MODE_OT_push_pull
from .rectangle import BONSAI_SKETCH_MODE_OT_rectangle

LINE_OP = BONSAI_SKETCH_MODE_OT_line.bl_idname
RECTANGLE_OP = BONSAI_SKETCH_MODE_OT_rectangle.bl_idname
PUSH_PULL_OP = BONSAI_SKETCH_MODE_OT_push_pull.bl_idname
OFFSET_OP = BONSAI_SKETCH_MODE_OT_offset.bl_idname
ERASER_OP = BONSAI_SKETCH_MODE_OT_eraser.bl_idname
IMPORT_OP = BONSAI_SKETCH_MODE_OT_import_cad.bl_idname

classes = (
    BONSAI_SKETCH_MODE_OT_build_drawing_project,
    BONSAI_SKETCH_MODE_OT_line,
    BONSAI_SKETCH_MODE_OT_rectangle,
    BONSAI_SKETCH_MODE_OT_push_pull,
    BONSAI_SKETCH_MODE_OT_offset,
    BONSAI_SKETCH_MODE_OT_eraser,
    BONSAI_SKETCH_MODE_OT_import_cad,
    BONSAI_SKETCH_MODE_OT_stand_up,
    BONSAI_SKETCH_MODE_OT_camera_from_view,
    BONSAI_SKETCH_MODE_OT_camera_two_point,
    BONSAI_SKETCH_MODE_MT_sketch,
)


def register() -> None:
    for cls in classes:
        bpy.utils.register_class(cls)
    bpy.types.TOPBAR_MT_file_import.append(menu_entry)
    bpy.types.VIEW3D_MT_object.append(object_menu_entry)
    bpy.types.VIEW3D_MT_editor_menus.append(sketch_menu_entry)


def unregister() -> None:
    for menu, entry in (
        (bpy.types.TOPBAR_MT_file_import, menu_entry),
        (bpy.types.VIEW3D_MT_object, object_menu_entry),
        (bpy.types.VIEW3D_MT_editor_menus, sketch_menu_entry),
    ):
        try:
            menu.remove(entry)
        except Exception:
            pass
    for cls in reversed(classes):
        try:
            bpy.utils.unregister_class(cls)
        except RuntimeError:
            pass
