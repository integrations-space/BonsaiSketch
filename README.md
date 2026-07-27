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
Blender 5.0 / 5.2      the application you install and launch
  └─ Bonsai 0.8.4/0.8.5  add-on: turns Blender into an IFC/BIM authoring tool
       └─ BonsaiSketch add-on: gives Bonsai a direct-modelling UI
```

You install all three. BonsaiSketch does not replace Bonsai — it sits on top of
it and calls into it.

## Quick start

Nothing here assumes you have used Blender before. Roughly fifteen minutes,
most of it downloading.

### Step 1 — Install Blender

Download from [blender.org/download](https://www.blender.org/download/).
**5.0 or 5.2 LTS** — both are tested.

Newer releases are refused on purpose. Bonsai ships compiled Python components,
so it only runs where those match the host Python, and a Blender nobody has run
this against is a silent breakage waiting to happen. Installing outside the
supported range fails with a clear message instead:

```text
This Blender version (5.3.0) must be less than the maximum version (5.3.0)
```

### Step 2 — Install Bonsai, inside Blender

Open Blender, then:

**`Edit` > `Preferences` > `Get Extensions`** → search **`Bonsai`** → **Install**

It is a large download and takes a few minutes. When it finishes, a **`BIM`**
tab appears in the bar across the top of the window.

> Tested against Bonsai **0.8.4** and **0.8.5**. Get Extensions installs 0.8.5
> today, which is also what makes Blender 5.2 possible — 0.8.4's wheels stopped
> at Python 3.11. If something misbehaves, your Bonsai version is the first
> thing to put in a bug report.

### Step 3 — Install BonsaiSketch

Download **`bonsaibim_sketch_mode-0.3.0.zip`** from
[the latest release](https://github.com/integrations-space/BonsaiSketch/releases/latest).
Do not unzip it. Then, in Blender:

**`Edit` > `Preferences` > `Add-ons`** → the **`▾`** button, top right →
**`Install from Disk...`** → choose the zip

A **`Sketch`** tab appears in the top bar next to `BIM`, immediately — no
restart, no reopening a file.

If Bonsai is missing or broken, the add-on's own preferences panel says so, in
words, instead of failing quietly.

### Step 4 — Draw something

Click the **`Sketch`** tab. The single-key shortcuts are live on this tab and
your normal Blender keymap comes back the moment you leave it, so nothing is
taken away from the rest of Blender.

One full-width viewport, tools down the left, nothing else — no outliner, no
properties editor, no timeline. Perspective, ground plane and coloured axes,
solid shading with outlines.

Try exactly this:

1. Press **`R`**. Click once, move the mouse, click again. That is a rectangle.
2. Press **`P`**. Move the mouse over the rectangle's face and drag upward —
   then type `3` and press **`Enter`**. That is a 3-metre box.
3. Press **`L`**. Click points to draw edges. **`C`** closes the loop back to
   the start, **`Enter`** finishes.
4. Press **`T`** and click two points to measure between them.

While drawing:

| | |
| --- | --- |
| Type a number | An exact value — metric, imperial (`5' 6"`), or `=2*1.5` |
| `X` `Y` `Z` | Lock to one axis |
| `Shift` + `X` `Y` `Z` | Lock to one plane |
| `Backspace` | Undo the last point |
| `Esc` | Abandon the whole thing |

`F`, `B` and `E` do nothing **on purpose**. Those tools are not built yet, and
a key wired to an approximation teaches the wrong habit.

### Step 5 — Turn it into IFC

Everything above is plain geometry, not IFC. That is the point: sketch first,
decide what it *is* second.

When a shape is right, select it, switch to the **`BIM`** tab and use Bonsai's
**Assign IFC Class** to make it a wall, a slab, or whatever it actually is.

Push/Pull deliberately **refuses** to touch an element that is already IFC. Its
shape is generated from material layers or a profile, and overwriting that with
a plain mesh would silently throw the parametric definition away. Use Bonsai's
own depth controls for those.

### If something does not work

| Symptom | Cause |
| --- | --- |
| Install fails, "must be less than the maximum version" | Your Blender is newer than 5.2. Use 5.0 or 5.2 |
| No `Sketch` tab after installing | The add-on is installed but not ticked in `Preferences > Add-ons` |
| `Sketch` tab present, letter keys do nothing | You are on a different tab. The keymap is only live on `Sketch` |
| Tools greyed out, or an error in their settings bar | Bonsai is missing or failed to load — check the `BIM` tab exists |
| Push/Pull says "no face under the cursor" | Hover directly over a face. It will also decline objects that have modifiers |

Still stuck: `Window > Toggle System Console` shows what Blender is complaining
about, and that output is the single most useful thing to put in an issue.

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
