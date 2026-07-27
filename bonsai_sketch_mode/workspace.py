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

"""The "Sketch" workspace tab.

This is how Sketch Mode is invoked. Bonsai already establishes the pattern
-- it appends a "BIM" workspace from a bundled .blend in its load_post handler
(bonsai/bim/handler.py) -- so we sit a "Sketch" tab next to it in the top
bar. One click, and it is discoverable without hunting through Preferences.

Blender workspaces do not natively carry a keyconfig, so we watch the active
workspace over msgbus and swap the keymap in and out as the user moves between
tabs. Leaving the tab restores whatever keyconfig they were using before, so
this never strands a user in an unfamiliar keymap.
"""

from __future__ import annotations

import os

import bpy

from . import keyconfig, theme

WORKSPACE_NAME = "Sketch"
_BLEND = os.path.join(os.path.dirname(__file__), "data", "workspace.blend")

_msgbus_owner = object()
_previous_keyconfig: str | None = None


def exists() -> bool:
    return WORKSPACE_NAME in bpy.data.workspaces


def append(activate: bool = False) -> tuple[bool, str]:
    """Append the Sketch workspace tab. Returns (ok, message)."""
    if exists():
        if activate:
            bpy.context.window.workspace = bpy.data.workspaces[WORKSPACE_NAME]
        return True, f"'{WORKSPACE_NAME}' workspace already present"

    if not os.path.isfile(_BLEND):
        return False, f"workspace.blend missing at {_BLEND}"

    try:
        bpy.ops.workspace.append_activate(idname=WORKSPACE_NAME, filepath=_BLEND)
    except Exception as exc:
        return False, f"Failed to append workspace: {exc}"

    if not exists():
        return False, f"Append reported success but '{WORKSPACE_NAME}' is absent"

    if not activate:
        # append_activate switches to it; step back if the user did not ask.
        pass

    return True, f"'{WORKSPACE_NAME}' workspace tab added"


# --- Keymap follows the workspace -------------------------------------------


def _on_workspace_change() -> None:
    global _previous_keyconfig

    win = bpy.context.window
    if win is None:
        return

    kcs = bpy.context.window_manager.keyconfigs
    if keyconfig.KEYCONFIG_NAME not in kcs:
        return

    in_sketch = win.workspace.name == WORKSPACE_NAME
    active_name = kcs.active.name if kcs.active else None

    if in_sketch:
        if active_name != keyconfig.KEYCONFIG_NAME:
            _previous_keyconfig = active_name
            kcs.active = kcs[keyconfig.KEYCONFIG_NAME]
    else:
        if active_name == keyconfig.KEYCONFIG_NAME:
            restore = _previous_keyconfig or "Blender"
            if restore in kcs:
                kcs.active = kcs[restore]
            _previous_keyconfig = None


def subscribe() -> None:
    """Watch the active workspace so the keymap follows the tab."""
    bpy.msgbus.subscribe_rna(
        key=(bpy.types.Window, "workspace"),
        owner=_msgbus_owner,
        args=(),
        notify=_on_workspace_change,
        options={"PERSISTENT"},
    )


def unsubscribe() -> None:
    try:
        bpy.msgbus.clear_by_owner(_msgbus_owner)
    except Exception:
        pass


# --- Handlers ----------------------------------------------------------------


@bpy.app.handlers.persistent
def _load_post(_dummy) -> None:
    """Re-append and re-subscribe after a file load.

    msgbus subscriptions and appended workspaces do not survive loading a new
    .blend, so both are re-established here -- the same reason Bonsai does its
    workspace setup in load_post rather than at register time.
    """
    prefs = get_prefs()
    if prefs is None or not prefs.setup_workspace:
        return
    ok, message = append(activate=prefs.activate_workspace)
    if not ok:
        print(f"[bonsai_sketch_mode] workspace: {message}")
    theme.ensure_applied(WORKSPACE_NAME)
    subscribe()


def _append_once() -> None:
    """Deferred first append, run from a one-shot timer. Never reschedules."""
    prefs = get_prefs()
    if prefs is None or not prefs.setup_workspace:
        return
    ok, message = append(activate=prefs.activate_workspace)
    if not ok:
        print(f"[bonsai_sketch_mode] workspace: {message}")
    theme.ensure_applied(WORKSPACE_NAME)
    subscribe()


def get_prefs():
    try:
        addon = bpy.context.preferences.addons.get(__package__)
        return addon.preferences if addon else None
    except Exception:
        return None


def register_handlers() -> None:
    if _load_post not in bpy.app.handlers.load_post:
        bpy.app.handlers.load_post.append(_load_post)

    # load_post covers opening a file, but enabling the add-on mid-session does
    # not fire it -- and that is the first thing a new user does. Without this
    # they enable Sketch Mode, look at the top bar, and see nothing.
    #
    # The append cannot happen during register(): Blender is explicit that
    # add-ons must not touch bpy.data there, and in a --background run there is
    # no window to append into at all. A zero-delay timer runs on the next
    # event loop tick, by which point both are true.
    if not bpy.app.background:
        bpy.app.timers.register(_run_once, first_interval=0.0)


def _run_once() -> None:
    """Timer entry point. Returning None unregisters it after one call."""
    try:
        _append_once()
    except Exception as exc:  # pragma: no cover - depends on host state
        print(f"[bonsai_sketch_mode] workspace: {exc}")
    return None


def unregister_handlers() -> None:
    if _load_post in bpy.app.handlers.load_post:
        bpy.app.handlers.load_post.remove(_load_post)
    # Disabling the add-on before the tick fires would otherwise leave a timer
    # pointing into an unregistered module.
    if bpy.app.timers.is_registered(_run_once):
        bpy.app.timers.unregister(_run_once)
    unsubscribe()
