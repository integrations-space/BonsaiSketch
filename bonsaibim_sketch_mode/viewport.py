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

"""Cursor-to-geometry queries.

Bonsai has its own raycasting (``bonsai/tool/raycast.py``), but it is tuned for
snap-point detection: it works through 2D bounding-box prefiltering and returns
the best *snap* candidate. Push/Pull needs the plain question "which face is
directly under the cursor", and Blender's ``Scene.ray_cast`` answers exactly
that against the evaluated depsgraph.

So this module deliberately does not go through bridge.py -- there is no Bonsai
in it to couple to.
"""

from __future__ import annotations

from typing import Optional

import bpy
from bpy_extras import view3d_utils
from mathutils import Vector


class FaceHit:
    """A face under the cursor, resolved back to its original datablock."""

    __slots__ = ("obj", "face_index", "location", "normal")

    def __init__(
        self,
        obj: bpy.types.Object,
        face_index: int,
        location: Vector,
        normal: Vector,
    ) -> None:
        self.obj = obj
        self.face_index = face_index
        self.location = location
        self.normal = normal


def mouse_ray(
    context: bpy.types.Context, mouse: tuple[int, int]
) -> Optional[tuple[Vector, Vector]]:
    """(origin, direction) of the view ray through a region-space mouse position."""
    region = context.region
    rv3d = context.region_data
    if region is None or rv3d is None:
        return None
    origin = view3d_utils.region_2d_to_origin_3d(region, rv3d, mouse)
    direction = view3d_utils.region_2d_to_vector_3d(region, rv3d, mouse)
    return origin, direction


def ray_cast_face(
    context: bpy.types.Context, mouse: tuple[int, int]
) -> Optional[FaceHit]:
    """The mesh face under the cursor, or None if the ray hit nothing usable.

    The hit is resolved back to the original datablock, since that is what an
    edit has to be applied to. Callers that intend to *edit* the face must also
    check :func:`has_modifiers` -- see its note on why the index alone is not
    enough to trust.
    """
    ray = mouse_ray(context, mouse)
    if ray is None:
        return None
    origin, direction = ray

    depsgraph = context.evaluated_depsgraph_get()
    hit, location, normal, face_index, obj, _matrix = context.scene.ray_cast(
        depsgraph, origin, direction
    )
    if not hit or obj is None or face_index is None or face_index < 0:
        return None

    original = obj.original
    if original is None or original.type != "MESH" or original.data is None:
        return None
    if face_index >= len(original.data.polygons):
        return None

    # ``location`` and ``normal`` come back in world space already.
    return FaceHit(original, face_index, location.copy(), normal.normalized())


def has_modifiers(obj: bpy.types.Object) -> bool:
    """True if the object's evaluated mesh may not match its editable one.

    ``Scene.ray_cast`` reports face indices on the *evaluated* mesh. Any
    modifier can renumber, add or remove faces, so an index that came back from
    a raycast points at the intended face only when the stack is empty. Editing
    on that assumption silently modifies the wrong part of the mesh.
    """
    return bool(obj.modifiers)
