"""Check the parallel-line wall detector against drawings stated by hand.

Run with plain Python:

    python3 tools/walls_check.py

No Blender, no ifcopenshell. Every fixture below is a wall (or a non-wall)
whose centreline, thickness and length are known by construction, which is
what makes a wrong detection unarguable. The refusals matter as much as the
detections: what does not pair must come back by index, unread rather than
misread.
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
    return abs(a - b) <= tolerance


def near_point(p, q, tolerance=1e-6):
    return near(p[0], q[0], tolerance) and near(p[1], q[1], tolerance)


root = Path(__file__).resolve().parent.parent
package = types.ModuleType("bonsai_sketch_mode")
package.__path__ = [str(root / "bonsai_sketch_mode")]
sys.modules["bonsai_sketch_mode"] = package

import importlib

walls = importlib.import_module("bonsai_sketch_mode.walls")
dxf = importlib.import_module("bonsai_sketch_mode.dxf")


section("One wall, two lines")
# A 4 m wall drawn as its two faces, 0.2 m apart.
pair = [((0.0, 0.0), (4.0, 0.0)), ((0.0, 0.2), (4.0, 0.2))]
found, unpaired = walls.detect(pair)
check("one candidate from one pair", len(found) == 1 and unpaired == [],
      f"{len(found)} candidates, {unpaired} unpaired")
wall = found[0]
check("the centreline runs between the faces",
      near_point(wall.start, (0.0, 0.1)) and near_point(wall.end, (4.0, 0.1)),
      f"{wall.start} -> {wall.end}")
check("thickness is the measured gap", near(wall.thickness, 0.2))
check("length is the measured shared run", near(wall.length, 4.0))
check("provenance names the stating segments", sorted(wall.sources) == [0, 1])
check("the evidence is sentences, not scores",
      len(wall.evidence) == 3 and all(isinstance(e, str) for e in wall.evidence)
      and not any("%" in e or "confidence" in e.lower() for e in wall.evidence),
      str(wall.evidence))

# Drawn the other way round, the same wall must come out -- direction canon.
reversed_pair = [((4.0, 0.0), (0.0, 0.0)), ((0.0, 0.2), (4.0, 0.2))]
found_r, _ = walls.detect(reversed_pair)
check("drawing direction does not matter",
      len(found_r) == 1 and near(found_r[0].thickness, 0.2)
      and near(found_r[0].length, 4.0))


section("The shared run is what is measured")
# The partner starts late and ends early: the wall is only where both run.
offset = [((0.0, 0.0), (4.0, 0.0)), ((1.0, 0.2), (3.0, 0.2))]
found, unpaired = walls.detect(offset)
check("overlap only", len(found) == 1 and near(found[0].length, 2.0),
      f"{[f.length for f in found]}")
check("and the centreline spans just that interval",
      near_point(found[0].start, (1.0, 0.1)) and near_point(found[0].end, (3.0, 0.1)),
      f"{found[0].start} -> {found[0].end}")


section("Refusals")
lone = [((0.0, 0.0), (4.0, 0.0))]
found, unpaired = walls.detect(lone)
check("a lone line states no wall", found == [] and unpaired == [0])

crossing = [((0.0, 0.0), (4.0, 0.0)), ((2.0, -1.0), (2.0, 1.0))]
found, unpaired = walls.detect(crossing)
check("perpendicular lines state no wall", found == [] and unpaired == [0, 1])

corridor = [((0.0, 0.0), (4.0, 0.0)), ((0.0, 1.5), (4.0, 1.5))]
found, unpaired = walls.detect(corridor)
check("a corridor's two sides are not one wall", found == [],
      f"{[f.thickness for f in found]}")

doubled = [((0.0, 0.0), (4.0, 0.0)), ((0.0, 0.004), (4.0, 0.004))]
found, unpaired = walls.detect(doubled)
check("a doubled drafting line is not a wall either", found == [])

leaning = [((0.0, 0.0), (4.0, 0.0)),
           ((0.0, 0.2), (4.0, 0.2 + 4.0 * math.tan(math.radians(3.0))))]
found, unpaired = walls.detect(leaning)
check("three degrees out of parallel is two lines, not a wall", found == [])

tapering = [((0.0, 0.0), (4.0, 0.0)), ((0.0, 0.15), (4.0, 0.25))]
found, unpaired = walls.detect(tapering)
check("a tapering gap is refused, not averaged", found == [],
      f"{[f.thickness for f in found]}")

stub = [((0.0, 0.0), (0.2, 0.0)), ((0.0, 0.2), (0.2, 0.2))]
found, unpaired = walls.detect(stub)
check("a jamb-length pair is below the minimum run", found == [])

crossing_line = [((0.0, 0.1), (4.0, 0.1)), ((0.0, 0.2), (4.0, -0.0001))]
found, unpaired = walls.detect(crossing_line)
check("a line crossing the other's axis is refused", found == [])


section("Exclusive pairing, longest run first")
# B sits between A and C at wall gaps to both; its longer run is with A.
three = [
    ((0.0, 0.0), (4.0, 0.0)),   # A
    ((0.0, 0.2), (4.0, 0.2)),   # B
    ((1.0, 0.4), (3.0, 0.4)),   # C
]
found, unpaired = walls.detect(three)
check("a line states at most one wall",
      len(found) == 1 and sorted(found[0].sources) == [0, 1] and unpaired == [2],
      f"{[f.sources for f in found]}, unpaired {unpaired}")


section("A drawn room, four walls")
# A 4x3 room as its two boundaries: outer rectangle and the inner one a
# 0.2 m wall leaves. Eight lines, four walls, no leftovers.
outer = dxf.Polyline("WALLS", [(0.0, 0.0), (4.0, 0.0), (4.0, 3.0), (0.0, 3.0)], True)
inner = dxf.Polyline("WALLS", [(0.2, 0.2), (3.8, 0.2), (3.8, 2.8), (0.2, 2.8)], True)
room_segments = walls.segments([outer, inner])
check("closed polylines contribute their closing edge", len(room_segments) == 8)
found, unpaired = walls.detect(room_segments)
check("four walls found", len(found) == 4, f"got {len(found)}")
check("nothing left over", unpaired == [], str(unpaired))
check("every wall measures 0.2 thick",
      all(near(f.thickness, 0.2) for f in found),
      str([round(f.thickness, 4) for f in found]))
lengths = sorted(round(f.length, 6) for f in found)
check("runs are the shared intervals, jambs unextended",
      lengths == [2.6, 2.6, 3.6, 3.6], str(lengths))
check("as_dict serialises for the report and the verbs",
      all(isinstance(f.as_dict(), dict) and f.as_dict()["sources"] for f in found))


section("Words on the drawing")
fixture = "\n".join(
    str(x) for pair in (
        (0, "SECTION"), (2, "HEADER"),
        (9, "$INSUNITS"), (70, 4),
        (0, "ENDSEC"),
        (0, "SECTION"), (2, "ENTITIES"),
        (0, "TEXT"), (8, "ROOMS"), (10, 2000), (20, 1500), (1, "BEDROOM 2"),
        (0, "MTEXT"), (8, "ROOMS"), (10, 5000), (20, 1500),
        (3, "LIVING "), (1, "ROOM"),
        (0, "LINE"), (8, "WALLS"), (10, 0), (20, 0), (11, 4000), (21, 0),
        (0, "ENDSEC"), (0, "EOF"),
    ) for x in pair
) + "\n"
drawing = dxf.parse(fixture)
check("TEXT and MTEXT are read, not skipped",
      "TEXT" not in drawing.skipped and "MTEXT" not in drawing.skipped,
      str(drawing.skipped))
check("two labels with their words",
      [t.text for t in drawing.texts] == ["BEDROOM 2", "LIVING ROOM"],
      str([t.text for t in drawing.texts]))
check("label positions scale with the drawing's units",
      near_point(drawing.texts[0].position, (2.0, 1.5)),
      str(drawing.texts[0].position))
check("labels keep their layer", drawing.texts[0].layer == "ROOMS")


print("\n".join(lines))
print(f"\n{checks} checks, {len(failures)} failures")
if failures:
    sys.exit(1)
