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

"""The inference mark: the coloured dot a snap answers with.

`(aligned)` in the header says a snap happened; it does not say *where*. A
SketchUp user's eye is on the geometry, not the header, and what it expects
there is the inference dot. This draws one, at the world-space point the drag
snapped to, whenever a tool says so.

Drawn in ``POST_PIXEL``, deliberately. The dot is a screen-space cue -- the
same seven pixels at every zoom, like SketchUp's -- and 2D drawing after the
frame is finished has no depth buffer to negotiate with, which is exactly the
negotiation that has ground.py's POST_VIEW quad still unfinished. A cue this
small wants to be on top of everything anyway.

The handler is installed once at registration and stays: it costs one ``is
None`` check per redraw while no mark is showing, and a permanent handler has
no per-modal lifecycle to leak. Tools call :func:`show` with a world location
and :func:`hide` on every way out. The mark is a world point, so a second
viewport showing the same scene draws it where the point is, not where the
first viewport had it.

The colour is a preference (``inference_colour``), grouped with the canvas
colours and covered by their Reset All -- but read through theme.py's
fallback, not written into Blender's theme: nothing in the theme carries it,
it exists only here.
"""

from __future__ import annotations

from typing import Optional

import bpy
import gpu
from gpu_extras.batch import batch_for_shader
from mathutils import Vector

from . import theme, viewport

#: The dot's width and height on screen. SketchUp's is about this size, and a
#: constant pixel size is the point of drawing in POST_PIXEL at all.
MARK_PIXELS = 7.0

#: A thin dark rim, so the dot reads on the light canvas -- a bright green
#: square on a pale sky otherwise loses its edge.
OUTLINE = (0.09, 0.09, 0.09, 1.0)

_handle = None
_shader = None
_location: Optional[Vector] = None


def square(center: Vector, half: float) -> list[tuple[float, float]]:
    """The dot's corners around a 2D centre, wound for a TRI_FAN."""
    return [
        (center.x - half, center.y - half),
        (center.x + half, center.y - half),
        (center.x + half, center.y + half),
        (center.x - half, center.y + half),
    ]


def show(location: Vector) -> None:
    """Put the mark at a world-space point. Stays until hide()."""
    global _location
    _location = location.copy()


def hide() -> None:
    global _location
    _location = None


def is_showing() -> bool:
    return _location is not None


def draw() -> None:
    """POST_PIXEL callback. One comparison and out while nothing is showing."""
    global _shader

    if _location is None:
        return
    context = bpy.context
    if context.region is None or context.region_data is None:
        return
    center = viewport.project_point(context, _location)
    if center is None:
        return  # behind the view; nowhere honest to draw it

    if _shader is None:
        _shader = gpu.shader.from_builtin("UNIFORM_COLOR")

    corners = square(center, MARK_PIXELS / 2.0)
    colour = theme.colour("inference_colour")

    _shader.bind()
    fill = batch_for_shader(_shader, "TRI_FAN", {"pos": corners})
    _shader.uniform_float("color", (colour[0], colour[1], colour[2], 1.0))
    fill.draw(_shader)
    rim = batch_for_shader(_shader, "LINE_LOOP", {"pos": corners})
    _shader.uniform_float("color", OUTLINE)
    rim.draw(_shader)


def is_drawing() -> bool:
    """Whether the handler is currently installed."""
    return _handle is not None


def install() -> bool:
    """Add the draw handler. Returns False if it was already there."""
    global _handle
    if _handle is not None:
        return False
    _handle = bpy.types.SpaceView3D.draw_handler_add(draw, (), "WINDOW", "POST_PIXEL")
    return True


def uninstall() -> bool:
    """Remove the draw handler. Returns False if there was nothing to remove."""
    global _handle, _location
    if _handle is None:
        return False
    bpy.types.SpaceView3D.draw_handler_remove(_handle, "WINDOW")
    _handle = None
    _location = None
    return True
