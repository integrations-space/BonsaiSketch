"""Check drawing identity, cross-sheet alignment and storey assembly.

Run with plain Python:

    python3 tools/building_check.py

Fixtures are DXF text with stated titles, level marks and grids, so a
wrong classification, a wrong transform or a wrong elevation is a wrong
answer to something the drawing literally says.
"""

import math
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
    return a is not None and abs(a - b) <= tolerance


root = Path(__file__).resolve().parent.parent
package = types.ModuleType("bonsai_sketch_mode")
package.__path__ = [str(root / "bonsai_sketch_mode")]
sys.modules["bonsai_sketch_mode"] = package

import importlib

dxf = importlib.import_module("bonsai_sketch_mode.dxf")
drawings = importlib.import_module("bonsai_sketch_mode.drawings")
align = importlib.import_module("bonsai_sketch_mode.align")
storeys = importlib.import_module("bonsai_sketch_mode.storeys")


def pairs(*items):
    return "\n".join(str(x) for pair in items for x in pair) + "\n"


def sheet(*entities, units=6):
    return dxf.parse(pairs(
        (0, "SECTION"), (2, "HEADER"), (9, "$INSUNITS"), (70, units), (0, "ENDSEC"),
        (0, "SECTION"), (2, "ENTITIES"), *entities, (0, "ENDSEC"), (0, "EOF"),
    ))


def grid(x1, y1, x2, y2, name, nx, ny):
    return (
        (0, "LINE"), (8, "GRID"), (10, x1), (20, y1), (11, x2), (21, y2),
        (0, "TEXT"), (8, "GRID"), (10, nx), (20, ny), (1, name),
    )


def label(x, y, words):
    return ((0, "TEXT"), (8, "NOTES"), (10, x), (20, y), (1, words))


section("Drawing identity")
plan = drawings.classify("D01", "A101_GF", sheet(
    *label(5, 9, "GROUND FLOOR PLAN"),
    *label(2, 2, "FFL +0.000"),
))
check("the sheet's own title names the view", plan.view_type == "PLAN",
      str(plan.as_dict()))
check("the title is the evidence", any("titled" in e for e in plan.evidence))
check("the filename hints the storey", plan.storey_hint == "GF")
check("a bare level mark reads as metres",
      len(plan.level_labels) == 1 and near(plan.level_labels[0]["metres"], 0.0)
      and "metres" in plan.level_labels[0]["reading"],
      str(plan.level_labels))

named_by_file = drawings.classify("D02", "02_PLAN", sheet(*label(2, 2, "FFL +3.600")))
check("the filename speaks when the sheet does not",
      named_by_file.view_type == "PLAN"
      and any("filename" in e for e in named_by_file.evidence))
check("FFL text reads in metres", near(named_by_file.level_labels[0]["metres"], 3.6))

mixed = drawings.classify("D03", "A201", sheet(
    *label(1, 9, "SECTION A-A"), *label(6, 9, "DETAIL 3")))
check("a mixed sheet is UNKNOWN with the reason, never a guess",
      mixed.view_type == "UNKNOWN"
      and any("mixed sheet" in d for d in mixed.diagnostics),
      str(mixed.diagnostics))

silent = drawings.classify("D04", "X9", sheet())
check("an unnamed sheet says so", silent.view_type == "UNKNOWN"
      and any("unstated" in d for d in silent.diagnostics))

mm_level = drawings.classify("D05", "03_PLAN", sheet(*label(1, 1, "LVL 7200")))
check("a millimetre-magnitude level reads as millimetres, and says so",
      near(mm_level.level_labels[0]["metres"], 7.2)
      and "millimetres" in mm_level.level_labels[0]["reading"])
odd_level = drawings.classify("D06", "04_PLAN", sheet(*label(1, 1, "RL 350")))
check("an ambiguous magnitude stays unread rather than misread",
      odd_level.level_labels[0]["metres"] is None
      and any("ambiguous" in d for d in odd_level.diagnostics))


section("Grids and their crossings")
gridded = drawings.classify("D07", "01_PLAN", sheet(
    *grid(0, -1, 0, 11, "A", 0, -1.5),
    *grid(6, -1, 6, 11, "B", 6, -1.5),
    *grid(-1, 0, 11, 0, "1", -1.5, 0),
    *grid(-1, 8, 11, 8, "2", -1.5, 8),
    *label(3, 4, "FFL +0.000"),
))
check("named grid axes are collected", len(gridded.grid_axes) == 4
      and sorted(g["name"] for g in gridded.grid_axes) == ["1", "2", "A", "B"],
      str(gridded.grid_axes))
crossings = drawings.intersections(gridded)
check("named crossings fall where the lines cross",
      len(crossings) == 4 and crossings[("1", "A")] == (0.0, 0.0)
      and crossings[("2", "B")] == (6.0, 8.0), str(crossings))

anonymous = drawings.classify("D08", "05_PLAN", sheet(
    (0, "LINE"), (8, "GRID"), (10, 0), (20, 0), (11, 0), (21, 10)))
check("a grid line with no bubble is recorded and flagged",
      len(anonymous.grid_axes) == 1 and anonymous.grid_axes[0]["name"] is None
      and any("no name bubble" in d for d in anonymous.diagnostics))


section("Cross-sheet alignment")
# The second sheet draws the same grids, shifted and rotated 90 degrees.
import math as _math


def moved(x, y):
    # local = rotate(-90) then translate: reference = rotate(90) + (12.5, -8.2)
    c, s = _math.cos(_math.radians(-90)), _math.sin(_math.radians(-90))
    rx, ry = x - 12.5, y + 8.2
    return (rx * c - ry * s, rx * s + ry * c)


def moved_grid(x1, y1, x2, y2, name):
    (lx1, ly1), (lx2, ly2) = moved(x1, y1), moved(x2, y2)
    (nx, ny) = moved(x1, y1 - 1.5) if y1 == y2 == y1 else moved(x1, y1)
    return grid(lx1, ly1, lx2, ly2, name, lx1, ly1 - 0.5)


second = drawings.classify("D09", "02_PLAN", sheet(
    *moved_grid(0, -1, 0, 11, "A"),
    *moved_grid(6, -1, 6, 11, "B"),
    *moved_grid(-1, 0, 11, 0, "1"),
    *moved_grid(-1, 8, 11, 8, "2"),
    *label(1, 1, "FFL +3.600"),
))
reference_transform = align.to_reference(gridded, gridded, "T01")
check("the reference sheet holds the datum, and says so",
      reference_transform.status == "ACCEPTED"
      and near(reference_transform.residual, 0.0)
      and gridded.transform == "T01")
second_transform = align.to_reference(second, gridded, "T02")
check("shared grids earn an ACCEPTED transform",
      second_transform.status == "ACCEPTED",
      str(second_transform.as_dict()))
check("the fit recovers the rotation and lands the crossings",
      near(abs(second_transform.rotation_degrees), 90.0, 1e-6)
      and near(second_transform.residual, 0.0, 1e-6),
      str(second_transform.as_dict()))
recovered = second_transform.apply(drawings.intersections(second)[("1", "A")])
check("A/1 lands on A/1", near(recovered[0], 0.0, 1e-6) and near(recovered[1], 0.0, 1e-6),
      str(recovered))
check("the transform names its evidence and its kind of claim",
      any("grid A/1" in e or "grid 1/A" in e for e in second_transform.evidence)
      and any("not surveyed" in e for e in second_transform.evidence),
      str(second_transform.evidence))

gridless = drawings.classify("D10", "03_PLAN", sheet(*label(1, 1, "FFL +7.200")))
gridless_transform = align.to_reference(gridless, gridded, "T03")
check("no shared grids means UNRESOLVED, a person's call",
      gridless_transform.status == "UNRESOLVED" and gridless.transform is None
      and any("by hand" in d for d in gridless.diagnostics))


section("Storeys from evidence")
built = storeys.build([gridded, second, gridless, mixed])
check("one storey per plan drawing, elevation-ordered",
      [s.elevation for s in built] == [0.0, 3.6, 7.2],
      str([(s.id, s.elevation) for s in built]))
check("floor-to-floor is derived, and says from which storeys",
      near(built[0].floor_to_floor, 3.6) and near(built[1].floor_to_floor, 3.6)
      and built[2].floor_to_floor is None
      and any("derived" in e for e in built[0].evidence),
      str([s.as_dict() for s in built]))
check("a mixed sheet contributes no storey", len(built) == 3)

unknown_level = storeys.build([silent, drawings.classify(
    "D11", "06_PLAN", sheet())])
check("unknown elevation is a valid state, sorted last and said",
      len(unknown_level) == 1 and unknown_level[0].elevation is None
      and any("valid state" in d for d in unknown_level[0].diagnostics),
      str([s.as_dict() for s in unknown_level]))


print("\n".join(lines))
print(f"\n{checks} checks, {len(failures)} failures")
if failures:
    sys.exit(1)
