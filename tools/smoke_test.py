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
    "T": tools.TAPE_TOOL,
}
for key, idname in expected.items():
    check(f"{key} -> {idname}", bound.get(key) == idname, f"got {bound.get(key)!r}")

for key in ("F", "B", "E"):
    check(f"{key} left unbound (tool not built)", key not in bound, f"got {bound.get(key)!r}")


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
