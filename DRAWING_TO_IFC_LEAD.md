# Lead brief: Bonsai Sketch drawing-to-IFC tools

Use this file as the lead brief for development or a drawing-modelling session.
It describes the intended product, not a claim that every capability exists.
Creating or reading this file alone does not start a modelling run.

## 1. Reusable starting prompt

```text
Act as the technical lead for the Bonsai Sketch drawing-to-IFC workflow.
Read DRAWING_TO_IFC_LEAD.md and DRAWING_WORKFLOW.md in C:\2026_bonsai.
Inspect the actual code, repository instructions and working-tree changes before
choosing work. Preserve existing work and build on the modular prototype.

Session mode: DEVELOP TOOLS
Priority: reliable layer-based wall creation from repaired 2D drawings.
Drawing set: use only the project drawing set explicitly identified in this
session. If none is identified, use labelled synthetic fixtures for development.
Output: local, reviewable code, examples, checks and an updated handoff.

Verify the current implementation rather than assuming the brief's intended
features already exist. For a development session, fetch and review upstream
changes when accessible; do not merge or replace local work automatically.
Identify the smallest complete next increment, state its acceptance criteria,
implement it, and test it. Keep drawing extraction, geometry repair, component
authoring and independent IFC checking separate.

Carry forward the site-to-roof sequence, component defaults, evidence rules and
modular tool contracts in the lead brief. Do not close intentional openings,
invent drawing dimensions or treat material defaults as verified facts.

Finish with: what changed, evidence of verification, remaining limitations,
output paths, and a precise next task. Ask only for missing information that
blocks dependent work; continue independent work where possible.
```

For modelling rather than software development, replace the session settings:

```text
Session mode: MODEL A DRAWING SET
Project: <project name>
Drawing source: <folder or explicit file list>
Authoritative revisions: <drawing register, or establish from supplied evidence>
Output folder: <project-specific output folder>
First delivery: <site setup / selected storey / complete draft model>
Known datum and storey levels: <values with sources, or unresolved>
```

Do not infer a project from every drawing directory accessible on the machine.
If project files are missing, identify the gap; do not substitute the synthetic
example and describe it as the user's building.

## 2. Objective

Develop small, reusable Bonsai Sketch tools that transform coordinated 2D
drawings into an editable 3D IFC model, with source evidence, reviewable repairs,
adjustable component parameters and independent checks. The tools should later
support agents that inspect, propose, build, check and refine bounded portions
of the model.

Build through the actual construction sequence: location plan, boundary,
setbacks, terrain, entrance and ramps, platforms, foundations and footings,
basement, successive storeys, circulation and roof. Reuse the same tools across
storeys without assuming the floor plans are identical.

## 3. Starting point: inspect before extending

Read [DRAWING_WORKFLOW.md](DRAWING_WORKFLOW.md) for the dated GitHub review,
current capability limits, example and verification history. Recheck code and
branch status in each development session; the recorded revisions are historical.

| Location | Responsibility |
| --- | --- |
| `bonsai_sketch_mode/dxf.py` | Supported DXF entity reading and skipped-entity reporting |
| `bonsai_sketch_mode/ops/importer.py` | Existing CAD import, ODA conversion and extrusion |
| `bonsai_sketch_mode/drawing_tools/repair.py` | Layer repair and profiles with holes |
| `bonsai_sketch_mode/drawing_tools/catalogue.py` | Defaults and supplied schedule reconciliation |
| `bonsai_sketch_mode/drawing_tools/project.py` | Drawing alignment, layer mapping and recipe preparation |
| `bonsai_sketch_mode/drawing_tools/shapes.py` | Parametric slope geometry and survey-point terrain |
| `bonsai_sketch_mode/drawing_tools/ifc.py` | IFC component authoring from a recipe |
| `bonsai_sketch_mode/drawing_tools/checks.py` | Independent IFC geometry/relationship checks |
| `bonsai_sketch_mode/ops/drawing_project.py` | Sketch operator for a separate IFC export |
| `tools/drawing_pipeline.py` | Existing CLI: `prepare`, `build`, `check` |
| `examples/drawing_project/` | Synthetic fixture, prepared recipe and example IFC |

Inspect `autobuild.py`, `modelcheck.py`, IFC+SG work and the existing agent command
system for reusable functionality. Preserve local changes. Do not create a
second competing authoring system without explaining why an extension or adapter
cannot serve the requirement.

Current limits include incomplete DXF entity coverage, no automatic full drawing
interpretation, no native Bonsai parameter-editing UI for the new recipe objects,
basic opening checks, and no incremental update of an existing IFC. The existing
in-app agents do not yet expose the new drawing-tool operations.

## 4. Drawing register and evidence

For each source record: file path, hash, sheet number/title, discipline, revision,
units, scale, drawing role, storey, datum, alignment transform and related sheets.
Keep model-space coordinates distinct from drawing-sheet/paper-space coordinates.

For each component record: stable ID, source sheet/revision/layer/entity or marked
region, geometry parameters, storey and placement, relevant schedule tag, material,
assumptions, unresolved conflicts and the checks performed.

Classify each parameter as:

- **Explicit:** stated dimension, level, schedule value or specification.
- **Measured:** derived from calibrated geometry, with method and tolerance.
- **Default:** supplied by project settings, identified as unverified.
- **Unresolved:** missing or conflicting evidence, with affected components.

Use an explicit dimension instead of a scaled estimate when they agree on the
feature being described. Establish authoritative revisions from the drawing
register. Do not silently resolve conflicts between plans, sections, elevations,
schedules, structural drawings and blow-up details. Report the disagreement and
its impact. The current schedule resolver selects the supplied schedule value
but reports explicit conflicts as build-blocking errors.

## 5. Modelling sequence and acceptance criteria

### A. Register and align

Establish units, coordinate system, local origin, vertical datum and storey levels.
Use common grid intersections or other identifiable control points to align
different drawings. Report alignment residuals against a declared tolerance.
Keep source linework available for comparison; avoid changing original files.

Acceptance: source register exists; transformations are reproducible; control
points align; units are explicit; unresolved levels are visible.

### B. Site and ground works

Extract the location-plan boundary and setback references. Setbacks must come
from supplied design/authority evidence, not an assumed universal distance.
Construct undulating terrain from surveyed spot heights and, when supported,
contours with elevations and breaklines. Add the entrance, ramps, platform,
foundations and footings from their relevant sections/details.

Acceptance: boundary is valid; terrain respects supplied heights and its domain;
ramps join specified levels; foundation locations and dimensions retain sources.
Flag missing contour interpretation or breakline support instead of presenting
an unconstrained point triangulation as a completed contour reconstruction.

### C. Repair and create walls, one storey at a time

Map layers by meaning: wall footprints, centrelines, columns, slabs, openings,
annotations and references. A closed room or furniture outline is not a wall.
Distinguish measured wall footprints from centrelines requiring thickness.

Detect open chains, duplicate/overlapping segments, small endpoint gaps,
self-intersections, ambiguous junctions and nested voids. Show a repair preview
and the added/removed segments. Automatically repair only unambiguous gaps
within a declared tolerance; retain intentional doorways and larger gaps.
Unresolved geometry blocks the affected component, not unrelated modelling work.

Create walls at the correct storey/base elevation with heights supported by
sections/elevations. Preserve holes. Retain source-to-wall identity after repair.

Acceptance: clean closed profiles produce valid wall solids; intentional gaps
survive; repair changes are inspectable; height, thickness, class and placement
are correct; edited topology cannot silently redirect hosted opening IDs.

### D. Structure and repeated floors

Create slabs, precast components, beams, columns, foundations and footings with
editable profiles/dimensions. Support rectangular, circular and arbitrary
profiles first; treat curved/segmented members and precast connections as
explicit extensions with their own fixtures and checks.

Repeat by actual storey: basement, level 1, level 2, level 3 and higher as supplied.
Do not copy openings, structure or dimensions merely because storeys look similar.

Acceptance: correct storey containment, orientation, profile, extrusion length,
material and void geometry. Structural sizes are sourced, not designed by guess.

### E. Openings, windows and doors

Identify host walls and opening locations from plans; obtain sill/head heights
from elevations/sections. Match tags to schedules and blow-up details. Reconcile
width, height, operation, material, glass/frame properties and fire rating.

Create actual IFC void/filling relationships. Provide adjustable overall sizes
and component parameters. Verify regeneration after edits. Recipe-based rebuild
and native Bonsai parameter editing must be reported as different capabilities.

Acceptance: the opening cuts its intended host; dimensions and placement fit;
frame and glass are separate; schedule conflicts remain visible; specified
fire-rating data retains its source. A rating property alone is not proof that
the geometry/specification constitutes a tested fire-rated assembly.

### F. Stairs and roofs

Coordinate stairs against plans, sections, elevations and available details:
rise, risers, treads, widths, landings, direction, headroom and adjacent openings.
Model straight flights first; add curved/spiral/segmented families separately.

Build flat roofs with supplied thickness/falls. Build pitched roofs from roof
plans and sections, resolving eaves, ridge, valleys and panel junctions. A supplied
sloping panel is not an automatic roof-assembly generator.

Acceptance: flights meet landings and storeys; roof panels meet their intended
edges/levels; omissions and unresolved dimensions are listed.

## 6. Editable initial defaults

Internal length unit: metres. Display architectural dimensions in millimetres
where appropriate. Project overrides remain editable and distinguishable from
verified drawing values.

| Item | Initial setting |
| --- | --- |
| Landed-house block walls | Hollow block masonry; interpretation of "empty block walls" |
| Household shelter walls | Precast concrete; explicitly classified as shelter |
| Columns | Concrete |
| Beams and floor slabs | Precast concrete |
| Foundations, footings, platforms, ramps, stairs | Concrete |
| Flat roof | Concrete |
| Pitched roof covering | Unresolved until supplied |
| Window frame | Aluminium, 50 mm visible width x 50 mm depth |
| Window glass | Separate 12 mm pane; adjustable thickness |
| Glass appearance | Transparent by default; blue, green, black and transparent presets |
| Window overall dimensions | Required from project/drawings; no universal size |
| Door | Timber; default height 2100 mm |
| Alternate door heights | 2400 mm or full height from an explicit clear-height value |
| Door width and operation | Drawing/schedule driven; adjustable |
| Fire rating | No assumed default; unresolved until evidence is supplied |

Glass colour is independent of its transparency. Frame section dimensions are
independent of the window's overall width and height. Full-height door size is
not automatically the floor-to-floor dimension.

## 7. Modular and agent-ready design

Use deterministic local functions for geometry and IFC mutations. Use AI, when
enabled, for bounded interpretation/proposals and evidence review. Do not make
an AI service necessary for ordinary repair, extrusion or checking.

Suggested responsibility boundaries, whether handled by one agent or by a team:

| Responsibility | Input | Reviewable output |
| --- | --- | --- |
| Drawing interpretation | Registered sources | Measurements, layer meanings, references and uncertainties |
| Site preparation | Boundary, levels, survey evidence | Site/terrain/ground-work recipes and findings |
| Geometry repair | One layer or selected region | Proposed repairs, profiles and unresolved geometry |
| Component authoring | Validated parameters and host references | IFC elements and source-ID mapping |
| Schedule reconciliation | Component tags and supplied schedules/details | Resolved parameters and conflicts |
| Independent checking | Exported IFC and evidence | Findings tied to components and locations |
| Lead coordination | Status, dependencies and findings | Next bounded task and completion evidence |

These are architectural boundaries, not instructions to spawn agents. Delegate
only when the active session authorizes it, with distinct file/module ownership.

Every new tool should specify its input schema, units, preconditions, outputs,
side effects, failure conditions and repeat/rebuild behaviour. Prefer structured
findings with code, severity, component ID, source reference, location, expected
value, observed value and suggested next action. Confidence scores never replace
source evidence or deterministic checks.

The **existing** executable interface is:

```text
prepare <drawing-project.json> <new-recipe.json>
build   <recipe.json>          <new-model.ifc>
check   <model.ifc>            <new-findings.json>
```

Future operations such as drawing registration, repair preview, schedule
extraction, component regeneration and targeted IFC updates are proposed
interfaces until implemented and registered. Do not call them as if they exist.

## 8. Development increments

Do not restart the prototype. Select an incomplete increment based on inspection:

1. Drawing/layer review and wall-repair preview with source tracking.
2. Alignment validation and durable component/host identities across revisions.
3. Centreline and parallel-line wall creation with explicit thickness.
4. Native editable window/door families and stronger opening containment checks.
5. Survey/contour/breakline terrain and site-level coordination.
6. Structural families, stair assemblies and complete roof assemblies.
7. Registered agent tools and controlled updates to an existing IFC.

The modelling sequence remains site-to-roof; software increments may prioritise
the wall workflow while site references are supplied manually. Deliver each
increment through its actual UI/CLI entry point with a reproducible fixture.

## 9. Verification and handoff

Use relevant existing checks and add independent tests for consequential changes.
Start with `python tools/drawing_pipeline_check.py`; use
`tools/drawing_blender_check.py` for the Blender operator. Choose fresh output
paths for CLI examples. Record current results instead of copying historic counts.

Include adversarial cases appropriate to the change: intentional doorway gaps,
nearby unrelated endpoints, nested holes, crossing profiles, mismatched units,
rotated drawings, basement levels, schedule conflicts, wrong hosts, partial
opening containment and repeated rebuilds. Read the resulting IFC back to test
geometry and relationships, not only the recipe or authoring return values.

A development increment is complete when its entry point works, its acceptance
criteria pass, material limitations are documented, and existing relevant
behaviour is preserved. A drawing model is not complete merely because IFC
export succeeds. Compare it with the actual source set and list unresolved items.

Update a session handoff with:

```text
Session date / mode:
Repository branch and revision:
Project and drawing revisions:
Completed increment:
Changed files / output paths:
Verification commands and actual results:
Unresolved evidence / limitations:
Defaults used:
Next bounded task and acceptance criteria:
Information needed before dependent work:
```

Preserve original drawings, existing outputs, open models and unrelated code
changes. Keep draft outputs separate and reviewable. Do not install, publish,
merge or push as an incidental consequence of preparing a model or lead brief;
follow the scope authorized in the active session.
