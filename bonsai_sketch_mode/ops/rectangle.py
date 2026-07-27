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

"""The Rectangle tool.

Two clicks give opposite corners. The polyline engine supplies both -- so
snapping, axis locks and typed coordinates all work exactly as they do for
Line -- and the other two corners are derived from them.

Which plane the rectangle lies in comes from the polyline's plane lock when the
user has set one (shift+X/Y/Z), and otherwise from the corners themselves: two
points at the same height describe a rectangle on the ground, two points in a
common vertical plane describe one standing up.
"""

from __future__ import annotations

from typing import Optional

import bpy
from mathutils import Vector

from .. import bridge, sketchmesh
from .base import COINCIDENT, PolylineToolBase


def infer_plane(start: Vector, end: Vector) -> str:
    """The plane two opposite corners describe: "XY", "XZ" or "YZ"."""
    if abs(end.z - start.z) <= COINCIDENT:
        return "XY"
    if abs(end.y - start.y) <= COINCIDENT:
        return "XZ"
    if abs(end.x - start.x) <= COINCIDENT:
        return "YZ"
    # A free diagonal in space does not describe one rectangle. Flattening onto
    # the horizontal matches where the polyline engine drops unsnapped points.
    return "XY"


def corners(start: Vector, end: Vector, plane: str) -> Optional[list[Vector]]:
    """The four corners in winding order, or None if the rectangle is degenerate."""
    if plane == "XZ":
        if abs(end.x - start.x) <= COINCIDENT or abs(end.z - start.z) <= COINCIDENT:
            return None
        return [
            Vector((start.x, start.y, start.z)),
            Vector((end.x, start.y, start.z)),
            Vector((end.x, start.y, end.z)),
            Vector((start.x, start.y, end.z)),
        ]
    if plane == "YZ":
        if abs(end.y - start.y) <= COINCIDENT or abs(end.z - start.z) <= COINCIDENT:
            return None
        return [
            Vector((start.x, start.y, start.z)),
            Vector((start.x, end.y, start.z)),
            Vector((start.x, end.y, end.z)),
            Vector((start.x, start.y, end.z)),
        ]
    if abs(end.x - start.x) <= COINCIDENT or abs(end.y - start.y) <= COINCIDENT:
        return None
    return [
        Vector((start.x, start.y, start.z)),
        Vector((end.x, start.y, start.z)),
        Vector((end.x, end.y, start.z)),
        Vector((start.x, end.y, start.z)),
    ]


class BONSAI_SKETCH_MODE_OT_rectangle(bpy.types.Operator, PolylineToolBase):
    bl_idname = "bonsai_sketch_mode.rectangle"
    bl_label = "Rectangle"
    bl_description = "Draw a rectangle from two opposite corners"
    bl_options = {"REGISTER", "UNDO"}

    custom_instructions = {
        "Place Corner": {"icons": True, "keys": ["MOUSE_LMB"]},
        "Choose Plane": {"icons": True, "keys": ["EVENT_SHIFT", "EVENT_X", "EVENT_Y", "EVENT_Z"]},
    }

    def __init__(self, *args, **kwargs):
        bpy.types.Operator.__init__(self, *args, **kwargs)
        self.init_polyline()

    def modal(self, context: bpy.types.Context, event: bpy.types.Event):
        result = self.handle_common(context, event)
        if result is not None:
            return result

        if self.wants_finish(event):
            # Right-click or Enter before the second corner abandons the stroke.
            self.teardown(context)
            return {"CANCELLED"}

        self.handle_keyboard_input(context, event)
        self.handle_inserting_polyline(context, event)

        if len(self.polyline_vectors()) >= 2:
            return self.finish(context)

        cancelled = self.handle_cancelation(context, event)
        if cancelled is not None:
            return cancelled

        return {"RUNNING_MODAL"}

    def finish(self, context: bpy.types.Context) -> set[str]:
        points = self.polyline_vectors()
        plane = self.tool_state.plane_method or infer_plane(points[0], points[1])
        rectangle = corners(points[0], points[1], plane)

        self.teardown(context)

        if rectangle is None:
            self.report({"WARNING"}, "Those corners have no area")
            return {"CANCELLED"}

        obj, faces = sketchmesh.commit(context, rectangle, close=True)
        if obj is None:
            self.report({"WARNING"}, "Nothing to draw")
            return {"CANCELLED"}

        self.report(
            {"INFO"},
            f"Rectangle on {plane}" + (f" ({faces} face)" if faces else " (edges only)") + f" in {obj.name}",
        )
        bridge.update_viewport()
        return {"FINISHED"}
