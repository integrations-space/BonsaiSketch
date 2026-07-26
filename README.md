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

1. Install [Blender](https://www.blender.org/) 4.2 LTS or 5.0
2. Install [Bonsai](https://bonsaibim.org/) 0.8.4
3. Download the latest `bonsaibim_sketch_mode-*.zip` from Releases
4. In Blender: `Edit > Preferences > Add-ons > Install from Disk`
5. A **`Sketch` tab** appears in the top bar, next to Bonsai's `BIM` tab

If Bonsai is missing, the add-on's preferences panel says so rather than
failing silently.

> Bonsai ships 17 compiled wheels tagged `cp310`/`cp311`, so it needs a Blender
> built against Python 3.10 or 3.11. Newer Blender releases may ship a Python
> those wheels do not support — check before upgrading.

## Status

Early. Working:

- Add-on registration, Bonsai detection and version guard
- A complete `Sketch` keyconfig (Select / Line / Move / Rotate / Scale / Orbit / Pan / Zoom)
- The `Sketch` workspace tab, added automatically on file load

Not yet built: most of the tool set. See the roadmap in
[bonsaibim_sketch_mode/README.md](bonsaibim_sketch_mode/README.md).

## Development

Junction the add-on directory into Blender's user extension repository so edits
are picked up in place:

```
mklink /J "%APPDATA%\Blender Foundation\Blender\5.0\extensions\user_default\bonsaibim_sketch_mode" "C:\2026_bonsai\bonsaibim_sketch_mode"
```

Build a distributable package:

```
blender --command extension build --source-dir bonsaibim_sketch_mode --output-dir dist
```

Regenerate the workspace `.blend` after changing the layout:

```
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
