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
    "F": tools.OFFSET_TOOL,
    "E": tools.ERASER_TOOL,
    "T": tools.TAPE_TOOL,
}
for key, idname in expected.items():
    check(f"{key} -> {idname}", bound.get(key) == idname, f"got {bound.get(key)!r}")

for key in ("B",):
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
check("apply operator registered", hasattr(bpy.ops.bonsaibim_sketch_mode, "apply_ifc_sg"))
check("sidebar panel registered", hasattr(bpy.types, "BONSAIBIM_SKETCH_PT_ifc_sg"))
check("stage is a scene property", hasattr(context.scene, "bonsaibim_sketch_stage"))
check("attachment defaults to on", context.scene.bonsaibim_sketch_auto_params is True)
check("typology defaults to unset", context.scene.bonsaibim_sketch_typology == "none")
check("optional parameters default to off",
      context.scene.bonsaibim_sketch_optional_params is False)

import ifcopenshell
import ifcopenshell.api.project
import ifcopenshell.api.pset
import ifcopenshell.api.root
import ifcopenshell.util.element

context.scene.bonsaibim_sketch_stage = "detailed"
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
context.scene.bonsaibim_sketch_stage = "schematic"
early_wall = ifcopenshell.api.root.create_entity(ifc, ifc_class="IfcWall", name="W3")
check("no requirements at this stage means no pset",
      ifcopenshell.util.element.get_pset(early_wall, psets.PSET_NAME) is None)
door = ifcopenshell.api.root.create_entity(ifc, ifc_class="IfcDoor", name="D")
door_pset = ifcopenshell.util.element.get_pset(door, psets.PSET_NAME)
check("a door gets its own, smaller schematic set",
      door_pset is not None and "Fire Rating" in door_pset)

# Advancing the stage: the sweep behind Apply to Existing Elements tops up
# what earlier stages did not ask for, then has nothing more to say.
context.scene.bonsaibim_sketch_stage = "detailed"
touched, added = psets.sweep(ifc, psets.AttachSettings(stage="detailed"))
check("a sweep tops up elements from an earlier stage",
      ifcopenshell.util.element.get_pset(early_wall, psets.PSET_NAME) is not None)
check("the sweep is idempotent",
      psets.sweep(ifc, psets.AttachSettings(stage="detailed")) == (0, 0))

# The scene switch turns attachment off entirely.
context.scene.bonsaibim_sketch_auto_params = False
off_wall = ifcopenshell.api.root.create_entity(ifc, ifc_class="IfcWall", name="W4")
check("turning it off attaches nothing",
      ifcopenshell.util.element.get_pset(off_wall, psets.PSET_NAME) is None)
context.scene.bonsaibim_sketch_auto_params = True

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
context.scene.bonsaibim_sketch_typology = "public_residential"
column = ifcopenshell.api.root.create_entity(ifc, ifc_class="IfcColumn", name="C1")
col_sg = ifcopenshell.util.element.get_pset(column, psets.PSET_NAME)
col_dl = ifcopenshell.util.element.get_pset(column, psets.DELIVERY_PSET_NAME)
check("a column gets both property sets", col_sg is not None and col_dl is not None)
check("delivery parameters attach unfilled",
      col_dl is not None and col_dl.get("b", "sentinel") is None)

context.scene.bonsaibim_sketch_typology = "industrial"
chair = ifcopenshell.api.root.create_entity(ifc, ifc_class="IfcFurniture", name="Chair")
check("a delivery-only class attaches under its typology",
      ifcopenshell.util.element.get_pset(chair, psets.DELIVERY_PSET_NAME) is not None)
check("it gets no IFC+SG set, which does not cover it",
      ifcopenshell.util.element.get_pset(chair, psets.PSET_NAME) is None)

context.scene.bonsaibim_sketch_typology = "none"
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

occurrence = ifcopenshell.api.root.create_entity(typed, ifc_class="IfcDoor", name="D1")
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
