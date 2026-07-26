# BonsaiSketch

A direct-modelling interaction layer for [Bonsai](https://bonsaibim.org/), the
open-source native IFC authoring platform for Blender.

Bonsai's IFC capability is excellent. Its adoption barrier is Blender's
interface — and most architects already know a direct modeller. BonsaiSketch
presents Bonsai's existing authoring tools through a familiar interaction
model: single-key tools, inference snapping, and a measurement box. The IFC
layer underneath is untouched.

## How the pieces fit

Three layers, each running inside the one below:

```
Blender 5.0            the application you install and launch
  └─ Bonsai 0.8.4      add-on: turns Blender into an IFC/BIM authoring tool
       └─ BonsaiSketch add-on: gives Bonsai a direct-modelling UI
```

You install all three. BonsaiSketch does not replace Bonsai — it sits on top of
it and calls into it.

## Install

1. Install [Blender](https://www.blender.org/) **5.0**
2. Install [Bonsai](https://bonsaibim.org/) 0.8.4
3. Download the latest `bonsaibim_sketch_mode-*.zip` from Releases
4. In Blender: `Edit > Preferences > Add-ons > Install from Disk`
5. A **`Sketch` tab** appears in the top bar, next to Bonsai's `BIM` tab —
   immediately, without restarting or reopening a file

If Bonsai is missing, the add-on's preferences panel says so rather than
failing silently.

> **Supported Blender: 5.0 only.** Bonsai 0.8.4 ships 17 compiled wheels tagged
> `cp310`/`cp311`, so it needs a Blender on Python 3.10 or 3.11. Blender 5.0 is
> on 3.11. Blender 5.2 LTS is on 3.13, where those wheels will not load and
> Bonsai cannot run at all — so the manifest bounds the top of the range as
> well as the bottom.

## Using it

Click the **`Sketch` tab** in the top bar. That is Sketch Mode: one full-width
viewport, tools down the left, nothing else. No outliner, no properties editor,
no timeline. The single-key shortcuts go live on that tab and hand your usual
keymap back when you leave it, so nothing is taken away from the rest of
Blender.

Then:

1. **`R`** and drag out a rectangle. Two clicks, opposite corners. Type a
   number at any point for an exact one.
2. **`P`** and drag that face upward. Type a height and press Enter.
3. **`L`** to draw edges freehand — click to place points, `C` to close the
   loop, Enter to stop.
4. **`T`** to measure between any two snapped points.

`Esc` abandons whatever you are drawing. Backspace walks points back one at a
time. `X`/`Y`/`Z` lock an axis; `Shift` with them locks a plane.

You are drawing plain geometry at this stage, not IFC. When a shape is right,
select it and use Bonsai's **Assign IFC Class** on the `BIM` tab to make it a
wall, a slab, whatever it is. That is the whole point of the split: sketch
first, decide what it *is* second.

## The tools

| Key | Tool |
| --- | --- |
| `Space` | Select |
| `L` | Line |
| `R` | Rectangle |
| `P` | Push/Pull |
| `T` | Tape Measure |
| `M` `Q` `S` | Move / Rotate / Scale |
| `O` `H` `Z` | Orbit / Pan / Zoom (`Shift+Z` for zoom extents) |

All of them are in the 3D View toolbar too. Line, Rectangle and Tape run on
Bonsai's polyline engine, so they share its inference snapping, axis and plane
locks, and its measurement box — imperial input and typed expressions included.

Line, Rectangle and Push/Pull produce plain Blender meshes, not IFC elements: a
direct modeller's workflow is to sketch first and assign meaning second, and
Bonsai's own **Assign IFC Class** completes it. Push/Pull declines to touch an
IFC element rather than tessellate away its parametric definition.

## Status

Early, but usable for sketching. Working:

- Add-on registration, Bonsai detection and version guard
- The `Sketch` workspace tab, added automatically on file load
- A complete `Sketch` keyconfig
- Line, Rectangle, Push/Pull and Tape Measure

Not yet built: Offset, Follow Me, Eraser, Paint, and Push/Pull on parametric
IFC elements. `F`, `B` and `E` are left unbound rather than pointed at an
approximation. See the roadmap in
[bonsaibim_sketch_mode/README.md](bonsaibim_sketch_mode/README.md).

## Testing it, and telling us what broke

This is early software. The most useful thing a tester can do is try to build
something small and real — a room, a slab, a couple of walls — and report where
the interaction fought back.

Worth reporting even when it feels minor:

- A tool that did nothing, or did something other than what the status bar said
- Geometry that came out wrong: a face that should have closed and did not, a
  push that went the wrong way, a solid that renders with holes in it
- A key that did nothing. `F`, `B` and `E` are unbound on purpose; anything
  else is a bug
- Anything printed to Blender's console (`Window > Toggle System Console`)

Open an issue at
[github.com/integrations-space/BonsaiSketch/issues](https://github.com/integrations-space/BonsaiSketch/issues).
Include your Blender and Bonsai versions, and the output of the headless check
below if you can run it — it takes about a minute and rules out a broken
install before anyone spends time on a bug that is not there.

## Building it yourself, or a fork

The licence is GPL-3.0-or-later, so forking, modifying and redistributing is
explicitly allowed — provided your version ships its complete source under the
same terms. Nothing here is locked down.

```text
git clone https://github.com/integrations-space/BonsaiSketch
cd BonsaiSketch
blender --command extension build --source-dir bonsaibim_sketch_mode --output-dir dist
```

That produces `dist/bonsaibim_sketch_mode-<version>.zip`, which installs
exactly like a release build via `Install from Disk`. A fork needs no other
change — but do give it a different `id` and `name` in
`bonsaibim_sketch_mode/blender_manifest.toml` if both versions might end up
installed side by side, since Blender keys extensions by `id`.

## Development

Junction the add-on directory into Blender's user extension repository so edits
are picked up in place:

```text
mklink /J "%APPDATA%\Blender Foundation\Blender\5.0\extensions\user_default\bonsaibim_sketch_mode" "C:\2026_bonsai\bonsaibim_sketch_mode"
```

Check it registers and its geometry is correct:

```text
blender -b --python tools/smoke_test.py
```

This exits non-zero on the first failure, so it works as a CI gate. It cannot
drive the modal tools — those need a viewport and a mouse — but it covers
everything underneath them, including the mesh operations Line, Rectangle and
Push/Pull ultimately perform. Verified against Blender 5.0 and Bonsai 0.8.4.

Build a distributable package:

```text
blender --command extension build --source-dir bonsaibim_sketch_mode --output-dir dist
```

Regenerate the workspace `.blend` after changing the layout:

```text
blender -b --factory-startup --python tools/gen_workspace.py -- bonsaibim_sketch_mode/data/workspace.blend
```

All coupling to Bonsai is confined to
[bonsaibim_sketch_mode/bridge.py](bonsaibim_sketch_mode/bridge.py). Bonsai is a
rolling release with no stable public API contract, so when an upgrade breaks
this add-on, that file should be the only one needing attention.

## Licence

GPL-3.0-or-later. See [LICENSE](bonsaibim_sketch_mode/LICENSE).

This add-on imports Bonsai, which is GPL-3.0-or-later, and is therefore a
derivative work. If you distribute it — free or paid — you must ship the
complete corresponding source under the same terms. Internal use carries no
such obligation.

Bonsai is copyright Dion Moult and contributors.

## Trademarks

SketchUp is a trademark of Trimble Inc. This project is not affiliated with,
endorsed by, or sponsored by Trimble. SketchUp is referred to descriptively
only, to identify the interaction model users may already be familiar with.
All icons and visual design are original work.

This project is an independent third-party add-on and is not an official
Bonsai or IfcOpenShell product.
