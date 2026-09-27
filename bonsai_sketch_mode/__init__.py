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

import os

import bpy

from . import align, bridge, classify, derive, drawings, dxf, failures, ground, heal, ir, keyconfig, marks, ops, pipeline, reconcile, requirements, sidebar, spaces, storeys, textmodel, theme, tools, walls, workspace

_keyconfig_status: tuple[bool, str] = (False, "Not yet loaded")
_workspace_status: tuple[bool, str] = (False, "Not yet loaded")
_tools_status: tuple[bool, str] = (False, "Not yet loaded")
_sidebar_status: tuple[bool, str] = (False, "Not yet loaded")
_textmodel_status: tuple[bool, str] = (False, "Not yet loaded")


class BONSAI_SKETCH_MODE_OT_activate_keyconfig(bpy.types.Operator):
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


class BONSAI_SKETCH_MODE_OT_open_workspace(bpy.types.Operator):
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
        theme.ensure_applied(workspace.WORKSPACE_NAME)
        prefs = workspace.get_prefs()
        if prefs is not None:
            theme.set_floor_grid(workspace.WORKSPACE_NAME, prefs.show_floor_grid)
        workspace.subscribe()
        self.report({"INFO"}, message)
        return {"FINISHED"}


class BONSAI_SKETCH_MODE_OT_toggle_textmodel(bpy.types.Operator):
    bl_idname = "bonsai_sketch_mode.toggle_textmodel"
    bl_label = "Text-to-Model Channel"
    bl_description = (
        "Open or close the local command channel that lets an agent or a script "
        "drive this Blender. Loopback only, and closed unless switched on"
    )

    def execute(self, context: bpy.types.Context):
        prefs = workspace.get_prefs()
        if textmodel.is_running():
            textmodel.unregister()
            if prefs is not None:
                prefs.textmodel_enabled = False
            self.report({"INFO"}, "Text-to-model channel closed")
            return {"FINISHED"}

        port = prefs.textmodel_port if prefs is not None else textmodel.DEFAULT_PORT
        ok, message = textmodel.register(port)
        if not ok:
            self.report({"ERROR"}, message)
            return {"CANCELLED"}
        if prefs is not None:
            prefs.textmodel_enabled = True
        self.report({"INFO"}, message)
        return {"FINISHED"}


class BONSAI_SKETCH_MODE_OT_apply_theme(bpy.types.Operator):
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


class BONSAI_SKETCH_MODE_OT_restore_theme(bpy.types.Operator):
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


def _recolour(self, context: bpy.types.Context) -> None:
    """Repaint the moment a colour changes, but only if the canvas is on.

    Picking a colour you cannot see the effect of is guesswork, and Blender's
    colour picker updates continuously while dragging. Applying when the canvas
    is off would switch it on behind the user's back, so this stays quiet then.
    """
    if self.theme_applied:
        theme.apply()


def _colour_prop(name: str, default, description: str, size: int = 3):
    """A 0-1 colour swatch that repaints the canvas when changed."""
    return bpy.props.FloatVectorProperty(
        name=name,
        description=description,
        subtype="COLOR",
        size=size,
        min=0.0,
        max=1.0,
        default=default,
        update=_recolour,
    )


class BONSAI_SKETCH_MODE_OT_reset_colours(bpy.types.Operator):
    bl_idname = "bonsai_sketch_mode.reset_colours"
    bl_label = "Reset All"
    bl_description = "Put every canvas colour back to the shipped SketchUp-style default"

    def execute(self, context: bpy.types.Context):
        prefs = workspace.get_prefs()
        if prefs is None:
            self.report({"ERROR"}, "Add-on preferences unavailable")
            return {"CANCELLED"}

        for field in theme.COLOUR_DEFAULTS:
            prefs.property_unset(field)
        prefs.property_unset("use_sky_ground")

        # property_unset does not fire the update callback, so repaint by hand.
        if prefs.theme_applied:
            theme.apply()
        self.report({"INFO"}, "Canvas colours reset")
        return {"FINISHED"}


class BONSAI_SKETCH_MODE_Preferences(bpy.types.AddonPreferences):
    bl_idname = __package__

    #: The theme values as they were before we touched them, as JSON. Kept in
    #: preferences rather than memory so a restore still works next session.
    saved_theme: bpy.props.StringProperty(default="")

    oda_converter: bpy.props.StringProperty(
        name="ODA File Converter",
        description=(
            "Path to the ODA File Converter executable (free, from "
            "opendesign.com). DWG is a proprietary format with no reliable "
            "free reader, so File > Import reads DWG by converting it to DXF "
            "through this tool first. Leave empty and DWG import explains "
            "itself instead of failing quietly"
        ),
        default="",
        subtype="FILE_PATH",
    )
    theme_applied: bpy.props.BoolProperty(default=False)

    show_ground: bpy.props.BoolProperty(
        name="Solid ground",
        description=(
            "Draw an opaque ground plane at Z=0, so the sky meets it at a real "
            "horizon that moves as you orbit.\n\n"
            "Drawn into the Sketch viewport rather than added to your file, so "
            "there is no object to select, move or export.\n\n"
            "UNFINISHED: the ground currently hides the floor grid and paints "
            "over geometry that should be in front of it"
        ),
        default=False,
        update=lambda self, context: ground.redraw(workspace.WORKSPACE_NAME),
    )

    show_floor_grid: bpy.props.BoolProperty(
        name="Floor grid",
        description=(
            "Show the measuring grid on the ground plane.\n\n"
            "An overlay on the Sketch viewport, so this leaves every other "
            "workspace alone. Visibility only -- Blender's grid snapping is a "
            "scene setting and keeps working either way"
        ),
        default=True,
        update=lambda self, context: theme.set_floor_grid(
            workspace.WORKSPACE_NAME, self.show_floor_grid
        ),
    )

    show_sidebar: bpy.props.BoolProperty(
        name="IFC sidebar",
        description=(
            "Open the Sketch sidebar, which holds the tab's only route into "
            "IFC: New IFC Project, and Assign IFC Class for a finished "
            "sketch.\n\n"
            "Without a project the BIM tools in the toolbar can do nothing, "
            "and nothing else on this tab can create one. Turn this off to "
            "get the bare viewport back -- N still opens it"
        ),
        default=True,
        update=lambda self, context: sidebar.set_sidebar(
            workspace.WORKSPACE_NAME, self.show_sidebar
        ),
    )

    canvas_on_setup: bpy.props.BoolProperty(
        name="Sketch canvas on by default",
        description=(
            "Raise the sky-and-ground canvas as soon as the Sketch tab is added, "
            "rather than waiting to be switched on.\n\n"
            "Blender keeps viewport colours in one global theme, so this restyles "
            "the 3D viewport in every workspace, not only the Sketch tab. Your "
            "colours are recorded first and Restore Previous Colours puts them back"
        ),
        default=True,
    )

    use_sky_ground: bpy.props.BoolProperty(
        name="Sky and ground",
        description=(
            "Fade a sky colour down to a ground colour at the horizon. "
            "Off gives one flat background colour instead, as SketchUp does "
            "when its sky and ground are switched off"
        ),
        default=True,
        update=_recolour,
    )
    sky_colour: _colour_prop("Sky", theme.SKY, "Above the horizon")
    ground_colour: _colour_prop("Ground", theme.GROUND, "Below the horizon")
    background_colour: _colour_prop(
        "Background", theme.BACKGROUND, "Used when sky and ground are switched off"
    )
    grid_colour: _colour_prop(
        "Grid", theme.GRID, "The measuring grid. The fourth slider is opacity", size=4
    )
    axis_x_colour: _colour_prop("Red Axis", theme.AXIS_X, "The X axis")
    axis_y_colour: _colour_prop("Green Axis", theme.AXIS_Y, "The Y axis")
    axis_z_colour: _colour_prop("Blue Axis", theme.AXIS_Z, "The Z axis")
    inference_colour: _colour_prop(
        "Inference",
        theme.INFERENCE,
        "The mark drawn where a drag has snapped level with existing geometry",
    )

    anthropic_api_key: bpy.props.StringProperty(
        name="Anthropic API key",
        description=(
            "Used by the Describe box on the Sketch tab to build from a "
            "sentence. Requests go to Anthropic and are billed to this key.\n\n"
            "Blender stores preferences in plain text. If that is not "
            "acceptable, leave this empty and set ANTHROPIC_API_KEY in the "
            "environment instead -- it is read when this is blank"
        ),
        default="",
        subtype="PASSWORD",
    )
    anthropic_model: bpy.props.StringProperty(
        name="Model",
        description="Which Claude model the Describe box uses",
        default=textmodel.claude.DEFAULT_MODEL,
    )

    textmodel_enabled: bpy.props.BoolProperty(
        name="Text-to-model channel",
        description=(
            "Records whether the channel was left open. Use the button, not "
            "this -- it is what the button writes to"
        ),
        default=False,
    )
    textmodel_port: bpy.props.IntProperty(
        name="Port",
        description="Loopback port the text-to-model channel listens on",
        default=textmodel.DEFAULT_PORT,
        min=1024,
        max=65535,
    )

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
        box.prop(self, "show_sidebar")

        box = layout.box()
        box.label(text="Describe", icon="OUTLINER_OB_FONT")
        column = box.column(align=True)
        column.scale_y = 0.8
        column.label(text="Type what to build on the Sketch tab, and let")
        column.label(text="Claude build it with the Sketch tools.")
        box.prop(self, "anthropic_api_key")
        box.prop(self, "anthropic_model")
        if not self.anthropic_api_key and not os.environ.get("ANTHROPIC_API_KEY"):
            row = box.row()
            row.label(text="No key set, so the Describe box is hidden.", icon="INFO")

        box = layout.box()
        box.label(text="Text to Model channel", icon="CONSOLE")
        column = box.column(align=True)
        column.scale_y = 0.8
        column.label(text="A local command channel, for an agent or a script.")
        column.label(text="Loopback only, and anything that reaches it can")
        column.label(text="rewrite the model. Closed unless you open it.")
        row = box.row(align=True)
        row.prop(self, "textmodel_port")
        row = box.row(align=True)
        if textmodel.is_running():
            row.operator(
                BONSAI_SKETCH_MODE_OT_toggle_textmodel.bl_idname, text="Close", icon="CANCEL"
            )
            box.label(text=textmodel.status(), icon="CHECKMARK")
            path = textmodel.discovery_file()
            if path:
                sub = box.column(align=True)
                sub.scale_y = 0.8
                sub.label(text="Port and token:")
                sub.label(text=path)
        else:
            row.operator(
                BONSAI_SKETCH_MODE_OT_toggle_textmodel.bl_idname, text="Open", icon="PLAY"
            )
        if workspace.exists():
            box.label(text="Sketch tab is in the top bar.", icon="CHECKMARK")
        else:
            box.operator(BONSAI_SKETCH_MODE_OT_open_workspace.bl_idname, icon="ADD")

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
                box.operator(BONSAI_SKETCH_MODE_OT_activate_keyconfig.bl_idname, icon="PLAY")

        box = layout.box()
        box.label(text="Viewport", icon="SHADING_RENDERED")
        applied = theme.looks_applied()
        if self.theme_applied and applied:
            box.label(text="Sketch canvas is on.", icon="CHECKMARK")
            box.operator(BONSAI_SKETCH_MODE_OT_restore_theme.bl_idname, icon="LOOP_BACK")
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
            box.operator(BONSAI_SKETCH_MODE_OT_apply_theme.bl_idname, icon="COLOR")

        box.prop(self, "canvas_on_setup")
        box.prop(self, "show_ground")
        box.prop(self, "show_floor_grid")

        # Editable whether or not the canvas is on, so colours can be chosen
        # first and switched on once. Grouped the way SketchUp groups them.
        box.separator()
        box.prop(self, "use_sky_ground")
        col = box.column(align=True)
        if self.use_sky_ground:
            col.prop(self, "sky_colour")
            col.prop(self, "ground_colour")
        else:
            col.prop(self, "background_colour")
        col.prop(self, "grid_colour")

        col = box.column(align=True)
        col.label(text="Axis and direction colours")
        col.prop(self, "axis_x_colour")
        col.prop(self, "axis_y_colour")
        col.prop(self, "axis_z_colour")

        col = box.column(align=True)
        col.label(text="Modelling colours")
        col.prop(self, "inference_colour")
        box.operator(BONSAI_SKETCH_MODE_OT_reset_colours.bl_idname, icon="LOOP_BACK")

        box = layout.box()
        box.label(text="Import", icon="IMPORT")
        box.label(text="File > Import > CAD Drawing reads DXF natively.")
        box.prop(self, "oda_converter")

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
    BONSAI_SKETCH_MODE_OT_activate_keyconfig,
    BONSAI_SKETCH_MODE_OT_open_workspace,
    BONSAI_SKETCH_MODE_OT_toggle_textmodel,
    BONSAI_SKETCH_MODE_OT_apply_theme,
    BONSAI_SKETCH_MODE_OT_restore_theme,
    BONSAI_SKETCH_MODE_OT_reset_colours,
    BONSAI_SKETCH_MODE_Preferences,
)


def register() -> None:
    global _keyconfig_status, _tools_status, _sidebar_status, _textmodel_status

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

    # The AutoModel pipeline rides behind the same File > Import door as the
    # plain CAD import it extends, so finding one means finding both.
    pipeline.register()

    _tools_status = tools.register()
    if not _tools_status[0]:
        print(f"[bonsai_sketch_mode] tools: {_tools_status[1]}")

    # The Sketch tab's only route into IFC. Registered like the toolbar is --
    # reported rather than raised -- because losing one panel should not cost
    # the user the drawing tools as well.
    _sidebar_status = sidebar.register()
    if not _sidebar_status[0]:
        print(f"[bonsai_sketch_mode] sidebar: {_sidebar_status[1]}")

    # The Describe panel, which is UI and therefore always present. The socket
    # channel next to it is a listener and stays shut until asked for.
    _textmodel_status = textmodel.register_ui()
    if not _textmodel_status[0]:
        print(f"[bonsai_sketch_mode] textmodel: {_textmodel_status[1]}")

    _keyconfig_status = keyconfig.load()
    if not _keyconfig_status[0]:
        print(f"[bonsai_sketch_mode] keymap: {_keyconfig_status[1]}")

    # The Sketch tab is added on file load (Bonsai does the same for its BIM
    # tab). Enabling the add-on mid-session does not fire load_post, so the
    # preferences panel also exposes an "Open Sketch Workspace" button.
    workspace.register_handlers()
    workspace.subscribe()

    # The ground is drawn, not themed, so it needs a live draw handler rather
    # than a value set once. The callback returns immediately off the Sketch
    # tab, so installing it globally costs nothing elsewhere.
    ground.install()

    # The inference mark likewise: one comparison per redraw while no tool is
    # showing one, and no per-modal lifecycle to leak.
    marks.install()


def unregister() -> None:
    # First: it is the only thing here holding an OS resource and a thread.
    textmodel.unregister()
    textmodel.unregister_ui()
    marks.uninstall()
    ground.uninstall()
    sidebar.unregister()
    workspace.unregister_handlers()
    keyconfig.unload()
    tools.unregister()
    pipeline.unregister()
    ops.unregister()

    for cls in reversed(classes):
        bpy.utils.unregister_class(cls)
