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

"""The geometry the drawing tools write into.

A SketchUp user draws first and assigns meaning second: lines become edges,
closed coplanar loops heal into faces, faces get pushed into solids, and only
then does anything get called a wall. Making every stroke an IfcProduct would
invert that order, so Line and Rectangle produce plain Blender meshes -- marked
as ours, but with no IFC behind them. Bonsai's own "Assign IFC Class" turns a
finished sketch into a real element when the user is ready.

Successive strokes accumulate into one object: whatever was last drawn into is
left active, and the next stroke finds it. Selecting something else -- or
nothing -- starts a fresh sketch.
"""

from __future__ import annotations

from typing import Iterable, Optional

import bmesh
import bpy
from mathutils import Vector

from . import bridge

#: Custom property marking an object as sketch geometry we own.
MARKER = "bonsaibim_sketch"

OBJECT_NAME = "Sketch"

#: Points closer than this are treated as the same vertex, in metres. Chosen at
#: 0.1 mm: below anything an architect draws deliberately, above the rounding
#: error of a snapped inference point.
WELD_METRES = 1e-4


def weld_distance(scene: bpy.types.Scene) -> float:
    """WELD_METRES expressed in Blender units for this scene."""
    scale = getattr(scene.unit_settings, "scale_length", 1.0) or 1.0
    return WELD_METRES / scale


def is_sketch_object(obj: Optional[bpy.types.Object]) -> bool:
    """True if this is a mesh we drew into and IFC has no claim on it."""
    return (
        obj is not None
        and obj.type == "MESH"
        and obj.data is not None
        and bool(obj.get(MARKER))
        and bridge.get_entity(obj) is None
    )


def create(context: bpy.types.Context) -> bpy.types.Object:
    """A new, empty sketch object linked at the top of the scene."""
    mesh = bpy.data.meshes.new(OBJECT_NAME)
    obj = bpy.data.objects.new(OBJECT_NAME, mesh)
    obj[MARKER] = True
    # The scene root, not the active collection: with an IFC project open the
    # active collection is part of Bonsai's spatial hierarchy, and dropping a
    # non-IFC object into it would imply a containment that does not exist.
    context.scene.collection.objects.link(obj)
    return obj


def target_object(context: bpy.types.Context) -> bpy.types.Object:
    """The object the next stroke should go into."""
    active = context.view_layer.objects.active
    if is_sketch_object(active) and active.mode == "OBJECT":
        return active
    return create(context)


def _find_vert(bm: bmesh.types.BMesh, co: Vector, tolerance: float):
    """The existing vertex at ``co``, or None. Welds strokes to what is there."""
    best = None
    best_distance = tolerance * tolerance
    for vert in bm.verts:
        distance = (vert.co - co).length_squared
        if distance <= best_distance:
            best_distance = distance
            best = vert
    return best


def commit(
    context: bpy.types.Context,
    points: Iterable[Vector],
    close: bool = False,
) -> tuple[Optional[bpy.types.Object], int]:
    """Add a polyline to the sketch. Returns (object, faces created).

    Points are world-space, as they come off Bonsai's polyline engine. New
    vertices weld onto coincident existing ones, so a stroke that ends where an
    earlier one began joins up rather than leaving a hairline seam -- and a loop
    that closes that way gets faced even without ``close``.
    """
    points = [Vector(p) for p in points]
    if len(points) < 2:
        return None, 0

    obj = target_object(context)
    to_local = obj.matrix_world.inverted()
    local = [to_local @ p for p in points]
    tolerance = weld_distance(context.scene)

    bm = bmesh.new()
    try:
        bm.from_mesh(obj.data)

        verts = [(_find_vert(bm, co, tolerance) or bm.verts.new(co)) for co in local]
        bm.verts.ensure_lookup_table()

        pairs = list(zip(verts, verts[1:]))
        if close and len(verts) > 2:
            pairs.append((verts[-1], verts[0]))

        loop_edges = []
        for start, end in pairs:
            if start is end:
                # Two clicks welded to the same vertex; nothing to connect.
                continue
            edge = bm.edges.get((start, end)) or bm.edges.new((start, end))
            loop_edges.append(edge)
        bm.edges.ensure_lookup_table()

        faces: list = []
        if loop_edges:
            # contextual_create only produces a face when the edges actually
            # bound a closed coplanar loop, so this is safe to attempt always.
            try:
                faces = bmesh.ops.contextual_create(bm, geom=loop_edges).get("faces", [])
            except (RuntimeError, ValueError):
                faces = []
            if faces:
                bmesh.ops.recalc_face_normals(bm, faces=faces)

        bm.normal_update()
        bm.to_mesh(obj.data)
    finally:
        bm.free()

    obj.data.update()
    # Leaving it active is what makes the next stroke join this sketch.
    context.view_layer.objects.active = obj
    return obj, len(faces)
