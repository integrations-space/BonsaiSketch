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

## Status

Working:

- Add-on registration, Bonsai detection and version guard
- The `Sketch` workspace tab, added automatically on file load
- A complete `Sketch` keyconfig
- Line, Rectangle, Push/Pull and Tape Measure, in the toolbar and on keys

### Why a keyconfig and not an addon keymap

Blender's defaults bind the single-key set 232 times across its keymaps.
Shadowing individual keys from an addon keymap gives unpredictable behaviour
depending on mode and editor, so this ships a full keyconfig built the same way
Blender's bundled "Industry Compatible" preset is. Conflicts are stripped only
inside 3D-View-related keymaps; the Outliner, Dope Sheet and other editors keep
Blender's defaults.

## Requirements

- Blender 5.0 (verified) or 4.2 LTS
- Bonsai 0.8.4

Bonsai ships 17 compiled wheels tagged `cp310`/`cp311`, so it requires a
Blender built against Python 3.10 or 3.11. Newer Blender releases may ship a
Python version those wheels do not support — verify before upgrading.

## Development install

Junction this directory into Blender's user extension repository so edits are
picked up in place:

```
mklink /J "%APPDATA%\Blender Foundation\Blender\5.0\extensions\user_default\bonsaibim_sketch_mode" "C:\2026_bonsai\bonsaibim_sketch_mode"
```

Then enable **BonsaiBIM Sketch Mode** in Preferences > Add-ons.

Headless check:

```
blender -b --python tools/smoke_test.py
```

## Architecture

```
__init__.py     registration, preferences
bridge.py       every reference to Bonsai
keyconfig.py    the Sketch keyconfig
workspace.py    the Sketch workspace tab, and the keymap that follows it
tools.py        toolbar entries
sketchmesh.py   the meshes the drawing tools write into
viewport.py     cursor-to-geometry queries (pure Blender)
ops/            the modal tools
  base.py       shared modal skeleton for the polyline tools
  line.py       Line
  rectangle.py  Rectangle
  pushpull.py   Push/Pull
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
- [ ] Live rectangle preview while dragging the second corner
- [ ] Push/Pull for typed IFC elements, driving Bonsai's parametric depth
- [ ] Offset, Follow Me, Eraser, Paint
- [ ] Theme, workspace layout, condensed Entity Info panel
- [ ] Instructor panel

## Licence

GPL-3.0-or-later. See [LICENSE](LICENSE).

This add-on imports Bonsai, which is GPL-3.0-or-later, and is therefore a
derivative work. If you distribute it — free or paid — you must ship the
complete source under the same terms. Internal use carries no such obligation.

Bonsai is copyright Dion Moult and contributors.
