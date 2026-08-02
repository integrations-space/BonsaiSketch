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

Regional push-pull: a face divided by lines into sub-regions can be pushed
independently, leaving the rest of the surface where it is. That is how a
step gets cut into a slab, or a plinth raised out of one. It matches
SketchUp's behaviour for intersected lines and shapes, and lets a user work
from a single drawn surface without the dividing lines coming apart.

Modifiers, matching SketchUp:

- ``Ctrl`` while starting the push forces an extrusion even on a solid's
  face, creating a new solid stacked on the original rather than moving
  the face.
- Double-clicking a face repeats the last push-pull distance.
"""

from __future__ import annotations

import bisect
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

#: Two inference candidates nearer than this are the same place, in Blender
#: units.
COINCIDENT = 1e-6

#: How near the drag has to come to a candidate, in pixels, before the
#: candidate takes it. Measured on screen rather than in the model, so
#: inference grabs equally firmly close up and far away.
SNAP_PIXELS = 10

#: Vertices read from one object before it is reduced to its bounding box.
#: Candidates are gathered once per push rather than once per mouse move, but
#: a Bonsai model can hold millions of vertices and even one pass would be
#: felt as a stall between pressing and the face starting to move.
VERTEX_BUDGET = 20_000


#: Translate the face's own vertices. The walls already attached to them
#: stretch to follow, so a box pushed down is simply a shorter box.
MOVE = "MOVE"

#: Extrude, and leave the original face behind as the new solid's bottom cap.
#: What a drawn sheet needs, since there is nothing underneath it yet.
EXTRUDE = "EXTRUDE"

#: Extrude, then remove the original face. What a region of a solid's surface
#: needs: the walls raised along its boundary make the step, and the face it
#: grew from would be left buried inside the result.
CUT = "CUT"


def _neighbourhood(face: bmesh.types.BMFace) -> tuple[bool, bool]:
    """Whether ``face`` meets any coplanar face, and any face out of its plane.

    These two answers between them say what kind of surface the face belongs
    to, which is all :func:`push_mode` needs.
    """
    coplanar = False
    out_of_plane = False
    for edge in face.edges:
        for neighbour in edge.link_faces:
            if neighbour is face:
                continue
            # abs(): a neighbour wound the opposite way is still coplanar, and
            # winding across a freshly drawn sheet is arbitrary.
            if abs(neighbour.normal.dot(face.normal)) >= 1.0 - COPLANAR:
                coplanar = True
            else:
                out_of_plane = True
    return coplanar, out_of_plane


def push_mode(face: bmesh.types.BMFace) -> str:
    """What pushing this face should do to the face itself.

    Three situations, told apart by what meets the face along its edges:

    A face with something rising out of its plane and nothing beside it in
    that plane is the whole face of a solid -- a box's top. Pushing it is not
    an extrusion at all; the face moves and the walls follow, so ``MOVE``.

    A face with neither is a sheet on its own, freshly drawn and hollow. It
    becomes the bottom cap of the solid the push creates, so ``EXTRUDE``.

    A face with a coplanar neighbour is a *region* of a larger surface, cut
    out of it by a drawn line. Only that region moves, and walls appear along
    the line dividing it from its neighbours. Whether the original face stays
    depends on what is behind it -- and that is what the third answer decides.
    On a sheet there is nothing behind it, so it stays as the cap: ``EXTRUDE``.
    On a solid's surface the interior is behind it, and leaving it there would
    seal a membrane across the inside of the result -- so ``CUT``.

    That last distinction is easy to miss, because both cases look right from
    outside until you cut a section or ask for the volume. A 2x2x3 box with one
    half of its top raised by 2 measures 16; with the membrane left in, 14.

    An earlier version asked whether *every* edge was a boundary, which meant
    two rectangles drawn side by side into the same sketch disqualified each
    other: their shared edge has two faces, so the face was read as part of a
    solid, its cap deleted, and the push came out with sides missing. Faces
    meeting in the same plane are still a flat sheet.
    """
    coplanar, out_of_plane = _neighbourhood(face)
    if coplanar:
        return CUT if out_of_plane else EXTRUDE
    return MOVE if out_of_plane else EXTRUDE


def extruded(
    source: bmesh.types.BMesh,
    face_index: int,
    to_local: Matrix,
    world_normal: Vector,
    distance: float,
    mode: str,
) -> bmesh.types.BMesh:
    """A copy of ``source`` with one face pushed along ``world_normal``.

    ``mode`` is one of :data:`MOVE`, :data:`EXTRUDE` or :data:`CUT`, normally
    whatever :func:`push_mode` said about the face. The caller passes it in
    rather than letting this work it out, because ``Ctrl`` overrides it.

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

    if mode == MOVE:
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

    # Asked before extruding, because extruding is what puts walls around the
    # face: afterwards every face has something out of its plane beside it and
    # the question no longer means anything.
    _, stood_on_a_solid = _neighbourhood(face)

    result = bmesh.ops.extrude_face_region(bm, geom=[face])
    verts = [g for g in result["geom"] if isinstance(g, bmesh.types.BMVert)]
    bmesh.ops.translate(bm, verts=verts, vec=offset)

    if mode == CUT:
        # The face was a region of a solid's surface, so the space behind it is
        # the solid's inside. The walls just raised along its boundary are the
        # step; the face they grew from is now a membrane sealed across the
        # interior, and has to go. Only the face -- its vertices and edges are
        # the rim those walls stand on.
        bmesh.ops.delete(bm, geom=[face], context="FACES_ONLY")
        # With the membrane gone the shell is a closed solid again, so "which
        # way is out" has a single right answer and recalculating finds it.
        # This is also what turns a downward push into a notch rather than an
        # inside-out lump: the walls inherit the winding of the face they were
        # extruded from, which points the wrong way when the push goes in.
        anchor = next(
            (g for g in result["geom"] if isinstance(g, bmesh.types.BMFace) and g.is_valid),
            None,
        )
        if anchor is not None:
            bmesh.ops.recalc_face_normals(bm, faces=_shell_faces(anchor))
        bm.normal_update()
        return bm

    if not stood_on_a_solid:
        # Which way the sheet's one face pointed was arbitrary until now, and
        # the new walls inherit that arbitrary winding -- extruding "up" from a
        # face that happened to point down turns every side wall inside out,
        # and the solid then renders with holes in it and exports worse.
        #
        # Consistency is a property of a whole connected shell, so that is the
        # scope: not the extrusion's own geometry, which does not include the
        # side walls that need flipping, and not the entire mesh, which may
        # hold sketch work we were not asked to touch.
        #
        # A sheet is the only case this is safe on. Ctrl stacks a new solid on
        # a face that already belongs to one, and the original face stays put
        # as the join between the two -- which makes the shell non-manifold,
        # leaves "outward" genuinely ambiguous, and had recalculation turning
        # the outer surface inside out. Extruding from a solid does not need
        # the help anyway: the face it starts from is already wound correctly,
        # and the new walls inherit that.
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


def axis_offsets(points, origin: Vector, normal: Vector) -> list[float]:
    """How far the face must travel for its plane to reach each point.

    These are the distances worth snapping to. A user dragging a face "up to
    there" is aiming at a height something else already occupies -- the top of
    the wall beside this one, the underside of the slab above it -- and every
    one of those is a point whose offset along the push axis this returns.

    Offsets of zero are dropped, which is doing more work than it looks.
    Everything already in the face's plane answers zero: the face's own
    corners, the rest of the surface it was cut out of, every coplanar
    neighbour. None of them is anywhere to snap to, and zero is the one
    distance the tool reads as no extrusion at all.

    Sorted and de-duplicated, so a drag can find the candidates either side of
    it by bisection rather than rescanning the model on every mouse move --
    and so that a height a hundred vertices happen to share does not get a
    hundred chances to outvote a nearer one.
    """
    offsets = sorted(
        offset
        for offset in ((point - origin).dot(normal) for point in points)
        if abs(offset) > NEGLIGIBLE
    )
    unique: list[float] = []
    for offset in offsets:
        if not unique or offset - unique[-1] > COINCIDENT:
            unique.append(offset)
    return unique


def bracketing(offsets: list[float], distance: float) -> list[float]:
    """The candidates immediately below and above ``distance``.

    Nowhere else can win. The projection of a straight line into the viewport
    is still a straight line, so the candidate nearest in the model along the
    push axis is also the nearest on screen, and the two either side of the
    drag are the only ones worth measuring in pixels.
    """
    index = bisect.bisect_left(offsets, distance)
    return offsets[max(0, index - 1):index + 1]


def inference_points(context: bpy.types.Context) -> list[Vector]:
    """World-space points worth snapping to, read once at the start of a push.

    Once, not per mouse move: the model does not change while a face is being
    dragged -- the pushed object's own mesh is rewritten each frame, but from
    a pristine copy taken before any of this, so the vertices that were worth
    aiming at when the drag began are the same ones throughout.
    """
    points: list[Vector] = []
    for obj in context.visible_objects:
        if obj.type != "MESH" or obj.data is None:
            continue
        matrix = obj.matrix_world
        vertices = obj.data.vertices
        if len(vertices) > VERTEX_BUDGET:
            # Too large to read vertex by vertex without a stall. Its bounding
            # box still carries the extents, and extents are most of what
            # anyone aligns a sketch against a large imported model to reach.
            points.extend(matrix @ Vector(corner) for corner in obj.bound_box)
            continue
        points.extend(matrix @ vertex.co for vertex in vertices)
    return points


class BONSAI_SKETCH_MODE_OT_push_pull(bpy.types.Operator):
    bl_idname = "bonsai_sketch_mode.push_pull"
    bl_label = "Push/Pull"
    bl_description = "Extrude the face under the cursor along its normal"
    bl_options = {"REGISTER", "UNDO"}

    #: The distance of the last completed push, for double-click repeat.
    #: Class-level so it survives across operator invocations.
    last_distance: Optional[float] = None

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
        self.mode = EXTRUDE
        self.area: Optional[bpy.types.Area] = None
        # The click that starts the tool releases inside the modal handler, so
        # a bare release cannot mean "confirm" -- it would confirm a zero
        # extrusion before the user had done anything. A release counts once
        # the user has either clicked again (click-move-click) or actually
        # dragged the face somewhere (press-drag-release). SketchUp accepts
        # both, and so should this.
        self.armed = False
        self.dragged = False
        #: Where the button went down, so a drag can be told from a click.
        self.press_mouse = (0, 0)
        #: Distances along the push axis where geometry lines up, sorted.
        self.offsets: list[float] = []
        #: Whether the distance showing is one of them rather than the raw drag.
        self.aligned = False

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

        # Ctrl stacks a new solid on the face instead of doing whatever the
        # face would otherwise call for -- the original stays put as the join
        # between the two, which is exactly what EXTRUDE leaves behind.
        self.mode = EXTRUDE if event.ctrl else push_mode(face)

        normal_matrix = obj.matrix_world.to_3x3().inverted().transposed()
        self.normal = (normal_matrix @ face.normal).normalized()
        self.origin = obj.matrix_world @ face.calc_center_median()

        self.distance = 0.0
        self.typed = ""
        self.armed = False
        self.dragged = False
        self.press_mouse = mouse
        self.aligned = False
        self.offsets = axis_offsets(inference_points(context), self.origin, self.normal)

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
            self.mode,
        )
        try:
            bm.to_mesh(self.obj.data)
        finally:
            bm.free()
        self.obj.data.update()

    def infer(
        self, context: bpy.types.Context, distance: float
    ) -> tuple[float, bool]:
        """``distance`` pulled onto nearby geometry, and whether it moved.

        The comparison happens in pixels rather than in the model. A tolerance
        in metres is a different size at every zoom level, so inference that
        felt right on one building would be unusable on a door handle.
        """
        if not self.offsets:
            return distance, False
        here = viewport.project_point(context, self.origin + self.normal * distance)
        if here is None:
            return distance, False
        best: Optional[float] = None
        best_pixels = float(SNAP_PIXELS)
        for candidate in bracketing(self.offsets, distance):
            there = viewport.project_point(context, self.origin + self.normal * candidate)
            if there is None:
                continue
            pixels = (there - here).length
            if pixels < best_pixels:
                best, best_pixels = candidate, pixels
        if best is None:
            return distance, False
        return best, True

    def past_drag_threshold(
        self, context: bpy.types.Context, event: bpy.types.Event
    ) -> bool:
        """True once the cursor has left the pixel the button went down on.

        Press-drag-release is told from click-move-click by whether the mouse
        moved while the button was held, and the test used to be whether the
        extrusion had become non-zero -- which any sub-pixel tremor satisfies.
        A hand that is not quite still therefore confirmed a sliver of an
        extrusion on the release of the very first click, before the user had
        aimed at anything. The double-click repeat made that worse, since a
        double click is a press, a wobble and another press.

        The threshold is Blender's own, so it matches every other drag in the
        application and follows the user's setting for it.
        """
        slop = context.preferences.inputs.drag_threshold_mouse
        dx = event.mouse_region_x - self.press_mouse[0]
        dy = event.mouse_region_y - self.press_mouse[1]
        return (dx * dx + dy * dy) > slop * slop

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
            if self.aligned:
                # Without this the snap is invisible: the number stops tracking
                # the mouse for a few pixels and there is nothing to say why.
                shown += "  (aligned)"
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
                    self.distance, self.aligned = self.infer(context, moved)
                    if self.past_drag_threshold(context, event):
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

        # Double-click repeats the last push-pull distance, as in SketchUp.
        if event.type == "LEFTMOUSE" and event.value == "DOUBLE_CLICK":
            last = type(self).last_distance
            if last is not None and abs(last) > NEGLIGIBLE:
                self.distance = last
                self.aligned = False
                self.apply(last)
                return self.confirm(context)
            # Nothing to repeat yet -- the first push of the session. Blender
            # only falls a double click back to a press if no handler took it,
            # and this one has, so arm it here instead: an unrepeatable double
            # click should still work as the second click of click-move-click
            # rather than vanishing.
            self.armed = True
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
        # An exact number is not an inference, whatever it happens to equal.
        self.aligned = False
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
        # Remember the distance for double-click repeat.
        type(self).last_distance = distance
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
