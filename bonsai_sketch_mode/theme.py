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
"""

from __future__ import annotations

import json
from typing import Any, Optional

import bpy

#: Sky. SketchUp fades a soft blue down toward the horizon.
SKY = (0.639, 0.745, 0.855)

#: Ground. Warm light grey, the colour SketchUp's default templates sit on.
GROUND = (0.878, 0.867, 0.827)

#: Grid. Pale enough to read as paper ruling rather than as geometry -- the
#: AutoCAD convention of a grid you measure against but never mistake for a
#: line you drew.
GRID = (0.451, 0.451, 0.451, 0.32)

#: Edges. Near-black, because on a light canvas Blender's default mid-grey
#: wire disappears into the ground.
WIRE = (0.09, 0.09, 0.09)

#: Values we set, as (path, attribute) pairs into preferences.themes[0].
_TARGETS = (
    ("view_3d.space.gradients", "background_type"),
    ("view_3d.space.gradients", "high_gradient"),
    ("view_3d.space.gradients", "gradient"),
    ("view_3d", "grid"),
    ("view_3d", "wire"),
    ("view_3d", "wire_edit"),
)


def _theme() -> Any:
    return bpy.context.preferences.themes[0]


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
    """Paint the SketchUp canvas. Returns (ok, message)."""
    try:
        _write("view_3d.space.gradients", "background_type", "LINEAR")
        _write("view_3d.space.gradients", "high_gradient", SKY)
        _write("view_3d.space.gradients", "gradient", GROUND)
        _write("view_3d", "grid", GRID)
        _write("view_3d", "wire", WIRE)
        _write("view_3d", "wire_edit", WIRE)
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
    """True if the canvas currently matches ours. None if it cannot be read."""
    try:
        gradients = _resolve("view_3d.space.gradients")
        if gradients.background_type != "LINEAR":
            return False
        return all(
            abs(a - b) < 1e-3 for a, b in zip(list(gradients.high_gradient), SKY)
        )
    except Exception:  # pragma: no cover - depends on host Blender
        return None
