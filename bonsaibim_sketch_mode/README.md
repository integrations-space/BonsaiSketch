# BonsaiSketch

A direct-modelling interaction layer for [Bonsai](https://bonsaibim.org/), the
open-source native IFC authoring platform for Blender.

Bonsai's IFC capability is excellent; its adoption barrier is Blender's
interface. Most architects already know a direct modeller. This add-on presents
Bonsai's existing authoring tools through a familiar interaction model —
single-key tools, inference snapping, and a measurement box — without touching
the IFC layer underneath.

## The tools

| Key | Tool | What it does |
| --- | --- | --- |
| `Space` | Select | Blender's box select |
| `L` | Line | Connected edges; closed coplanar loops become faces |
| `R` | Rectangle | Two opposite corners |
| `P` | Push/Pull | Extrudes the face under the cursor along its normal |
| `T` | Tape Measure | Bonsai's measure tool |
| `M` `Q` `S` | Move / Rotate / Scale | Blender's transforms |
| `O` `H` `Z` | Orbit / Pan / Zoom | `Shift+Z` for zoom extents |

All of them are also in the 3D View toolbar, so the toolset is discoverable
without already knowing the shortcuts.

Line, Rectangle and Tape all run on Bonsai's polyline engine, so they share its
inference snapping, axis locks (`X`/`Y`/`Z`), plane locks (`Shift`+`X`/`Y`/`Z`)
and measurement box — including imperial input and `=`-prefixed expressions.
Push/Pull has its own measurement box using the same parser.

`F`, `B` and `E` are deliberately unbound. Their tools do not exist yet, and an
unbound key is honest where a wrong one teaches the wrong muscle memory.

## Sketch geometry is not IFC

Line, Rectangle and Push/Pull produce plain Blender meshes, marked as ours and
linked at the top of the scene. Nothing about them is an IfcProduct.

That is deliberate. A direct modeller's workflow is to sketch first and assign
meaning second; making every stroke an IFC element would invert it. Bonsai's
own **Assign IFC Class** turns a finished sketch into a real element when the
user is ready.

Successive strokes accumulate into one object — whatever was last drawn into
stays active, and the next stroke finds it and welds onto its vertices.
Selecting something else, or nothing, starts a fresh sketch.

Push/Pull declines to touch an IFC element. Its shape is generated from
material layers or a profile, and overwriting that with a tessellated mesh
would silently discard the parametric definition. Depth belongs to Bonsai's own
controls until this tool can drive them directly.

## IFC+SG parameters attach on creation

When an element does come into being — Assign IFC Class on a sketch, or any of
Bonsai's own tools — it is given the parameters the IFC+SG Model Content
Requirements ask of its class, as an `IFCSG_Parameters` property set with null
values. The standard prescribes the questions, not the answers, and a null
property is a visible unanswered question — in Bonsai's property panels and in
the exported IFC — where an absent one is invisible.

The hook is one ifcopenshell post listener on `root.create_entity`, which
every creation path passes through. The listener only ever *adds missing
names*: filled values are never overwritten, which makes attachment idempotent
and a whole-file sweep always safe. That sweep is exposed as **Apply to
Existing Elements** in the 3D View sidebar (`N` > `Sketch`), next to the
project stage selector — requirements grow as a project advances, and the
stage is the user's to set, never guessed. Stage and the on/off switch are
scene properties, so they save with the file.

`requirements.py` answers what the standard asks (from
`data/ifc_sg.json`, extracted out of the published workbook by
`tools/extract_ifc_sg.py`, and the hand-maintained class mapping in
`data/ifc_sg_classes.json`); `psets.py` writes it onto elements. Elements
whose class mapping is uncertain are deliberately unmapped and get nothing —
attaching the wrong parameter set silently would be worse than attaching none.

## The Sketch workspace

The `Sketch` tab is a single 3D viewport — no outliner, no properties editor,
no timeline — with the tool palette shown, the properties sidebar hidden,
perspective, ground plane and red/green axes, and solid shading with outlines.

Building it took three attempts, because Blender has no data-level way to
remove an area and its screen operators all appear broken:

- `screen.area_close` hangs until the process is killed, headless or GUI.
- `screen.screen_full_area` runs, but does not build a one-area screen — it
  triggers the *temporary fullscreen overlay*, which hides the workspace
  switcher and shows an empty viewport. 0.2.0 shipped that. It was a real bug.
- `screen.area_join` returns `FINISHED` under `-b` while the area list *grows*.

The common cause: screen surgery is applied by Blender's event loop, not by the
operator call. Under `-b` there is no loop, so nothing is applied and repeated
calls pile up unresolved areas; in a GUI session there is one, but calling the
operators back-to-back inside a single callback never yields to it, which is
what made `area_close` look like a deadlock.

So `tools/gen_workspace.py` runs in a GUI session and performs exactly one join
per timer tick. Two further traps are worth knowing. `area_join` removes the
area at `target_xy` and keeps the one at `source_xy` — passing them the
intuitive way round merges the viewport into the timeline and deletes it. And
`Window.workspace` assignment is deferred too, so reading it straight after
`workspace.duplicate()` returns the *old* workspace; renaming there names the
original and leaves the joined layout on an orphan.

Entering the tab activates the Sketch keymap and leaving it restores whichever
keymap was in use before, so this never strands anyone in an unfamiliar keymap.
The tab appears as soon as the add-on is enabled — `load_post` alone would mean
a new user enables Sketch Mode, looks at the top bar, and sees nothing.

## Status

Working:

- Add-on registration, Bonsai detection and version guard
- The `Sketch` workspace tab: a single tuned viewport
- A complete `Sketch` keyconfig
- Line, Rectangle, Push/Pull and Tape Measure, in the toolbar and on keys
- IFC+SG required parameters attached automatically as elements are created,
  per project stage

### Why a keyconfig and not an addon keymap

Blender's defaults bind the single-key set 232 times across its keymaps.
Shadowing individual keys from an addon keymap gives unpredictable behaviour
depending on mode and editor, so this ships a full keyconfig built the same way
Blender's bundled "Industry Compatible" preset is. Conflicts are stripped only
inside 3D-View-related keymaps; the Outliner, Dope Sheet and other editors keep
Blender's defaults.

## Requirements

- Blender **5.0** or **5.2 LTS** — both tested, both ends bounded
- Bonsai **0.8.4** or **0.8.5**

The constraint is Bonsai's, not ours. It ships compiled wheels, so it only runs
where those match the host Python: 0.8.4 stopped at cp311, which ruled out
Blender 5.2 on Python 3.13, and 0.8.5 ships 3.13 wheels, which lets it in. The
manifest sets `blender_version_max` as well as `blender_version_min` so Blender
never offers to install this into a release nobody has run it on.

## Development install

Junction this directory into Blender's user extension repository so edits are
picked up in place:

```text
mklink /J "%APPDATA%\Blender Foundation\Blender\5.0\extensions\user_default\bonsaibim_sketch_mode" "C:\2026_bonsai\bonsaibim_sketch_mode"
```

Then enable **BonsaiBIM Sketch Mode** in Preferences > Add-ons.

Two check suites. Headless, for registration and geometry:

```text
blender -b --python tools/smoke_test.py
```

And one that needs a real window, for the things the first cannot reach — poll
methods, toolbar activation, the workspace layout, and the keymap swapping in
and out as you move between tabs:

```text
blender --python tools/ui_check.py -- report.txt
```

## Architecture

```
__init__.py       registration, preferences, the IFC+SG panel and operator
bridge.py         every reference to Bonsai
keyconfig.py      the Sketch keyconfig
workspace.py      the Sketch workspace tab, and the keymap that follows it
tools.py          toolbar entries
sketchmesh.py     the meshes the drawing tools write into
viewport.py       cursor-to-geometry queries (pure Blender)
theme.py          the Sketch canvas colours, snapshot and restore
requirements.py   what the IFC+SG standard asks of an element (queries data/)
psets.py          writes those requirements onto elements as they are created
ops/              the modal tools
  base.py         shared modal skeleton for the polyline tools
  line.py         Line
  rectangle.py    Rectangle
  pushpull.py     Push/Pull
data/             shipped IFC+SG requirements and class mapping
```

All coupling to Bonsai is confined to `bridge.py`. Bonsai is a rolling release
with no stable public API contract, so when an upgrade breaks this add-on, that
file should be the only one needing attention. Do not `import bonsai` anywhere
else.

Bonsai already provides the machinery this add-on builds on:

| Capability | Bonsai module |
| --- | --- |
| Inference / snapping | `bonsai/tool/snap.py` |
| Raycasting | `bonsai/tool/raycast.py` |
| Measurement box input (metric + imperial) | `bonsai/tool/polyline.py` |
| Viewport overlay drawing | `bonsai/bim/module/model/decorator.py` |
| Modal tool framework | `bonsai/bim/module/model/polyline.py` |
| Toolbar tools | `bonsai/bim/module/model/workspace.py` |

## Roadmap

- [x] Add-on scaffold, Bonsai detection and version guard
- [x] Keyconfig preset
- [x] Workspace tab
- [x] Line tool over Bonsai's polyline operator and snap engine
- [x] Rectangle
- [x] Push/Pull for sketch meshes
- [x] Tape Measure
- [x] Stripped-down workspace layout: a single viewport
- [x] IFC+SG required parameters, attached on element creation per stage
- [ ] Live rectangle preview while dragging the second corner
- [ ] Push/Pull for typed IFC elements, driving Bonsai's parametric depth
- [ ] Offset, Follow Me, Eraser, Paint
- [ ] Theme, condensed Entity Info panel
- [ ] Instructor panel

## Licence

GPL-3.0-or-later. See [LICENSE](LICENSE).

This add-on imports Bonsai, which is GPL-3.0-or-later, and is therefore a
derivative work. If you distribute it — free or paid — you must ship the
complete source under the same terms. Internal use carries no such obligation.

Bonsai is copyright Dion Moult and contributors.
