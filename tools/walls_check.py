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
ir = importlib.import_module("bonsai_sketch_mode.ir")


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


section("Source handles survive the explode")
fixture_sources = "\n".join(
    str(x) for pair in (
        (0, "SECTION"), (2, "ENTITIES"),
        (0, "LINE"), (5, "AB12"), (8, "WALLS"), (10, 0), (20, 0), (11, 4), (21, 0),
        (0, "LINE"), (8, "WALLS"), (10, 0), (20, 0.2), (11, 4), (21, 0.2),
        (0, "ENDSEC"), (0, "EOF"),
    ) for x in pair
) + "\n"
sourced = dxf.parse(fixture_sources)
handled, ordinal = sourced.layers["WALLS"]
check("a file's own handle names the entity", handled.source == "LINE:AB12",
      handled.source)
check("a file without handles still names it, by position",
      ordinal.source.startswith("LINE:#"), ordinal.source)
seg_list, handles = walls.explode(sourced.layers["WALLS"])
check("segment handles carry entity and place",
      handles[0] == "LINE:AB12/0" and handles[1].endswith("/0"), str(handles))
found_sourced, _ = walls.detect(seg_list, sources=handles)
check("a candidate's provenance is the drawn entities, not list positions",
      len(found_sourced) == 1 and "LINE:AB12/0" in found_sourced[0].sources,
      str([f.sources for f in found_sourced]))


section("Junctions: a room's four corners")
source_map = ir.SourceMap()
room_walls, room_junctions = walls.resolve(found, source_map)
check("four semantic walls with deterministic names",
      [w.id for w in room_walls] == ["W001", "W002", "W003", "W004"])
check("four L junctions",
      len(room_junctions) == 4 and all(j.kind == "L" for j in room_junctions),
      str([(j.id, j.kind) for j in room_junctions]))
resolved_lengths = sorted(round(w.length, 6) for w in room_walls)
check("corners resolved: lengths grow to the centreline crossings",
      resolved_lengths == [2.8, 2.8, 3.8, 3.8], str(resolved_lengths))
check("every wall meets two junctions",
      all(len(w.junctions) == 2 for w in room_walls),
      str([w.junctions for w in room_walls]))
check("identity survives the junction: thickness and sources untouched",
      all(near(w.thickness, 0.2) and len(w.sources) == 2 for w in room_walls))
check("each endpoint move is a written decision",
      all(len(w.diagnostics) == 2 and "extended" in w.diagnostics[0]
          for w in room_walls),
      str([w.diagnostics for w in room_walls]))
ops = [r["op"] for r in source_map.records]
check("the source map holds the whole derivation",
      ops.count("PAIR") == 4 and ops.count("JUNCTION") == 4
      and ops.count("EXTEND") == 8 and ops.count("TRIM") == 0,
      str({op: ops.count(op) for op in set(ops)}))
check("asking about a wall walks its records",
      len(source_map.about("W001")) >= 3, str(source_map.about("W001")))


def candidate(start, end, thickness):
    length = ((end[0] - start[0]) ** 2 + (end[1] - start[1]) ** 2) ** 0.5
    return walls.WallCandidate(start, end, thickness, length, (0, 1), ["stated by hand"])


section("Junctions: T, X, acute, mixed thickness")
t_walls, t_junctions = walls.resolve([
    candidate((0.0, 0.0), (2.0, 0.0), 0.2),
    candidate((1.0, 0.2), (1.0, 2.0), 0.2),
])
check("a T: the stem extends, the bar stands still",
      len(t_junctions) == 1 and t_junctions[0].kind == "T"
      and near_point(t_walls[1].start, (1.0, 0.0))
      and near_point(t_walls[0].start, (0.0, 0.0)) and near_point(t_walls[0].end, (2.0, 0.0)),
      str([w.as_dict() for w in t_walls]))
check("the bar still knows the junction happened on it",
      t_walls[0].junctions == [t_junctions[0].id])

x_walls, x_junctions = walls.resolve([
    candidate((0.0, 0.0), (4.0, 0.0), 0.2),
    candidate((2.0, -2.0), (2.0, 2.0), 0.2),
])
check("an X: recorded, nothing moved",
      len(x_junctions) == 1 and x_junctions[0].kind == "X"
      and all(not w.diagnostics for w in x_walls))

acute_walls, acute_junctions = walls.resolve([
    candidate((0.0, 0.0), (1.8, 0.0), 0.1),
    candidate((2.0, 0.1), (3.0, 1.1), 0.1),
])
check("a 45-degree corner meets where the centrelines cross",
      len(acute_junctions) == 1 and acute_junctions[0].kind == "L"
      and near_point(acute_walls[0].end, (1.9, 0.0))
      and near_point(acute_walls[1].start, (1.9, 0.0)),
      str([w.as_dict() for w in acute_walls]))

thick_walls, thick_junctions = walls.resolve([
    candidate((0.0, 0.0), (1.65, 0.0), 0.3),
    candidate((2.0, 0.35), (2.0, 2.0), 0.1),
])
check("mixed thicknesses reach by their sum",
      len(thick_junctions) == 1
      and near_point(thick_walls[0].end, (2.0, 0.0))
      and near_point(thick_walls[1].start, (2.0, 0.0)),
      str([w.as_dict() for w in thick_walls]))

parallel_walls, parallel_junctions = walls.resolve([
    candidate((0.0, 0.0), (2.0, 0.0), 0.2),
    candidate((2.1, 0.01), (4.1, 0.08), 0.2),
])
check("near-parallel continuations are not junctions",
      parallel_junctions == [] and all(not w.diagnostics for w in parallel_walls))


section("Continuation merging: predicates, not thresholds")
split = [candidate((0.0, 0.0), (2.0, 0.0), 0.2),
         candidate((2.003, 0.0), (5.0, 0.0), 0.2)]
merged_walls, verdicts = walls.merge_continuations(walls.resolve(split)[0])
check("a 3mm drafting break merges the geometry",
      len(merged_walls) == 1 and near(merged_walls[0].length, 5.0),
      str([w.as_dict() for w in merged_walls]))
check("the decision is MERGE_GEOMETRY, with the predicates on it",
      len(verdicts) == 1 and verdicts[0].decision == "MERGE_GEOMETRY"
      and verdicts[0].predicates["collinear"] is True
      and verdicts[0].predicates["thickness_match"] is True,
      str(verdicts[0].as_dict()))
check("semantic identity is assumed, not shown",
      "assumed" in verdicts[0].note
      and any("assumed" in d for d in merged_walls[0].diagnostics))
check("the merge carries both walls' provenance",
      len(merged_walls[0].sources) == 4, str(merged_walls[0].sources))

mismatch = walls.resolve([candidate((0.0, 0.0), (2.0, 0.0), 0.3),
                          candidate((2.003, 0.0), (5.0, 0.0), 0.1)])[0]
kept_walls, kept = walls.merge_continuations(mismatch)
check("different thicknesses keep the walls apart, predicate named",
      len(kept_walls) == 2 and kept[0].decision == "KEEP_SEMANTICALLY_SEPARATE"
      and "thickness_match" in kept[0].note, str(kept[0].as_dict()))

skew = walls.resolve([candidate((0.0, 0.0), (2.0, 0.0), 0.2),
                      candidate((2.003, 0.06), (5.0, 0.06), 0.2)])[0]
skew_walls, skew_verdicts = walls.merge_continuations(skew)
check("off the shared line is not collinear",
      len(skew_walls) == 2 and skew_verdicts[0].decision == "KEEP_SEMANTICALLY_SEPARATE"
      and "collinear" in skew_verdicts[0].note, str(skew_verdicts[0].as_dict()))

wide = walls.resolve([candidate((0.0, 0.0), (2.0, 0.0), 0.2),
                      candidate((2.2, 0.0), (5.0, 0.0), 0.2)])[0]
wide_walls, wide_verdicts = walls.merge_continuations(wide)
check("a 200mm break is a real gap, not fragmentation",
      len(wide_walls) == 2 and wide_verdicts
      and wide_verdicts[0].decision == "KEEP_SEMANTICALLY_SEPARATE"
      and "gap_within" in wide_verdicts[0].note, str([v.as_dict() for v in wide_verdicts]))

# A third wall terminates exactly at the joint: that junction is a
# statement, and the two runs stay two walls.
tee = walls.resolve([
    candidate((0.0, 0.1), (2.0, 0.1), 0.2),
    candidate((2.01, 0.1), (5.0, 0.1), 0.2),
    candidate((2.0, 0.3), (2.0, 3.0), 0.2),
])
term_walls, term_verdicts = walls.merge_continuations(tee[0], junctions=tee[1])
check("a terminating junction keeps the walls apart",
      len(term_walls) == 3
      and any(v.decision == "KEEP_SEMANTICALLY_SEPARATE"
              and "terminating_junction" in v.note for v in term_verdicts),
      str([v.as_dict() for v in term_verdicts]))

# An opening already explaining geometry at the joint vetoes the merge:
# that break is the opening stage's business, not fragmentation.
veto = walls.resolve([candidate((0.0, 0.0), (2.0, 0.0), 0.2),
                      candidate((2.02, 0.0), (5.0, 0.0), 0.2)])[0]
near_joint = ir.OpeningCandidate("O099", veto[0].id, 1.9, 0.9, [], ["stated by hand"])
veto_walls, veto_verdicts = walls.merge_continuations(veto, openings=[near_joint])
check("an opening at the joint keeps the walls apart",
      len(veto_walls) == 2
      and veto_verdicts[0].decision == "KEEP_SEMANTICALLY_SEPARATE"
      and "conflicting_opening" in veto_verdicts[0].note,
      str([v.as_dict() for v in veto_verdicts]))

# Chained fragmentation: three strokes, one wall, two recorded merges.
strokes = walls.resolve([candidate((0.0, 0.0), (1.5, 0.0), 0.2),
                         candidate((1.503, 0.0), (3.0, 0.0), 0.2),
                         candidate((3.004, 0.0), (5.0, 0.0), 0.2)])[0]
stroke_walls, stroke_verdicts = walls.merge_continuations(strokes)
check("three drafting strokes become one wall through two merges",
      len(stroke_walls) == 1 and near(stroke_walls[0].length, 5.0, 1e-2)
      and sum(1 for v in stroke_verdicts if v.decision == "MERGE_GEOMETRY") == 2,
      str([v.as_dict() for v in stroke_verdicts]))


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
