"""Check the opening evidence engine against openings stated by hand.

Run with any Python that has ifcopenshell:

    python3 tools/openings_check.py

The detection half is pure arithmetic -- gaps, radii, token tables -- and
needs nothing installed; the last section drives real ifcopenshell to pin
the emission shape, IfcWall -> IfcRelVoidsElement -> IfcOpeningElement ->
IfcRelFillsElement -> IfcDoor, because a semantic chain the library would
not actually build is a diagram, not a design.
"""

import sys
import types
from pathlib import Path

lines = []
failures = []
checks = 0


def check(label, condition, detail=""):
    global checks
    checks += 1
    if condition:
        lines.append("  ok    %s" % label)
    else:
        lines.append("  FAIL  %s%s" % (label, " -- %s" % detail if detail else ""))
        failures.append(label)


def section(title):
    lines.append("\n%s" % title)


def near(a, b, tolerance=1e-6):
    return abs(a - b) <= tolerance


root = Path(__file__).resolve().parent.parent
package = types.ModuleType("bonsai_sketch_mode")
package.__path__ = [str(root / "bonsai_sketch_mode")]
sys.modules["bonsai_sketch_mode"] = package

import importlib

dxf = importlib.import_module("bonsai_sketch_mode.dxf")
walls = importlib.import_module("bonsai_sketch_mode.walls")
spaces = importlib.import_module("bonsai_sketch_mode.spaces")
openings = importlib.import_module("bonsai_sketch_mode.openings")
ir = importlib.import_module("bonsai_sketch_mode.ir")


def candidate(start, end, thickness):
    length = ((end[0] - start[0]) ** 2 + (end[1] - start[1]) ** 2) ** 0.5
    return walls.WallCandidate(start, end, thickness, length, (0, 1), ["stated by hand"])


def semantic(*cands):
    """Resolved walls from hand-stated candidates: detect()'s real input."""
    return walls.resolve(list(cands))[0]


section("A doorway in a divider, through the whole chain")
plan = [
    candidate((0.2, 0.1), (3.8, 0.1), 0.2),    # bottom bar
    candidate((0.2, 2.9), (3.8, 2.9), 0.2),    # top bar
    candidate((0.1, 0.2), (0.1, 2.8), 0.2),    # left
    candidate((3.9, 0.2), (3.9, 2.8), 0.2),    # right
    candidate((2.0, 0.25), (2.0, 1.2), 0.2),   # divider below the door
    candidate((2.0, 2.1), (2.0, 2.75), 0.2),   # divider above the door
]
source_map = ir.SourceMap()
resolved, junctions = walls.resolve(plan, source_map)
swing = dxf.Arc("DOORS", (2.0, 1.2), 0.9, source="ARC:E1")
found, merged = openings.detect(resolved, arcs=[swing], source_map=source_map)
check("one opening from the divider's gap", len(found) == 1, str(len(found)))
door = found[0]
check("the two divider pieces merged into one host",
      len(merged) == 5 and door.host_wall == "W005",
      f"{len(merged)} walls, host {door.host_wall}")
host = next(w for w in merged if w.id == "W005")
check("the host spans the doorway",
      near(host.start[1], 0.1) and near(host.end[1], 2.9)
      or near(host.start[1], 2.9) and near(host.end[1], 0.1),
      f"{host.start} -> {host.end}")
check("the width is the measured gap", near(door.width, 0.9), str(door.width))
check("the position runs along the host's centreline",
      near(door.position, 1.55), str(door.position))
check("the swing arc resolves it as a door",
      door.classification == "DOOR" and door.status == "resolved",
      f"{door.classification} ({door.status}): {door.evidence}")
check("the arc is on the record", "ARC:E1" in door.sources, str(door.sources))
check("the merge is the opening's doing, in the source map",
      any(r["op"] == "MERGE" and door.id in r["inputs"] for r in source_map.records),
      str([r for r in source_map.records if r["op"] == "MERGE"]))
check("the host still knows both corners' junctions",
      len(host.junctions) == 2, str(host.junctions))

rooms = spaces.detect(merged, junctions)
check("the merged host closes the enclosures a doorway would have broken",
      len(rooms) == 2 and all(near(r.area, 1.7 * 2.6) for r in rooms),
      str([(r.id, r.area) for r in rooms]))
joined = openings.connects(door, host, rooms)
check("the door connects the two rooms",
      sorted(joined) == sorted([r.id for r in rooms]), str(joined))


section("Orientation and repetition")
flipped = [
    candidate((2.0, 0.25), (2.0, 1.2), 0.2),
    candidate((2.0, 2.75), (2.0, 2.1), 0.2),  # drawn top-down
]
f_found, f_merged = openings.detect(semantic(*flipped))
check("a piece drawn the other way round merges the same",
      len(f_found) == 1 and len(f_merged) == 1
      and near(f_found[0].width, 0.9)
      and near(max(f_merged[0].start[1], f_merged[0].end[1]), 2.75),
      str([w.as_dict() for w in f_merged]))

double = [
    candidate((0.1, 0.1), (1.0, 0.1), 0.2),
    candidate((1.9, 0.1), (3.0, 0.1), 0.2),
    candidate((3.9, 0.1), (5.0, 0.1), 0.2),
]
d_found, d_merged = openings.detect(semantic(*double))
check("a wall broken by two doors is one wall with two openings",
      len(d_found) == 2 and len(d_merged) == 1
      and all(near(o.width, 0.9) for o in d_found)
      and all(o.host_wall == d_merged[0].id for o in d_found),
      f"{len(d_found)} openings, {len(d_merged)} walls")


section("Evidence rules")
gap_only, _ = openings.detect(semantic(
    candidate((0.1, 0.1), (1.5, 0.1), 0.2),
    candidate((2.4, 0.1), (3.9, 0.1), 0.2),
))
check("a gap alone is possible, never a door",
      gap_only[0].classification is None and gap_only[0].status == "possible",
      f"{gap_only[0].classification} ({gap_only[0].status})")

window_found, _ = openings.detect(
    semantic(candidate((0.1, 0.1), (1.5, 0.1), 0.2), candidate((2.4, 0.1), (3.9, 0.1), 0.2)),
    glazing_segments=[((1.6, 0.1), (2.3, 0.1))],
    glazing_sources=["LINE:G1"],
)
check("glazing lines across the gap resolve a window",
      window_found[0].classification == "WINDOW"
      and "LINE:G1" in window_found[0].sources,
      str(window_found[0].as_dict()))

jamb_only, _ = openings.detect(
    semantic(candidate((0.1, 0.1), (1.5, 0.1), 0.2), candidate((2.4, 0.1), (3.9, 0.1), 0.2)),
    glazing_segments=[((1.95, 0.0), (1.95, 0.2))],
    glazing_sources=["LINE:J1"],
)
check("a jamb across the wall is not glazing",
      jamb_only[0].classification is None, str(jamb_only[0].evidence))

contested, _ = openings.detect(
    semantic(candidate((0.1, 0.1), (1.5, 0.1), 0.2), candidate((2.4, 0.1), (3.9, 0.1), 0.2)),
    arcs=[dxf.Arc("D", (1.5, 0.1), 0.9, source="ARC:C1")],
    inserts=[dxf.Insert("W", "WINDOW-TYPE-3", (1.95, 0.1), source="INSERT:C2")],
)
check("door and window evidence together is contested, not chosen",
      contested[0].status == "contested" and contested[0].classification is None,
      str(contested[0].diagnostics))

block_door, _ = openings.detect(
    semantic(candidate((0.1, 0.1), (1.5, 0.1), 0.2), candidate((2.4, 0.1), (3.9, 0.1), 0.2)),
    inserts=[dxf.Insert("D", "M_Door-Single_900", (1.95, 0.1), source="INSERT:B1")],
)
check("a door-named block resolves a door",
      block_door[0].classification == "DOOR", str(block_door[0].evidence))

check("block names read as whole tokens",
      openings.block_reading("M_Window_Casement") == "WINDOW"
      and openings.block_reading("DOOR-900") == "DOOR"
      and openings.block_reading("OUTDOOR-UNIT") is None
      and openings.block_reading("DOOR_WIN_COMBO") is None,
      str([openings.block_reading(n) for n in
           ("M_Window_Casement", "DOOR-900", "OUTDOOR-UNIT", "DOOR_WIN_COMBO")]))

tiny, tiny_walls = openings.detect(semantic(
    candidate((0.1, 0.1), (1.5, 0.1), 0.2),
    candidate((1.52, 0.1), (3.9, 0.1), 0.2),
))
check("a drafting break is not an opening",
      tiny == [] and len(tiny_walls) == 2)

thick_mismatch, _ = openings.detect(semantic(
    candidate((0.1, 0.1), (1.5, 0.1), 0.3),
    candidate((2.4, 0.1), (3.9, 0.1), 0.1),
))
check("different walls facing along a line are not one interrupted wall",
      thick_mismatch == [])


section("The emission shape, against real ifcopenshell")
import ifcopenshell
import ifcopenshell.api.feature
import ifcopenshell.api.project
import ifcopenshell.api.root

ifc = ifcopenshell.api.project.create_file(version="IFC4")
ifcopenshell.api.root.create_entity(ifc, ifc_class="IfcProject", name="Openings")
wall_entity = ifcopenshell.api.root.create_entity(ifc, ifc_class="IfcWall", name="W005")
opening_entity = ifcopenshell.api.root.create_entity(
    ifc, ifc_class="IfcOpeningElement", name="O001")
ifcopenshell.api.feature.add_feature(ifc, feature=opening_entity, element=wall_entity)
door_entity = ifcopenshell.api.root.create_entity(ifc, ifc_class="IfcDoor", name="D:O001")
ifcopenshell.api.feature.add_filling(ifc, opening=opening_entity, element=door_entity)

voids = wall_entity.HasOpenings
check("the wall is voided through IfcRelVoidsElement",
      len(voids) == 1 and voids[0].is_a("IfcRelVoidsElement")
      and voids[0].RelatedOpeningElement == opening_entity,
      str(voids))
fills = opening_entity.HasFillings
check("the opening is filled through IfcRelFillsElement",
      len(fills) == 1 and fills[0].is_a("IfcRelFillsElement")
      and fills[0].RelatedBuildingElement == door_entity,
      str(fills))
check("the chain survives serialisation",
      ifcopenshell.file.from_string(ifc.to_string())
      .by_type("IfcRelFillsElement")[0].RelatedBuildingElement.is_a("IfcDoor"))


print("\n".join(lines))
print(f"\n{checks} checks, {len(failures)} failures")
if failures:
    sys.exit(1)
