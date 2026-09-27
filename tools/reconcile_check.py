"""Check that views reconcile into one object and disagreement surfaces.

Run with plain Python:

    python3 tools/reconcile_check.py

The one behaviour these checks exist to forbid is silent resolution:
whatever else changes, disagreeing evidence must come back as a Conflict
with every claim intact, and nothing may average, weight or vote.
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
    return a is not None and abs(a - b) <= tolerance


root = Path(__file__).resolve().parent.parent
package = types.ModuleType("bonsai_sketch_mode")
package.__path__ = [str(root / "bonsai_sketch_mode")]
sys.modules["bonsai_sketch_mode"] = package

import importlib

dxf = importlib.import_module("bonsai_sketch_mode.dxf")
walls = importlib.import_module("bonsai_sketch_mode.walls")
openings = importlib.import_module("bonsai_sketch_mode.openings")
drawings = importlib.import_module("bonsai_sketch_mode.drawings")
reconcile = importlib.import_module("bonsai_sketch_mode.reconcile")
ir = importlib.import_module("bonsai_sketch_mode.ir")


def candidate(start, end, thickness):
    length = ((end[0] - start[0]) ** 2 + (end[1] - start[1]) ** 2) ** 0.5
    return walls.WallCandidate(start, end, thickness, length, (0, 1), ["stated by hand"])


section("Marks name openings on the plan")
marked, _ = openings.detect(
    walls.resolve([candidate((0.1, 0.1), (1.5, 0.1), 0.2),
                   candidate((2.4, 0.1), (3.9, 0.1), 0.2)])[0],
    labels=[dxf.Label("MARKS", "D1", (1.95, 0.4), source="TEXT:M1"),
            dxf.Label("MARKS", "NOTE 5", (1.95, 0.6), source="TEXT:M2")],
)
door = marked[0]
check("the tag in reach becomes the opening's mark",
      door.mark == "D1" and "TEXT:M1" in door.sources, str(door.as_dict()))
check("and a D-mark reads as door evidence",
      door.classification == "DOOR" and door.status == "resolved")
check("prose nearby is not a mark", "NOTE 5" not in str(door.as_dict()))

window_marked, _ = openings.detect(
    walls.resolve([candidate((0.1, 0.1), (1.5, 0.1), 0.2),
                   candidate((2.4, 0.1), (3.9, 0.1), 0.2)])[0],
    labels=[dxf.Label("MARKS", "W3", (1.95, 0.4), source="TEXT:M3")],
)
check("a W-mark reads as window evidence",
      window_marked[0].classification == "WINDOW"
      and window_marked[0].mark == "W3")


section("A section speaks the assertion grammar")
sheet = dxf.parse("\n".join(str(x) for pair in (
    (0, "SECTION"), (2, "ENTITIES"),
    (0, "TEXT"), (8, "NOTES"), (10, 0), (20, 9), (1, "SECTION A-A"),
    (0, "TEXT"), (8, "NOTES"), (10, 1), (20, 5), (1, "D1 H=2100"),
    (0, "TEXT"), (8, "NOTES"), (10, 1), (20, 4), (1, "D1 W=1000"),
    (0, "TEXT"), (8, "NOTES"), (10, 1), (20, 3), (1, "D9 H=2000"),
    (0, "TEXT"), (8, "NOTES"), (10, 1), (20, 2), (1, "SEE DETAIL 3"),
    (0, "ENDSEC"), (0, "EOF"),
) for x in pair) + "\n")
section_candidate = drawings.classify("D03", "03_SEC_A", sheet)
assertions = reconcile.extract(section_candidate, sheet)
check("the sheet knows it is a section", section_candidate.view_type == "SECTION")
check("three assertions read, prose ignored",
      len(assertions) == 3
      and [a.as_dict()["mark"] for a in assertions] == ["D1", "D1", "D9"],
      str([a.as_dict() for a in assertions]))
check("millimetre magnitudes read as millimetres, and say so",
      near(assertions[0].value, 2.1) and "millimetres" in assertions[0].reading)


section("Agreement fills, disagreement conflicts, nothing averages")
source_map = ir.SourceMap()
fills, conflicts, unmatched = reconcile.reconcile([door], assertions, source_map)
check("the agreeing height becomes one fill with its sources",
      len(fills) == 1 and fills[0][1] == "OverallHeight"
      and near(fills[0][2], 2.1) and len(fills[0][3]) == 1,
      str([(f[1], f[2], f[3]) for f in fills]))
check("the section's width against the measured gap is a conflict",
      len(conflicts) == 1 and conflicts[0].property == "OverallWidth"
      and conflicts[0].action == "HUMAN_REVIEW",
      str([c.as_dict() for c in conflicts]))
conflict_values = sorted(e["value"] for e in conflicts[0].evidence)
check("every claim survives intact -- 0.9 measured and 1.0 asserted, no average",
      conflict_values == [0.9, 1.0]
      and any(e["view"] == "PLAN:measured" for e in conflicts[0].evidence),
      str(conflicts[0].evidence))
check("the opening says its width is contested, and by whom",
      any("contested" in d and "C001" in d for d in door.diagnostics),
      str(door.diagnostics))
check("evidence about a mark nobody carries comes back unmatched",
      len(unmatched) == 1 and unmatched[0].mark == "D9")
ops = [r["op"] for r in source_map.records]
check("the ledger holds the assertion and the conflict",
      ops.count("ASSERT") == 1 and ops.count("CONFLICT") == 1, str(ops))

# Two independent views agreeing within drafting tolerance corroborate.
agreeing = [
    reconcile.Assertion("D1", "OverallHeight", 2.100, "TEXT:S1", "D03:SECTION", "r"),
    reconcile.Assertion("D1", "OverallHeight", 2.102, "TEXT:E1", "D04:ELEVATION", "r"),
]
door2, _ = openings.detect(
    walls.resolve([candidate((0.1, 0.1), (1.5, 0.1), 0.2),
                   candidate((2.4, 0.1), (3.9, 0.1), 0.2)])[0],
    labels=[dxf.Label("MARKS", "D1", (1.95, 0.4), source="TEXT:M1")],
)
fills2, conflicts2, _ = reconcile.reconcile(door2, agreeing)
check("claims two millimetres apart are one claim, both sources kept",
      len(fills2) == 1 and len(fills2[0][3]) == 2 and conflicts2 == [],
      str([(f[2], f[3]) for f in fills2]))
check("the corroboration names both views",
      any("SECTION" in e and "ELEVATION" in e
          for e in door2[0].evidence), str(door2[0].evidence))

disagreeing = [
    reconcile.Assertion("D1", "OverallHeight", 2.1, "TEXT:S1", "D03:SECTION", "r"),
    reconcile.Assertion("D1", "OverallHeight", 2.4, "TEXT:E1", "D04:ELEVATION", "r"),
]
door3, _ = openings.detect(
    walls.resolve([candidate((0.1, 0.1), (1.5, 0.1), 0.2),
                   candidate((2.4, 0.1), (3.9, 0.1), 0.2)])[0],
    labels=[dxf.Label("MARKS", "D1", (1.95, 0.4), source="TEXT:M1")],
)
fills3, conflicts3, _ = reconcile.reconcile(door3, disagreeing)
check("disagreeing views fill nothing and escalate everything",
      fills3 == [] and len(conflicts3) == 1
      and sorted(e["value"] for e in conflicts3[0].evidence) == [2.1, 2.4])


print("\n".join(lines))
print(f"\n{checks} checks, {len(failures)} failures")
if failures:
    sys.exit(1)
