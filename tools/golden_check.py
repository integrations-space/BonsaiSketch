"""Compile the golden project blind, outside Blender, against stated truth.

Run with plain Python:

    python3 tools/golden_check.py

This is the golden package's local half: everything upstream of Blender
-- reading, pairing, junctions, openings, continuation, spaces,
drawing identity, alignment, storeys, reconciliation -- runs on the
committed drawings and is compared to golden/expected.json, which was
stated by hand, never captured from output. The Blender half (IFC
emission, containment, georeferencing, schema validation) is covered by
the same golden files in the CI smoke.

Nothing here may be loosened to make a new feature pass. A deliberate
fixture change lands in tools/gen_golden.py and expected.json together.
"""

import json
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


root = Path(__file__).resolve().parent.parent
package = types.ModuleType("bonsai_sketch_mode")
package.__path__ = [str(root / "bonsai_sketch_mode")]
sys.modules["bonsai_sketch_mode"] = package

import importlib

dxf = importlib.import_module("bonsai_sketch_mode.dxf")
walls = importlib.import_module("bonsai_sketch_mode.walls")
spaces = importlib.import_module("bonsai_sketch_mode.spaces")
openings = importlib.import_module("bonsai_sketch_mode.openings")
drawings = importlib.import_module("bonsai_sketch_mode.drawings")
align = importlib.import_module("bonsai_sketch_mode.align")
storeys = importlib.import_module("bonsai_sketch_mode.storeys")
reconcile = importlib.import_module("bonsai_sketch_mode.reconcile")
ir = importlib.import_module("bonsai_sketch_mode.ir")

golden = root / "golden"
expected = json.loads((golden / "expected.json").read_text())

sheets = {}
for name in ("01_PLAN_GF", "02_PLAN_L2", "03_SEC_A"):
    sheets[name] = dxf.parse((golden / f"{name}.dxf").read_text())

candidates = [
    drawings.classify("D%02d" % i, name, sheets[name])
    for i, name in enumerate(("01_PLAN_GF", "02_PLAN_L2", "03_SEC_A"), 1)
]

section("Drawing identity")
check("view types as stated",
      [c.view_type for c in candidates] == expected["drawings"]["view_types"],
      str([c.view_type for c in candidates]))

section("Alignment")
plans = [c for c in candidates if c.view_type == "PLAN"]
transforms = {}
for number, candidate in enumerate(plans, 1):
    transform = align.to_reference(candidate, plans[0], "T%02d" % number)
    transforms[transform.id] = transform
for transform_id, want in expected["transforms"].items():
    got = transforms[transform_id]
    check(f"{transform_id} lands as stated",
          got.status == want["status"]
          and abs(got.rotation_degrees - want["rotation_degrees"]) < 1e-9
          and abs(got.translation[0] - want["translation"][0]) < 1e-6
          and abs(got.translation[1] - want["translation"][1]) < 1e-6
          and (got.residual or 0.0) <= want.get("max_residual", 1e-9),
          str(got.as_dict()))

section("Storeys")
built = storeys.build(plans)
check("elevations and derivations as stated",
      [(s.elevation, s.floor_to_floor) for s in built]
      == [(w["elevation"], w["floor_to_floor"]) for w in expected["storeys"]],
      str([(s.elevation, s.floor_to_floor) for s in built]))

section("Per-storey compilation, blind")
shared = {"wall": 0, "junction": 0, "opening": 0, "merge": 0, "space": 0}
all_openings = []
all_labels = []
per = expected["per_storey"]
for plan, transform_id in zip(plans, ("T01", "T02")):
    sheet = sheets[plan.source_file]
    transform = transforms[transform_id]
    for polylines in sheet.layers.values():
        for polyline in polylines:
            polyline.points = [transform.apply(p) for p in polyline.points]
    for label in sheet.texts:
        label.position = transform.apply(label.position)
    for arc in sheet.arcs:
        arc.center = transform.apply(arc.center)

    segs, handles = walls.explode(sheet.layers["WALLS"])
    cands, unpaired = walls.detect(segs, sources=handles)
    semantic, junctions = walls.resolve(
        cands, first_wall=shared["wall"] + 1, first_junction=shared["junction"] + 1)
    shared["wall"] += len(cands)
    shared["junction"] += len(junctions)
    found, semantic = openings.detect(
        semantic, arcs=sheet.arcs, inserts=sheet.inserts,
        glazing_segments=[segs[i] for i in unpaired],
        glazing_sources=[handles[i] for i in unpaired],
        labels=sheet.texts, first=shared["opening"] + 1)
    shared["opening"] += len(found)
    semantic, _merges = walls.merge_continuations(
        semantic, junctions=junctions, openings=found)
    rooms = spaces.detect(semantic, junctions, sheet.texts, first=shared["space"] + 1)
    shared["space"] += len(rooms)
    all_openings.extend(found)
    all_labels += [r.label for r in rooms]

    check(f"{plan.source_file}: walls as stated",
          len(semantic) == per["walls"]
          and sorted(round(w.length, 6) for w in semantic) == per["wall_lengths"]
          and sorted({round(w.thickness, 3) for w in semantic}) == per["wall_thicknesses"],
          str([(w.id, round(w.length, 3), w.thickness) for w in semantic]))
    check(f"{plan.source_file}: junctions as stated",
          sorted(j.kind for j in junctions) == per["junction_kinds"],
          str(sorted(j.kind for j in junctions)))
    got_openings = sorted(
        (o.classification, round(o.width, 6),
         len(openings.connects(o, next(w for w in semantic if w.id == o.host_wall), rooms)))
        for o in found)
    want_openings = sorted(
        (o["classification"], o["width"], o["connects_spaces"])
        for o in per["openings"])
    check(f"{plan.source_file}: openings as stated",
          got_openings == want_openings, str(got_openings))
    check(f"{plan.source_file}: room areas as stated",
          sorted(round(r.area, 2) for r in rooms) == per["space_areas"],
          str(sorted(round(r.area, 3) for r in rooms)))

check("every room label as stated",
      sorted(all_labels) == expected["spaces"]["labels"], str(sorted(all_labels)))
check("marks as stated",
      sorted(o.mark for o in all_openings if o.classification == "DOOR")
      == expected["openings"]["door_marks"]
      and sorted(o.mark for o in all_openings if o.classification == "WINDOW")
      == expected["openings"]["window_marks"]
      and all(o.status == "resolved" for o in all_openings)
      == expected["openings"]["all_resolved"],
      str([(o.mark, o.status) for o in all_openings]))

section("Reconciliation")
section_candidate = candidates[2]
assertions = reconcile.extract(section_candidate, sheets["03_SEC_A"])
fills, conflicts, unmatched = reconcile.reconcile(all_openings, assertions)
by_mark = {opening.id: opening.mark for opening in all_openings}
got_fills = sorted((by_mark.get(f[0].id), f[1], round(f[2], 6)) for f in fills)
want_fills = sorted((f["mark"], f["property"], f["value"])
                    for f in expected["reconcile"]["fills"])
check("fills as stated", got_fills == want_fills, str(got_fills))
check("conflicts as stated, values intact",
      [(c.property, sorted(e["value"] for e in c.evidence), c.action)
       for c in conflicts]
      == [(c["property"], c["values"], c["action"])
          for c in expected["reconcile"]["conflicts"]],
      str([c.as_dict() for c in conflicts]))
check("unmatched as stated",
      sorted({a.mark for a in unmatched}) == expected["reconcile"]["unmatched_marks"])


print("\n".join(lines))
print(f"\n{checks} checks, {len(failures)} failures")
if failures:
    sys.exit(1)
