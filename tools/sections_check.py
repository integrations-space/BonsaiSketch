"""Check the drawn-section reader against geometry stated by hand.

Run with plain Python:

    python3 tools/sections_check.py

Every fixture is a section whose levels, jambs and answers are known by
construction. The refusals matter most: a sheet whose levels disagree
about the datum is refused whole, a mark with no jambs contributes
nothing, and a drawn width that contradicts the plan's measured gap
escalates instead of overwriting it.
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
sections = importlib.import_module("bonsai_sketch_mode.sections")
reconcile = importlib.import_module("bonsai_sketch_mode.reconcile")
storeys = importlib.import_module("bonsai_sketch_mode.storeys")


def dxf_pairs(*items):
    return "\n".join(str(x) for pair in items for x in pair) + "\n"


def sheet(*entities):
    return dxf.parse(dxf_pairs(
        (0, "SECTION"), (2, "HEADER"), (9, "$INSUNITS"), (70, 4), (0, "ENDSEC"),
        (0, "SECTION"), (2, "ENTITIES"), *entities, (0, "ENDSEC"), (0, "EOF"),
    ))


def line(layer, x1, y1, x2, y2):
    return ((0, "LINE"), (8, layer), (10, x1), (20, y1), (11, x2), (21, y2))


def word(layer, x, y, words):
    return ((0, "TEXT"), (8, layer), (10, x), (20, y), (1, words))


section("A door drawn in section")
drawn = sheet(
    *word("NOTES", 0, 9000, "SECTION B-B"),
    *line("LEVELS", 0, 0, 6000, 0), *word("LEVELS", -500, 0, "FFL +0.000"),
    *line("LEVELS", 0, 3600, 6000, 3600), *word("LEVELS", -500, 3600, "FFL +3.600"),
    *line("OPENINGS", 2000, 0, 2000, 2100),
    *line("OPENINGS", 2900, 0, 2900, 2100),
    *word("MARKS", 2450, 2300, "D1"),
)
candidate = drawings.classify("D03", "03_SEC_B", drawn)
assertions, levels = sections.extract_geometry(candidate, drawn)
check("the sheet knows it is a section", candidate.view_type == "SECTION")
check("both levels pair with their lines",
      len(levels) == 2 and sorted(l["metres"] for l in levels) == [0.0, 3.6],
      str(levels))
by_property = {a.property: a for a in assertions}
check("three measured assertions for the mark",
      sorted(by_property) == ["OverallHeight", "OverallWidth", "SillHeight"],
      str([a.as_dict() for a in assertions]))
check("the head-to-sill height is measured, not asserted",
      near(by_property["OverallHeight"].value, 2.1)
      and "measured off drawn jambs" in by_property["OverallHeight"].reading,
      str(by_property["OverallHeight"].as_dict()))
check("the width is the jamb spacing", near(by_property["OverallWidth"].value, 0.9))
check("the sill sits on the level below it",
      near(by_property["SillHeight"].value, 0.0)
      and "+0.000 level" in by_property["SillHeight"].reading)
check("the jambs' entity handles are the sources",
      "LINE:" in by_property["OverallHeight"].source,
      by_property["OverallHeight"].source)

window_drawn = sheet(
    *word("NOTES", 0, 9000, "SECTION C-C"),
    *line("LEVELS", 0, 0, 6000, 0), *word("LEVELS", -500, 0, "FFL +0.000"),
    *line("OPENINGS", 1000, 900, 1000, 2400),
    *line("OPENINGS", 1600, 900, 1600, 2400),
    *word("MARKS", 1300, 2600, "W1"),
)
w_candidate = drawings.classify("D04", "04_SEC_C", window_drawn)
w_assertions, _levels = sections.extract_geometry(w_candidate, window_drawn)
w_by = {a.property: a for a in w_assertions}
check("a window's sill height is measured above its floor",
      near(w_by["SillHeight"].value, 0.9)
      and near(w_by["OverallHeight"].value, 1.5)
      and near(w_by["OverallWidth"].value, 0.6),
      str([a.as_dict() for a in w_assertions]))


section("Refusals")
crooked = sheet(
    *word("NOTES", 0, 9000, "SECTION D-D"),
    *line("LEVELS", 0, 0, 6000, 0), *word("LEVELS", -500, 0, "FFL +0.000"),
    *line("LEVELS", 0, 3000, 6000, 3000), *word("LEVELS", -500, 3000, "FFL +3.600"),
    *line("OPENINGS", 2000, 0, 2000, 2100),
    *line("OPENINGS", 2900, 0, 2900, 2100),
    *word("MARKS", 2450, 2300, "D1"),
)
c_candidate = drawings.classify("D05", "05_SEC_D", crooked)
c_assertions, c_levels = sections.extract_geometry(c_candidate, crooked)
check("levels that disagree about the datum refuse the whole sheet",
      c_assertions == [] and len(c_levels) == 2
      and any("not drawn 1:1" in d for d in c_candidate.diagnostics),
      str(c_candidate.diagnostics))

bare = sheet(
    *word("NOTES", 0, 9000, "SECTION E-E"),
    *line("LEVELS", 0, 0, 6000, 0), *word("LEVELS", -500, 0, "FFL +0.000"),
    *word("MARKS", 2450, 2300, "D1"),
)
b_candidate = drawings.classify("D06", "06_SEC_E", bare)
b_assertions, _ = sections.extract_geometry(b_candidate, bare)
check("a mark with no jamb pair contributes nothing, and says so",
      b_assertions == []
      and any("no jamb pair" in d for d in b_candidate.diagnostics))

textonly = drawings.classify("D07", "07_SEC_F", sheet(
    *word("NOTES", 0, 9000, "SECTION F-F"),
    *word("NOTES", 1000, 5000, "D1 H=2100")))
t_assertions, t_levels = sections.extract_geometry(textonly, sheet())
check("a text-only section stays quiet -- the grammar's business, not this reader's",
      t_assertions == [] and t_levels == [] and textonly.diagnostics == [])


section("Drawn evidence reconciles like any other")
plan_openings, _ = openings.detect(
    walls.resolve([
        walls.WallCandidate((0.1, 0.1), (1.5, 0.1), 0.2, 1.4, (0, 1), ["by hand"]),
        walls.WallCandidate((2.4, 0.1), (3.9, 0.1), 0.2, 1.5, (0, 1), ["by hand"]),
    ])[0],
    labels=[dxf.Label("MARKS", "D1", (1.95, 0.4), source="TEXT:M1")],
)
fills, conflicts, _un = reconcile.reconcile(plan_openings, assertions)
check("the drawn height fills the plan's door",
      any(f[1] == "OverallHeight" and near(f[2], 2.1) for f in fills),
      str([(f[1], f[2]) for f in fills]))
check("the drawn width corroborates the measured gap -- no conflict",
      conflicts == [] and any(f[1] == "OverallWidth" for f in fills),
      str([c.as_dict() for c in conflicts]))
corroborated = next(f for f in fills if f[1] == "OverallWidth")
check("both the measurement and the drawing are on the width's record",
      len(corroborated[3]) == 2, str(corroborated[3]))


section("Drawn levels against the storeys")
plan_candidate = drawings.classify("D01", "01_PLAN_GF", sheet(
    *word("NOTES", 0, 9000, "GROUND FLOOR PLAN"),
    *word("NOTES", 100, 100, "FFL +0.000")))
built = storeys.build([plan_candidate])
matched_conflicts = sections.corroborate_storeys(built, levels, candidate)
check("a drawn level within tolerance corroborates the storey",
      matched_conflicts == []
      and any("corroborated by drawn level" in e for e in built[0].evidence),
      str(built[0].evidence))
check("a level matching no storey is noted as unmodelled, not failed",
      any("matches no storey" in d for d in candidate.diagnostics),
      str(candidate.diagnostics))

skewed = [{"metres": 0.05, "y": 0.05, "source": "LINE:X1"}]
built2 = storeys.build([plan_candidate])
skew_conflicts = sections.corroborate_storeys(built2, skewed, candidate)
check("a nearly-matching level contests the elevation as a Conflict",
      len(skew_conflicts) == 1 and skew_conflicts[0].property == "Elevation"
      and skew_conflicts[0].action == "HUMAN_REVIEW"
      and sorted(e["value"] for e in skew_conflicts[0].evidence) == [0.0, 0.05],
      str([c.as_dict() for c in skew_conflicts]))


print("\n".join(lines))
print(f"\n{checks} checks, {len(failures)} failures")
if failures:
    sys.exit(1)
