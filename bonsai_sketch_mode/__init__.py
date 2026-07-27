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

"""Bonsai Sketch Mode.

An add-on layered on top of Bonsai (https://bonsaibim.org/) that presents
Bonsai's IFC authoring capability through SketchUp's interaction model, to
lower the adoption barrier for architects coming from SketchUp.

Sketch Mode is invoked from a "Sketch" tab in the top bar, next to Bonsai's own
"BIM" tab. Switching to that tab activates the SketchUp keymap; leaving it
restores the previous one.

This add-on imports Bonsai and is therefore a derivative work: it is licensed
GPL-3.0-or-later, matching Bonsai.
"""

from __future__ import annotations

import bpy

from . import bridge, keyconfig, ops, requirements, theme, tools, workspace

_keyconfig_status: tuple[bool, str] = (False, "Not yet loaded")
_workspace_status: tuple[bool, str] = (False, "Not yet loaded")
_tools_status: tuple[bool, str] = (False, "Not yet loaded")


class BONSAI_SKETCH_OT_activate_keyconfig(bpy.types.Operator):
    bl_idname = "bonsai_sketch_mode.activate_keyconfig"
    bl_label = "Activate Sketch Keymap"
    bl_description = "Switch Blender's active keymap to the Sketch Mode preset"

    def execute(self, context: bpy.types.Context):
        kcs = context.window_manager.keyconfigs
        if keyconfig.KEYCONFIG_NAME not in kcs:
            self.report({"ERROR"}, "Sketch keyconfig is not registered")
            return {"CANCELLED"}
        kcs.active = kcs[keyconfig.KEYCONFIG_NAME]
        self.report({"INFO"}, "Sketch keymap active")
        return {"FINISHED"}


class BONSAI_SKETCH_OT_open_workspace(bpy.types.Operator):
    bl_idname = "bonsai_sketch_mode.open_workspace"
    bl_label = "Open Sketch Workspace"
    bl_description = "Add the Sketch tab to the top bar and switch to it"

    def execute(self, context: bpy.types.Context):
        ok, message = workspace.append(activate=True)
        global _workspace_status
        _workspace_status = (ok, message)
        if not ok:
            self.report({"ERROR"}, message)
            return {"CANCELLED"}
        workspace.subscribe()
        self.report({"INFO"}, message)
        return {"FINISHED"}


class BONSAI_SKETCH_OT_apply_theme(bpy.types.Operator):
    bl_idname = "bonsai_sketch_mode.apply_theme"
    bl_label = "Use the Sketch Canvas"
    bl_description = (
        "Sky-and-ground gradient behind the model, with a pale measuring grid.\n\n"
        "Blender keeps viewport colours in one global theme, so this changes the "
        "3D viewport everywhere, not only on the Sketch tab. Your current colours "
        "are recorded first and restored if you turn it off"
    )

    def execute(self, context: bpy.types.Context):
        prefs = workspace.get_prefs()
        if prefs is None:
            self.report({"ERROR"}, "Add-on preferences unavailable")
            return {"CANCELLED"}

        # Record before changing, so "off" restores what was actually there.
        prefs.saved_theme = theme.snapshot()
        ok, message = theme.apply()
        if not ok:
            self.report({"ERROR"}, message)
            return {"CANCELLED"}

        switched = theme.use_theme_background(workspace.WORKSPACE_NAME)
        prefs.theme_applied = True
        self.report({"INFO"}, f"{message} ({switched} viewport(s) switched)")
        return {"FINISHED"}


class BONSAI_SKETCH_OT_restore_theme(bpy.types.Operator):
    bl_idname = "bonsai_sketch_mode.restore_theme"
    bl_label = "Restore Previous Colours"
    bl_description = "Put the viewport colours back the way they were before the Sketch canvas"

    def execute(self, context: bpy.types.Context):
        prefs = workspace.get_prefs()
        if prefs is None:
            self.report({"ERROR"}, "Add-on preferences unavailable")
            return {"CANCELLED"}

        ok, message = theme.restore(prefs.saved_theme)
        theme.use_flat_background(workspace.WORKSPACE_NAME)
        prefs.theme_applied = False
        prefs.saved_theme = ""
        self.report({"INFO"} if ok else {"WARNING"}, message)
        return {"FINISHED"}


class BONSAI_SKETCH_Preferences(bpy.types.AddonPreferences):
    bl_idname = __package__

    #: The theme values as they were before we touched them, as JSON. Kept in
    #: preferences rather than memory so a restore still works next session.
    saved_theme: bpy.props.StringProperty(default="")
    theme_applied: bpy.props.BoolProperty(default=False)

    setup_workspace: bpy.props.BoolProperty(
        name="Add Sketch workspace tab",
        description="Add a Sketch tab to the top bar when a file is loaded",
        default=True,
    )
    activate_workspace: bpy.props.BoolProperty(
        name="Switch to it automatically",
        description="Make Sketch the active workspace on load, rather than only adding the tab",
        default=False,
    )

    def draw(self, context: bpy.types.Context) -> None:
        layout = self.layout

        if not bridge.is_available():
            box = layout.box()
            box.alert = True
            box.label(text="Bonsai is required but was not found.", icon="ERROR")
            reason = bridge.unavailable_reason()
            if reason:
                box.label(text=reason)
            box.operator("wm.url_open", text="Install Bonsai").url = "https://bonsaibim.org/"
            return

        detected = bridge.version() or "unknown"
        layout.label(text=f"Bonsai {detected} detected", icon="CHECKMARK")

        if bridge.is_untested_version():
            box = layout.box()
            box.label(
                text=(
                    f"Built against Bonsai {bridge.TESTED_BONSAI_VERSION}. "
                    "Bonsai has no stable API contract, so other versions may break."
                ),
                icon="INFO",
            )

        box = layout.box()
        box.label(text="Workspace", icon="WORKSPACE")
        box.prop(self, "setup_workspace")
        sub = box.row()
        sub.enabled = self.setup_workspace
        sub.prop(self, "activate_workspace")
        if workspace.exists():
            box.label(text="Sketch tab is in the top bar.", icon="CHECKMARK")
        else:
            box.operator(BONSAI_SKETCH_OT_open_workspace.bl_idname, icon="ADD")

        ok, message = _keyconfig_status
        box = layout.box()
        box.label(text="Keymap", icon="KEYINGSET")
        box.label(text=message, icon="CHECKMARK" if ok else "ERROR")
        if ok:
            box.label(
                text="Activates automatically on the Sketch tab.",
                icon="INFO",
            )
            active = context.window_manager.keyconfigs.active
            if not (active and active.name == keyconfig.KEYCONFIG_NAME):
                box.operator(BONSAI_SKETCH_OT_activate_keyconfig.bl_idname, icon="PLAY")

        box = layout.box()
        box.label(text="Viewport", icon="SHADING_RENDERED")
        applied = theme.looks_applied()
        if self.theme_applied and applied:
            box.label(text="Sketch canvas is on.", icon="CHECKMARK")
            box.operator(BONSAI_SKETCH_OT_restore_theme.bl_idname, icon="LOOP_BACK")
        else:
            if self.theme_applied and applied is False:
                box.label(text="Something else has changed the theme since.", icon="INFO")
            col = box.column(align=True)
            col.label(text="Sky and ground behind the model, with a pale grid.")
            col.label(
                text="Blender keeps viewport colours in one global theme,",
                icon="ERROR",
            )
            col.label(text="so this restyles the 3D viewport in every workspace.")
            col.label(text="Your current colours are recorded and can be restored.")
            box.operator(BONSAI_SKETCH_OT_apply_theme.bl_idname, icon="COLOR")

        ok, message = _tools_status
        box = layout.box()
        box.label(text="Tools", icon="TOOL_SETTINGS")
        box.label(text=message, icon="CHECKMARK" if ok else "ERROR")
        if ok and not bridge.polyline_engine_available():
            sub = box.row()
            sub.alert = True
            sub.label(
                text=bridge.polyline_unavailable_reason() or "Drawing tools unavailable",
                icon="ERROR",
            )


classes = (
    BONSAI_SKETCH_OT_activate_keyconfig,
    BONSAI_SKETCH_OT_open_workspace,
    BONSAI_SKETCH_OT_apply_theme,
    BONSAI_SKETCH_OT_restore_theme,
    BONSAI_SKETCH_Preferences,
)


def register() -> None:
    global _keyconfig_status, _tools_status

    for cls in classes:
        bpy.utils.register_class(cls)

    if not bridge.is_available():
        # Register preferences anyway so the user gets a readable explanation
        # instead of a silent no-op.
        print(f"[bonsai_sketch_mode] {bridge.unavailable_reason()}")
        return

    # Operators first: the toolbar entries reference them by idname, and
    # register_tool validates that the keymap targets exist.
    ops.register()

    _tools_status = tools.register()
    if not _tools_status[0]:
        print(f"[bonsai_sketch_mode] tools: {_tools_status[1]}")

    _keyconfig_status = keyconfig.load()
    if not _keyconfig_status[0]:
        print(f"[bonsai_sketch_mode] keymap: {_keyconfig_status[1]}")

    # The Sketch tab is added on file load (Bonsai does the same for its BIM
    # tab). Enabling the add-on mid-session does not fire load_post, so the
    # preferences panel also exposes an "Open Sketch Workspace" button.
    workspace.register_handlers()
    workspace.subscribe()


def unregister() -> None:
    workspace.unregister_handlers()
    keyconfig.unload()
    tools.unregister()
    ops.unregister()

    for cls in reversed(classes):
        bpy.utils.unregister_class(cls)
