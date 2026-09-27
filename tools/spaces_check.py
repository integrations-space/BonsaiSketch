"""Check the space detector against rooms whose areas are known arithmetic.

Run with plain Python:

    python3 tools/spaces_check.py

The fixtures run the real chain -- drawn lines to wall candidates to
resolved walls to spaces -- so a wrong area here is a wrong area a user
would see. Boundaries are the walls' inner faces, so a 4x3 room behind
200mm walls measures 3.6 x 2.6 = 9.36, not 12: the area you can stand in.
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
ir = importlib.import_module("bonsai_sketch_mode.ir")


def candidate(start, end, thickness):
    length = ((end[0] - start[0]) ** 2 + (end[1] - start[1]) ** 2) ** 0.5
    return walls.WallCandidate(start, end, thickness, length, (0, 1), ["stated by hand"])


section("One room, through the whole chain")
outer = dxf.Polyline("WALLS", [(0.0, 0.0), (4.0, 0.0), (4.0, 3.0), (0.0, 3.0)], True,
                     source="LWPOLYLINE:AA01")
inner = dxf.Polyline("WALLS", [(0.2, 0.2), (3.8, 0.2), (3.8, 2.8), (0.2, 2.8)], True,
                     source="LWPOLYLINE:AA02")
segs, handles = walls.explode([outer, inner])
found, _unpaired = walls.detect(segs, sources=handles)
source_map = ir.SourceMap()
resolved, junctions = walls.resolve(found, source_map)
labels = [
    dxf.Label("ROOMS", "BEDROOM 2", (2.0, 1.5), source="TEXT:BB01"),
    dxf.Label("ROOMS", "OUTSIDE", (9.0, 9.0), source="TEXT:BB02"),
]
rooms = spaces.detect(resolved, junctions, labels, source_map)
check("one space from four walls", len(rooms) == 1, f"got {len(rooms)}")
room = rooms[0]
check("its area is the room you can stand in", near(room.area, 3.6 * 2.6),
      f"got {room.area}")
corners = {(round(x, 6), round(y, 6)) for x, y in room.boundary}
check("its boundary is the walls' inner faces",
      corners == {(0.2, 0.2), (3.8, 0.2), (3.8, 2.8), (0.2, 2.8)}, str(corners))
check("bounded by all four walls, each once",
      sorted(room.walls) == ["W001", "W002", "W003", "W004"], str(room.walls))
check("the label inside names it", room.label == "BEDROOM 2", repr(room.label))
check("and the name knows which entity wrote it",
      room.label_source == "TEXT:BB01", repr(room.label_source))
check("the label outside names nothing", "OUTSIDE" not in (room.label or ""))
ops = [r["op"] for r in source_map.records]
check("the source map records the enclosure and the naming",
      ops.count("ENCLOSE") == 1 and ops.count("LABEL") == 1,
      str({op: ops.count(op) for op in set(ops)}))
check("it serialises for the report", room.as_dict()["area"] == round(room.area, 6))


section("Two rooms sharing a divider")
perimeter = [
    candidate((0.2, 0.1), (3.8, 0.1), 0.2),
    candidate((0.2, 2.9), (3.8, 2.9), 0.2),
    candidate((0.1, 0.2), (0.1, 2.8), 0.2),
    candidate((3.9, 0.2), (3.9, 2.8), 0.2),
    candidate((2.0, 0.25), (2.0, 2.75), 0.2),
]
two_walls, two_junctions = walls.resolve(perimeter)
check("the divider meets the bars in two Ts",
      sorted(j.kind for j in two_junctions) == ["L", "L", "L", "L", "T", "T"],
      str([(j.id, j.kind) for j in two_junctions]))
two_rooms = spaces.detect(
    two_walls, two_junctions,
    [dxf.Label("ROOMS", "ROOM A", (1.0, 1.5), source="TEXT:CC01"),
     dxf.Label("ROOMS", "ROOM B", (3.0, 1.5), source="TEXT:CC02")],
)
check("two spaces", len(two_rooms) == 2, f"got {len(two_rooms)}")
areas = sorted(round(r.area, 6) for r in two_rooms)
check("each side measures to the divider's face",
      areas == [round(1.7 * 2.6, 6)] * 2, str(areas))
names = sorted(r.label or "" for r in two_rooms)
check("each room takes its own label", names == ["ROOM A", "ROOM B"], str(names))
check("the divider bounds both rooms",
      all("W005" in r.walls for r in two_rooms),
      str([r.walls for r in two_rooms]))


section("Refusals")
open_walls, open_junctions = walls.resolve([
    candidate((0.2, 0.1), (3.8, 0.1), 0.2),
    candidate((0.1, 0.2), (0.1, 2.8), 0.2),
    candidate((0.2, 2.9), (3.8, 2.9), 0.2),
])  # no fourth wall: a U, not a room
check("an unclosed plan encloses nothing",
      spaces.detect(open_walls, open_junctions) == [])

double_label_rooms = spaces.detect(resolved, junctions, [
    dxf.Label("ROOMS", "FIRST", (1.0, 1.0), source="TEXT:DD01"),
    dxf.Label("ROOMS", "SECOND", (3.0, 2.0), source="TEXT:DD02"),
])
check("two labels in one room: first kept, second reported",
      double_label_rooms[0].label == "FIRST"
      and any("SECOND" in d for d in double_label_rooms[0].diagnostics),
      str((double_label_rooms[0].label, double_label_rooms[0].diagnostics)))


print("\n".join(lines))
print(f"\n{checks} checks, {len(failures)} failures")
if failures:
    sys.exit(1)
