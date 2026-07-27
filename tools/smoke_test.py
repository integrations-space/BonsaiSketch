"""Headless check that the add-on registers and its geometry layer is correct.

Run with:
    blender -b --python tools/smoke_test.py

Exits non-zero on the first failure, so it works as a CI gate. This does not
drive the modal tools -- those need a real 3D View and a mouse -- but it does
cover everything underneath them: registration, the keyconfig, the toolbar, and
the mesh operations Line, Rectangle and Push/Pull ultimately perform.
"""

import sys
import traceback

import bpy

BONSAI = "bl_ext.blender_org.bonsai"
ADDON = "bl_ext.user_default.bonsaibim_sketch_mode"

failures = []
checks = 0


def check(label, condition, detail=""):
    global checks
    checks += 1
    if condition:
        print(f"  ok    {label}")
    else:
        print(f"  FAIL  {label}" + (f" -- {detail}" if detail else ""))
        failures.append(label)


def section(title):
    print(f"\n{title}")


# --- Enable ------------------------------------------------------------------

section("Add-ons")
try:
    bpy.ops.preferences.addon_enable(module=BONSAI)
    bonsai_enabled = BONSAI in bpy.context.preferences.addons
except Exception as exc:
    bonsai_enabled = False
    print(f"  note  Bonsai could not be enabled: {exc}")
check("Bonsai enabled", bonsai_enabled)

bpy.ops.preferences.addon_enable(module=ADDON)
check("Sketch Mode enabled", ADDON in bpy.context.preferences.addons)

addon = sys.modules.get(ADDON)
check("add-on module importable", addon is not None)
if addon is None:
    print("\nCannot continue without the add-on module.")
    sys.exit(1)

bridge = addon.bridge
sketchmesh = addon.sketchmesh
tools = addon.tools
keyconfig = addon.keyconfig
rectangle = sys.modules[ADDON + ".ops.rectangle"]


# --- Bonsai surface ----------------------------------------------------------

section("Bonsai bridge")
check("Bonsai available", bridge.is_available(), bridge.unavailable_reason() or "")
check("Bonsai version detected", bridge.version() is not None)

# Deliberately not asserting the versions match. The add-on treats an untested
# Bonsai as a warning, not an error -- it says so in the preferences panel and
# carries on -- so a test that fails on any mismatch would contradict the
# design and turn every Bonsai release into a red build. What is worth
# asserting is that the guard agrees with reality.
detected = bridge.version()
check(
    "untested-version guard tracks the installed version",
    bridge.is_untested_version() == (detected != bridge.TESTED_BONSAI_VERSION),
)
if bridge.is_untested_version():
    print(
        f"  NOTE  running against Bonsai {detected}, "
        f"built against {bridge.TESTED_BONSAI_VERSION} -- "
        "everything below is therefore also an untested-version report"
    )
check(
    "polyline engine available",
    bridge.polyline_engine_available(),
    bridge.polyline_unavailable_reason() or "",
)
check("Polyline namespace bound", bridge.Polyline is not None)
check("Model namespace bound", bridge.Model is not None)
check("measure operator exists", hasattr(bpy.ops.bim, bridge.MEASURE_OP.split(".")[1]))
check(
    "clear measurement operator exists",
    hasattr(bpy.ops.bim, bridge.CLEAR_MEASUREMENT_OP.split(".")[1]),
)

# What PolylineToolBase.init_polyline calls. A signature change here is the
# most likely way a Bonsai upgrade breaks the drawing tools.
try:
    tool_state = bridge.Polyline.create_tool_state()
    input_ui = bridge.Polyline.create_input_ui(input_options=["D", "A", "X", "Y", "Z"])
    polyline_api = tool_state is not None and input_ui is not None
    detail = ""
except Exception as exc:
    polyline_api = False
    detail = str(exc)
check("polyline tool state and input UI construct", polyline_api, detail)
check("polyline props readable", bridge.Model.get_polyline_props() is not None)

# The measurement box Push/Pull types into.
check("parses a plain number", bridge.parse_length("2.5") == 2.5, f"got {bridge.parse_length('2.5')!r}")
check("parses an expression", bridge.parse_length("=1+2") == 3.0, f"got {bridge.parse_length('=1+2')!r}")
check("rejects nonsense", bridge.parse_length("banana") is None, f"got {bridge.parse_length('banana')!r}")
check("rejects empty input", bridge.parse_length("") is None)
check("formats a length", isinstance(bridge.format_length(2.5), str))


# --- Registration ------------------------------------------------------------

section("Registration")
check("Sketch keyconfig present", "Sketch" in bpy.context.window_manager.keyconfigs)
for op_name in ("line", "rectangle", "push_pull"):
    check(f"operator bonsaibim_sketch_mode.{op_name}", hasattr(bpy.ops.bonsaibim_sketch_mode, op_name))

# Mirrors how bpy.utils.register_tool finds the list it appends to.
from bl_ui.space_toolsystem_common import ToolSelectPanelHelper

registered_tools = set()
try:
    panel = ToolSelectPanelHelper._tool_class_from_space_type("VIEW_3D")
    for item in ToolSelectPanelHelper._tools_flatten(panel._tools["OBJECT"]):
        if item is not None:
            registered_tools.add(item.idname)
except Exception:
    traceback.print_exc()

for tool_cls in tools.tools:
    check(f"toolbar entry {tool_cls.bl_label}", tool_cls.bl_idname in registered_tools)


# --- Keymap ------------------------------------------------------------------

section("Keymap")
kc = bpy.context.window_manager.keyconfigs.get("Sketch")
bound = {}
if kc is not None:
    km = kc.keymaps.get("3D View")
    if km is not None:
        for kmi in km.keymap_items:
            if kmi.idname == "wm.tool_set_by_id" and not (kmi.ctrl or kmi.alt or kmi.shift):
                bound[kmi.type] = kmi.properties.name

expected = {
    "SPACE": tools.SELECT_TOOL,
    "L": tools.LINE_TOOL,
    "R": tools.RECTANGLE_TOOL,
    "P": tools.PUSH_PULL_TOOL,
    "T": tools.TAPE_TOOL,
}
for key, idname in expected.items():
    check(f"{key} -> {idname}", bound.get(key) == idname, f"got {bound.get(key)!r}")

# A claimed-but-unbuilt key must answer with nothing at all -- not merely with
# no *tool*. Checking `bound` alone would pass a key that still runs Blender's
# own unrelated operator, which is how A (Select All), C and G (Grab) stayed
# live inside the Sketch keymap while meaning Arc, Circle and Make Component to
# whoever pressed them.
for key in sorted(keyconfig.UNBUILT_KEYS):
    culprits = []
    if kc is not None:
        for km_name in keyconfig.SCOPED_KEYMAPS:
            scoped_km = kc.keymaps.get(km_name)
            if scoped_km is None:
                continue
            for kmi in scoped_km.keymap_items:
                if kmi.type != key or kmi.value != "PRESS":
                    continue
                if kmi.ctrl or kmi.alt or kmi.shift or kmi.oskey or kmi.any:
                    continue
                culprits.append(f"{km_name}:{kmi.idname}")
    check(f"{key} answers with nothing (tool not built)", not culprits,
          f"still runs {culprits}")

check("every key bound to a tool is also claimed",
      set(expected) <= keyconfig.CLAIMED_KEYS,
      f"unclaimed: {sorted(set(expected) - keyconfig.CLAIMED_KEYS)}")
check("no key is both bound and declared unbuilt",
      not (set(bound) & keyconfig.UNBUILT_KEYS),
      f"both: {sorted(set(bound) & keyconfig.UNBUILT_KEYS)}")


# --- Sketch geometry ---------------------------------------------------------

from mathutils import Vector

section("Sketch geometry")
context = bpy.context
for obj in list(bpy.data.objects):
    bpy.data.objects.remove(obj, do_unlink=True)
context.view_layer.objects.active = None

square = [Vector((0, 0, 0)), Vector((4, 0, 0)), Vector((4, 3, 0)), Vector((0, 3, 0))]
obj, faces = sketchmesh.commit(context, square, close=True)
check("closed loop creates an object", obj is not None)
check("closed loop is faced", faces == 1, f"got {faces}")
check("4 vertices", len(obj.data.vertices) == 4, f"got {len(obj.data.vertices)}")
check("4 edges", len(obj.data.edges) == 4, f"got {len(obj.data.edges)}")
check("marked as sketch geometry", sketchmesh.is_sketch_object(obj))
check("left active for the next stroke", context.view_layer.objects.active is obj)

# A second stroke should join the first, not start a new object.
tail = [Vector((4, 3, 0)), Vector((8, 3, 0))]
obj2, faces2 = sketchmesh.commit(context, tail, close=False)
check("second stroke reuses the object", obj2 is obj)
check("shared endpoint welds", len(obj.data.vertices) == 5, f"got {len(obj.data.vertices)}")
check("open stroke adds no face", faces2 == 0, f"got {faces2}")
check("5 edges", len(obj.data.edges) == 5, f"got {len(obj.data.edges)}")

# An open stroke that walks back to its start still closes.
context.view_layer.objects.active = None
triangle = [Vector((0, 0, 9)), Vector((2, 0, 9)), Vector((1, 2, 9)), Vector((0, 0, 9))]
tri_obj, tri_faces = sketchmesh.commit(context, triangle, close=False)
check("stroke back onto its start is faced", tri_faces == 1, f"got {tri_faces}")
check("start point not duplicated", len(tri_obj.data.vertices) == 3, f"got {len(tri_obj.data.vertices)}")

# Degenerate input.
none_obj, none_faces = sketchmesh.commit(context, [Vector((0, 0, 0))], close=False)
check("single point draws nothing", none_obj is None and none_faces == 0)


# --- Rectangle geometry ------------------------------------------------------

section("Rectangle")
a = Vector((1.0, 2.0, 3.0))
check("flat pair infers XY", rectangle.infer_plane(a, Vector((5.0, 7.0, 3.0))) == "XY")
check("constant Y infers XZ", rectangle.infer_plane(a, Vector((5.0, 2.0, 8.0))) == "XZ")
check("constant X infers YZ", rectangle.infer_plane(a, Vector((1.0, 7.0, 8.0))) == "YZ")

corners = rectangle.corners(a, Vector((5.0, 7.0, 3.0)), "XY")
check("XY rectangle has 4 corners", corners is not None and len(corners) == 4)
check("XY rectangle stays level", all(abs(c.z - 3.0) < 1e-9 for c in corners))
check(
    "XY corners wind around the diagonal",
    corners[1] == Vector((5.0, 2.0, 3.0)) and corners[3] == Vector((1.0, 7.0, 3.0)),
    f"got {corners}",
)

vertical = rectangle.corners(a, Vector((5.0, 2.0, 8.0)), "XZ")
check("XZ rectangle holds Y", all(abs(c.y - 2.0) < 1e-9 for c in vertical))
check("XZ rectangle spans X and Z", vertical[2] == Vector((5.0, 2.0, 8.0)), f"got {vertical}")

side = rectangle.corners(a, Vector((1.0, 7.0, 8.0)), "YZ")
check("YZ rectangle holds X", all(abs(c.x - 1.0) < 1e-9 for c in side))

check("zero-width rectangle rejected", rectangle.corners(a, Vector((1.0, 7.0, 3.0)), "XY") is None)
check("zero-height rectangle rejected", rectangle.corners(a, Vector((5.0, 2.0, 3.0)), "XY") is None)

# The rectangle a user actually gets.
context.view_layer.objects.active = None
rect_obj, rect_faces = sketchmesh.commit(context, corners, close=True)
check("rectangle is one face", rect_faces == 1, f"got {rect_faces}")
check("rectangle area is 4x5", abs(rect_obj.data.polygons[0].area - 20.0) < 1e-6)


# --- Push/Pull ---------------------------------------------------------------
#
# The modal loop needs a viewport and a mouse, but the geometry it performs
# does not -- and that is where a mistake would silently produce a mesh that
# looks solid and is not.

import bmesh
from mathutils import Matrix

section("Push/Pull")
pushpull = sys.modules[ADDON + ".ops.pushpull"]
identity = Matrix.Identity(3)
up = Vector((0.0, 0.0, 1.0))

context.view_layer.objects.active = None
plate = [Vector((0, 0, 0)), Vector((2, 0, 0)), Vector((2, 2, 0)), Vector((0, 2, 0))]
plate_obj, _ = sketchmesh.commit(context, plate, close=True)

flat = bmesh.new()
flat.from_mesh(plate_obj.data)
flat.faces.ensure_lookup_table()
check("a drawn face reads as an open sheet", pushpull.face_is_in_flat_sheet(flat.faces[0]))

box = pushpull.extruded(flat, 0, identity, up, 3.0, keep_face=True)
check("sheet extrudes to 8 vertices", len(box.verts) == 8, f"got {len(box.verts)}")
check("sheet extrudes to 6 faces", len(box.faces) == 6, f"got {len(box.faces)}")
check("box is closed", all(len(e.link_faces) == 2 for e in box.edges))
check("box volume is 2x2x3", abs(box.calc_volume(signed=False) - 12.0) < 1e-6,
      f"got {box.calc_volume(signed=False)}")
# A signed volume matching the unsigned one means every face points outward.
# A sheet's winding is arbitrary, so closing it into a solid has to fix that.
check("new solid's normals all point outward", box.calc_volume(signed=True) > 0,
      f"signed volume {box.calc_volume(signed=True)}")

# Pulling a face of that solid must consume the original face, not bury it.
box.faces.ensure_lookup_table()
top = max(box.faces, key=lambda f: f.calc_center_median().z)
check("a solid's face is not an open sheet", not pushpull.face_is_in_flat_sheet(top))

taller = pushpull.extruded(box, top.index, identity, up, 2.0, keep_face=False)
check("pulling a solid keeps 8 vertices", len(taller.verts) == 8, f"got {len(taller.verts)}")
check("pulling a solid keeps 6 faces", len(taller.faces) == 6, f"got {len(taller.faces)}")
check("no interior face left behind", all(len(e.link_faces) == 2 for e in taller.edges))
check("volume grows to 2x2x5", abs(taller.calc_volume(signed=False) - 20.0) < 1e-6,
      f"got {taller.calc_volume(signed=False)}")

# Widening a box sideways: the seam merges into the caps it extends.
side = max(box.faces, key=lambda f: f.calc_center_median().x)
wider = pushpull.extruded(box, side.index, identity, side.normal.copy(), 1.0, keep_face=False)
check("widening a box keeps 8 vertices", len(wider.verts) == 8, f"got {len(wider.verts)}")
check("widening a box keeps 6 faces", len(wider.faces) == 6, f"got {len(wider.faces)}")
check("volume grows to 3x2x3", abs(wider.calc_volume(signed=False) - 18.0) < 1e-6,
      f"got {wider.calc_volume(signed=False)}")

# Two rectangles drawn side by side into the same sketch share an edge. That
# edge has two faces, which an earlier version read as "part of a solid" -- so
# it deleted the cap and the push came out with its sides missing. Coplanar
# neighbours are still a flat sheet.
pair = bmesh.new()
pv = [pair.verts.new(c) for c in [(0, 0, 0), (2, 0, 0), (2, 2, 0), (0, 2, 0), (4, 0, 0), (4, 2, 0)]]
pair.faces.new([pv[0], pv[1], pv[2], pv[3]])
pair.faces.new([pv[1], pv[4], pv[5], pv[2]])
pair.normal_update()
pair.faces.ensure_lookup_table()

check("coplanar neighbours still count as a flat sheet",
      pushpull.face_is_in_flat_sheet(pair.faces[0]))
adjacent = pushpull.extruded(pair, 0, identity, up, 3.0, keep_face=True)
check("pushing one of two adjacent rectangles keeps its cap",
      len(adjacent.faces) == 7, f"got {len(adjacent.faces)} faces")
# Only the untouched neighbour should still have free edges: 3 of its 4.
check("the pushed box has no missing sides",
      len([e for e in adjacent.edges if len(e.link_faces) == 1]) == 3,
      f"got {len([e for e in adjacent.edges if len(e.link_faces) == 1])} open edges")
check("pushed volume is 2x2x3", abs(adjacent.calc_volume(signed=False) - 12.0) < 1e-6,
      f"got {adjacent.calc_volume(signed=False)}")

# Pushing inward is the same operation with a negative distance.
shorter = pushpull.extruded(box, top.index, identity, up, -1.0, keep_face=False)
check("pushing inward keeps it closed", all(len(e.link_faces) == 2 for e in shorter.edges))
check("volume shrinks to 2x2x2", abs(shorter.calc_volume(signed=False) - 8.0) < 1e-6,
      f"got {shorter.calc_volume(signed=False)}")

# Pushing a face into a solid must move the walls with it, not build a second
# set of walls inside the first. Extruding here left the original rim standing
# at full height around a recessed face -- a shorter box with a lip on it.
# Nothing may remain at the height the face came from.
heights = sorted({round(v.co.z, 6) for v in shorter.verts})
check("no shell left at the original height", heights == [0.0, 2.0], f"heights {heights}")
check("pushing in leaves 8 vertices", len(shorter.verts) == 8, f"got {len(shorter.verts)}")
check("pushing in leaves 6 faces", len(shorter.faces) == 6, f"got {len(shorter.faces)}")

# Zero distance must not duplicate geometry -- it is the state the tool sits in
# before the user has dragged, and every mouse move rebuilds from here.
unchanged = pushpull.extruded(flat, 0, identity, up, 0.0, keep_face=True)
check("zero distance changes nothing", len(unchanged.verts) == 4 and len(unchanged.faces) == 1)

# Non-uniform object scale must not distort the requested distance.
half = Matrix.Diagonal(Vector((2.0, 1.0, 4.0))).to_3x3()
scaled = pushpull.extruded(flat, 0, half.inverted(), up, 4.0, keep_face=True)
heights = sorted({round(v.co.z, 6) for v in scaled.verts})
check("world distance survives object scale", heights == [0.0, 1.0], f"local heights {heights}")

for mesh in (flat, box, taller, wider, shorter, unchanged, scaled):
    mesh.free()


# --- IFC+SG requirements -----------------------------------------------------

section("IFC+SG requirements")
requirements = addon.requirements
check("requirements data loads", requirements.load_error() is None, requirements.load_error() or "")
counts = requirements.summary()
check("all 21 elements present", counts["elements"] == 21, f"got {counts['elements']}")
check("853 parameters extracted", counts["parameters"] == 853, f"got {counts['parameters']}")
check("stages are ordered and named", [k for k, _ in requirements.stages()][:3]
      == ["conceptual", "schematic", "detailed"], f"got {requirements.stages()[:3]}")

# Requirements grow as a project advances. A tool that showed As-Built
# parameters during concept design would be worse than showing none.
early = requirements.parameter_names("IfcDoor", "schematic")
late = requirements.parameter_names("IfcDoor", "detailed")
check("a door needs fewer parameters early than late", len(early) < len(late),
      f"schematic {len(early)}, detailed {len(late)}")
check("early requirements survive into later stages", set(early) <= set(late),
      f"dropped {sorted(set(early) - set(late))}")
check("door parameters are real names", "Fire Rating" in late, f"got {late[:6]}")
check("names are de-duplicated across sub-elements", len(late) == len(set(late)))

check("IfcWall maps to Wall", requirements.element_for_class("IfcWall") == "Wall")
check("IfcWallStandardCase falls back to its base class",
      requirements.element_for_class("IfcWallStandardCase") == "Wall")
check("an unmapped class yields nothing",
      requirements.element_for_class("IfcNotAThing") is None)
check("unmapped classes ask for no parameters",
      requirements.parameters_for_class("IfcNotAThing", "detailed") == [])

# Deliberately unmapped elements must say why, so an empty result is never
# mistaken for "this element has no requirements".
check("External Works is unmapped with a stated reason",
      bool(requirements.unmapped_reason("External Works")))
check("Wall is mapped, so has no unmapped reason",
      requirements.unmapped_reason("Wall") is None)
check("broad mappings carry a review note",
      bool(requirements.needs_review("Terminal")))
check("the source revision is recorded", "IFC+SG" in requirements.source())


# --- Theme -------------------------------------------------------------------
#
# The one thing this add-on changes outside its own tab, so the promise that it
# can be undone has to hold exactly -- not approximately, and not back to
# Blender's defaults, but back to whatever the user had.

section("Theme")
theme = addon.theme
original = theme.snapshot()
check("canvas is not applied to begin with", theme.looks_applied() is False)
applied_ok, applied_message = theme.apply()
check("canvas applies", applied_ok, applied_message)
check("canvas reads as applied", theme.looks_applied() is True)
restored_ok, restored_message = theme.restore(original)
check("previous colours restore", restored_ok, restored_message)
check("canvas reads as removed", theme.looks_applied() is False)
check("restore is byte-exact, not approximate", theme.snapshot() == original)
check("restoring nothing is refused", theme.restore("")[0] is False)
check("unreadable saved values are refused", theme.restore("{not json")[0] is False)


# --- Unregister --------------------------------------------------------------

section("Unregister")
try:
    bpy.ops.preferences.addon_disable(module=ADDON)
    clean = True
    message = ""
except Exception as exc:
    clean = False
    message = str(exc)
check("disables cleanly", clean, message)
check("keyconfig removed", "Sketch" not in bpy.context.window_manager.keyconfigs)


# --- Result ------------------------------------------------------------------

print(f"\n{checks - len(failures)}/{checks} checks passed")
if failures:
    print("failed:")
    for name in failures:
        print(f"  - {name}")
    sys.exit(1)
print("SMOKE TEST PASSED")
sys.exit(0)
