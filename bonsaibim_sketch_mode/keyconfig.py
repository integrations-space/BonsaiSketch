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

"""A "Sketch" keyconfig for Bonsai.

SketchUp drives everything from unmodified letter keys. Blender's defaults
claim those keys 232 times across its keymaps, so shadowing them from an addon
keymap is not workable â€” a user would hit unpredictable behaviour depending on
mode and editor.

Instead this builds a complete keyconfig the same way Blender's bundled
"Industry Compatible" preset does: generate the default keymap data, remove the
unmodified single-key bindings that collide with the SketchUp set, then inject
the SketchUp bindings. Everything not in that set keeps Blender's behaviour.

Conflicts are only stripped inside 3D-View-related keymaps. The Outliner,
Dope Sheet, Graph Editor and so on keep their defaults, because rebinding them
would break unrelated editors for no gain to a SketchUp user.
"""

from __future__ import annotations

import os

import bpy

from . import bridge

KEYCONFIG_NAME = "Sketch"

# Only these keymaps get conflicting bindings stripped.
SCOPED_KEYMAPS = {
    "3D View",
    "3D View Generic",
    "Object Mode",
    "Object Non-modal",
    "Mesh",
}

# Keys the SketchUp set claims. Any unmodified PRESS binding on these, inside
# SCOPED_KEYMAPS, is removed before ours are injected.
CLAIMED_KEYS = {"L", "R", "P", "M", "Q", "S", "T", "E", "F", "B", "O", "H", "Z", "SPACE"}


def _su_bindings() -> list:
    """SketchUp bindings, in Blender keyconfig item format.

    Only bindings with a verified target are included. Tools that still need
    building (Rectangle, Push/Pull, Offset, Tape, Eraser, Paint) are
    deliberately left unbound rather than pointed at an approximation â€” an
    unbound key is honest, a wrong one teaches the wrong muscle memory.
    """
    items = [
        # Select is Space in SketchUp.
        ("wm.tool_set_by_id", {"type": "SPACE", "value": "PRESS"},
         {"properties": [("name", "builtin.select_box")]}),

        # Line -> Bonsai's generic authoring tool (polyline + snapping).
        ("wm.tool_set_by_id", {"type": "L", "value": "PRESS"},
         {"properties": [("name", bridge.BIM_TOOL)]}),

        # Transforms map cleanly onto SketchUp's Move / Rotate / Scale.
        ("transform.translate", {"type": "M", "value": "PRESS"}, None),
        ("transform.rotate", {"type": "Q", "value": "PRESS"}, None),
        ("transform.resize", {"type": "S", "value": "PRESS"}, None),

        # Navigation.
        ("view3d.rotate", {"type": "O", "value": "PRESS"}, None),
        ("view3d.move", {"type": "H", "value": "PRESS"}, None),
        ("view3d.zoom", {"type": "Z", "value": "PRESS"}, None),
        # Zoom Extents.
        ("view3d.view_all", {"type": "Z", "value": "PRESS", "shift": True}, None),
    ]
    return items


def _strip_conflicts(keyconfig_data: list) -> int:
    """Remove unmodified single-key PRESS bindings on claimed keys.

    Returns the number of bindings removed, so registration can report it.
    """
    removed = 0
    for km_name, _km_args, km_content in keyconfig_data:
        if km_name not in SCOPED_KEYMAPS:
            continue
        items = km_content.get("items")
        if not isinstance(items, list):
            continue

        kept = []
        for item in items:
            # Items are (idname, kmi_params, kmi_props). Modal keymaps use a
            # different shape, but none of SCOPED_KEYMAPS is modal.
            try:
                _idname, kmi_params, _kmi_props = item
            except (TypeError, ValueError):
                kept.append(item)
                continue

            if (
                isinstance(kmi_params, dict)
                and kmi_params.get("type") in CLAIMED_KEYS
                and kmi_params.get("value") == "PRESS"
                and not kmi_params.get("ctrl")
                and not kmi_params.get("alt")
                and not kmi_params.get("shift")
                and not kmi_params.get("oskey")
                and not kmi_params.get("any")
            ):
                removed += 1
                continue

            kept.append(item)

        km_content["items"] = kept
    return removed


def _inject(keyconfig_data: list) -> bool:
    """Add the SketchUp bindings to the 3D View keymap. True if injected."""
    for km_name, _km_args, km_content in keyconfig_data:
        if km_name != "3D View":
            continue
        items = km_content.get("items")
        if not isinstance(items, list):
            return False
        # Prepend so ours are matched first.
        km_content["items"] = _su_bindings() + items
        return True
    return False


def load() -> tuple[bool, str]:
    """Build and register the SketchUp keyconfig.

    Returns (ok, message). Never raises: a keymap failure should not prevent
    the rest of the add-on from loading.
    """
    try:
        from bl_keymap_utils.io import keyconfig_init_from_data
    except ImportError as exc:
        return False, f"Blender keymap utils unavailable: {exc}"

    presets = bpy.utils.preset_paths("keyconfig")
    data_path = None
    for preset_dir in presets:
        candidate = os.path.join(preset_dir, "keymap_data", "blender_default.py")
        if os.path.isfile(candidate):
            data_path = candidate
            break

    if data_path is None:
        return False, "Could not locate Blender's blender_default.py keymap data"

    try:
        blender_default = bpy.utils.execfile(data_path)
        prefs = bpy.context.preferences
        params = blender_default.Params(
            use_mouse_emulate_3_button=prefs.inputs.use_mouse_emulate_3_button,
        )
        keyconfig_data = blender_default.generate_keymaps(params)
    except Exception as exc:
        return False, f"Failed to generate base keymap data: {exc}"

    removed = _strip_conflicts(keyconfig_data)
    if not _inject(keyconfig_data):
        return False, "Could not find the '3D View' keymap to inject into"

    try:
        kc = bpy.context.window_manager.keyconfigs.new(KEYCONFIG_NAME)
        keyconfig_init_from_data(kc, keyconfig_data)
    except Exception as exc:
        return False, f"Failed to register keyconfig: {exc}"

    return True, f"Sketch keyconfig registered ({removed} conflicting bindings removed)"


def unload() -> None:
    kcs = bpy.context.window_manager.keyconfigs
    kc = kcs.get(KEYCONFIG_NAME)
    if kc is not None:
        try:
            kcs.remove(kc)
        except Exception:
            pass
