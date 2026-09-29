# Drawing-to-model development

Reviewed 19 September 2026. This document separates the working prototype from
the remaining drawing-interpretation and modelling tools.

## GitHub review

Fetched `origin` and checked all remote branches. The development branch
[`next-steps`](https://github.com/integrations-space/BonsaiSketch/tree/next-steps)
is at `e455609` (14 September), matching the local committed HEAD. The release
tag `v0.4.0` points to `4083009`. The default branch
[`main`](https://github.com/integrations-space/BonsaiSketch/tree/main) is older,
at `fd680a2` (27 July). The IFC+SG/Offset/Eraser and key-binding feature branches
also end in July; they are separate development, not a newer drawing pipeline.
No merge, reset or push was performed.

The development branch already has DXF layer import, DWG conversion through
ODA, small-gap healing, layer extrusion, IFC assignment and a reviewed agent
command workflow. The working tree additionally contains uncommitted
`autobuild.py`, `modelcheck.py` and IFC+SG field work. Those files were preserved.
The existing agent vocabulary does not yet expose the new drawing tools.

## Intended sequence

| Stage | Inputs and actions | Review evidence |
| --- | --- | --- |
| Drawing register | Register revision, units, origin, rotation and references for every plan, section, elevation, schedule and detail | Alignment points and source hashes |
| Site | Location plan: boundary and setback references; surveyed XYZ points or elevated contours | Survey datum, boundary closure and setback dimensions |
| Ground works | Terrain, entrance, ramps, platforms, foundations and footings | Levels, slopes, structural sections and details |
| Each storey | Basement upward: map wall-footprint layers, repair gaps, inspect profiles, create walls and structural elements | Repair report, floor elevation, heights and thicknesses |
| Openings | Position hosted voids; reconcile door/window tags against schedules, elevations and details | Host, width, sill, head height, material and fire rating |
| Circulation | Flights and landings from plans, sections and elevations | Floor-to-floor rise, tread count, widths, landings and headroom |
| Roof | Flat slabs or individually oriented pitched panels | Roof plan, section, falls, ridges and drainage details |
| Review/rebuild | Inspect findings, amend only the relevant recipe and rebuild a separate IFC | Source references, parameter diff and read-back geometry checks |

Do not identify a wall merely because a loop closes: a room outline, hatch,
setback or furniture outline can also close. Select layers with **wall footprint**
geometry explicitly. Centreline-to-wall generation needs a measured thickness
and is a separate tool. Wide gaps and ambiguous junctions require interpretation.

## Working prototype added here

The modules in `bonsai_sketch_mode/drawing_tools/` run without Blender or an AI
provider. `prepare`, `build` and `check` are independently callable:

- `repair.py`: nodes line intersections, joins mutually unique nearby free
  endpoints, records every bridge, rejects self-crossing source polylines,
  preserves nested holes and reports leftover linework. Repairs operate per
  mapped semantic layer, in metres. This replaces neither the old importer nor
  its existing behaviour; the new drawing-project route uses it.
- `catalogue.py`: editable component defaults and explicit schedule lookup.
  Conflicting component/schedule dimensions block a build until reconciled.
  Missing schedules or fire ratings are review findings, with no invented rating.
- `project.py`: reads supported ASCII DXF entities, aligns drawings, records
  source hashes and layer names, repairs footprint layers, resolves storeys and
  prepares an inspectable JSON recipe. Unsupported geometry on a mapped layer
  blocks export; skipped annotations are reported. DWG must first be converted
  to ASCII DXF with the existing CAD/ODA route.
- `shapes.py`: sloping closed slabs for ramps/roof panels, and an undulating TIN
  from supplied XYZ survey points. Boundary vertices need known heights.
- `ifc.py`: separate IFC4 export, arbitrary profiles with holes, circular
  columns, oriented beam extrusions, footings, foundation strips, slabs,
  platforms, flat roofs, explicit mesh terrain/ramps/roof panels, straight
  stair flights, hosted openings, windows and doors. Each component retains
  its recipe parameters. Annotation references represent boundaries/setbacks.
- `checks.py`: reads back element geometry, verifies opening/filling
  relationships, flags missing materials and openings whose bounding boxes
  miss the host entirely. It is a basic check, not a complete clash, opening
  containment, structural, staircase-headroom or regulatory assessment.

`Build IFC from Drawing Project...` is in **N > Sketch > Import 2D Drawing**
after installing this updated source. Select a drawing-project JSON. The tool
writes a new IFC beside it, puts the prepared recipe and checks in Blender Text
Editor documents, and preserves the open scene and existing output files.
Open the resulting IFC through Bonsai. No installed add-on was replaced by this
development session.

## Editable defaults

All lengths are metres internally. "Empty block walls" is interpreted as hollow
block masonry. It remains a project default, not a verified drawing fact.

| Component | Initial setting |
| --- | --- |
| Ordinary walls | Hollow block masonry |
| Household shelter walls | Precast concrete; use `shelter` explicitly |
| Columns, foundations, footings, platforms, ramps, stairs | Concrete |
| Beams and floor slabs | Precast concrete |
| Flat roof | Concrete |
| Pitched roof | Material required from project/drawings; no assumed covering |
| Window frame | Aluminium, 50 mm visible face width and 50 mm depth |
| Glass | Separate 12 mm pane, transparent; blue/green/black/transparent presets |
| Door | Timber, 2100 mm height; override to 2400 mm or `full_height` with `clear_height_m` |
| Fire rating | No default; record schedule evidence |

The 50 x 50 profile runs around all four window sides. Overall window width and
height must be provided. Window components have independently styled glass and
frame solids, and IFC material constituents. Door operation is passed to
IfcOpenShell's parametric door generator. Parameters remain editable in the
recipe; this prototype does **not** register native Bonsai window/door type
editing panels. Change dimensions and rebuild the IFC. Fire-rating data is
copied as declared; it does not establish a fire-rated assembly specification.

## Run the example

Use Python with IfcOpenShell and Shapely available (the tested environment has
IfcOpenShell 0.8.4.post1 and Shapely 2.0.6). From the repository root:

```powershell
python tools/drawing_pipeline.py prepare examples/drawing_project/project.json dist/drawing-prepared.json
python tools/drawing_pipeline.py build dist/drawing-prepared.json dist/drawing-example.ifc
python tools/drawing_pipeline.py check dist/drawing-example.ifc dist/drawing-checks.json
```

Choose unused output names on subsequent runs. `prepare` writes the repair and
findings report even when unresolved errors prevent building. The example is
synthetic: it demonstrates a repaired DXF wall, basement column/footing, upper
floor with a void, beam, window, door, stairs, ramp, roof panel and terrain.
It is not a coordinated building design. Missing fire-rating findings are
intentional. Geometry checks are in `examples/drawing_project/checks.json`;
an exported model is `examples/drawing_project/example.ifc`.

The manifest has `drawings`, `layers`, `storeys`, `components`, optional
`defaults`, and optional `schedules`. Drawing offsets are in project metres;
`scale_to_m` explicitly overrides DXF units. Component `origin_m` is relative
to its storey elevation. Profiles contain `outer` and optional `holes` XY rings.
`height_m` is extrusion depth; an optional `axis` directs a beam extrusion.
Window/door origin is the bottom-left corner on the host's near face; local X
runs along the opening and local Y through the wall. Set `host_depth_m` to the
wall depth and reference a host component ID. Layer islands use IDs such as
`walls:1`; review those references after topology changes that reorder islands.

Example schedule entry:

```json
{
  "D01": {
    "kind": "door",
    "source": "A601 revision C, door schedule D01",
    "width_m": 0.9,
    "height_m": 2.4,
    "material": "Timber",
    "fire_rating": "60 min"
  }
}
```

Set a door's `schedule_tag` to `D01`. The value above is an example, not a
default requirement. The tool looks up supplied schedule data; it does not OCR
or interpret the schedule sheet.

## Remaining modular work

1. Drawing register/review UI, control-point alignment and entity-level source
   IDs; richer DXF support for blocks, splines and elevated contours.
2. Boundary/setback measurement tools and contour/breakline-constrained terrain.
   Current terrain uses supplied spot points; it does not reconstruct contour
   labels, enforce contour breaklines or design grading/drainage.
3. Centreline walls, parallel-line wall detection, junction repair preview and
   per-gap review; durable island identities across drawing revisions.
4. Schedule/elevation/detail interpretation, robust opening containment/clash
   checks, native editable Bonsai types, multi-panel windows and door families.
5. Structural profile/type library, segmented/curved beams and columns,
   precast connections, stair assemblies/landings/curved flights and headroom.
6. Roof assembly generation from ridges/valleys and sections. Current pitched
   roofs are supplied panels; no automatic roof solving is implemented.
7. Agent tool registration and incremental rebuild against an existing model.
   Today agents can call the Python/CLI modules, inspect JSON findings and
   request a rebuild. The existing in-app agents do not yet call these verbs.

Keep extraction, parameter resolution, authoring and checking separate. Each
future tool should return component/source IDs, changes and unresolved evidence;
checks should inspect the produced IFC independently. Avoid a single agent
silently interpreting and approving an entire drawing set.

## Verification

`python tools/drawing_pipeline_check.py`: 19 passing tests, including independent
IFC schema/geometry validation, wall volume after void subtraction, slab holes,
storey elevations, separate glass thickness/transparency, repeatable component
identity, schedule conflicts, gap repair and source attribution.

`tools/drawing_blender_check.py` passed with factory startup in Blender 5.0 and
5.2: operator registration, example export, unchanged open scene and existing
output protection. These are headless integration checks; interactive panel
layout and a coordinated real drawing set have not been acceptance-tested.
