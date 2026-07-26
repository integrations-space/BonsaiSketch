# BonsaiBIM Sketch Mode - direct-modelling interaction for Bonsai
# Copyright (C) 2026 TODO
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

"""The Line tool.

Click to place points, type a distance to place one exactly, C to close the
loop, Enter or right-click to stop, Esc to abandon. A loop that closes -- by C
or by drawing back onto the first point -- is faced.

Geometry is committed when the stroke ends rather than segment by segment.
Bonsai's polyline engine keeps the whole run live until then, which is what
makes Backspace able to walk points back; committing early would strand
half-drawn geometry in the mesh the moment the user changed their mind.
"""

from __future__ import annotations

import bpy

from .. import bridge, sketchmesh
from .base import PolylineToolBase


class BONSAIBIM_SKETCH_OT_line(bpy.types.Operator, PolylineToolBase):
    bl_idname = "bonsaibim_sketch_mode.line"
    bl_label = "Line"
    bl_description = "Draw connected edges. Type a distance for an exact length"
    bl_options = {"REGISTER", "UNDO"}

    custom_instructions = {
        "Place Point": {"icons": True, "keys": ["MOUSE_LMB"]},
        "Finish": {"icons": True, "keys": ["EVENT_RETURN"]},
        "Choose Axis": {"icons": True, "keys": ["EVENT_X", "EVENT_Y", "EVENT_Z"]},
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
            return self.finish(context)

        self.handle_keyboard_input(context, event)
        self.handle_inserting_polyline(context, event)

        # C, or a click back onto the first point, closes the loop -- and a
        # closed loop is the end of the stroke.
        if self.is_closed(self.polyline_vectors()):
            return self.finish(context)

        cancelled = self.handle_cancelation(context, event)
        if cancelled is not None:
            return cancelled

        return {"RUNNING_MODAL"}

    def finish(self, context: bpy.types.Context) -> set[str]:
        points = self.polyline_vectors()
        closed = self.is_closed(points)
        if closed:
            # The repeated first point tells us it is closed; the edge loop
            # carries that information from here on.
            points = points[:-1]

        self.teardown(context)

        if len(points) < 2:
            return {"CANCELLED"}

        obj, faces = sketchmesh.commit(context, points, close=closed)
        if obj is None:
            self.report({"WARNING"}, "Nothing to draw")
            return {"CANCELLED"}

        segments = len(points) if closed else len(points) - 1
        detail = f", {faces} face{'s' if faces != 1 else ''}" if faces else ""
        self.report({"INFO"}, f"{segments} edge{'s' if segments != 1 else ''}{detail} in {obj.name}")
        bridge.update_viewport()
        return {"FINISHED"}
