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

"""The Offset tool.

Press on a face and drag: its boundary is copied parallel to itself at the
dragged distance, splitting the face into a border ring and an inner face --
SketchUp's Offset, the stroke behind door frames, wall thicknesses and window
reveals. Dragging toward the face's centre offsets inward; away from it,
outward, growing a ring beyond the boundary. Type a number for an exact
distance; the drag direction decides which side it lands.

Like Push/Pull, the result is real from the first pixel of movement -- the
mesh is rebuilt from a pristine copy on every event, so what is on screen is
the actual geometry, not a preview of it. And like Push/Pull, IFC elements are
declined rather than tessellated.
"""

from __future__ import annotations

from typing import Callable, Optional

import bmesh
import bpy
from mathutils import Vector
from mathutils.geometry import intersect_line_plane

from .. import bridge, viewport

# The same characters and thresholds as Push/Pull's measurement box, so the
# two tools parse and judge input identically.
from .pushpull import NEGLIGIBLE, NUMBER_CHARS


#: Below this, a corner's mitre is too shallow to reach the asked distance
#: without shooting off toward infinity, so the reach is capped and the corner
#: lands short. The value is a sine of half the interior angle, so 0.05 is a
#: corner of about 5.7 degrees -- sharper than anything a wall or reveal makes,
#: and the cap is still 20x the asked distance at that point.
MITRE_FLOOR = 0.05


def offsetted(
    source: bmesh.types.BMesh,
    face_index: int,
    distance: float,
    on_clamp: Optional[Callable[[int], None]] = None,
) -> bmesh.types.BMesh:
    """A copy of ``source`` with one face's boundary offset by ``distance``.

    Positive offsets inward -- the original face becomes the inner one, ringed
    by new border faces. Negative offsets outward, growing the ring beyond the
    original boundary. ``distance`` is in the mesh's local units; the caller
    resolves object scale, and owns the returned bmesh.

    ``on_clamp`` is called with the number of corners too sharp to offset
    exactly, when there are any. Those corners land short of ``distance``, and
    a tool whose whole promise is an exact distance should say so rather than
    quietly miss.
    """
    bm = source.copy()
    if abs(distance) <= NEGLIGIBLE:
        return bm
    bm.faces.ensure_lookup_table()
    face = bm.faces[face_index]
    if distance > 0.0:
        bmesh.ops.inset_region(
            bm,
            faces=[face],
            thickness=distance,
            depth=0.0,
            use_boundary=True,
            use_even_offset=True,
        )
    else:
        clamped = _outset_ring(bm, face, -distance)
        if clamped and on_clamp is not None:
            on_clamp(clamped)
    bm.normal_update()
    return bm


def _outset_ring(bm: bmesh.types.BMesh, face: bmesh.types.BMFace, distance: float) -> int:
    """Grow a ring of faces outside ``face``'s boundary, ``distance`` wide.

    Returns how many corners were too sharp to honour exactly.

    Built by hand because inset_region's own ``use_outset`` works by insetting
    the faces *around* the target -- and a lone sheet face, the very thing
    Offset outward is for, has nothing around it, so the flag silently does
    nothing there. Each boundary vertex instead slides along its exterior
    mitre, scaled so every edge of the new loop sits exactly ``distance`` from
    the edge it came from -- the same even-offset rule the inward case gets
    from inset_region.
    """
    normal = face.normal
    old = [loop.vert for loop in face.loops]
    count = len(old)

    grown = []
    clamped = 0
    for i in range(count):
        before = old[i - 1].co
        here = old[i].co
        after = old[(i + 1) % count].co
        arriving = (here - before).normalized()
        leaving = (after - here).normalized()
        # Loop order follows the face winding, so cross(edge, normal) points
        # away from the interior.
        out_arriving = arriving.cross(normal).normalized()
        out_leaving = leaving.cross(normal).normalized()
        mitre = out_arriving + out_leaving
        if mitre.length <= NEGLIGIBLE:
            mitre = out_arriving.copy()  # a hairpin corner; no bisector to bisect
        mitre.normalize()
        # The clamp stops a near-hairpin corner shooting its mitre to infinity.
        # It is counted, not hidden: past MITRE_FLOOR the new edges land short
        # of the asked distance, and the caller is told so.
        spread = mitre.dot(out_leaving)
        if spread < MITRE_FLOOR:
            clamped += 1
        reach = distance / max(spread, MITRE_FLOOR)
        grown.append(bm.verts.new(here + mitre * reach))

    for i in range(count):
        after = (i + 1) % count
        ring = bm.faces.new((old[i], grown[i], grown[after], old[after]))
        # The quad's winding above is arbitrary; the sheet's orientation is
        # not. Recalc is avoided on purpose -- on an open sheet its inside /
        # outside heuristic may flip the original face too.
        ring.normal_update()
        if ring.normal.dot(normal) < 0:
            ring.normal_flip()

    return clamped


class BONSAIBIM_SKETCH_OT_offset(bpy.types.Operator):
    bl_idname = "bonsaibim_sketch_mode.offset"
    bl_label = "Offset"
    bl_description = "Copy the boundary of the face under the cursor parallel to itself"
    bl_options = {"REGISTER", "UNDO"}

    @classmethod
    def poll(cls, context: bpy.types.Context) -> bool:
        space = context.space_data
        return space is not None and space.type == "VIEW_3D" and context.mode == "OBJECT"

    def __init__(self, *args, **kwargs):
        bpy.types.Operator.__init__(self, *args, **kwargs)
        self.obj: Optional[bpy.types.Object] = None
        self.face_index: int = -1
        self.source: Optional[bmesh.types.BMesh] = None
        self.start = Vector((0.0, 0.0, 0.0))
        self.centre = Vector((0.0, 0.0, 0.0))
        self.normal = Vector((0.0, 0.0, 1.0))
        self.distance = 0.0
        self.typed = ""
        #: Corners the last apply() could not offset exactly.
        self.clamped = 0
        self.area: Optional[bpy.types.Area] = None
        # Same two-part confirmation as Push/Pull: the click that starts the
        # tool releases inside the modal, so a bare release only confirms once
        # the user has clicked again or actually dragged.
        self.armed = False
        self.dragged = False

    # --- Setup ----------------------------------------------------------------

    def invoke(self, context: bpy.types.Context, event: bpy.types.Event) -> set[str]:
        mouse = (event.mouse_region_x, event.mouse_region_y)
        hit = viewport.ray_cast_face(context, mouse)
        if hit is None:
            self.report({"WARNING"}, "No face under the cursor")
            return {"CANCELLED"}

        obj = hit.obj
        element = bridge.get_entity(obj)
        if element is not None:
            self.report(
                {"WARNING"},
                f"{obj.name} is {element.is_a()}; offsetting would tessellate away its "
                "parametric shape",
            )
            return {"CANCELLED"}
        if viewport.has_modifiers(obj):
            self.report(
                {"WARNING"},
                f"{obj.name} has modifiers, so the face under the cursor cannot be "
                "matched to the editable mesh",
            )
            return {"CANCELLED"}
        if obj.mode != "OBJECT":
            self.report({"WARNING"}, f"{obj.name} is in {obj.mode.lower()} mode")
            return {"CANCELLED"}
        if obj.library is not None or obj.data.library is not None:
            self.report({"WARNING"}, f"{obj.name} is linked from another file")
            return {"CANCELLED"}

        self.obj = obj
        self.face_index = hit.face_index
        self.area = context.area

        self.source = bmesh.new()
        self.source.from_mesh(obj.data)
        self.source.faces.ensure_lookup_table()
        face = self.source.faces[self.face_index]

        self.normal = hit.normal
        self.start = hit.location
        self.centre = obj.matrix_world @ face.calc_center_median()

        self.distance = 0.0
        self.typed = ""
        self.armed = False
        self.dragged = False

        self.report_state(context)
        context.window_manager.modal_handler_add(self)
        return {"RUNNING_MODAL"}

    # --- Geometry -------------------------------------------------------------

    def apply(self, distance: float) -> None:
        """Rebuild the mesh as the source offset by ``distance`` (world units)."""
        assert self.obj is not None and self.source is not None
        # inset thickness is a scalar, so object scale reduces to one factor.
        # Sketch objects carry an identity transform; median_scale keeps a
        # uniformly scaled one honest, which is as far as a scalar can go.
        scale = self.obj.matrix_world.median_scale or 1.0
        self.clamped = 0
        bm = offsetted(
            self.source, self.face_index, distance / scale, on_clamp=self._note_clamped
        )
        try:
            bm.to_mesh(self.obj.data)
        finally:
            bm.free()
        self.obj.data.update()

    def _note_clamped(self, corners: int) -> None:
        self.clamped = corners

    def distance_from_mouse(
        self, context: bpy.types.Context, event: bpy.types.Event
    ) -> Optional[float]:
        """Signed offset from the cursor: positive toward the face's centre."""
        ray = viewport.mouse_ray(context, (event.mouse_region_x, event.mouse_region_y))
        if ray is None:
            return None
        origin, direction = ray
        on_plane = intersect_line_plane(origin, origin + direction, self.start, self.normal)
        if on_plane is None:
            return None  # looking edge-on at the face's plane
        displacement = on_plane - self.start
        inward = self.centre - self.start
        if inward.length <= NEGLIGIBLE:
            # Clicked dead centre; there is no inward direction to compare
            # against, so read any drag as inward.
            return displacement.length
        sign = 1.0 if displacement.dot(inward.normalized()) >= 0.0 else -1.0
        return displacement.length * sign

    # --- Feedback -------------------------------------------------------------

    def report_state(self, context: bpy.types.Context) -> None:
        shown = self.typed if self.typed else bridge.format_length(abs(self.distance))
        side = "out" if self.distance < 0 else "in"
        if self.area is not None:
            self.area.header_text_set(f"Offset {side}: {shown}")
        context.workspace.status_text_set(
            text="Confirm: LMB / Enter    Cancel: Esc    Type a distance for an exact value"
        )

    def clear_state(self, context: bpy.types.Context) -> None:
        if self.area is not None:
            self.area.header_text_set(None)
        context.workspace.status_text_set(text=None)
        if self.source is not None:
            self.source.free()
            self.source = None

    # --- Modal ----------------------------------------------------------------

    def modal(self, context: bpy.types.Context, event: bpy.types.Event):
        if event.type in {"MIDDLEMOUSE", "WHEELUPMOUSE", "WHEELDOWNMOUSE"}:
            return {"PASS_THROUGH"}

        if event.type in {"MOUSEMOVE", "INBETWEEN_MOUSEMOVE"}:
            if not self.typed:
                moved = self.distance_from_mouse(context, event)
                if moved is not None:
                    self.distance = moved
                    if abs(self.distance) > NEGLIGIBLE:
                        self.dragged = True
                    self.apply(self.distance)
                    self.report_state(context)
                    bridge.update_viewport()
            return {"RUNNING_MODAL"}

        if event.value == "PRESS" and event.type == "BACK_SPACE":
            self.typed = self.typed[:-1]
            self.apply_typed(context)
            return {"RUNNING_MODAL"}

        if event.value == "PRESS" and event.ascii in NUMBER_CHARS:
            self.typed += event.ascii
            self.apply_typed(context)
            return {"RUNNING_MODAL"}

        if event.type == "LEFTMOUSE" and event.value == "PRESS":
            self.armed = True
            return {"RUNNING_MODAL"}

        if event.value == "RELEASE" and event.type in {"RET", "NUMPAD_ENTER"}:
            return self.confirm(context)

        if event.value == "RELEASE" and event.type == "LEFTMOUSE" and (self.armed or self.dragged):
            return self.confirm(context)

        if event.value == "PRESS" and event.type in {"ESC", "RIGHTMOUSE"}:
            return self.cancel_modal(context)

        return {"RUNNING_MODAL"}

    def apply_typed(self, context: bpy.types.Context) -> None:
        """Re-apply from the measurement box, keeping the dragged side."""
        if self.typed:
            value = bridge.parse_length(self.typed)
            if value is not None:
                sign = -1.0 if self.distance < 0 else 1.0
                self.distance = abs(value) * sign
                self.apply(self.distance)
        self.report_state(context)
        bridge.update_viewport()

    def confirm(self, context: bpy.types.Context) -> set[str]:
        assert self.obj is not None
        distance = self.distance
        name = self.obj.name
        clamped = self.clamped
        self.clear_state(context)
        bridge.update_viewport()
        if abs(distance) <= NEGLIGIBLE:
            self.report({"INFO"}, "No offset")
            return {"CANCELLED"}
        side = "outward" if distance < 0 else "inward"
        self.report(
            {"INFO"}, f"Offset {name} {side} by {bridge.format_length(abs(distance))}"
        )
        if clamped:
            # Said out loud rather than left to be discovered by measuring: the
            # tool's promise is an exact distance, and at these corners it is
            # not one.
            plural = "corner is" if clamped == 1 else "corners are"
            self.report(
                {"WARNING"},
                f"{clamped} {plural} too sharp to offset exactly, and fell short of "
                f"{bridge.format_length(abs(distance))}",
            )
        return {"FINISHED"}

    def cancel_modal(self, context: bpy.types.Context) -> set[str]:
        self.apply(0.0)
        self.clear_state(context)
        bridge.update_viewport()
        return {"CANCELLED"}

    def cancel(self, context: bpy.types.Context) -> None:
        """Blender's hook for a modal cut short from outside; our own exits
        have already cleaned up, which the ``source`` guard detects."""
        if self.source is None:
            return
        self.apply(0.0)
        self.clear_state(context)
