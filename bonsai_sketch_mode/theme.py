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

"""The SketchUp-style viewport canvas: sky above, ground below, pale grid.

Everything else this add-on ships is scoped to the Sketch tab. This is not, and
it cannot be: a viewport's background gradient and its grid colour are Blender
*theme* values, and a theme is one global object shared by every workspace and
every file. There is no per-workspace override.

So this is opt-in and reversible rather than applied on install. Turning it on
changes how the 3D viewport looks everywhere in Blender, and someone who came
for a drawing tool did not ask to have their Layout tab restyled. The exact
previous values are recorded first, so turning it off puts back what was there
rather than what we guessed the defaults were.

Only 3D-viewport colours are touched. Menus, buttons, the outliner and the rest
of Blender's interface are left alone -- restyling the whole application would
be a much larger promise than "make the canvas look familiar".

Every colour here is a default rather than a fixed value: the add-on's
preferences expose sky, ground, background, grid and the three axes, in the same
grouping SketchUp's own Accessibility preferences use. The constants below are
what "Reset All" returns to, and what applies when preferences cannot be read.
Adding a colour means adding it to `_TARGETS` and `COLOUR_DEFAULTS` -- snapshot
and restore then cover it without further work.
"""

from __future__ import annotations

import json
from typing import Any, Optional

import bpy

#: Sky. SketchUp fades a soft blue down toward the horizon.
SKY = (0.639, 0.745, 0.855)

#: Ground. Warm light grey, the colour SketchUp's default templates sit on.
GROUND = (0.878, 0.867, 0.827)

#: Background, used when sky and ground are switched off. SketchUp's own
#: default here is plain white, and this is the one place it is worth copying
#: literally -- a "no sky, no ground" canvas that is not white reads as a
#: mistake rather than a choice.
BACKGROUND = (1.0, 1.0, 1.0)

#: Grid. Pale enough to read as paper ruling rather than as geometry -- the
#: AutoCAD convention of a grid you measure against but never mistake for a
#: line you drew.
GRID = (0.451, 0.451, 0.451, 0.32)

#: Axes. SketchUp uses fully saturated red, green and blue, which looks crude
#: written down and is instantly readable on screen. Blender's defaults are
#: prettier and half a hue away from what the muscle memory expects, so the
#: point of this add-on argues for SketchUp's.
AXIS_X = (1.0, 0.0, 0.0)
AXIS_Y = (0.0, 1.0, 0.0)
AXIS_Z = (0.0, 0.0, 1.0)

#: Edges. Near-black, because on a light canvas Blender's default mid-grey
#: wire disappears into the ground.
WIRE = (0.09, 0.09, 0.09)

#: Values we set, as (path, attribute) pairs into preferences.themes[0].
#: Anything listed here is snapshotted before apply() and put back by
#: restore(), so adding a colour needs no other bookkeeping.
_TARGETS = (
    ("view_3d.space.gradients", "background_type"),
    ("view_3d.space.gradients", "high_gradient"),
    ("view_3d.space.gradients", "gradient"),
    ("view_3d", "grid"),
    ("view_3d", "wire"),
    ("view_3d", "wire_edit"),
    # Axis colours live on user_interface, not view_3d, which only carries
    # grid, wire and wire_edit. Easy hour to lose.
    ("user_interface", "axis_x"),
    ("user_interface", "axis_y"),
    ("user_interface", "axis_z"),
)

#: How close two colours must be to count as the same one.
#:
#: Blender stores theme colours as bytes, so a preference of 0.1 reads back as
#: 26/255 = 0.10196 -- a round trip that loses up to half a step either way.
#: The shipped defaults all happen to sit near 8-bit boundaries, so a tighter
#: tolerance appears to work right up until someone picks their own colour and
#: the canvas starts reporting itself as switched off.
SAME_COLOUR = 1.0 / 255.0

#: Preference field -> module default, for the colours a user can override.
#: Drives both the reset operator and the fallback when preferences cannot be
#: reached, so the two cannot drift apart.
COLOUR_DEFAULTS = {
    "sky_colour": SKY,
    "ground_colour": GROUND,
    "background_colour": BACKGROUND,
    "grid_colour": GRID,
    "axis_x_colour": AXIS_X,
    "axis_y_colour": AXIS_Y,
    "axis_z_colour": AXIS_Z,
}


def _theme() -> Any:
    return bpy.context.preferences.themes[0]


def _prefs() -> Any:
    """This add-on's preferences, or None when they cannot be reached.

    Genuinely absent in ordinary situations -- mid-registration, and under
    ``--factory-startup``, which is how `tools/gen_workspace.py` runs. Every
    read below therefore falls back to the module default rather than raising.
    """
    try:
        return bpy.context.preferences.addons[__package__].preferences
    except (KeyError, AttributeError):  # pragma: no cover - host dependent
        return None


def colour(field: str) -> tuple:
    """A user-set colour, or this module's default if none is readable."""
    prefs = _prefs()
    value = getattr(prefs, field, None) if prefs is not None else None
    return tuple(value) if value is not None else COLOUR_DEFAULTS[field]


def sky_and_ground() -> bool:
    """Whether to draw a sky/ground gradient rather than a flat background."""
    prefs = _prefs()
    return True if prefs is None else bool(prefs.use_sky_ground)


def _resolve(path: str) -> Any:
    node = _theme()
    for part in path.split("."):
        node = getattr(node, part)
    return node


def _read(path: str, attribute: str) -> Any:
    value = getattr(_resolve(path), attribute)
    # Colour properties are bpy_prop_array; JSON needs plain lists.
    return value if isinstance(value, str) else list(value)


def _write(path: str, attribute: str, value: Any) -> None:
    setattr(_resolve(path), attribute, value)


def snapshot() -> str:
    """The current values of everything we are about to change, as JSON."""
    return json.dumps({f"{p}::{a}": _read(p, a) for p, a in _TARGETS})


def apply() -> tuple[bool, str]:
    """Paint the SketchUp canvas, in the user's colours. Returns (ok, message).

    Safe to call repeatedly. Changing a colour re-runs this rather than
    computing a delta, which is why the preference fields update live.
    """
    gradients = "view_3d.space.gradients"
    try:
        if sky_and_ground():
            _write(gradients, "background_type", "LINEAR")
            _write(gradients, "high_gradient", colour("sky_colour"))
            _write(gradients, "gradient", colour("ground_colour"))
        else:
            # SINGLE_COLOR reads high_gradient and ignores gradient entirely.
            _write(gradients, "background_type", "SINGLE_COLOR")
            _write(gradients, "high_gradient", colour("background_colour"))
        _write("view_3d", "grid", colour("grid_colour"))
        _write("view_3d", "wire", WIRE)
        _write("view_3d", "wire_edit", WIRE)
        _write("user_interface", "axis_x", colour("axis_x_colour"))
        _write("user_interface", "axis_y", colour("axis_y_colour"))
        _write("user_interface", "axis_z", colour("axis_z_colour"))
    except Exception as exc:  # pragma: no cover - depends on host Blender
        return False, f"Could not apply the Sketch theme: {exc}"
    return True, "Sketch canvas applied"


def restore(saved: str) -> tuple[bool, str]:
    """Put back exactly what was there before apply()."""
    if not saved:
        return False, "Nothing recorded to restore"
    try:
        stored = json.loads(saved)
    except ValueError as exc:
        return False, f"Recorded theme values are unreadable: {exc}"

    missing = []
    for path, attribute in _TARGETS:
        key = f"{path}::{attribute}"
        if key not in stored:
            missing.append(key)
            continue
        try:
            _write(path, attribute, stored[key])
        except Exception as exc:  # pragma: no cover - depends on host Blender
            return False, f"Could not restore {key}: {exc}"

    if missing:
        return True, f"Restored, but {len(missing)} value(s) were not recorded"
    return True, "Previous viewport colours restored"


def use_theme_background(workspace_name: str) -> int:
    """Point the Sketch viewports at the theme, so the gradient shows.

    The workspace ships with a flat background colour, which is a decent canvas
    on its own and needs no global change. A flat colour also overrides the
    theme entirely, so the gradient would be invisible until the viewports are
    switched over. Returns how many were switched.
    """
    return _set_background(workspace_name, "THEME")


def use_flat_background(workspace_name: str) -> int:
    """Back to the shipped flat colour, when the theme is turned off."""
    return _set_background(workspace_name, "VIEWPORT")


def _set_background(workspace_name: str, kind: str) -> int:
    workspace = bpy.data.workspaces.get(workspace_name)
    if workspace is None:
        return 0
    changed = 0
    for screen in workspace.screens:
        for area in screen.areas:
            if area.type != "VIEW_3D":
                continue
            for space in area.spaces:
                if space.type == "VIEW_3D":
                    space.shading.background_type = kind
                    changed += 1
    return changed


def looks_applied() -> Optional[bool]:
    """True if the canvas currently matches ours. None if it cannot be read.

    Compares against the colours in force now, not the shipped defaults, so a
    user who has recoloured the canvas is not told it is switched off.
    """
    try:
        gradients = _resolve("view_3d.space.gradients")
        if sky_and_ground():
            if gradients.background_type != "LINEAR":
                return False
            expected = colour("sky_colour")
        else:
            if gradients.background_type != "SINGLE_COLOR":
                return False
            expected = colour("background_colour")
        return all(
            abs(a - b) <= SAME_COLOUR
            for a, b in zip(list(gradients.high_gradient), expected)
        )
    except Exception:  # pragma: no cover - depends on host Blender
        return None
