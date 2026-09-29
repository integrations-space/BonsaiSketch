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

"""An opaque ground plane at Z=0, drawn rather than themed.

Blender offers three viewport backdrops -- a flat colour, the theme gradient, or
the scene world -- and none of them produces SketchUp's ground: an opaque
surface meeting the sky at a real horizon that moves as you orbit. The theme
gradient is screen-space, and in Solid shading the world option draws its flat
viewport colour and ignores the node tree entirely.

So this draws the ground instead of asking for it, which is what SketchUp and
Openshrimp both do -- neither is using a host application's background feature,
which is why neither is bound by those limits. A `POST_VIEW` draw handler paints
a quad at Z=0 through the `UNIFORM_COLOR` builtin shader, depth-tested against
real geometry so anything in front of it occludes it correctly.

Two properties this buys that a theme cannot:

- The horizon is real. It sits where the ground plane vanishes, and it moves
  when the camera does, because the quad is in world space.
- Nothing is written to the user's file. A ground-plane *object* would achieve
  the same look, but it would be geometry in an IFC project, selectable and
  exportable and wrong.

Draw handlers are registered per space *type*, so this callback runs for every
3D viewport in Blender, including Bonsai's BIM tab. It returns immediately
unless the window is on the Sketch workspace.

UNFINISHED, and `show_ground` therefore defaults to off. The quad draws --
that much is settled, and it is why this module exists rather than a note
saying it cannot be done -- but it does not yet compose correctly with the rest
of the viewport. Two things are known and neither should be rediscovered:

- In `POST_VIEW` the quad paints opaquely but does not appear to respect the
  depth buffer. It covers the floor grid, and geometry that should be in front
  of it is painted over. `depth_mask_set(False)` does not change this, so the
  problem is not the mask.
- In `PRE_VIEW` the quad is drawn and then erased: Blender clears the
  background after the handler runs, so nothing survives to the frame.

The likely answer is that `POST_VIEW` is correct and the depth state needs
setting differently, or the draw belongs in an overlay pass rather than either
of these. Until that is settled this stays off, because a ground that hides the
grid and eats geometry is worse than no ground.
"""

from __future__ import annotations

from typing import Optional

import bpy
import gpu
from gpu_extras.batch import batch_for_shader

from . import theme

#: How far past the far clip to stop. Short of it, so the quad is never
#: clipped mid-plane, which reads as a torn horizon rather than a distant one.
_CLIP_MARGIN = 0.9

_handle = None
_shader = None


def _prefs():
    try:
        addon = bpy.context.preferences.addons.get(__package__)
        return addon.preferences if addon else None
    except Exception:  # pragma: no cover - host dependent
        return None


def _should_draw(workspace_name: str) -> bool:
    window = bpy.context.window
    if window is None or window.workspace is None:
        return False
    if window.workspace.name != workspace_name:
        return False
    prefs = _prefs()
    return bool(prefs.show_ground) if prefs is not None else False


def _extent(space) -> float:
    """How far the quad reaches, in metres.

    Sized off the viewport's own far clip rather than a guessed multiple of the
    view distance. A fixed multiple either falls short of the horizon when you
    zoom out or runs past the clip plane and gets cut off when you zoom in.
    """
    clip_end = getattr(space, "clip_end", 1000.0) if space else 1000.0
    return max(clip_end * _CLIP_MARGIN, 1.0)


def draw() -> None:
    """POST_VIEW callback. Cheap and silent when it is not our workspace."""
    global _shader

    from . import workspace as _workspace  # local: avoids an import cycle

    if not _should_draw(_workspace.WORKSPACE_NAME):
        return

    region_3d = bpy.context.region_data
    if region_3d is None:
        return

    if _shader is None:
        _shader = gpu.shader.from_builtin("UNIFORM_COLOR")

    reach = _extent(bpy.context.space_data)
    verts = [
        (-reach, -reach, 0.0),
        (reach, -reach, 0.0),
        (reach, reach, 0.0),
        (-reach, reach, 0.0),
    ]
    batch = batch_for_shader(_shader, "TRI_FAN", {"pos": verts})

    colour = theme.colour("ground_colour")
    # Depth is written, not just tested. Drawn in PRE_VIEW, this lays the ground
    # down before the scene, so Blender's own geometry and overlays -- the floor
    # grid above all -- depth-test against it and draw over the top. Writing
    # depth is what makes anything below Z=0 disappear behind it, which is the
    # whole point of an opaque ground rather than a painted backdrop.
    gpu.state.depth_test_set("LESS_EQUAL")
    gpu.state.depth_mask_set(True)
    _shader.bind()
    _shader.uniform_float("color", (colour[0], colour[1], colour[2], 1.0))
    batch.draw(_shader)
    gpu.state.depth_mask_set(False)
    gpu.state.depth_test_set("NONE")


def is_drawing() -> bool:
    """Whether the handler is currently installed."""
    return _handle is not None


def install() -> bool:
    """Add the draw handler. Returns False if it was already there."""
    global _handle
    if _handle is not None:
        return False
    _handle = bpy.types.SpaceView3D.draw_handler_add(draw, (), "WINDOW", "POST_VIEW")
    return True


def uninstall() -> bool:
    """Remove the draw handler. Returns False if there was nothing to remove."""
    global _handle
    if _handle is None:
        return False
    bpy.types.SpaceView3D.draw_handler_remove(_handle, "WINDOW")
    _handle = None
    return True


def redraw(workspace_name: Optional[str] = None) -> int:
    """Tag the Sketch viewports for redraw, so a toggle is visible at once."""
    changed = 0
    for window in bpy.context.window_manager.windows:
        if workspace_name and window.workspace.name != workspace_name:
            continue
        for area in window.screen.areas:
            if area.type == "VIEW_3D":
                area.tag_redraw()
                changed += 1
    return changed
