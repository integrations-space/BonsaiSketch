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

"""The Push/Pull tool.

Press on a face and drag along its normal; type a distance to set it exactly.
The extrusion is real from the first pixel of movement rather than a drawn
preview -- the sketch meshes this operates on are small, so rebuilding from a
pristine copy each mouse move is cheaper than maintaining an overlay, and what
the user sees is the actual result rather than an approximation of it.

Only plain meshes are pushed. An IFC element's shape is generated from its
material layers or profile, and overwriting that with a tessellated mesh would
silently discard the parametric definition -- so those are declined with an
explanation instead. Parametric depth belongs to Bonsai's own controls until
this tool can drive them directly.
"""

from __future__ import annotations

from typing import Optional

import bmesh
import bpy
from mathutils import Matrix, Vector
from mathutils.geometry import intersect_line_line

from .. import bridge, viewport

#: Characters the measurement box accepts. Matches Bonsai's polyline input so
#: imperial, fractions and "=" expressions all parse the same way.
NUMBER_CHARS = set("0123456789 .+-*/'\"=")

#: Below this the extrusion is treated as not having happened, in Blender units.
NEGLIGIBLE = 1e-9

#: How parallel two face normals must be to count as one surface. 1e-5 on the
#: dot product is roughly a quarter of a degree.
COPLANAR = 1e-5


def face_is_in_flat_sheet(face: bmesh.types.BMFace) -> bool:
    """True if nothing rises out of the plane of this face along its edges.

    This decides the fate of the face being pushed. On a flat sheet -- the
    rectangle a user has just drawn -- the face becomes the bottom cap of the
    new solid and has to stay. On a face of an existing solid it would become
    an interior wall, so it has to go. Getting this backwards produces a mesh
    that looks right and is not: either a hollow shell or a solid with a
    membrane through it.

    The test is coplanarity, not edge valency. An earlier version asked whether
    every edge was a boundary, which meant two rectangles drawn side by side
    into the same sketch disqualified each other: their shared edge has two
    faces, so the face was read as part of a solid, its cap deleted, and the
    push came out with sides missing. Faces meeting in the same plane are still
    a flat sheet.
    """
    for edge in face.edges:
        for neighbour in edge.link_faces:
            if neighbour is face:
                continue
            # abs(): a neighbour wound the opposite way is still coplanar, and
            # winding across a freshly drawn sheet is arbitrary.
            if abs(neighbour.normal.dot(face.normal)) < 1.0 - COPLANAR:
                return False
    return True


def extruded(
    source: bmesh.types.BMesh,
    face_index: int,
    to_local: Matrix,
    world_normal: Vector,
    distance: float,
    keep_face: bool,
) -> bmesh.types.BMesh:
    """A copy of ``source`` with one face pushed along ``world_normal``.

    ``to_local`` is the inverse of the object's world matrix, as a 3x3.
    Translating a world-space vector through it keeps the extrusion the
    distance the user asked for even under non-uniform object scale.

    The caller owns the returned bmesh and must free it.
    """
    bm = source.copy()
    if abs(distance) <= NEGLIGIBLE:
        return bm
    bm.faces.ensure_lookup_table()
    face = bm.faces[face_index]
    offset = to_local @ (world_normal * distance)

    if not keep_face:
        # The face already belongs to a solid, so this is not an extrusion at
        # all -- it is the face moving, with the walls around it following.
        # Sliding its own vertices does exactly that: every wall sharing them
        # stretches or shrinks to match, and a box pushed down is simply a
        # shorter box.
        #
        # Extruding here instead builds a *second* set of walls running inward
        # from the original rim, and leaves the first set standing at full
        # height. The result reads as a recess with a lip around it rather than
        # a shorter box -- the leftover shell that made this obviously wrong
        # the first time anyone pushed a face in.
        bmesh.ops.translate(bm, verts=list(face.verts), vec=offset)
        bm.normal_update()
        return bm

    # A flat sheet has no walls yet, so here an extrusion is the point: the
    # original face stays as the bottom cap and a copy of it travels.
    result = bmesh.ops.extrude_face_region(bm, geom=[face])
    verts = [g for g in result["geom"] if isinstance(g, bmesh.types.BMVert)]
    bmesh.ops.translate(bm, verts=verts, vec=offset)

    # Which way the sheet's one face pointed was arbitrary until now, and the
    # new walls inherit that arbitrary winding -- extruding "up" from a face
    # that happened to point down turns every side wall inside out, and the
    # solid then renders with holes in it and exports worse.
    #
    # Consistency is a property of a whole connected shell, so that is the
    # scope: not the extrusion's own geometry, which does not include the side
    # walls that need flipping, and not the entire mesh, which may hold sketch
    # work we were not asked to touch.
    bmesh.ops.recalc_face_normals(bm, faces=_shell_faces(face))
    bm.normal_update()
    return bm


def _shell_faces(face: bmesh.types.BMFace) -> list:
    """Every face reachable from ``face`` across shared edges."""
    seen = {face}
    frontier = [face]
    while frontier:
        current = frontier.pop()
        for edge in current.edges:
            for neighbour in edge.link_faces:
                if neighbour not in seen:
                    seen.add(neighbour)
                    frontier.append(neighbour)
    return list(seen)


class BONSAIBIM_SKETCH_OT_push_pull(bpy.types.Operator):
    bl_idname = "bonsaibim_sketch_mode.push_pull"
    bl_label = "Push/Pull"
    bl_description = "Extrude the face under the cursor along its normal"
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
        self.origin = Vector((0.0, 0.0, 0.0))
        self.normal = Vector((0.0, 0.0, 1.0))
        self.distance = 0.0
        self.typed = ""
        self.keep_face = True
        self.area: Optional[bpy.types.Area] = None
        # The click that starts the tool releases inside the modal handler, so
        # a bare release cannot mean "confirm" -- it would confirm a zero
        # extrusion before the user had done anything. A release counts once
        # the user has either clicked again (click-move-click) or actually
        # dragged the face somewhere (press-drag-release). SketchUp accepts
        # both, and so should this.
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
                f"{obj.name} is {element.is_a()}; edit its depth in Bonsai rather than "
                "tessellating the parametric shape",
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

        self.keep_face = face_is_in_flat_sheet(face)

        normal_matrix = obj.matrix_world.to_3x3().inverted().transposed()
        self.normal = (normal_matrix @ face.normal).normalized()
        self.origin = obj.matrix_world @ face.calc_center_median()

        self.distance = 0.0
        self.typed = ""
        self.armed = False
        self.dragged = False

        self.report_state(context)
        context.window_manager.modal_handler_add(self)
        return {"RUNNING_MODAL"}

    # --- Geometry -------------------------------------------------------------

    def apply(self, distance: float) -> None:
        """Rebuild the mesh as the source extruded by ``distance``."""
        assert self.obj is not None and self.source is not None

        bm = extruded(
            self.source,
            self.face_index,
            self.obj.matrix_world.to_3x3().inverted(),
            self.normal,
            distance,
            self.keep_face,
        )
        try:
            bm.to_mesh(self.obj.data)
        finally:
            bm.free()
        self.obj.data.update()

    def distance_from_mouse(
        self, context: bpy.types.Context, event: bpy.types.Event
    ) -> Optional[float]:
        """Signed distance along the face normal nearest the cursor's view ray."""
        ray = viewport.mouse_ray(context, (event.mouse_region_x, event.mouse_region_y))
        if ray is None:
            return None
        ray_origin, ray_direction = ray
        crossing = intersect_line_line(
            self.origin, self.origin + self.normal, ray_origin, ray_origin + ray_direction
        )
        if crossing is None:
            # Looking straight down the normal; there is no drag axis on screen.
            return None
        return (crossing[0] - self.origin).dot(self.normal)

    # --- Feedback -------------------------------------------------------------

    def report_state(self, context: bpy.types.Context) -> None:
        if self.typed:
            shown = self.typed
        else:
            shown = bridge.format_length(abs(self.distance))
        direction = "Push" if self.distance < 0 else "Pull"
        if self.area is not None:
            self.area.header_text_set(f"{direction}: {shown}")
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
            # A typed value wins until it is cleared: chasing the mouse after
            # someone has entered an exact number throws their number away.
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
        """Re-apply from the measurement box, keeping the drag direction."""
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
        self.clear_state(context)
        bridge.update_viewport()
        if abs(distance) <= NEGLIGIBLE:
            self.report({"INFO"}, "No extrusion")
            return {"CANCELLED"}
        verb = "Pushed" if distance < 0 else "Pulled"
        self.report({"INFO"}, f"{verb} {name} by {bridge.format_length(abs(distance))}")
        return {"FINISHED"}

    def cancel_modal(self, context: bpy.types.Context) -> set[str]:
        self.apply(0.0)
        self.clear_state(context)
        bridge.update_viewport()
        return {"CANCELLED"}

    def cancel(self, context: bpy.types.Context) -> None:
        """Blender's hook for a modal cut short from outside -- a closed area,
        a loaded file. Our own exits have already cleaned up, which is what the
        ``source`` guard detects."""
        if self.source is None:
            return
        self.apply(0.0)
        self.clear_state(context)
