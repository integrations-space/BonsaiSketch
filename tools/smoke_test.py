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
ADDON = "bl_ext.user_default.bonsai_sketch_mode"

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
for op_name in ("line", "rectangle", "push_pull", "offset", "eraser"):
    check(f"operator bonsai_sketch_mode.{op_name}", hasattr(bpy.ops.bonsai_sketch_mode, op_name))

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
    "F": tools.OFFSET_TOOL,
    "E": tools.ERASER_TOOL,
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
check("a drawn face reads as an open sheet", pushpull.push_mode(flat.faces[0]) == pushpull.EXTRUDE)

box = pushpull.extruded(flat, 0, identity, up, 3.0, pushpull.EXTRUDE)
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
check("a solid's face is not an open sheet", pushpull.push_mode(top) == pushpull.MOVE)

taller = pushpull.extruded(box, top.index, identity, up, 2.0, pushpull.MOVE)
check("pulling a solid keeps 8 vertices", len(taller.verts) == 8, f"got {len(taller.verts)}")
check("pulling a solid keeps 6 faces", len(taller.faces) == 6, f"got {len(taller.faces)}")
check("no interior face left behind", all(len(e.link_faces) == 2 for e in taller.edges))
check("volume grows to 2x2x5", abs(taller.calc_volume(signed=False) - 20.0) < 1e-6,
      f"got {taller.calc_volume(signed=False)}")

# Widening a box sideways: the seam merges into the caps it extends.
side = max(box.faces, key=lambda f: f.calc_center_median().x)
wider = pushpull.extruded(box, side.index, identity, side.normal.copy(), 1.0, pushpull.MOVE)
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
      pushpull.push_mode(pair.faces[0]) == pushpull.EXTRUDE)
adjacent = pushpull.extruded(pair, 0, identity, up, 3.0, pushpull.EXTRUDE)
check("pushing one of two adjacent rectangles keeps its cap",
      len(adjacent.faces) == 7, f"got {len(adjacent.faces)} faces")
# Only the untouched neighbour should still have free edges: 3 of its 4.
check("the pushed box has no missing sides",
      len([e for e in adjacent.edges if len(e.link_faces) == 1]) == 3,
      f"got {len([e for e in adjacent.edges if len(e.link_faces) == 1])} open edges")
check("pushed volume is 2x2x3", abs(adjacent.calc_volume(signed=False) - 12.0) < 1e-6,
      f"got {adjacent.calc_volume(signed=False)}")

# Pushing inward is the same operation with a negative distance.
shorter = pushpull.extruded(box, top.index, identity, up, -1.0, pushpull.MOVE)
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
unchanged = pushpull.extruded(flat, 0, identity, up, 0.0, pushpull.EXTRUDE)
check("zero distance changes nothing", len(unchanged.verts) == 4 and len(unchanged.faces) == 1)

# --- Regional push-pull ------------------------------------------------------
#
# A face divided by lines into sub-regions can be pushed independently. Pushing
# one sub-region extrudes just that region, creating walls along its boundary,
# while the surrounding sheet stays in place. This is the SketchUp behaviour
# for intersected lines and shapes.

# A 4x4 sheet divided into four 2x2 quadrants by a cross of lines.
regional = bmesh.new()
rv = [regional.verts.new(c) for c in [
    (0, 0, 0), (2, 0, 0), (4, 0, 0),
    (0, 2, 0), (2, 2, 0), (4, 2, 0),
    (0, 4, 0), (2, 4, 0), (4, 4, 0),
]]
# Bottom-left quadrant.
regional.faces.new([rv[0], rv[1], rv[4], rv[3]])
# Bottom-right quadrant.
regional.faces.new([rv[1], rv[2], rv[5], rv[4]])
# Top-left quadrant.
regional.faces.new([rv[3], rv[4], rv[7], rv[6]])
# Top-right quadrant.
regional.faces.new([rv[4], rv[5], rv[8], rv[7]])
regional.normal_update()
regional.faces.ensure_lookup_table()

# Every quadrant has coplanar neighbours and nothing out of plane, so each is a
# region of a sheet: extruded, with the original face left as the bottom cap.
check("a divided sheet's region reads as extrudable",
      all(pushpull.push_mode(f) == pushpull.EXTRUDE for f in regional.faces))

# Pushing one quadrant extrudes just that region, leaving the other three flat.
pushed_region = pushpull.extruded(regional, 0, identity, up, 3.0, pushpull.EXTRUDE)
# 9 original verts + 4 new verts from the extruded quadrant = 13.
check("regional push adds 4 vertices", len(pushed_region.verts) == 13,
      f"got {len(pushed_region.verts)}")
# 4 original faces + 1 extruded top + 4 side walls = 9.
check("regional push adds 5 faces", len(pushed_region.faces) == 9,
      f"got {len(pushed_region.faces)}")
# The three untouched quadrants plus the pushed region's bottom cap stay at z=0.
flat_centers = [f.calc_center_median().z for f in pushed_region.faces
                if abs(f.calc_center_median().z) < 0.5]
check("untouched regions stay flat", len(flat_centers) == 4, f"got {len(flat_centers)}")
# The pushed region's top is at z=3.
top_centers = [f.calc_center_median().z for f in pushed_region.faces
               if f.calc_center_median().z > 2.5]
check("pushed region rises to 3", len(top_centers) == 1, f"got {len(top_centers)}")
# The dividing lines are undisturbed: the shared centre vertex is still at z=0.
centre = next(v for v in pushed_region.verts if (v.co - Vector((2, 2, 0))).length < 1e-6)
check("dividing lines stay in place", abs(centre.co.z) < 1e-6, f"centre z {centre.co.z}")

# Pushing a region of a solid's face (e.g. a line across a box's top) must
# extrude just that region, not move the whole face.
# Build a 2x2x3 box with the top face split into two halves by a dividing
# edge at x=1 -- exactly what a user gets by drawing a line across a box's top.
# The dividing edge runs through the front, top and back faces, so each of
# those is split into two faces.
split = bmesh.new()
sv = [split.verts.new(c) for c in [
    (0, 0, 0), (1, 0, 0), (2, 0, 0), (2, 2, 0), (1, 2, 0), (0, 2, 0),
    (0, 0, 3), (1, 0, 3), (2, 0, 3), (2, 2, 3), (1, 2, 3), (0, 2, 3),
]]
# Bottom-left face (wound so its normal points down).
split.faces.new([sv[0], sv[5], sv[4], sv[1]])
# Bottom-right face (wound so its normal points down).
split.faces.new([sv[1], sv[4], sv[3], sv[2]])
# Front-left face (y=0, x<1).
split.faces.new([sv[0], sv[1], sv[7], sv[6]])
# Front-right face (y=0, x>1).
split.faces.new([sv[1], sv[2], sv[8], sv[7]])
# Right face (x=2).
split.faces.new([sv[2], sv[3], sv[9], sv[8]])
# Back-right face (y=2, x>1).
split.faces.new([sv[3], sv[4], sv[10], sv[9]])
# Back-left face (y=2, x<1).
split.faces.new([sv[4], sv[5], sv[11], sv[10]])
# Left face (x=0).
split.faces.new([sv[5], sv[0], sv[6], sv[11]])
# Top-left half.
split.faces.new([sv[6], sv[7], sv[10], sv[11]])
# Top-right half.
split.faces.new([sv[7], sv[8], sv[9], sv[10]])
split.normal_update()
split.faces.ensure_lookup_table()

# Each half of the split top has a coplanar neighbour (the other half) and the
# side walls out of plane, so it is a region of a *solid* -- CUT, not EXTRUDE.
# The difference is the face the region grew from: on a sheet it becomes the
# bottom cap, but here the solid's interior is behind it, and leaving it in
# seals a membrane across the inside of the step.
halves = [f for f in split.faces if f.normal.z > 0.9]
check("a split solid face reads as a region", len(halves) == 2,
      f"got {len(halves)} top faces")
check("a region of a solid is cut, not capped",
      all(pushpull.push_mode(f) == pushpull.CUT for f in halves))

# Pushing one half up by 2 makes a step: 2x2x3 plus a raised 1x2x2.
stepped = pushpull.extruded(split, halves[0].index, identity, up, 2.0, pushpull.CUT)
check("stepped push leaves no open edges",
      all(len(e.link_faces) >= 2 for e in stepped.edges))
check("a step leaves no interior membrane",
      all(len(e.link_faces) == 2 for e in stepped.edges),
      f"{sum(1 for e in stepped.edges if len(e.link_faces) != 2)} edges are not shared by 2 faces")
# The volume is the arithmetic and catches a buried membrane, which the face
# and vertex counts alone do not: with the membrane left in this measured 14.
check("stepped volume is 12 + 1x2x2", abs(stepped.calc_volume(signed=False) - 16.0) < 1e-6,
      f"got {stepped.calc_volume(signed=False)}")
check("the step points outward", stepped.calc_volume(signed=True) > 0,
      f"signed volume {stepped.calc_volume(signed=True)}")
# Exactly one horizontal face survives at the old height: the untouched half.
at_old_height = [f for f in stepped.faces
                 if abs(f.calc_center_median().z - 3.0) < 1e-6 and abs(f.normal.z) > 0.9]
check("only the untouched half remains at the old height", len(at_old_height) == 1,
      f"got {len(at_old_height)}")
heights = sorted({round(v.co.z, 6) for v in stepped.verts})
check("stepped push creates two levels", heights == [0.0, 3.0, 5.0],
      f"heights {heights}")

# The same region pushed the other way is a notch cut into the slab. The walls
# inherit the winding of the face they grew from, which points the wrong way
# for an inward push -- so this is where an un-recalculated shell shows up as a
# negative volume.
notched = pushpull.extruded(split, halves[0].index, identity, up, -1.0, pushpull.CUT)
check("a notch stays closed", all(len(e.link_faces) == 2 for e in notched.edges))
check("notched volume is 12 - 1x2x1", abs(notched.calc_volume(signed=False) - 10.0) < 1e-6,
      f"got {notched.calc_volume(signed=False)}")
check("the notch points outward", notched.calc_volume(signed=True) > 0,
      f"signed volume {notched.calc_volume(signed=True)}")

# Ctrl overrides the mode and stacks a new solid on a face that already belongs
# to one, leaving the original in place as the join. That makes the shell
# non-manifold on purpose, so "outward" is ambiguous and normals must be left
# as they are -- recalculating turned the outer surface inside out.
box.faces.ensure_lookup_table()
top = max(box.faces, key=lambda f: f.calc_center_median().z)
stacked = pushpull.extruded(box, top.index, identity, up, 2.0, pushpull.EXTRUDE)
check("Ctrl stacking adds a solid", len(stacked.verts) == 12 and len(stacked.faces) == 11,
      f"got {len(stacked.verts)} verts, {len(stacked.faces)} faces")
check("Ctrl stacking leaves no open edges",
      all(len(e.link_faces) >= 2 for e in stacked.edges))
check("Ctrl stacking keeps the join", len(
    [f for f in stacked.faces
     if abs(f.calc_center_median().z - 3.0) < 1e-6 and abs(f.normal.z) > 0.9]) == 1)
# Every outward-facing face of the original box must still face outward.
outward = {
    (1.0, 1.0, 0.0): Vector((0.0, 0.0, -1.0)),
    (2.0, 1.0, 1.5): Vector((1.0, 0.0, 0.0)),
    (0.0, 1.0, 1.5): Vector((-1.0, 0.0, 0.0)),
    (1.0, 2.0, 1.5): Vector((0.0, 1.0, 0.0)),
    (1.0, 0.0, 1.5): Vector((0.0, -1.0, 0.0)),
    (1.0, 1.0, 5.0): Vector((0.0, 0.0, 1.0)),
}
flipped = [key for f in stacked.faces
           for key in [tuple(round(x, 2) for x in f.calc_center_median())]
           if key in outward and f.normal.dot(outward[key]) < 0.9]
check("Ctrl stacking keeps the outer surface right side out", not flipped,
      f"flipped {flipped}")

# --- Nested regional push-pull ----------------------------------------------
#
# The point of regional push-pull is that a solid raised out of a sheet can
# itself be subdivided and pushed again -- a plinth out of a slab, then a
# pedestal out of the plinth. Each push reads the current surface the same way
# the first did: a face with coplanar neighbours becomes a region, and a region
# of a solid is cut, not capped.

# Start from the already-tested `stepped` shape: a 2x2x3 box with one 1x2x2
# step raised out of its top. Bisect the whole solid at y=1, the middle of its
# footprint. That splits the step's top into two 0.5x1 halves, and because the
# cut plane passes through the entire solid it splits the step's walls and the
# box's sides too -- exactly what a drawn line does. No seams for the nested
# push to open.
nested = stepped.copy()
bmesh.ops.bisect_plane(
    nested,
    geom=nested.verts[:] + nested.edges[:] + nested.faces[:],
    plane_co=(0.0, 1.0, 0.0),
    plane_no=(0.0, 1.0, 0.0),
    clear_inner=False,
    clear_outer=False,
)
nested.normal_update()
nested.faces.ensure_lookup_table()

# The step's top at z=5 is now two 0.5x1 halves. Each has a coplanar neighbour
# plus walls out of plane, so both read as CUT.
inner_halves = [
    f for f in nested.faces
    if abs(f.calc_center_median().z - 5.0) < 1e-6 and abs(f.normal.z) > 0.9
]
check("a subdivided raised region reads as CUT",
      len(inner_halves) == 2
      and all(pushpull.push_mode(f) == pushpull.CUT for f in inner_halves),
      f"got {len(inner_halves)} halves, modes {[pushpull.push_mode(f) for f in inner_halves]}")

# Push one half up 1 more. Volume: the 2x2x3 box (12) plus the step (1x2x2 =
# 4) plus the new 1x1x1 (1) = 17.
tower = pushpull.extruded(nested, inner_halves[0].index, identity, up, 1.0, pushpull.CUT)
check("nested push volume is 12 + 4 + 1", abs(tower.calc_volume(signed=False) - 17.0) < 1e-6,
      f"got {tower.calc_volume(signed=False)}")
check("nested push points outward", tower.calc_volume(signed=True) > 0,
      f"signed volume {tower.calc_volume(signed=True)}")
open_edges = [e for e in tower.edges if len(e.link_faces) < 2]
check("nested push leaves no open edges", not open_edges,
      f"{len(open_edges)} open edges")
heights = sorted({round(v.co.z, 6) for v in tower.verts})
check("nested push creates three levels", heights == [0.0, 3.0, 5.0, 6.0],
      f"heights {heights}")

nested.free()
tower.free()

for mesh in (regional, pushed_region, split, stepped, notched, stacked):
    mesh.free()

# --- Inference --------------------------------------------------------------
#
# Dragging a face should stop where geometry already is: the top of the wall
# beside this one, the underside of the slab above it. The candidates are the
# distances the face has to travel for its plane to reach each point, gathered
# once at the start of the push. Choosing between them happens in pixels and
# needs a viewport, so what is checked here is which candidates exist and which
# two of them a given drag is between.

origin = Vector((0.0, 0.0, 0.0))
points = [
    Vector((5.0, 5.0, 3.0)),    # 3 above
    Vector((-2.0, 9.0, 3.0)),   # also 3 above -- the same candidate
    Vector((0.0, 0.0, 7.5)),    # 7.5 above
    Vector((1.0, 1.0, -2.0)),   # 2 below: pushing in is inference too
]
offsets = pushpull.axis_offsets(points, origin, up)
check("candidates are the distances to each point", offsets == [-2.0, 3.0, 7.5],
      f"got {offsets}")

# Anything already in the face's plane answers zero, and zero is the one
# distance the tool reads as no extrusion -- so the face's own corners and
# every coplanar neighbour must not become candidates.
coplanar_points = [Vector((4.0, 0.0, 0.0)), Vector((0.0, 9.0, 0.0)), Vector((1.0, 1.0, 4.0))]
check("geometry in the face's own plane is not a candidate",
      pushpull.axis_offsets(coplanar_points, origin, up) == [4.0],
      f"got {pushpull.axis_offsets(coplanar_points, origin, up)}")

check("no geometry means no candidates", pushpull.axis_offsets([], origin, up) == [])

# The axis is the face normal, not the world Z, so a sideways push infers off
# the same geometry measured the other way.
sideways = pushpull.axis_offsets(points, origin, Vector((1.0, 0.0, 0.0)))
check("candidates follow the push axis", sideways == [-2.0, 1.0, 5.0], f"got {sideways}")

# Only the two candidates either side of the drag can win, since projecting a
# straight line into the viewport leaves it straight.
check("a drag between two candidates is bracketed by them",
      pushpull.bracketing(offsets, 4.0) == [3.0, 7.5],
      f"got {pushpull.bracketing(offsets, 4.0)}")
check("a drag below every candidate takes the lowest",
      pushpull.bracketing(offsets, -9.0) == [-2.0],
      f"got {pushpull.bracketing(offsets, -9.0)}")
check("a drag above every candidate takes the highest",
      pushpull.bracketing(offsets, 99.0) == [7.5],
      f"got {pushpull.bracketing(offsets, 99.0)}")
check("a drag exactly on a candidate still finds it",
      3.0 in pushpull.bracketing(offsets, 3.0),
      f"got {pushpull.bracketing(offsets, 3.0)}")
check("no candidates brackets nothing", pushpull.bracketing([], 1.0) == [])

# The real thing: a box beside a shorter one. Pushing the short box's top must
# offer the tall box's height, so the two can be brought level by eye.
context.view_layer.objects.active = None
tall = bpy.data.meshes.new("tall")
tall_bm = bmesh.new()
bmesh.ops.create_cube(tall_bm, size=2.0)
bmesh.ops.translate(tall_bm, verts=tall_bm.verts, vec=Vector((4.0, 0.0, 1.0)))
tall_bm.to_mesh(tall)
tall_bm.free()
tall_obj = bpy.data.objects.new("tall", tall)
context.scene.collection.objects.link(tall_obj)

gathered = pushpull.inference_points(context)
check("a visible object contributes its vertices in world space",
      any((p - Vector((5.0, 1.0, 2.0))).length < 1e-6 for p in gathered),
      "the tall box's top corner is not among the candidates")
# Its top sits at z=2, so a face pushed up from z=0 should be offered 2.
heights = pushpull.axis_offsets(gathered, origin, up)
check("the neighbour's height is offered as a candidate",
      any(abs(h - 2.0) < 1e-6 for h in heights), f"got {heights}")

bpy.data.objects.remove(tall_obj, do_unlink=True)
bpy.data.meshes.remove(tall)

# Planes, not just points: a wall pulled up beside a sloped roof should stop
# where it touches the roof's plane, and it touches corner-first -- the near
# corner grazing the near side, the far corner reaching under the far side.
# Each (corner, plane) pair is one distance along the push axis.
square = [Vector((0.0, 0.0, 0.0)), Vector((2.0, 0.0, 0.0)),
          Vector((2.0, 2.0, 0.0)), Vector((0.0, 2.0, 0.0))]
roof = [(Vector((0.0, 0.0, 3.0)), Vector((0.0, 1.0, 1.0)).normalized())]
slopes = pushpull.sorted_unique(pushpull.plane_offsets(roof, square, up))
# The plane rises 1:1 with y from z=3, so corners at y=0 reach it at 3 and
# corners at y=2 at 1.
check("a sloped plane is reached corner by corner",
      len(slopes) == 2 and abs(slopes[0] - 1.0) < 1e-6 and abs(slopes[1] - 3.0) < 1e-6,
      f"got {slopes}")

# The two families of plane that must not divide: parallel to the push axis is
# never reached, and parallel to the face is already offered through its
# vertices as points.
check("a plane parallel to the push axis is not a candidate",
      pushpull.plane_offsets([(Vector((5.0, 0.0, 0.0)), Vector((1.0, 0.0, 0.0)))], square, up) == [])
check("a plane parallel to the face is left to the point pass",
      pushpull.plane_offsets([(Vector((0.0, 0.0, 4.0)), Vector((0.0, 0.0, 1.0)))], square, up) == [])

# The real thing again: a two-triangle roof over the scene. One plane, however
# many faces it is tessellated into, and its touch distances join the same
# candidate list the points feed.
roof_mesh = bpy.data.meshes.new("roof")
roof_bm = bmesh.new()
rv = [roof_bm.verts.new(co) for co in
      ((0.0, 0.0, 3.0), (4.0, 0.0, 3.0), (4.0, 4.0, 7.0), (0.0, 4.0, 7.0))]
roof_bm.faces.new((rv[0], rv[1], rv[2]))
roof_bm.faces.new((rv[0], rv[2], rv[3]))
roof_bm.normal_update()
roof_bm.to_mesh(roof_mesh)
roof_bm.free()
roof_obj = bpy.data.objects.new("roof", roof_mesh)
context.scene.collection.objects.link(roof_obj)

roof_normal = Vector((0.0, -1.0, 1.0)).normalized()
gathered_planes = pushpull.inference_planes(context)
matching = [m for _p, m in gathered_planes if abs(abs(m.dot(roof_normal)) - 1.0) < 1e-3]
check("a tessellated plane is gathered once", len(matching) == 1,
      f"got {len(matching)} planes along the roof normal")

merged = pushpull.sorted_unique(
    pushpull.axis_offsets(pushpull.inference_points(context), origin, up)
    + pushpull.plane_offsets(gathered_planes, square, up)
)
# The roof rises 1:1 with y from z=3, so the square's corners touch its plane
# at 3 (y=0) and 5 (y=2). 5 is reachable through the plane alone: no vertex of
# anything sits at that height.
check("plane touches join the candidate list", any(abs(o - 5.0) < 1e-6 for o in merged),
      f"got {merged}")
check("the point candidates are still there too", any(abs(o - 3.0) < 1e-6 for o in merged))

bpy.data.objects.remove(roof_obj, do_unlink=True)
bpy.data.meshes.remove(roof_mesh)

# Non-uniform object scale must not distort the requested distance.
half = Matrix.Diagonal(Vector((2.0, 1.0, 4.0))).to_3x3()
scaled = pushpull.extruded(flat, 0, half.inverted(), up, 4.0, pushpull.EXTRUDE)
heights = sorted({round(v.co.z, 6) for v in scaled.verts})
check("world distance survives object scale", heights == [0.0, 1.0], f"local heights {heights}")

# A horizontal sheet 4 above the drag origin. Its face's plane is parallel to
# the push axis (world Z), so pulling up should be offered the offset 4 -- a
# height no single vertex of the sheet happens to carry (its corners are at
# various heights off the plane, but the plane itself is the alignment).
sheet_mesh = bpy.data.meshes.new("overhead")
sheet_bm = bmesh.new()
sheet_verts = [sheet_bm.verts.new(c) for c in [
    (-1.0, -1.0, 4.0), (3.0, -1.0, 4.0), (3.0, 3.0, 4.0), (-1.0, 3.0, 4.0),
]]
sheet_bm.faces.new(sheet_verts)
sheet_bm.normal_update()
sheet_bm.to_mesh(sheet_mesh)
sheet_bm.free()
sheet_obj = bpy.data.objects.new("overhead", sheet_mesh)
context.scene.collection.objects.link(sheet_obj)

all_offsets = pushpull.infer_offsets(context, origin, up)
# 4 is there from both the sheet's vertices and the sheet's plane.
check("a parallel face plane is offered as a candidate",
      any(abs(h - 4.0) < 1e-6 for h in all_offsets), f"got {all_offsets}")

# A sloped face must *not* be offered. The push axis is Z; an inclined plane
# can never be made coplanar by translating along Z, so its height is not an
# alignment even though its vertices do carry heights worth snapping to.
slope_mesh = bpy.data.meshes.new("slope")
slope_bm = bmesh.new()
slope_verts = [slope_bm.verts.new(c) for c in [
    (0.0, 0.0, 6.0), (2.0, 0.0, 5.0), (2.0, 2.0, 5.0), (0.0, 2.0, 6.0),
]]
slope_bm.faces.new(slope_verts)
slope_bm.normal_update()
slope_bm.to_mesh(slope_mesh)
slope_bm.free()
slope_obj = bpy.data.objects.new("slope", slope_mesh)
context.scene.collection.objects.link(slope_obj)

slope_offsets = pushpull.infer_offsets(context, origin, up)
# The slope's vertices (5, 6) are point candidates; only its *plane* adds 5.5,
# and the plane is not parallel to Z, so nothing from the plane itself should
# appear. Point candidates from the slope's vertices remain.
point_only = pushpull.axis_offsets(pushpull.inference_points(context), origin, up)
check("a sloped plane adds no candidate of its own",
      sorted(slope_offsets) == sorted(point_only),
      f"plane inference added {sorted(set(slope_offsets) - set(point_only))}")

bpy.data.objects.remove(sheet_obj, do_unlink=True)
bpy.data.meshes.remove(sheet_mesh)
bpy.data.objects.remove(slope_obj, do_unlink=True)
bpy.data.meshes.remove(slope_mesh)


# --- CAD import --------------------------------------------------------------
#
# A DXF comes in as sketch geometry, one object per layer; broken outlines are
# healed up to a gap tolerance; closed outlines become faces; a non-zero
# extrude stands them up. The parser and healer are pure Python and get their
# analytic checks here; the built solids get volume checks, because volumes
# are what caught the membrane bug that topology checks slept through.

section("CAD import")
dxf = addon.dxf
heal = addon.heal
importer = sys.modules[ADDON + ".ops.importer"]

def dxf_pairs(*items):
    return "\n".join(str(x) for pair in items for x in pair) + "\n"

# Millimetre file: a 4000x3000 square of LINEs on WALLS with one 2mm gap, a
# closed triangle and a circle on FURNITURE, and an entity outside the subset.
fixture = dxf_pairs(
    (0, "SECTION"), (2, "HEADER"),
    (9, "$INSUNITS"), (70, 4),
    (0, "ENDSEC"),
    (0, "SECTION"), (2, "ENTITIES"),
    (0, "LINE"), (8, "WALLS"), (10, 0), (20, 0), (11, 4000), (21, 0),
    (0, "LINE"), (8, "WALLS"), (10, 4000), (20, 0), (11, 4000), (21, 3000),
    (0, "LINE"), (8, "WALLS"), (10, 4000), (20, 3000), (11, 0), (21, 3000),
    (0, "LINE"), (8, "WALLS"), (10, 0), (20, 3000), (11, 0), (21, 2),
    (0, "LWPOLYLINE"), (8, "FURNITURE"), (90, 3), (70, 1),
    (10, 0), (20, 0), (10, 1000), (20, 0), (10, 500), (20, 800),
    (0, "CIRCLE"), (8, "FURNITURE"), (10, 9000), (20, 9000), (40, 500),
    (0, "MTEXT"), (8, "NOTES"), (10, 0), (20, 0),
    (0, "ENDSEC"), (0, "EOF"),
)

drawing = dxf.parse(fixture)
check("layers found", sorted(drawing.layers) == ["FURNITURE", "WALLS"],
      str(sorted(drawing.layers)))
check("millimetres understood and scaled", drawing.scale == 0.001
      and drawing.layers["WALLS"][0].points[1] == (4.0, 0.0))
check("entities outside the subset are counted, not silently dropped",
      drawing.skipped == {"MTEXT": 1}, str(drawing.skipped))
circle = [p for p in drawing.layers["FURNITURE"] if len(p.points) == 24][0]
check("a circle is SketchUp's 24 chords, closed", circle.closed)

# The spec's bulge sign: positive arcs counter-clockwise from start to end,
# which for a rightward chord is the LOWER semicircle.
bulged = dxf.parse(dxf_pairs(
    (0, "SECTION"), (2, "ENTITIES"),
    (0, "LWPOLYLINE"), (8, "0"), (90, 2), (70, 0),
    (10, 0), (20, 0), (42, 1), (10, 2), (20, 0),
    (0, "ENDSEC"), (0, "EOF"),
)).layers["0"][0]
check("a bulge of 1 is a counter-clockwise half circle",
      abs(min(p[1] for p in bulged.points) + 1.0) < 1e-6
      and bulged.points[-1] == (2.0, 0.0),
      f"low point {min(p[1] for p in bulged.points)}")

# Healing: a 2mm break closes under a 5mm gap tolerance and stays open under
# a 1.5mm one -- a doorway is not a drafting error.
wall_pairs = [(p.points, p.closed) for p in drawing.layers["WALLS"]]
loops, opens, report = heal.heal(wall_pairs, weld=0.001, gap=0.005)
check("the broken square closes as one loop", len(loops) == 1 and opens == [],
      f"{len(loops)} loops, {len(opens)} open")
check("healing says what it did", report.welded == 3 and report.bridged == 1,
      report.summary())
tight_loops, tight_opens, tight_report = heal.heal(wall_pairs, weld=0.001, gap=0.0015)
check("a gap wider than the tolerance stays open",
      tight_loops == [] and tight_report.left_open == 1)

# The crossing test itself, both ways round: bmesh checks topology, not
# geometry, so this test is the only thing standing between a healed figure
# of eight and a bowtie face.
check("a crossing loop is recognised, an honest one is not",
      heal.self_crossing([(0.0, 0.0), (2.0, 2.0), (2.0, 0.0), (0.0, 2.0)])
      and not heal.self_crossing([(0.0, 0.0), (2.0, 0.0), (2.0, 2.0), (0.0, 2.0)]))

# The whole pipeline through the real operator, extruding 2m.
import os
import tempfile

context.view_layer.objects.active = None
for existing in list(bpy.data.objects):
    existing.select_set(False)
with tempfile.NamedTemporaryFile("w", suffix=".dxf", delete=False) as handle:
    handle.write(fixture)
    plan_path = handle.name
result = bpy.ops.bonsai_sketch_mode.import_cad(
    filepath=plan_path, weld=0.001, gap=0.005, extrude=2.0)
check("the import operator finishes", result == {"FINISHED"}, str(result))

plan_stem = os.path.splitext(os.path.basename(plan_path))[0]
walls_obj = bpy.data.objects.get(f"{plan_stem}/WALLS")
furniture_obj = bpy.data.objects.get(f"{plan_stem}/FURNITURE")
check("one object per layer, named for it",
      walls_obj is not None and furniture_obj is not None,
      str(sorted(o.name for o in bpy.data.objects if plan_stem in o.name)))
check("imported layers are sketch geometry",
      sketchmesh.is_sketch_object(walls_obj) and sketchmesh.is_sketch_object(furniture_obj))

walls_bm = bmesh.new()
walls_bm.from_mesh(walls_obj.data)
check("the healed square stood up: volume is 4x3x2",
      abs(walls_bm.calc_volume(signed=False) - 24.0) < 1e-6,
      f"got {walls_bm.calc_volume(signed=False)}")
walls_bm.free()

# Triangle prism 0.5*1*0.8*2 plus a 24-gon prism 0.5*24*r^2*sin(15deg)*2.
import math as _math

furniture_bm = bmesh.new()
furniture_bm.from_mesh(furniture_obj.data)
expected = (0.5 * 1.0 * 0.8 + 0.5 * 24 * 0.25 * _math.sin(_math.radians(15.0))) * 2.0
check("the furniture layer's solids measure up",
      abs(furniture_bm.calc_volume(signed=False) - expected) < 1e-6,
      f"got {furniture_bm.calc_volume(signed=False)}, expected {expected}")
furniture_bm.free()

for gone in (walls_obj, furniture_obj):
    data = gone.data
    bpy.data.objects.remove(gone, do_unlink=True)
    bpy.data.meshes.remove(data)
os.unlink(plan_path)

# A healed loop that crosses itself has no single face; it stays as edges and
# is counted rather than guessed at.
bow = dxf.Polyline("L", [(0.0, 0.0), (2.0, 2.0), (2.0, 0.0), (0.0, 2.0)], True)
bow_obj, _bow_report, unfaceable = importer.build_layer(
    context, "bowtie", [bow], weld=0.001, gap=0.005, extrude=1.0)
check("a self-crossing loop stays as edges", unfaceable == 1
      and len(bow_obj.data.polygons) == 0 and len(bow_obj.data.edges) == 4,
      f"{unfaceable} unfaceable, {len(bow_obj.data.polygons)} faces")
bow_data = bow_obj.data
bpy.data.objects.remove(bow_obj, do_unlink=True)
bpy.data.meshes.remove(bow_data)

# Per-layer heights, after the fact: import flat with a gap tolerance too
# tight to close anything, then Stand Up Outlines on the selected layers with
# a working tolerance and a height of its own. This is the "each layer its
# own height" path -- one run, one height, selection says which layers.
with tempfile.NamedTemporaryFile("w", suffix=".dxf", delete=False) as handle:
    handle.write(fixture)
    flat_path = handle.name
for existing in bpy.data.objects:
    existing.select_set(False)
result = bpy.ops.bonsai_sketch_mode.import_cad(
    filepath=flat_path, weld=0.001, gap=0.0001, extrude=0.0)
check("a flat import finishes", result == {"FINISHED"}, str(result))
flat_stem = os.path.splitext(os.path.basename(flat_path))[0]
flat_walls = bpy.data.objects.get(f"{flat_stem}/WALLS")
flat_furniture = bpy.data.objects.get(f"{flat_stem}/FURNITURE")
check("the too-tight gap left the square as wire",
      flat_walls is not None and len(flat_walls.data.polygons) == 0
      and len(flat_walls.data.edges) >= 3)

for existing in bpy.data.objects:
    existing.select_set(False)
flat_walls.select_set(True)
flat_furniture.select_set(True)
context.view_layer.objects.active = flat_walls
result = bpy.ops.bonsai_sketch_mode.stand_up(height=2.5, weld=0.001, gap=0.005)
check("standing up the selection finishes", result == {"FINISHED"}, str(result))

stood_bm = bmesh.new()
stood_bm.from_mesh(flat_walls.data)
check("the wire square healed and stood to 4x3x2.5",
      abs(stood_bm.calc_volume(signed=False) - 30.0) < 1e-6,
      f"got {stood_bm.calc_volume(signed=False)}")
stood_bm.free()

furn_bm = bmesh.new()
furn_bm.from_mesh(flat_furniture.data)
expected_furniture = (0.5 * 1.0 * 0.8 + 0.5 * 24 * 0.25 * _math.sin(_math.radians(15.0))) * 2.5
check("already-faced layers take the same height",
      abs(furn_bm.calc_volume(signed=False) - expected_furniture) < 1e-6,
      f"got {furn_bm.calc_volume(signed=False)}")
furn_bm.free()

# Standing geometry is declined, not doubled: this operator exists to be
# re-run with different numbers, and stacking would make every re-run wrong.
for existing in bpy.data.objects:
    existing.select_set(False)
flat_walls.select_set(True)
result = bpy.ops.bonsai_sketch_mode.stand_up(height=2.5)
still_bm = bmesh.new()
still_bm.from_mesh(flat_walls.data)
check("a standing layer is left alone",
      result == {"CANCELLED"} and abs(still_bm.calc_volume(signed=False) - 30.0) < 1e-6,
      f"{result}, volume {still_bm.calc_volume(signed=False)}")
still_bm.free()

# Geometry we did not mark is not ours to rebuild.
foreign = bpy.data.objects.new("foreign", bpy.data.meshes.new("foreign"))
context.scene.collection.objects.link(foreign)
for existing in bpy.data.objects:
    existing.select_set(False)
foreign.select_set(True)
check("unmarked geometry is declined",
      bpy.ops.bonsai_sketch_mode.stand_up(height=1.0) == {"CANCELLED"})
check("stand-up operator registered", hasattr(bpy.ops.bonsai_sketch_mode, "stand_up"))

foreign_data = foreign.data
bpy.data.objects.remove(foreign, do_unlink=True)
bpy.data.meshes.remove(foreign_data)
for gone in (flat_walls, flat_furniture):
    data = gone.data
    bpy.data.objects.remove(gone, do_unlink=True)
    bpy.data.meshes.remove(data)
os.unlink(flat_path)

# DWG without the converter refuses with directions, not silence.
converted, why_not = importer.convert_dwg("plan.dwg", "")
check("DWG without ODA says what to install",
      converted is None and "opendesign.com" in why_not, why_not)
check("import operator registered", hasattr(bpy.ops.bonsai_sketch_mode, "import_cad"))


# --- Offset ------------------------------------------------------------------
#
# Same reasoning as Push/Pull: the modal needs a mouse, the geometry does not,
# and the geometry is where a subtle mistake would ship a wrong mesh.

section("Offset")
offset = sys.modules[ADDON + ".ops.offset"]

context.view_layer.objects.active = None
sheet = [Vector((0, 0, 0)), Vector((4, 0, 0)), Vector((4, 3, 0)), Vector((0, 3, 0))]
sheet_obj, _ = sketchmesh.commit(context, sheet, close=True)
base = bmesh.new()
base.from_mesh(sheet_obj.data)
base.faces.ensure_lookup_table()

inward = offset.offsetted(base, 0, 0.5)
areas = sorted(f.calc_area() for f in inward.faces)
check("inward offset splits into ring + inner face", len(inward.faces) == 5,
      f"got {len(inward.faces)}")
check("inward offset keeps 8 vertices", len(inward.verts) == 8, f"got {len(inward.verts)}")
check("inner face is 3x2", abs(areas[-1] - 6.0) < 1e-6, f"largest face {areas[-1]}")
check("nothing gained or lost inward", abs(sum(areas) - 12.0) < 1e-6, f"total {sum(areas)}")
check("outer boundary stays open, inner loop is shared",
      sorted(len(e.link_faces) for e in inward.edges) == [1] * 4 + [2] * 8,
      f"got {sorted(len(e.link_faces) for e in inward.edges)}")

outward = offset.offsetted(base, 0, -0.5)
out_areas = sorted(f.calc_area() for f in outward.faces)
check("outward offset also makes ring + face", len(outward.faces) == 5,
      f"got {len(outward.faces)}")
check("outward offset grows the boundary to 5x4",
      abs(sum(out_areas) - 20.0) < 1e-6, f"total {sum(out_areas)}")
check("the original face is untouched outward", abs(out_areas[-1] - 12.0) < 1e-6,
      f"largest face {out_areas[-1]}")

untouched = offset.offsetted(base, 0, 0.0)
check("zero offset changes nothing",
      len(untouched.verts) == 4 and len(untouched.faces) == 1)

# A corner sharper than the mitre floor cannot be offset to the asked distance
# without its point shooting off toward infinity, so the reach is capped and
# that corner lands short. The cap is fine; being quiet about it is not, since
# the whole promise of the tool is the distance typed into the box.
clamp_reports = []
wide = bmesh.new()
for co in ((0, 0, 0), (4, 0, 0), (4, 3, 0), (0, 3, 0)):
    wide.verts.new(co)
wide.faces.new(wide.verts)
wide.faces.ensure_lookup_table()
wide.normal_update()
wide_out = offset.offsetted(wide, 0, -0.5, on_clamp=clamp_reports.append)
check("an ordinary corner reports no clamping", clamp_reports == [], f"got {clamp_reports}")

import math

spike = bmesh.new()
half = math.radians(4) / 2
for co in ((0, 0, 0), (10, -10 * math.tan(half), 0), (10, 10 * math.tan(half), 0)):
    spike.verts.new(co)
spike.faces.new(spike.verts)
spike.faces.ensure_lookup_table()
spike.normal_update()
spike_out = offset.offsetted(spike, 0, -0.5, on_clamp=clamp_reports.append)
check("a corner too sharp to honour is reported, not hidden",
      clamp_reports == [1], f"got {clamp_reports}")

for mesh in (inward, outward, untouched, base, wide, wide_out, spike, spike_out):
    mesh.free()


# --- Eraser ------------------------------------------------------------------

section("Eraser")
eraser = sys.modules[ADDON + ".ops.eraser"]
vp = sys.modules[ADDON + ".viewport"]

# The screen-space pick underneath the tool is pure 2D math.
check("distance to a segment's middle",
      abs(vp.point_segment_distance_2d(Vector((5, 5)), Vector((0, 0)), Vector((10, 0))) - 5.0) < 1e-9)
check("distance clamps at the endpoints",
      abs(vp.point_segment_distance_2d(Vector((15, 0)), Vector((0, 0)), Vector((10, 0))) - 5.0) < 1e-9)
check("degenerate segment is a point",
      abs(vp.point_segment_distance_2d(Vector((3, 4)), Vector((0, 0)), Vector((0, 0))) - 5.0) < 1e-9)

context.view_layer.objects.active = None
square = [Vector((0, 0, 0)), Vector((2, 0, 0)), Vector((2, 2, 0)), Vector((0, 2, 0))]
square_obj, _ = sketchmesh.commit(context, square, close=True)
full = bmesh.new()
full.from_mesh(square_obj.data)

one_gone = eraser.erased(full, [0])
check("erasing an edge takes its face with it", len(one_gone.faces) == 0)
check("the other three edges survive", len(one_gone.edges) == 3, f"got {len(one_gone.edges)}")
check("shared endpoints stay", len(one_gone.verts) == 4, f"got {len(one_gone.verts)}")

two_gone = eraser.erased(full, [0, 1])
check("a vertex left with no edges is swept up", len(two_gone.verts) == 3,
      f"got {len(two_gone.verts)}")
check("two edges remain of the square", len(two_gone.edges) == 2)

all_gone = eraser.erased(full, [0, 1, 2, 3])
check("erasing every edge empties the mesh", len(all_gone.verts) == 0)

# An open wire polyline: erasing one stroke must not strand its far endpoint.
# Built directly rather than through sketchmesh.commit: commit runs
# contextual_create over every stroke, which added closing geometry to this
# open chain and made the fixture something other than two bare strokes --
# this check is about the eraser, so it gets exactly two bare strokes.
strokes = bmesh.new()
sv = [strokes.verts.new(co) for co in ((0, 0, 5), (1, 0, 5), (2, 0, 5))]
strokes.edges.new((sv[0], sv[1]))
strokes.edges.new((sv[1], sv[2]))
half_chain = eraser.erased(strokes, [0])
check("erasing one stroke of a polyline leaves the other",
      len(half_chain.edges) == 1 and len(half_chain.verts) == 2,
      f"got {len(half_chain.verts)} verts, {len(half_chain.edges)} edges")

# Sweeping up endpoints the erase stranded is the contract; sweeping up a loose
# vertex that was already there is not. It may be a snap target the user placed,
# and erasing an unrelated edge is the wrong moment to rule it litter.
littered = bmesh.new()
lv = [littered.verts.new(co) for co in ((0, 0, 7), (1, 0, 7))]
littered.edges.new((lv[0], lv[1]))
littered.verts.new((5, 5, 7))  # nothing to do with the edge about to go
littered.edges.ensure_lookup_table()
swept = eraser.erased(littered, [0])
check("an unrelated loose vertex is left alone",
      len(swept.verts) == 1, f"got {len(swept.verts)} verts, expected the 1 bystander")

for mesh in (full, one_gone, two_gone, all_gone, strokes, half_chain, littered, swept):
    mesh.free()


# --- Layer classification ------------------------------------------------
#
# AutoModel stage 4: a drafting layer's name read against the conventions,
# proposing an IFC class or refusing with a reason. Deterministic and pure;
# the agents handle what it refuses.

section("Layer classification")
classify = addon.classify
for name, want in (("WALLS", "IfcWall"), ("A-GLAZ", "IfcWindow"),
                   ("S-COLS", "IfcColumn"), ("plan/WALLS", "IfcWall")):
    proposal = classify.classify(name)
    check(f"{name} reads as {want}", proposal.ifc_class == want,
          f"got {proposal.ifc_class} ({proposal.reason})")
check("a ROOF layer is a slab with the ROOF type",
      classify.classify("ROOF").predefined_type == "ROOF")
check("an unknown name proposes nothing",
      not classify.classify("EQUIPMENT-ROOM-3").resolved)
check("disagreeing conventions propose nothing",
      not classify.classify("WALL-DOOR-TRIM").resolved)
resolved_props, unresolved_props = classify.classify_all(["WALLS", "MYSTERY"])
check("resolved and unresolved split cleanly",
      len(resolved_props) == 1 and len(unresolved_props) == 1)


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

# One class, two elements, told apart by PredefinedType: the roof plane is an
# IfcSlab like any floor, and getting this wrong would hang roof requirements
# on every landing.
check("a plain slab is a Floor", requirements.element_for_class("IfcSlab") == "Floor")
check("a ROOF slab is a Roof", requirements.element_for_class("IfcSlab", "ROOF") == "Roof")
check("floor and roof slabs are asked different questions",
      requirements.parameter_names("IfcSlab", "detailed", "FLOOR")
      != requirements.parameter_names("IfcSlab", "detailed", "ROOF"))
check("sweep classes carry no qualifiers",
      all("/" not in c for c in requirements.mapped_classes()))

# The Project Delivery dataset: per building typology, with optional marks.
check("8 delivery typologies ship", len(requirements.typologies()) == 8,
      str(requirements.typologies()))
check("a known typology loads cleanly",
      requirements.delivery_load_error("public_residential") is None,
      requirements.delivery_load_error("public_residential") or "")
check("an unknown typology fails loudly",
      requirements.delivery_load_error("atlantis") is not None)
check("no typology has mapping collisions",
      all(not requirements.delivery_warnings(k) for k, _ in requirements.typologies()))
check("delivery requirements differ per typology",
      requirements.delivery_parameter_names("IfcColumn", "schematic", "public_residential")
      != requirements.delivery_parameter_names("IfcColumn", "schematic", "commercial"))
check("delivery-only elements resolve under their typology",
      requirements.delivery_element_for_class("IfcFurniture", "industrial") == "Furniture"
      and requirements.delivery_element_for_class("IfcFurniture", "commercial") is None)
opt_off = requirements.delivery_parameter_names("IfcDoor", "tender", "commercial")
opt_on = requirements.delivery_parameter_names("IfcDoor", "tender", "commercial", True)
check("optional parameters appear only when asked for", set(opt_off) < set(opt_on),
      f"mandatory {len(opt_off)}, with optional {len(opt_on)}")
check("infrastructure typologies map nothing on IFC4",
      requirements.delivery_mapped_classes("infra_road") == [])

# Deliberately unmapped elements must say why, so an empty result is never
# mistaken for "this element has no requirements".
check("External Works is unmapped with a stated reason",
      bool(requirements.unmapped_reason("External Works")))
check("Wall is mapped, so has no unmapped reason",
      requirements.unmapped_reason("Wall") is None)
check("broad mappings carry a review note",
      bool(requirements.needs_review("Terminal")))
check("the source revision is recorded", "IFC+SG" in requirements.source())


# --- IFC+SG parameter attachment ---------------------------------------------
#
# Elements get the standard's parameters the moment they are created. The
# listener the add-on installs is global to ifcopenshell's API, so this is
# testable on a plain in-memory file: production differs only in where the
# file came from. The scene properties are the real ones -- this is the
# production path end to end, not a harness around it.

section("IFC+SG parameter attachment")
psets = addon.psets
check("attachment layer available", psets.is_available(), psets.unavailable_reason() or "")
check("apply operator registered", hasattr(bpy.ops.bonsai_sketch_mode, "sg_apply"))
check("sidebar panel registered", hasattr(bpy.types, "BONSAI_SKETCH_MODE_PT_sg"))
check("stage is a scene property", hasattr(context.scene, "bonsai_sketch_sg_stage"))
check("attachment defaults to on", context.scene.bonsai_sketch_sg_attach is True)
check("typology defaults to unset", context.scene.bonsai_sketch_sg_typology == "none")
check("optional parameters default to off",
      context.scene.bonsai_sketch_sg_optional is False)

import ifcopenshell
import ifcopenshell.api.project
import ifcopenshell.api.pset
import ifcopenshell.api.root
import ifcopenshell.util.element

context.scene.bonsai_sketch_sg_stage = "detailed"
ifc = ifcopenshell.api.project.create_file(version="IFC4")
ifcopenshell.api.root.create_entity(ifc, ifc_class="IfcProject", name="Smoke")

wall = ifcopenshell.api.root.create_entity(ifc, ifc_class="IfcWall", name="W")
pset = ifcopenshell.util.element.get_pset(wall, psets.PSET_NAME)
needed = requirements.parameter_names("IfcWall", "detailed")
check("a created wall carries the pset", pset is not None)
check("every required parameter is on it",
      pset is not None and all(name in pset for name in needed),
      f"missing {[n for n in needed if n not in (pset or {})]}")
check("parameters attach unfilled",
      pset is not None and pset.get("Load Bearing", "sentinel") is None)
check("the project itself gets nothing",
      ifcopenshell.util.element.get_pset(ifc.by_type("IfcProject")[0], psets.PSET_NAME) is None)

# A value the user has filled in must survive every later sweep -- the next
# creation of the same class re-visits this wall.
ifcopenshell.api.pset.edit_pset(ifc, pset=ifc.by_id(pset["id"]),
                                properties={"Load Bearing": "TRUE"})
ifcopenshell.api.root.create_entity(ifc, ifc_class="IfcWall", name="W2")
check("a filled value survives the next creation",
      ifcopenshell.util.element.get_pset(wall, psets.PSET_NAME).get("Load Bearing") == "TRUE")

# Stages gate what attaches. A wall has nothing to declare at schematic, so it
# must not even get an empty container; a door does have schematic asks.
context.scene.bonsai_sketch_sg_stage = "schematic"
early_wall = ifcopenshell.api.root.create_entity(ifc, ifc_class="IfcWall", name="W3")
check("no requirements at this stage means no pset",
      ifcopenshell.util.element.get_pset(early_wall, psets.PSET_NAME) is None)
door = ifcopenshell.api.root.create_entity(ifc, ifc_class="IfcDoor", name="D")
door_pset = ifcopenshell.util.element.get_pset(door, psets.PSET_NAME)
check("a door gets its own, smaller schematic set",
      door_pset is not None and "Fire Rating" in door_pset)

# Advancing the stage: the sweep behind Apply to Existing Elements tops up
# what earlier stages did not ask for, then has nothing more to say.
context.scene.bonsai_sketch_sg_stage = "detailed"
touched, added = psets.sweep(ifc, psets.AttachSettings(stage="detailed"))
check("a sweep tops up elements from an earlier stage",
      ifcopenshell.util.element.get_pset(early_wall, psets.PSET_NAME) is not None)
check("the sweep is idempotent",
      psets.sweep(ifc, psets.AttachSettings(stage="detailed")) == (0, 0))

# The scene switch turns attachment off entirely.
context.scene.bonsai_sketch_sg_attach = False
off_wall = ifcopenshell.api.root.create_entity(ifc, ifc_class="IfcWall", name="W4")
check("turning it off attaches nothing",
      ifcopenshell.util.element.get_pset(off_wall, psets.PSET_NAME) is None)
context.scene.bonsai_sketch_sg_attach = True

# A roof slab and a floor slab are the same class; PredefinedType decides
# which questions each is asked.
floor_slab = ifcopenshell.api.root.create_entity(
    ifc, ifc_class="IfcSlab", name="S1", predefined_type="FLOOR")
roof_slab = ifcopenshell.api.root.create_entity(
    ifc, ifc_class="IfcSlab", name="S2", predefined_type="ROOF")
floor_pset = ifcopenshell.util.element.get_pset(floor_slab, psets.PSET_NAME) or {}
roof_pset = ifcopenshell.util.element.get_pset(roof_slab, psets.PSET_NAME) or {}
check("a floor slab gets the Floor set",
      set(floor_pset) - {"id"} == set(requirements.parameter_names("IfcSlab", "detailed", "FLOOR")))
check("a roof slab gets the Roof set",
      set(roof_pset) - {"id"} == set(requirements.parameter_names("IfcSlab", "detailed", "ROOF")))

# Choosing a typology brings the Project Delivery dataset in, as its own
# property set: a second submission's questions, kept out of the first's.
context.scene.bonsai_sketch_sg_typology = "public_residential"
column = ifcopenshell.api.root.create_entity(ifc, ifc_class="IfcColumn", name="C1")
col_sg = ifcopenshell.util.element.get_pset(column, psets.PSET_NAME)
col_dl = ifcopenshell.util.element.get_pset(column, psets.DELIVERY_PSET_NAME)
check("a column gets both property sets", col_sg is not None and col_dl is not None)
check("delivery parameters attach unfilled",
      col_dl is not None and col_dl.get("b", "sentinel") is None)

context.scene.bonsai_sketch_sg_typology = "industrial"
chair = ifcopenshell.api.root.create_entity(ifc, ifc_class="IfcFurniture", name="Chair")
check("a delivery-only class attaches under its typology",
      ifcopenshell.util.element.get_pset(chair, psets.DELIVERY_PSET_NAME) is not None)
check("it gets no IFC+SG set, which does not cover it",
      ifcopenshell.util.element.get_pset(chair, psets.PSET_NAME) is None)

context.scene.bonsai_sketch_sg_typology = "none"
chair2 = ifcopenshell.api.root.create_entity(ifc, ifc_class="IfcFurniture", name="Chair2")
check("no typology means no delivery parameters",
      ifcopenshell.util.element.get_pset(chair2, psets.DELIVERY_PSET_NAME) is None)

# The nulls are not a Blender-session artefact: they survive the file itself
# being written out and read back.
reread = ifcopenshell.file.from_string(ifc.to_string())
reread_wall = [e for e in reread.by_type("IfcWall") if e.Name == "W"][0]
reread_pset = ifcopenshell.util.element.get_pset(reread_wall, psets.PSET_NAME)
check("unfilled parameters survive serialisation",
      reread_pset is not None and reread_pset.get("Is External", "sentinel") is None)
check("filled parameters survive serialisation",
      reread_pset is not None and reread_pset.get("Load Bearing") == "TRUE")

# An occurrence must get its own copy of the set even when its type already
# carries every name. Reading through type inheritance would see nothing
# missing, so the occurrence would stay permanently short and no later sweep
# would notice -- the "Apply to Existing Elements" button would report the file
# complete while the element itself held none of the answers.
import ifcopenshell.api.type

typed = ifcopenshell.api.project.create_file(version="IFC4")
ifcopenshell.api.root.create_entity(typed, ifc_class="IfcProject", name="Typed")
door_type = ifcopenshell.api.root.create_entity(typed, ifc_class="IfcDoorType", name="DT")
type_pset = ifcopenshell.api.pset.add_pset(typed, product=door_type, name=psets.PSET_NAME)
ifcopenshell.api.pset.edit_pset(
    typed, pset=type_pset,
    properties={n: None for n in requirements.parameter_names("IfcDoor", "detailed")},
    should_purge=False)
ifcopenshell.api.pset.edit_pset(
    typed, pset=type_pset, properties={"Fire Rating": "2h"}, should_purge=False)

# Created with listeners off: this fixture is the door that is *already
# typed* when the sweep meets it -- the library-template scenario. With the
# add-on's creation listener live, the untyped just-created door would get
# the full set (Fire Rating included) a moment before assign_type runs,
# which is the separate, accepted create-then-type ordering -- real, but
# not what these checks pin.
occurrence = ifcopenshell.api.root.create_entity(
    typed, ifc_class="IfcDoor", name="D1", should_run_listeners=False)
ifcopenshell.api.type.assign_type(typed, related_objects=[occurrence], relating_type=door_type)
psets.forget()
psets.sweep(typed, psets.AttachSettings(stage="detailed"))
own = ifcopenshell.util.element.get_pset(occurrence, psets.PSET_NAME, should_inherit=False) or {}
wanted = requirements.parameter_names("IfcDoor", "detailed")
unanswered = [n for n in wanted if n != "Fire Rating"]
check("a typed occurrence gets its own copy of the unanswered questions",
      all(name in own for name in unanswered),
      f"absent from the occurrence: {[n for n in unanswered if n not in own]}")
# ...but a question the type has answered is not re-asked. This is not a
# nicety: in the merged dict views (get_psets, and get_pset without a prop) an
# occurrence's null SHADOWS the type's filled value -- only the single-property
# accessor falls back through it. A placeholder written beside the type's "2h"
# would report the fire rating as unanswered to every consumer of those views.
# Both halves are pinned here so a change in either accessor's behaviour shows
# up as a failure rather than as silently hidden data.
check("a question the type has answered is not re-asked on the occurrence",
      "Fire Rating" not in own,
      f"occurrence carries Fire Rating = {own.get('Fire Rating')!r}")
check("the type's answer stays visible in the merged dict view",
      (ifcopenshell.util.element.get_psets(occurrence).get(psets.PSET_NAME) or {}).get("Fire Rating") == "2h",
      f"got {(ifcopenshell.util.element.get_psets(occurrence).get(psets.PSET_NAME) or {}).get('Fire Rating')!r}")
check("and in the single-property accessor",
      ifcopenshell.util.element.get_pset(occurrence, psets.PSET_NAME, "Fire Rating") == "2h",
      f"got {ifcopenshell.util.element.get_pset(occurrence, psets.PSET_NAME, 'Fire Rating')!r}")

# The listener remembers what it has examined, so a creation does not rescan
# every instance of its class. What it must never do is skip an element that
# still needs something.
counted = ifcopenshell.api.project.create_file(version="IFC4")
ifcopenshell.api.root.create_entity(counted, ifc_class="IfcProject", name="Counted")
psets.forget()
settings_now = psets.AttachSettings(stage="detailed")
for i in range(3):
    ifcopenshell.api.root.create_entity(counted, ifc_class="IfcWall", name=f"CW{i}")
walls = counted.by_type("IfcWall")
check("every wall still got its parameters with the record on",
      all(ifcopenshell.util.element.get_pset(w, psets.PSET_NAME) for w in walls),
      f"{sum(1 for w in walls if not ifcopenshell.util.element.get_pset(w, psets.PSET_NAME))} bare")
check("a remembering sweep skips what it has already examined",
      psets.sweep(counted, settings_now, remember=True) == (0, 0))
# The by-hand sweep is the escape hatch, so it must not trust the record. Strip
# a property behind the module's back and it has to be put back.
victim = counted.by_type("IfcWall")[0]
victim_pset = ifcopenshell.util.element.get_pset(victim, psets.PSET_NAME, should_inherit=False)
ifcopenshell.api.pset.remove_pset(counted, product=victim, pset=counted.by_id(victim_pset["id"]))
check("a remembering sweep does not notice work undone behind it",
      psets.sweep(counted, settings_now, remember=True) == (0, 0))
psets.forget()
check("forgetting makes it look again",
      psets.sweep(counted, settings_now)[0] == 1,
      f"got {psets.sweep(counted, settings_now)}")


# --- Theme -------------------------------------------------------------------
#
# The one thing this add-on changes outside its own tab, so the promise that it
# can be undone has to hold exactly -- not approximately, and not back to
# Blender's defaults, but back to whatever the user had.

section("Theme")
theme = addon.theme

# Establish a known starting point rather than assuming a clean machine.
# Blender auto-saves preferences by default, and the canvas is a preference, so
# any earlier run that raised it -- including the add-on doing so by itself when
# the workspace is added -- leaves it up in userpref.blend for every session
# afterwards. Asserting "not applied to begin with" against whatever the last
# run happened to leave behind makes this section report on the machine rather
# than on the code.
gradients = bpy.context.preferences.themes[0].view_3d.space.gradients
gradients.background_type = "SINGLE_COLOR"
gradients.high_gradient = (0.05, 0.06, 0.07)
gradients.gradient = (0.05, 0.06, 0.07)

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

# Colours are user-configurable. Everything reachable from preferences has to
# be both applied and restorable, or "you can undo this" stops being true.
prefs = bpy.context.preferences.addons[ADDON].preferences
ui = bpy.context.preferences.themes[0].user_interface
gradients = bpy.context.preferences.themes[0].view_3d.space.gradients


def close(actual, expected):
    # Theme colours are stored as bytes, so a round trip lands within one
    # 8-bit step of what was asked for, never exactly on it.
    return all(
        abs(a - b) <= theme.SAME_COLOUR for a, b in zip(list(actual), list(expected))
    )


theme.apply()
check("apply sets the three axis colours",
      close(ui.axis_x, theme.AXIS_X)
      and close(ui.axis_y, theme.AXIS_Y)
      and close(ui.axis_z, theme.AXIS_Z),
      f"got {list(ui.axis_x)}, {list(ui.axis_y)}, {list(ui.axis_z)}")
check("axis colours are recorded for restore",
      "user_interface::axis_x" in theme.snapshot())

prefs.sky_colour = (0.1, 0.2, 0.3)
theme.apply()
check("a chosen sky colour is used, not the default",
      close(gradients.high_gradient, (0.1, 0.2, 0.3)),
      f"got {list(gradients.high_gradient)}")
check("the canvas still reads as on after recolouring", theme.looks_applied() is True)

prefs.axis_x_colour = (0.5, 0.25, 0.75)
theme.apply()
check("a chosen axis colour is used", close(ui.axis_x, (0.5, 0.25, 0.75)),
      f"got {list(ui.axis_x)}")

prefs.use_sky_ground = False
prefs.background_colour = (0.2, 0.4, 0.6)
theme.apply()
check("sky and ground off gives a flat background",
      gradients.background_type == "SINGLE_COLOR", gradients.background_type)
check("the flat background uses the background colour",
      close(gradients.high_gradient, (0.2, 0.4, 0.6)),
      f"got {list(gradients.high_gradient)}")
check("a flat canvas still reads as on", theme.looks_applied() is True)

bpy.ops.bonsai_sketch_mode.reset_colours()
check("reset puts the sky colour back", close(prefs.sky_colour, theme.SKY))
check("reset puts the axis colour back", close(prefs.axis_x_colour, theme.AXIS_X))
check("reset turns sky and ground back on", prefs.use_sky_ground is True)

check("restore is still byte-exact after all of that",
      theme.restore(original)[0] and theme.snapshot() == original)
check("the canvas reads as off again", theme.looks_applied() is False)

# The floor grid is an overlay, not a theme value, so it is per-viewport and
# scoped to the Sketch tab. Nothing to snapshot; it just has to reach the
# viewports and report how many it touched.
addon.workspace.append(activate=False)
hidden = theme.set_floor_grid(addon.workspace.WORKSPACE_NAME, False)
check("hiding the floor grid reaches a viewport", hidden >= 1, f"changed {hidden}")
check("the grid is actually off",
      all(not s.overlay.show_floor
          for s in theme.viewports(addon.workspace.WORKSPACE_NAME)))
theme.set_floor_grid(addon.workspace.WORKSPACE_NAME, True)
check("the grid comes back",
      all(s.overlay.show_floor
          for s in theme.viewports(addon.workspace.WORKSPACE_NAME)))
check("an unknown workspace changes nothing", theme.set_floor_grid("Nope", False) == 0)


# --- Inference mark ----------------------------------------------------------
#
# The dot that shows where a drag snapped. Whether it draws in the right place
# needs a viewport and eyes; what can be pinned headless is the lifecycle --
# installed with the add-on, silent without a mark, silent without a region --
# and the arithmetic and colour plumbing under it.

section("Inference mark")
marks = addon.marks
check("handler installed with the add-on", marks.is_drawing())
check("installing twice is refused", marks.install() is False)

check("nothing showing to begin with", not marks.is_showing())
marks.show(Vector((1.0, 2.0, 3.0)))
check("a shown mark is showing", marks.is_showing())
# Headless there is no region to draw into; the callback must simply return.
try:
    marks.draw()
    silent = True
except Exception:
    silent = False
check("draw is silent without a viewport", silent)
marks.hide()
check("hidden is hidden", not marks.is_showing())

corners = marks.square(Vector((10.0, 20.0)), 3.5)
check("the dot is a square around its centre",
      corners == [(6.5, 16.5), (13.5, 16.5), (13.5, 23.5), (6.5, 23.5)],
      f"got {corners}")

# Compared with SAME_COLOUR, not equality: section 4's byte-storage lesson
# again, one storage down. FloatVectorProperty holds float32, so the shipped
# default 0.878 reads back as 0.87800002... and an exact comparison fails on
# the very default it is checking.
mark_colour = tuple(theme.colour("inference_colour"))
check("the mark's colour is a preference with a reset-covered default",
      "inference_colour" in theme.COLOUR_DEFAULTS
      and all(abs(a - b) <= theme.SAME_COLOUR for a, b in zip(mark_colour, theme.INFERENCE)),
      f"got {mark_colour!r}")
prefs_check = bpy.context.preferences.addons[ADDON].preferences
check("the preference field exists", hasattr(prefs_check, "inference_colour"))


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
check("mark handler removed", not marks.is_drawing())


# --- Result ------------------------------------------------------------------

print(f"\n{checks - len(failures)}/{checks} checks passed")
if failures:
    print("failed:")
    for name in failures:
        print(f"  - {name}")
    sys.exit(1)
print("SMOKE TEST PASSED")
sys.exit(0)
