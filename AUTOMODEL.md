# AutoModel: 2D drawings to IFC+SG, agentically

The building sequence, targets and progress of the automated modelling
pipeline: a 2D DWG/DXF plan in, a 3D IFC model out, carrying the IFC+SG
parameters the standard requires — attached, and filled where a machine can
honestly fill them.

State as of 2026-09-27. Maintained alongside the work; every stage's row
below moves through `planned → building → CI-green → eyes-passed`.

## The approach, in one paragraph

Nothing here is a monolith and nothing is new-for-newness. Every stage is a
**verb in `textmodel/commands.py`** — the same registry the five Sketch
agents (Geometry, BIM/IFC, Compliance, Coordinator, QA) already drive — so
each step can be run by a human from the UI, by a script over the text
channel, or proposed and QA-gated by the agents. The pipeline operator just
runs the verbs in order and reports stage by stage. Determinism does the
work wherever determinism is honest (parsing, healing, geometry-derived
values); the agent layer is reserved for the judgement calls (an ambiguous
layer name, a missing storey height), through the existing
propose → review → approve flow — never silently.

## Building sequence

```
 DXF/DWG ──▶ 1 READ ──▶ 2 HEAL ──▶ 3 STAND ──▶ 4 CLASSIFY ──▶ 5 ASSIGN ──▶ 6 MCR ──▶ 7 FILL ──▶ 8 CHECK
             layers      loops      solids      layer→class    IfcWall...   IFC+SG     values     report
```

| # | Stage | Tool | Target | Status |
| --- | --- | --- | --- | --- |
| 1 | READ | `dxf.py` (+ ODA for DWG) | Layers, polylines, arcs in metres; skipped entities counted | CI-green (v0.4.0) |
| 2 | HEAL | `heal.py` | Broken outlines welded and enclosed to tolerance; crossings refused | CI-green (v0.4.0) |
| 3 | STAND | `ops/importer.py` | Per-layer solids at per-layer heights, volumes asserted | CI-green (v0.4.0) |
| 4 | CLASSIFY | `classify.py` | Layer names to IFC classes by drafting convention; unresolved named, never guessed — the agents' seam | CI-green (949d982) |
| 5 | ASSIGN | `assign_class` verb (exists) | Solids become IfcWall/IfcSlab/... in a real project, headless-capable | CI-green (1d8c813) |
| 6 | MCR | `psets.py` | Every element gets the IFC+SG parameters its class owes at the project stage | CI-green (6eacd58) |
| 7 | FILL | `derive.py` + `derive_values` verb | Geometry-derived values filled per class-aware readings; everything else left visibly unanswered, by name | CI-green (0f4fd76) |
| 8 | CHECK | `sg.py` (exists) | The checker's report closes the loop: what is present, what is still owed | CI-green (v0.4.0) |
| 9 | PIPELINE | `pipeline.py` + `auto_model` verb/operator | One command runs 1–8 with a stage-by-stage report; any stage can run alone | CI-green (1d8c813) |

## Prerequisite: the merge train (NEXT.md §1, §7)

Stage 6 lives in PR #1 (`psets.py`, the write side of IFC+SG) under the old
module path. NEXT.md §7 already warned that building the write side twice in
two shapes is the failure mode here — and the read side (`sg.py` /
`check_element`) has in fact independently re-solved slab-vs-roof, so the
two sides must be reconciled once, in the merge, not papered over.

Order, per NEXT.md §1: **#1 → main, #2 → main (three documented
resolutions), then main → `next-steps` with the rename sweep.**

One deliberate deviation from §1, recorded here so it is a decision and not
a drift: `next-steps` is **merged, not rebased**, and nothing is
force-pushed. This branch's owner works locally for weeks at a time — the
08-18 divergence happened exactly that way — and a rewritten remote under
unpushed local work manufactures the next divergence. A merge commit
reaches the same tree, keeps every SHA the laptop may be sitting on, and
lets git's directory-rename detection carry #1's added files into
`bonsai_sketch_mode/` before the identifier sweep runs.

## Value-filling policy (stage 7)

A machine fills a value only when the geometry states it: Height, Length,
Width, Thickness, Area, Volume — matched to IFC+SG parameter names
conservatively, in project units. A null that a human must answer is
information; a guessed fire rating is a defect. The agents may *propose*
the judgement values through the existing plan/approve flow; nothing writes
without the QA gate and the human Approve that flow already enforces.

As built, the matching turned out to need one more refusal than planned:
**what a name means depends on the class that carries it.** The workbook
asks a slab and a wall alike for `Area`, but a slab's is its footprint and
a wall's its elevation — so `derive.py` reads names through per-class
profiles, and a class gets a measurement only where the reading is
uncontested (a wall's Area, a column's `b`/`h`, a pile's `Length` all stay
questions). Volume is written only for a closed shell, footprint area only
when the solid provably is a prism over it. Perimeter and the containing
storey, listed in the original plan, are deferred to the same standard:
computable, but not yet stated by the geometry alone in a way every case
survives.

## Progress log

- **2026-09-27** — Research done: pipeline composes the verb registry;
  stages 1–3 and 8 already CI-green on `next-steps`; stage 6 gated on the
  merge train; read/write IFC+SG duplication confirmed (NEXT.md §7 called
  it). This document created. Merge train and stages 4–9 begin.
- **2026-09-27** — Merge train executed per §1: PR #1 → main (8112619),
  PR #2's three foretold conflicts resolved (e13d771), PR #2 → main
  (d66232c), main → `next-steps` as a merge, not a rebase (6eacd58), with
  the identifier sweep and the write/read IFC+SG reconciliation verified
  against ifcopenshell 0.8.5 before pushing. Stage 6 unblocked.
- **2026-09-27** — Stage 4 built: `classify.py` reads layer names against
  the drafting conventions, refusing no-matches and disagreements with
  reasons (949d982).
- **2026-09-27** — Stage 7 built: `derive.py` answers the geometric
  questions from the geometry, through per-class readings (see the
  value-filling policy above for the refusal it added to the plan);
  `derive_values` joins the verb vocabulary; 38 analytic checks in
  `tools/derive_check.py`, mesh-measuring covered in the smoke test.
  CI-green (0f4fd76).
- **2026-09-27** — Stages 5 and 9 built: `pipeline.py` runs
  READ→HEAL→STAND→CLASSIFY→ASSIGN→MCR→FILL→CHECK by composing the
  existing modules and verbs, wiring ASSIGN through the `assign_class`
  verb into a real Bonsai project. The stage-by-stage report goes to the
  caller, the "AutoModel Report" text block and the operator's INFO line;
  unresolved layers and unanswered values are reported, never guessed.
  `auto_model` and `classify_layers` join the verb vocabulary; File >
  Import gains "CAD Drawing to IFC (AutoModel)". End-to-end smoke: a
  fixture DXF's wall outline comes out as an IfcWall carrying both
  requirement sets, Thickness/Height/Length/Volume derived in project
  units, Area and Load Bearing still visibly open. CI-green (1d8c813) —
  the first headless create-project-and-assign in the suite held. **All
  nine stages verified. The road is open end to end.**
