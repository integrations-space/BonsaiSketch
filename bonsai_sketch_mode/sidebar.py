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

from . import bridge, psets, requirements, sketchmesh, theme

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


class BONSAI_SKETCH_MODE_PT_drawing(bpy.types.Panel):
    bl_space_type = "VIEW_3D"
    bl_region_type = "UI"
    bl_category = CATEGORY
    bl_label = "Import 2D Drawing"
    bl_idname = "BONSAI_SKETCH_MODE_PT_drawing"
    bl_order = -10

    def draw(self, context):
        layout = self.layout
        layout.operator_context = "INVOKE_DEFAULT"
        layout.operator("bonsai_sketch_mode.import_cad", text="Import DXF / DWG...", icon="IMPORT")
        layout.operator("bonsai_sketch_mode.build_drawing_project", text="Build IFC from Drawing Project...", icon="FILE_3D")
        layout.label(text="Local import; no AI credits needed")
        layout.label(text="DWG requires ODA File Converter")
        layout.operator("bonsai_sketch_mode.stand_up")


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


class BONSAI_SKETCH_MODE_OT_sg_check(bpy.types.Operator):
    bl_idname = "bonsai_sketch_mode.sg_check"
    bl_label = "Check Selected IFC+SG"

    @classmethod
    def poll(cls, context):
        return bridge.has_project() and bool(context.selected_objects)

    def execute(self, context):
        import json
        from . import sg
        report = {"source": requirements.source(), "stage": sg.stage(),
                  "elements": [sg.inspect(obj) for obj in context.selected_objects]}
        text = bpy.data.texts.get("Sketch IFC+SG Report.json") or bpy.data.texts.new("Sketch IFC+SG Report.json")
        text.clear()
        text.write(json.dumps(report, indent=2, default=str))
        self.report({"INFO"}, "Checklist saved in Text Editor: Sketch IFC+SG Report.json")
        return {"FINISHED"}


def attach_settings():
    """What the creation listener attaches, read from the scene. None for off.

    The same scene stage the checker reads -- the write side and the read
    side must never disagree about where the project stands. Typology and
    the switches save with the file for the same reason the stage does.
    """
    try:
        scene = bpy.context.scene
        if scene is None or not scene.bonsai_sketch_sg_attach:
            return None
        typology = scene.bonsai_sketch_sg_typology
        return psets.AttachSettings(
            stage=scene.bonsai_sketch_sg_stage,
            typology=None if typology == "none" else typology,
            include_optional=scene.bonsai_sketch_sg_optional,
        )
    except Exception:
        return None


class BONSAI_SKETCH_MODE_OT_sg_apply(bpy.types.Operator):
    bl_idname = "bonsai_sketch_mode.sg_apply"
    bl_label = "Apply to Existing Elements"
    bl_description = (
        "Attach the parameters required at the current stage -- IFC+SG, and "
        "Project Delivery if a typology is chosen -- to every element already "
        "in the project. Only missing parameters are added; values already "
        "filled in are not touched"
    )

    @classmethod
    def poll(cls, context: bpy.types.Context) -> bool:
        return psets.is_available() and bridge.has_project()

    def execute(self, context: bpy.types.Context):
        scene = context.scene
        typology = scene.bonsai_sketch_sg_typology
        settings = psets.AttachSettings(
            stage=scene.bonsai_sketch_sg_stage,
            typology=None if typology == "none" else typology,
            include_optional=scene.bonsai_sketch_sg_optional,
        )
        # Forget first: this button exists for the cases where something has
        # changed behind the listener's back, so it must not trust an
        # earlier verdict.
        psets.forget()
        touched, added = psets.sweep(bridge.ifc_file(), settings)
        for warning in requirements.delivery_warnings(settings.typology or ""):
            self.report({"WARNING"}, warning)
        if added:
            self.report({"INFO"}, f"Added {added} parameters across {touched} elements")
        else:
            self.report({"INFO"}, "Every element already carries its required parameters")
        return {"FINISHED"}


class BONSAI_SKETCH_MODE_PT_sg(bpy.types.Panel):
    bl_space_type = "VIEW_3D"
    bl_region_type = "UI"
    bl_category = CATEGORY
    bl_label = "IFC+SG Requirements"
    bl_idname = "BONSAI_SKETCH_MODE_PT_sg"

    def draw(self, context):
        from . import sg
        from . import sg_defaults
        layout = self.layout
        if hasattr(context.scene, 'bonsai_sketch_sg_auto'):
            layout.prop(context.scene, 'bonsai_sketch_sg_auto')
        layout.label(text='Automatic fields: IFC4 mapping, 4 Dec 2025')
        layout.label(text='New BIM / classified Sketch elements')
        layout.label(text='Empty fields still need design values')
        if sg_defaults.status():
            layout.label(text='Automatic field setup failed; see console', icon='ERROR')
        if bridge.has_project() and bridge.Ifc.get().schema != 'IFC4':
            layout.label(text='Automatic field setup supports IFC4 only', icon='INFO')
        layout.separator()
        layout.prop(context.scene, "bonsai_sketch_sg_stage", text="Stage")
        layout.prop(context.scene, "bonsai_sketch_sg_typology", text="Typology")
        col = layout.column(align=True)
        col.prop(context.scene, "bonsai_sketch_sg_attach")
        sub = col.row()
        sub.enabled = context.scene.bonsai_sketch_sg_typology != "none"
        sub.prop(context.scene, "bonsai_sketch_sg_optional")
        if context.scene.bonsai_sketch_sg_typology != "none":
            for warning in requirements.delivery_warnings(context.scene.bonsai_sketch_sg_typology):
                row = layout.row()
                row.alert = True
                row.label(text=warning, icon="ERROR")
        if bridge.has_project():
            layout.operator(BONSAI_SKETCH_MODE_OT_sg_apply.bl_idname, icon="FILE_REFRESH")
        layout.label(text="Model Content Requirements V2.0")
        layout.label(text="20 Mar 2026; candidate checklist")
        if requirements.load_error():
            layout.label(text=requirements.load_error(), icon="ERROR")
            return
        obj = context.active_object
        if obj is None or bridge.get_entity(obj) is None:
            layout.label(text="Select a classified IFC element", icon="INFO")
            return
        result = sg.inspect(obj)
        entity = bridge.get_entity(obj)
        exact = sg_defaults.applicable(entity)
        layout.label(text=f'{len(exact)} exact mapping fields for this subtype')
        layout.label(text=result["element"] or "Unmapped element", icon="INFO")
        layout.label(text="Review applicability and Pset mapping")
        missing = result["missing"]
        layout.label(text=f"{len(missing)} candidate fields missing")
        for name in missing[:10]:
            layout.label(text=name, icon="DOT")
        if len(missing) > 10:
            layout.label(text=f"... and {len(missing) - 10} more in report")
        layout.operator(BONSAI_SKETCH_MODE_OT_sg_check.bl_idname)
        layout.label(text="Not a regulatory compliance verdict")


class BONSAI_SKETCH_MODE_PT_perspective(bpy.types.Panel):
    bl_space_type = "VIEW_3D"
    bl_region_type = "UI"
    bl_category = CATEGORY
    bl_label = "Perspective & Style"
    bl_idname = "BONSAI_SKETCH_MODE_PT_perspective"
    bl_options = {"DEFAULT_CLOSED"}

    def draw(self, context):
        from . import style

        layout = self.layout
        layout.operator("bonsai_sketch_mode.camera_from_view", icon="CAMERA_DATA")
        layout.operator("bonsai_sketch_mode.camera_two_point", icon="DRIVER_ROTATIONAL_DIFFERENCE")
        if style.is_on(context.scene):
            layout.operator("bonsai_sketch_mode.sketch_style",
                            text="Sketch Style Off", icon="SHADING_SOLID").mode = "OFF"
        else:
            layout.operator("bonsai_sketch_mode.sketch_style",
                            text="Sketch Style On", icon="GREASEPENCIL").mode = "ON"


classes = (BONSAI_SKETCH_MODE_PT_drawing, BONSAI_SKETCH_MODE_OT_assign_class, BONSAI_SKETCH_MODE_PT_ifc,
           BONSAI_SKETCH_MODE_OT_sg_check, BONSAI_SKETCH_MODE_OT_sg_apply,
           BONSAI_SKETCH_MODE_PT_sg, BONSAI_SKETCH_MODE_PT_perspective)


def register() -> tuple[bool, str]:
    """Add the Sketch sidebar panel. Returns (ok, message). Never raises."""
    added = []
    try:
        bpy.types.Scene.bonsai_sketch_sg_stage = bpy.props.EnumProperty(
            name="IFC+SG Stage", items=[(key, label, label) for key, label in requirements.stages()],
            default="conceptual")
        bpy.types.Scene.bonsai_sketch_sg_typology = bpy.props.EnumProperty(
            name="Typology",
            description=(
                "What kind of project this is. The Project Delivery "
                "requirements differ per building typology; choosing one "
                "attaches that typology's parameters as a "
                f"{psets.DELIVERY_PSET_NAME!r} set beside the IFC+SG set. "
                "Left unset, only IFC+SG attaches -- never guessed"
            ),
            items=[("none", "None (IFC+SG only)", "Attach only the IFC+SG parameters")]
            + [(key, label, label) for key, label in requirements.typologies()],
            default="none")
        bpy.types.Scene.bonsai_sketch_sg_attach = bpy.props.BoolProperty(
            name="Attach on Creation",
            description=(
                "Give every newly created element the parameters the Model "
                "Content Requirements ask of it, as property sets with the "
                "values left for you to fill in"
            ),
            default=True)
        bpy.types.Scene.bonsai_sketch_sg_optional = bpy.props.BoolProperty(
            name="Include Optional Parameters",
            description=(
                "Also attach the Project Delivery parameters the workbook "
                "marks 'O' (optional). The IFC+SG set has none, so this only "
                "matters once a typology is chosen"
            ),
            default=False)
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
    # The write side of IFC+SG starts with the panel that controls it: from
    # here on, every element created gets the parameters its class owes at
    # the scene's stage (psets.py). install() degrades to a message when
    # ifcopenshell or the data cannot be reached.
    attached, note = psets.install(attach_settings)
    if not attached:
        print(f"[bonsai_sketch_mode] IFC+SG attachment: {note}")
    return True, f"{len(added)} Sketch sidebar panel"


def unregister() -> None:
    psets.remove()
    for prop in ("bonsai_sketch_sg_stage", "bonsai_sketch_sg_typology",
                 "bonsai_sketch_sg_attach", "bonsai_sketch_sg_optional"):
        if hasattr(bpy.types.Scene, prop):
            delattr(bpy.types.Scene, prop)
    for cls in reversed(classes):
        try:
            bpy.utils.unregister_class(cls)
        except Exception:
            pass
