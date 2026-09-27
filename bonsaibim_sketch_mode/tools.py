# BonsaiBIM Sketch Mode - direct-modelling interaction for Bonsai
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

"""The Sketch tools, as entries in the 3D View toolbar.

A SketchUp user reaches for a tool two ways: the palette, or the letter key.
The keyconfig covers the letters; this covers the palette, so the toolset is
discoverable without already knowing the shortcuts.

Every tool starts its modal on left-mouse press. The modal operators then read
the *release* of that same click as their first action -- placing the first
polyline point, or arming the Push/Pull drag -- which is why press and release
are not bound to different things here.

Icons are Blender's own. Shipping bespoke artwork for tools whose behaviour is
still settling would date faster than it helps.
"""

from __future__ import annotations

import bpy
from bpy.types import WorkSpaceTool

from . import bridge, ops

LINE_TOOL = "bonsaibim_sketch_mode.line_tool"
RECTANGLE_TOOL = "bonsaibim_sketch_mode.rectangle_tool"
PUSH_PULL_TOOL = "bonsaibim_sketch_mode.push_pull_tool"
OFFSET_TOOL = "bonsaibim_sketch_mode.offset_tool"
ERASER_TOOL = "bonsaibim_sketch_mode.eraser_tool"
TAPE_TOOL = "bonsaibim_sketch_mode.tape_tool"

#: Blender's stock select tool, which Sketch binds to Space.
SELECT_TOOL = "builtin.select_box"


def _unavailable_note(layout: bpy.types.UILayout) -> bool:
    """Explain a missing Bonsai in the tool settings bar. True if we drew one."""
    if bridge.polyline_engine_available():
        return False
    row = layout.row()
    row.alert = True
    row.label(text=bridge.polyline_unavailable_reason() or "Bonsai is unavailable", icon="ERROR")
    return True


class SketchLineTool(WorkSpaceTool):
    bl_space_type = "VIEW_3D"
    bl_context_mode = "OBJECT"
    bl_idname = LINE_TOOL
    bl_label = "Line"
    bl_description = "Draw connected edges. Closed coplanar loops become faces"
    bl_icon = "ops.gpencil.primitive_polyline"
    bl_widget = None
    bl_keymap = ((ops.LINE_OP, {"type": "LEFTMOUSE", "value": "PRESS"}, None),)

    @staticmethod
    def draw_settings(context, layout, ws_tool):
        if _unavailable_note(layout):
            return
        row = layout.row(align=True)
        row.label(text="Place Point", icon="MOUSE_LMB")
        row = layout.row(align=True)
        row.label(text="Close Loop", icon="EVENT_C")
        row = layout.row(align=True)
        row.label(text="Finish", icon="EVENT_RETURN")


class SketchRectangleTool(WorkSpaceTool):
    bl_space_type = "VIEW_3D"
    bl_context_mode = "OBJECT"
    bl_idname = RECTANGLE_TOOL
    bl_label = "Rectangle"
    bl_description = "Draw a rectangle from two opposite corners"
    bl_icon = "ops.gpencil.primitive_box"
    bl_widget = None
    bl_keymap = ((ops.RECTANGLE_OP, {"type": "LEFTMOUSE", "value": "PRESS"}, None),)

    @staticmethod
    def draw_settings(context, layout, ws_tool):
        if _unavailable_note(layout):
            return
        row = layout.row(align=True)
        row.label(text="Place Corner", icon="MOUSE_LMB")
        row = layout.row(align=True)
        row.label(text="", icon="EVENT_SHIFT")
        row.label(text="Lock Plane", icon="EVENT_X")


class SketchPushPullTool(WorkSpaceTool):
    bl_space_type = "VIEW_3D"
    bl_context_mode = "OBJECT"
    bl_idname = PUSH_PULL_TOOL
    bl_label = "Push/Pull"
    bl_description = "Extrude the face under the cursor along its normal"
    bl_icon = "ops.mesh.extrude_region_move"
    bl_widget = None
    bl_keymap = ((ops.PUSH_PULL_OP, {"type": "LEFTMOUSE", "value": "PRESS"}, None),)

    @staticmethod
    def draw_settings(context, layout, ws_tool):
        row = layout.row(align=True)
        row.label(text="Drag a Face", icon="MOUSE_LMB")
        row = layout.row(align=True)
        row.label(text="Type an exact distance to confirm", icon="EVENT_RETURN")


class SketchOffsetTool(WorkSpaceTool):
    bl_space_type = "VIEW_3D"
    bl_context_mode = "OBJECT"
    bl_idname = OFFSET_TOOL
    bl_label = "Offset"
    bl_description = "Copy a face's boundary parallel to itself, inward or outward"
    bl_icon = "ops.mesh.inset"
    bl_widget = None
    bl_keymap = ((ops.OFFSET_OP, {"type": "LEFTMOUSE", "value": "PRESS"}, None),)

    @staticmethod
    def draw_settings(context, layout, ws_tool):
        row = layout.row(align=True)
        row.label(text="Drag a Face", icon="MOUSE_LMB")
        row = layout.row(align=True)
        row.label(text="Toward the centre is inward; type an exact distance", icon="EVENT_RETURN")


class SketchEraserTool(WorkSpaceTool):
    bl_space_type = "VIEW_3D"
    bl_context_mode = "OBJECT"
    bl_idname = ERASER_TOOL
    bl_label = "Eraser"
    bl_description = "Erase sketch edges; faces they bounded go with them"
    bl_icon = "ops.gpencil.draw.eraser"
    bl_widget = None
    bl_keymap = ((ops.ERASER_OP, {"type": "LEFTMOUSE", "value": "PRESS"}, None),)

    @staticmethod
    def draw_settings(context, layout, ws_tool):
        row = layout.row(align=True)
        row.label(text="Click or Drag Over Edges", icon="MOUSE_LMB")
        row = layout.row(align=True)
        row.label(text="Esc undoes the sweep", icon="EVENT_ESC")


class SketchTapeTool(WorkSpaceTool):
    """SketchUp's Tape Measure, which is Bonsai's Measure Tool already.

    Bonsai's measure operator does everything the tape does -- snapping,
    imperial and metric readout, persistent measurement overlay -- so this is a
    toolbar entry pointing at it rather than a reimplementation.
    """

    bl_space_type = "VIEW_3D"
    bl_context_mode = "OBJECT"
    bl_idname = TAPE_TOOL
    bl_label = "Tape Measure"
    bl_description = "Measure a distance between two snapped points"
    bl_icon = "ops.view3d.ruler"
    bl_widget = None
    bl_keymap = (
        (
            bridge.MEASURE_OP,
            {"type": "LEFTMOUSE", "value": "PRESS"},
            {"properties": [("measure_type", "SINGLE")]},
        ),
    )

    @staticmethod
    def draw_settings(context, layout, ws_tool):
        if _unavailable_note(layout):
            return
        row = layout.row(align=True)
        row.label(text="Measure", icon="MOUSE_LMB")
        row = layout.row(align=True)
        row.operator(bridge.CLEAR_MEASUREMENT_OP, text="Clear Measurements", icon="X")


#: Order matters: this is the order they appear in the toolbar.
tools = (
    SketchLineTool,
    SketchRectangleTool,
    SketchPushPullTool,
    SketchOffsetTool,
    SketchEraserTool,
    SketchTapeTool,
)


def register() -> tuple[bool, str]:
    """Add the Sketch tools to the 3D View toolbar. Returns (ok, message).

    Never raises: Blender's tool registry is keyed by idname across all
    add-ons, so a clash or a version change here should cost us the toolbar,
    not the whole add-on.
    """
    added = []
    try:
        for index, cls in enumerate(tools):
            bpy.utils.register_tool(cls, after={added[-1]} if added else None, separator=not index)
            added.append(cls.bl_idname)
    except Exception as exc:  # pragma: no cover - depends on host Blender
        for idname in reversed(added):
            _safe_unregister(idname)
        return False, f"Could not add the Sketch tools to the toolbar: {exc}"
    return True, f"{len(added)} Sketch tools in the 3D View toolbar"


def _safe_unregister(idname: str) -> None:
    for cls in tools:
        if cls.bl_idname == idname:
            try:
                bpy.utils.unregister_tool(cls)
            except Exception:
                pass
            return


def unregister() -> None:
    for cls in reversed(tools):
        try:
            bpy.utils.unregister_tool(cls)
        except Exception:
            pass
