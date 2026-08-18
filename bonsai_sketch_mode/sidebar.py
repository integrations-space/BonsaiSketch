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

"""The route from a sketch into IFC, without leaving the Sketch tab.

Sketch is a single 3D viewport, and that is the whole point of it. But Bonsai
puts its authoring UI in the Properties editor -- 202 panels there against 38
in the viewport, and the two that matter most, the New Project Wizard and
Assign Class, are both Properties panels. A workspace with no Properties editor
therefore has no route into IFC at all:

- Bonsai's thirteen BIM tools sit in the Sketch toolbar, because the workspace
  does not filter tools by owner. Every one of them draws "No IFC Project" and
  returns, and nothing on this tab can create the project that would unblock
  them. The tools read as broken when they are only gated.
- README step 5 -- sketch first, assign meaning second -- ends with "switch to
  the BIM tab", which is a tab this workspace exists to avoid needing.

So this panel is the two missing buttons and nothing else. It is not a port of
Bonsai's UI into the viewport: everything past creating a project and naming
what a shape is still belongs on the BIM tab, where there is room for it.
"""

from __future__ import annotations

import bpy

from . import bridge, sketchmesh, theme

CATEGORY = "Sketch"

#: What a drawn shape can become. Bonsai's class list is filtered by this, and
#: it defaults to IfcElementType -- a *construction type*, not a thing in the
#: model. Assigning one to a sketch is never right, so the panel pins it.
OCCURRENCE = "IfcElement"


class BONSAI_SKETCH_MODE_OT_assign_class(bpy.types.Operator):
    """Assign the chosen IFC class to the selected sketch geometry"""

    bl_idname = "bonsai_sketch_mode.assign_class"
    bl_label = "Assign IFC Class"
    bl_description = "Turn this sketch into an IFC element of the chosen class"
    bl_options = {"REGISTER", "UNDO"}

    @classmethod
    def poll(cls, context: bpy.types.Context) -> bool:
        return bridge.has_project() and sketchmesh.is_sketch_object(context.active_object)

    def execute(self, context: bpy.types.Context):
        props = bridge.root_props()
        if props is None:
            self.report({"ERROR"}, "Bonsai's class properties are unavailable")
            return {"CANCELLED"}

        # A panel may not write to properties while drawing, so the correction
        # happens here instead. Bonsai's own update callback maps the class
        # across when the product changes -- IfcWallType becomes IfcWall -- so
        # a user who picked a type still gets the element they meant.
        if props.ifc_product != OCCURRENCE:
            props.ifc_product = OCCURRENCE

        try:
            result = getattr(bpy.ops.bim, bridge.ASSIGN_CLASS_OP.partition(".")[2])()
        except Exception as exc:
            self.report({"ERROR"}, f"Bonsai could not assign the class: {exc}")
            return {"CANCELLED"}
        if "CANCELLED" in result:
            return {"CANCELLED"}

        entity = bridge.get_entity(context.active_object)
        self.report({"INFO"}, f"Assigned {entity.is_a()}" if entity else "Assigned")
        return {"FINISHED"}


def set_sidebar(workspace_name: str, show: bool) -> int:
    """Show or hide the N sidebar in one workspace. Returns viewports changed.

    The workspace ships with the sidebar closed, which was right while it had
    nothing in it. Now that it carries the only route into IFC, a user who does
    not already know to press N cannot find it -- and not knowing Blender is the
    premise of this whole add-on.
    """
    changed = 0
    for space in theme.viewports(workspace_name):
        space.show_region_ui = show
        changed += 1
    if show:
        raise_category(workspace_name)
    return changed


def raise_category(workspace_name: str) -> int:
    """Bring our tab to the front of the sidebar. Returns regions changed.

    Opening the sidebar is not enough on its own. Blender remembers a category
    per region and defaults to "Item", so the sidebar opens on Transform with
    ours collapsed into a vertical tab down the edge -- which is the same
    "there is no route into IFC" problem one click further in.

    Best effort: the category only exists once the region has been drawn, and a
    workspace appended moments ago may not have been. Failing here costs the
    default tab, not the panel.
    """
    workspace = bpy.data.workspaces.get(workspace_name)
    if workspace is None:
        return 0
    changed = 0
    for screen in workspace.screens:
        for area in screen.areas:
            if area.type != "VIEW_3D":
                continue
            for region in area.regions:
                if region.type != "UI":
                    continue
                try:
                    region.active_panel_category = CATEGORY
                    changed += 1
                except (AttributeError, TypeError):
                    pass
    return changed


class BONSAI_SKETCH_MODE_PT_ifc(bpy.types.Panel):
    bl_space_type = "VIEW_3D"
    bl_region_type = "UI"
    bl_category = CATEGORY
    bl_label = "IFC"
    bl_idname = "BONSAI_SKETCH_MODE_PT_ifc"

    def draw(self, context: bpy.types.Context) -> None:
        layout = self.layout

        if not bridge.is_available():
            box = layout.box()
            box.alert = True
            box.label(text="Bonsai is not loaded", icon="ERROR")
            reason = bridge.unavailable_reason()
            if reason:
                box.label(text=reason)
            return

        if not bridge.has_project():
            self._draw_no_project(layout)
            return

        self._draw_project(context, layout)

    def _draw_no_project(self, layout: bpy.types.UILayout) -> None:
        box = layout.box()
        box.label(text="No IFC Project", icon="ERROR")
        # The single most important button on this tab. Without it the Wall,
        # Slab, Door and Window tools in the toolbar can never do anything.
        box.operator(bridge.CREATE_PROJECT_OP, text="New IFC Project", icon="ADD")
        column = box.column(align=True)
        column.scale_y = 0.8
        column.label(text="Drawing works without one.")
        column.label(text="The BIM tools do not.")

    def _draw_project(self, context: bpy.types.Context, layout: bpy.types.UILayout) -> None:
        row = layout.row(align=True)
        row.label(text=bridge.project_name() or "IFC Project", icon="FILE")

        obj = context.active_object
        if obj is None:
            layout.label(text="Nothing selected", icon="INFO")
            return

        entity = bridge.get_entity(obj)
        if entity is not None:
            box = layout.box()
            box.label(text=entity.is_a(), icon="CHECKMARK")
            column = box.column(align=True)
            column.scale_y = 0.8
            # Explaining the refusal where it is met, rather than only in the
            # README, is the difference between a rule and a bug report.
            column.label(text="Push/Pull leaves IFC elements alone.")
            column.label(text="Edit it on the BIM tab.")
            return

        if not sketchmesh.is_sketch_object(obj):
            layout.label(text="Not sketch geometry", icon="INFO")
            return

        props = bridge.root_props()
        if props is None:
            layout.label(text="Bonsai's class list is unavailable", icon="ERROR")
            return

        box = layout.box()
        box.label(text="Assign IFC Class", icon="OBJECT_DATA")
        # Only the class and its predefined type. The product dropdown above
        # them in Bonsai's own panel chooses between occurrences and
        # construction types, and on a drawn shape there is only one right
        # answer -- so the operator pins it rather than the user.
        box.prop(props, "ifc_class", text="")
        if getattr(props, "ifc_predefined_type", None) is not None:
            box.prop(props, "ifc_predefined_type", text="")
        box.operator(
            BONSAI_SKETCH_MODE_OT_assign_class.bl_idname, text="Assign", icon="CHECKMARK"
        )
        if props.ifc_product != OCCURRENCE:
            column = box.column(align=True)
            column.scale_y = 0.8
            column.label(text="Listing construction types.")
            column.label(text="Assign makes the element itself.")


classes = (BONSAI_SKETCH_MODE_OT_assign_class, BONSAI_SKETCH_MODE_PT_ifc)


def register() -> tuple[bool, str]:
    """Add the Sketch sidebar panel. Returns (ok, message). Never raises."""
    added = []
    try:
        for cls in classes:
            bpy.utils.register_class(cls)
            added.append(cls)
    except Exception as exc:  # pragma: no cover - depends on host Blender
        for cls in reversed(added):
            try:
                bpy.utils.unregister_class(cls)
            except Exception:
                pass
        return False, f"Could not add the Sketch sidebar: {exc}"
    return True, f"{len(added)} Sketch sidebar panel"


def unregister() -> None:
    for cls in reversed(classes):
        try:
            bpy.utils.unregister_class(cls)
        except Exception:
            pass
