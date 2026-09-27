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

"""The Eraser tool.

Click an edge to erase it; hold and drag to sweep over several. Erasing an
edge takes the faces it bounded with it -- rub out one side of a rectangle and
the fill goes too, exactly as in SketchUp -- and endpoints left connected to
nothing disappear rather than litter the sketch with invisible stray vertices.

Edges are found in screen space, not by raycast: a sketch is mostly bare
strokes whose loops have not closed yet, and a ray only ever reports faces.

The eraser works on sketch geometry only. It does not delete IFC elements --
an element is a modelled decision with data hanging off it, and Bonsai's own
delete handles the IFC consequences; a stroke eraser should not. A drag also
stays on the object it started on, so sweeping past a neighbouring sketch
cannot take out strokes the user never aimed at.
"""

from __future__ import annotations

from typing import Iterable, Optional

import bmesh
import bpy

from .. import bridge, sketchmesh, viewport

#: How close the cursor must be to an edge to erase it, in screen pixels.
PICK_PIXELS = 10.0


def erased(source: bmesh.types.BMesh, edge_indices: Iterable[int]) -> bmesh.types.BMesh:
    """A copy of ``source`` with the given edges gone.

    Faces bounded by a deleted edge are deleted with it, and endpoints the
    deletion left with no edges are swept up too. The caller owns the returned
    bmesh.
    """
    bm = source.copy()
    bm.edges.ensure_lookup_table()
    doomed = [bm.edges[i] for i in edge_indices]
    # The endpoints are noted before the edges go, because afterwards there is
    # no way back to them -- and only these are candidates for sweeping up. A
    # loose vertex that was already sitting in the mesh is somebody else's,
    # possibly a snap target the user placed, and erasing an unrelated edge is
    # not the moment to decide it is litter.
    endpoints = {v for edge in doomed for v in edge.verts}
    # Removed one by one rather than through bmesh.ops.delete: its "EDGES"
    # context handles face-bearing edges but leaves *wire* edges standing,
    # and bare strokes are most of what a sketch is. BMEdgeSeq.remove is
    # BM_edge_kill underneath, which takes the faces using the edge with it
    # -- exactly the eraser's contract -- wire or not.
    for edge in doomed:
        bm.edges.remove(edge)
    stranded = [v for v in endpoints if v.is_valid and not v.link_edges]
    if stranded:
        bmesh.ops.delete(bm, geom=stranded, context="VERTS")
    return bm


class BONSAIBIM_SKETCH_OT_eraser(bpy.types.Operator):
    bl_idname = "bonsaibim_sketch_mode.eraser"
    bl_label = "Eraser"
    bl_description = "Erase the edge under the cursor; drag to sweep over several"
    bl_options = {"REGISTER", "UNDO"}

    @classmethod
    def poll(cls, context: bpy.types.Context) -> bool:
        space = context.space_data
        return space is not None and space.type == "VIEW_3D" and context.mode == "OBJECT"

    def __init__(self, *args, **kwargs):
        bpy.types.Operator.__init__(self, *args, **kwargs)
        self.obj: Optional[bpy.types.Object] = None
        self.source: Optional[bmesh.types.BMesh] = None
        self.count = 0

    def invoke(self, context: bpy.types.Context, event: bpy.types.Event) -> set[str]:
        mouse = (event.mouse_region_x, event.mouse_region_y)
        candidates = [
            obj for obj in context.visible_objects if sketchmesh.is_sketch_object(obj)
        ]
        hit = viewport.nearest_edge_2d(context, mouse, candidates, PICK_PIXELS)
        if hit is None:
            # Distinguish "missed" from "aimed at something the eraser refuses"
            # -- silence about the refusal would read as a broken tool.
            face = viewport.ray_cast_face(context, mouse)
            if face is not None and bridge.get_entity(face.obj) is not None:
                self.report(
                    {"WARNING"},
                    f"{face.obj.name} is an IFC element; delete it with Bonsai's own "
                    "delete, which handles the IFC side",
                )
            else:
                self.report({"INFO"}, "No edge under the cursor")
            return {"CANCELLED"}

        self.obj = hit.obj
        self.source = bmesh.new()
        self.source.from_mesh(hit.obj.data)
        self.count = 0

        self.erase(hit.edge_index)

        # A sweep is only meaningful while a button is held, and the only thing
        # that establishes that is having been invoked by its press. Launched
        # any other way -- a keybinding straight onto the operator, the search
        # menu, a script -- there is no release coming to end the modal, and a
        # modal that erases on plain MOUSEMOVE would then eat every stroke the
        # cursor passed. So that case erases the one edge aimed at and stops.
        if not (event.type == "LEFTMOUSE" and event.value == "PRESS"):
            return self.confirm(context)

        context.workspace.status_text_set(
            text="Drag over edges to erase    Release: done    Esc: undo the sweep"
        )
        context.window_manager.modal_handler_add(self)
        return {"RUNNING_MODAL"}

    def erase(self, edge_index: int) -> None:
        """Erase one edge of the locked object, by its current index."""
        assert self.obj is not None
        bm = bmesh.new()
        try:
            bm.from_mesh(self.obj.data)
            trimmed = erased(bm, [edge_index])
        finally:
            bm.free()
        try:
            trimmed.to_mesh(self.obj.data)
        finally:
            trimmed.free()
        self.obj.data.update()
        self.count += 1
        bridge.update_viewport()

    def modal(self, context: bpy.types.Context, event: bpy.types.Event):
        if event.type in {"MIDDLEMOUSE", "WHEELUPMOUSE", "WHEELDOWNMOUSE"}:
            return {"PASS_THROUGH"}

        if event.type in {"MOUSEMOVE", "INBETWEEN_MOUSEMOVE"}:
            assert self.obj is not None
            mouse = (event.mouse_region_x, event.mouse_region_y)
            hit = viewport.nearest_edge_2d(context, mouse, [self.obj], PICK_PIXELS)
            if hit is not None:
                self.erase(hit.edge_index)
            return {"RUNNING_MODAL"}

        if event.value == "RELEASE" and event.type == "LEFTMOUSE":
            return self.confirm(context)

        if event.value == "PRESS" and event.type in {"ESC", "RIGHTMOUSE"}:
            return self.cancel_modal(context)

        return {"RUNNING_MODAL"}

    def confirm(self, context: bpy.types.Context) -> set[str]:
        assert self.obj is not None
        name = self.obj.name
        count = self.count
        emptied = len(self.obj.data.vertices) == 0
        if emptied:
            # A sketch erased down to nothing is gone, not an invisible empty
            # object left to puzzle over in a selection cycle.
            bpy.data.objects.remove(self.obj, do_unlink=True)
            self.obj = None
        self.clear_state(context)
        bridge.update_viewport()
        plural = "edge" if count == 1 else "edges"
        suffix = f"; {name} is empty and was removed" if emptied else f" from {name}"
        self.report({"INFO"}, f"Erased {count} {plural}{suffix}")
        return {"FINISHED"}

    def cancel_modal(self, context: bpy.types.Context) -> set[str]:
        """Esc puts back everything this sweep erased."""
        if self.obj is not None and self.source is not None:
            self.source.to_mesh(self.obj.data)
            self.obj.data.update()
        self.clear_state(context)
        bridge.update_viewport()
        return {"CANCELLED"}

    def clear_state(self, context: bpy.types.Context) -> None:
        context.workspace.status_text_set(text=None)
        if self.source is not None:
            self.source.free()
            self.source = None

    def cancel(self, context: bpy.types.Context) -> None:
        """Blender's hook for a modal cut short from outside; our own exits
        have already cleaned up, which the ``source`` guard detects."""
        if self.source is None:
            return
        if self.obj is not None:
            self.source.to_mesh(self.obj.data)
            self.obj.data.update()
        self.clear_state(context)
