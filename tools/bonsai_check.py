"""Headless check that Bonsai's own authoring path works under Sketch Mode.

Run with:
    blender -b --python tools/bonsai_check.py

`smoke_test.py` covers this add-on's layer: its registration, its keymap and the
mesh operations its tools perform. It deliberately never touches Bonsai's
authoring operators, so a Bonsai upgrade that broke "add a door" would leave it
fully green -- which is exactly the gap that let the BIM tools read as broken.

This walks the path a user actually takes: create a project, create a
construction type, place an occurrence, void it with a sketch mesh, and assign
a class to plain geometry. Every step is the operator the toolbar button calls,
so a break here is a break in the product.

Two things this cannot reach, both marked SKIP rather than passed:

- The toolbar itself. `bonsai/bim/module/model/__init__.py` guards
  `register_tool` with `if not bpy.app.background`, so under `-b` Bonsai's
  tools are never registered and their presence cannot be asserted. That is
  `ui_check.py`'s job.
- The modal placement operators (`bim.draw_occurrence`,
  `bim.draw_polyline_wall`). They need a viewport and a mouse.
  `bim.add_occurrence` is the non-modal equivalent and is what runs here.

Exits non-zero on the first failure so it works as a CI gate.
"""

import sys
import traceback

import bpy

BONSAI = "bl_ext.blender_org.bonsai"
ADDON = "bl_ext.user_default.bonsai_sketch_mode"

failures = []
skipped = []
checks = 0


def check(label, condition, detail=""):
    global checks
    checks += 1
    if condition:
        print(f"  ok    {label}")
    else:
        print(f"  FAIL  {label}" + (f" -- {detail}" if detail else ""))
        failures.append(label)


def skip(label, why):
    print(f"  skip  {label} -- {why}")
    skipped.append(label)


def section(title):
    print(f"\n{title}")


def attempt(label, fn):
    """Run fn, reporting the exception as the failure detail rather than dying.

    A report that stops at the first traceback says nothing about the twelve
    checks after it, and those are usually what identify the cause.
    """
    try:
        ok, detail = fn()
        check(label, ok, detail)
        return ok
    except Exception as exc:
        check(label, False, f"{type(exc).__name__}: {exc}")
        traceback.print_exc()
        return False


# --- Enable ------------------------------------------------------------------

section("Add-ons")
bpy.ops.preferences.addon_enable(module=BONSAI)
check("Bonsai enabled", BONSAI in bpy.context.preferences.addons)
bpy.ops.preferences.addon_enable(module=ADDON)
check("Sketch Mode enabled", ADDON in bpy.context.preferences.addons)

addon = sys.modules.get(ADDON)
if addon is None:
    print("\nCannot continue without the add-on module.")
    sys.exit(1)

bridge = addon.bridge
sketchmesh = addon.sketchmesh
check(
    "Bonsai importable through the bridge",
    bridge.is_available(),
    bridge.unavailable_reason() or "",
)
print(f"  note  Bonsai {bridge.version()}, built against {bridge.TESTED_BONSAI_VERSION}")

import bonsai.tool as tool


# --- The operators the toolbar buttons call ----------------------------------
#
# bridge.py names these as a "verified Bonsai surface" and keeps them in step
# with the tested version by hand. That claim is only worth anything if
# something checks it.

section("Bonsai operator surface")
SURFACE = [
    bridge.MEASURE_OP,
    bridge.MEASURE_FACE_AREA_OP,
    bridge.CLEAR_MEASUREMENT_OP,
    bridge.ASSIGN_CLASS_OP,
    bridge.UPDATE_REPRESENTATION_OP,
    bridge.DELETE_OP,
    "bim.create_project",
    "bim.add_default_type",
    "bim.add_element",
    "bim.add_occurrence",
    "bim.draw_occurrence",
    "bim.draw_polyline_wall",
    "bim.launch_type_manager",
    "bim.add_opening",
    "bim.add_boolean",
]
for idname in SURFACE:
    module, _, name = idname.partition(".")
    check(f"operator {idname}", hasattr(getattr(bpy.ops, module), name))

section("Bonsai toolbar")
skip(
    "13 BIM tools in the 3D View toolbar",
    "register_tool is guarded by `if not bpy.app.background` -- see ui_check.py",
)


# --- Gate 1: no project ------------------------------------------------------
#
# What a user sees on the Sketch tab before doing anything. CreateObjectUI
# returns after one error label when this is None, which is the whole of
# "the Bonsai tools do not work".

section("Gate 1 -- before a project exists")
check("no IFC project to begin with", tool.Ifc.get() is None)
check("bridge agrees there is no project", bridge.has_project() is False)


# --- Create a project --------------------------------------------------------

section("Creating a project")


def create_project():
    bpy.ops.bim.create_project()
    return tool.Ifc.get() is not None, "tool.Ifc.get() still None"


attempt("bim.create_project makes a project", create_project)
ifc = tool.Ifc.get()
if ifc is None:
    print("\nCannot continue without a project.")
    sys.exit(1)
check("bridge sees the project", bridge.has_project() is True)
print(f"  note  schema {ifc.schema}")
check("project has an IfcProject", len(ifc.by_type("IfcProject")) == 1)


# --- Gate 2: no construction types -------------------------------------------

section("Gate 2 -- a fresh project has no types")
check("no IfcWallType yet", len(ifc.by_type("IfcWallType")) == 0)
check("no IfcDoorType yet", len(ifc.by_type("IfcDoorType")) == 0)


def add_type(ifc_class):
    def run():
        before = len(ifc.by_type(ifc_class))
        bpy.ops.bim.add_default_type(ifc_element_type=ifc_class)
        after = len(ifc.by_type(ifc_class))
        return after > before, f"{ifc_class} count stayed at {before}"

    return run


section("Creating construction types")
attempt("bim.add_default_type creates an IfcWallType", add_type("IfcWallType"))
attempt("bim.add_default_type creates an IfcDoorType", add_type("IfcDoorType"))


# --- Placing occurrences -----------------------------------------------------
#
# bim.draw_occurrence is modal; bim.add_occurrence is the same creation without
# the mouse. If this fails, the toolbar path is broken for a reason that has
# nothing to do with the modal.

section("Placing occurrences")


def add_occurrence(type_class, occurrence_class):
    def run():
        types = ifc.by_type(type_class)
        if not types:
            return False, f"no {type_class} to place"
        before = len(ifc.by_type(occurrence_class))
        bpy.ops.bim.add_occurrence(relating_type_id=types[0].id())
        after = len(ifc.by_type(occurrence_class))
        return after > before, f"{occurrence_class} count stayed at {before}"

    return run


attempt("a wall occurrence is created", add_occurrence("IfcWallType", "IfcWall"))
attempt("a door occurrence is created", add_occurrence("IfcDoorType", "IfcDoor"))

walls = [o for o in bpy.data.objects if (e := tool.Ifc.get_entity(o)) and e.is_a("IfcWall")]
check("the wall has a Blender object", bool(walls), "no object carries an IfcWall")


# --- Sketch geometry as a void -----------------------------------------------
#
# bim.add_opening's own description says "Opening can be just a Blender mesh
# object", which makes a Sketch-drawn box a valid cutter against an IFC wall.
# Nothing in this repo uses that, and nothing tested it until now.

section("Sketch geometry voiding an IFC element")

import bmesh
from mathutils import Matrix, Vector

pushpull = sys.modules[ADDON + ".ops.pushpull"]
context = bpy.context


def sketch_box():
    """A box drawn the way the tools draw one: commit, then extrude."""
    context.view_layer.objects.active = None
    corners = [Vector((0, 0, 0)), Vector((1, 0, 0)), Vector((1, 1, 0)), Vector((0, 1, 0))]
    obj, _ = sketchmesh.commit(context, corners, close=True)
    source = bmesh.new()
    source.from_mesh(obj.data)
    source.faces.ensure_lookup_table()
    solid = pushpull.extruded(
        source, 0, Matrix.Identity(3), Vector((0, 0, 1)), 2.0, pushpull.EXTRUDE
    )
    solid.to_mesh(obj.data)
    solid.free()
    source.free()
    obj.data.update()
    return obj


def void_a_wall():
    if not walls:
        return False, "no wall to void"
    wall = walls[0]
    cutter = sketch_box()
    check("the cutter is plain sketch geometry", sketchmesh.is_sketch_object(cutter))

    before = len(ifc.by_type("IfcOpeningElement"))
    bpy.ops.object.select_all(action="DESELECT")
    # add_opening takes selected_objects[0] as the target, so the wall must be
    # first. Selection order is not preserved, so select the wall alone, then
    # add the cutter -- which is also how the tool header's "Apply Void" button
    # ends up with them.
    wall.select_set(True)
    context.view_layer.objects.active = wall
    cutter.select_set(True)
    bpy.ops.bim.add_opening()
    after = len(ifc.by_type("IfcOpeningElement"))
    return after > before, f"IfcOpeningElement count stayed at {before}"


attempt("a sketch mesh voids an IFC wall", void_a_wall)
check(
    "the void is a real IfcRelVoidsElement",
    len(ifc.by_type("IfcRelVoidsElement")) > 0,
    "no voids relationship recorded",
)


# --- Assign class ------------------------------------------------------------
#
# The README's step 5: sketch first, decide what it is second. If this breaks,
# the sketch half of the product has no exit into IFC at all.

section("Assign IFC Class")


def assign_class():
    context.view_layer.objects.active = None
    plate = [Vector((10, 0, 0)), Vector((13, 0, 0)), Vector((13, 2, 0)), Vector((10, 2, 0))]
    obj, _ = sketchmesh.commit(context, plate, close=True)
    check("starts as plain geometry", bridge.get_entity(obj) is None)

    bpy.ops.object.select_all(action="DESELECT")
    obj.select_set(True)
    context.view_layer.objects.active = obj
    props = tool.Root.get_root_props()
    props.ifc_product = "IfcElement"
    props.ifc_class = "IfcSlab"
    bpy.ops.bim.assign_class()
    entity = bridge.get_entity(obj)
    return entity is not None and entity.is_a("IfcSlab"), f"got {entity}"


assigned = attempt("a sketch mesh becomes an IfcSlab", assign_class)


# --- The Sketch tab's route into IFC -----------------------------------------
#
# The Sketch workspace is a single 3D viewport, and Bonsai's authoring UI is
# almost entirely Properties-editor panels. Everything above passes while that
# route is unreachable from the tab a user is actually sitting on, which is
# precisely how "the BIM tools do not work" happens with nothing failing.
#
# sidebar.py is that route. These check the Bonsai surface it depends on;
# ui_check.py checks that the panel is on screen.

section("Sketch sidebar's route into IFC")

sidebar = sys.modules[ADDON + ".sidebar"]

check(
    "the sidebar panel is registered",
    hasattr(bpy.types, "BONSAI_SKETCH_MODE_PT_ifc"),
)
check(
    "it sits in the 3D View sidebar",
    sidebar.BONSAI_SKETCH_MODE_PT_ifc.bl_space_type == "VIEW_3D"
    and sidebar.BONSAI_SKETCH_MODE_PT_ifc.bl_region_type == "UI",
)

module, _, name = bridge.CREATE_PROJECT_OP.partition(".")
check(
    f"its New IFC Project button calls a real operator ({bridge.CREATE_PROJECT_OP})",
    hasattr(getattr(bpy.ops, module), name),
)

check("bridge.project_name reads the open project", bool(bridge.project_name()))

props = bridge.root_props()
check("bridge.root_props reaches Bonsai's class properties", props is not None)
# The panel draws these three by name. A rename in Bonsai would leave the
# panel drawing nothing and the Assign button assigning whatever was last set.
for field in ("ifc_product", "ifc_class", "ifc_predefined_type"):
    check(f"root props still expose {field}", props is not None and hasattr(props, field))


# The trap this operator exists to close: Bonsai's class list is filtered by
# ifc_product, which defaults to IfcElementType. Assigning a *construction
# type* to a drawn shape is never what the user meant, and nothing in Bonsai's
# UI stops it happening from a panel that only shows the class.

section("Assign from the sidebar pins the product to an occurrence")


def assign_from_sidebar():
    context.view_layer.objects.active = None
    pts = [Vector((20, 0, 0)), Vector((24, 0, 0)), Vector((24, 3, 0)), Vector((20, 3, 0))]
    obj, _ = sketchmesh.commit(context, pts, close=True)
    bpy.ops.object.select_all(action="DESELECT")
    obj.select_set(True)
    context.view_layer.objects.active = obj

    props = tool.Root.get_root_props()
    props.ifc_product = "IfcElementType"
    props.ifc_class = "IfcWallType"
    check("starts pointed at a construction type", props.ifc_product == "IfcElementType")

    bpy.ops.bonsai_sketch_mode.assign_class()
    entity = bridge.get_entity(obj)
    check("the product was corrected to an occurrence", props.ifc_product == sidebar.OCCURRENCE)
    return (
        entity is not None and entity.is_a("IfcWall"),
        f"got {entity.is_a() if entity else None}, expected IfcWall",
    )


attempt("IfcWallType becomes an IfcWall, not a type", assign_from_sidebar)


# --- Push/Pull's refusal -----------------------------------------------------
#
# The guard that stops a parametric definition being tessellated away. It reads
# the entity through the bridge, which is testable without the modal.

section("Push/Pull declines IFC elements")
typed = [o for o in bpy.data.objects if bridge.get_entity(o) is not None]
check("there is a typed element to refuse", bool(typed))
if typed:
    check("the bridge reports its entity", bridge.get_entity(typed[0]) is not None)
    check(
        "sketchmesh does not claim it",
        not sketchmesh.is_sketch_object(typed[0]),
        "an IFC element reads as sketch geometry, so Push/Pull would rewrite it",
    )


# --- Result ------------------------------------------------------------------

print(f"\n{checks - len(failures)}/{checks} checks passed, {len(skipped)} skipped")
if failures:
    print("failed:")
    for name in failures:
        print(f"  - {name}")
    sys.exit(1)
print("BONSAI CHECK PASSED")
sys.exit(0)
