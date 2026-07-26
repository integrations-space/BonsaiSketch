# Bonsai SketchUp UI

A SketchUp-style interaction layer for [Bonsai](https://bonsaibim.org/), the
open-source native IFC authoring platform for Blender.

Bonsai's IFC capability is excellent; its adoption barrier is Blender's
interface. Most architects already know SketchUp. This add-on presents Bonsai's
existing authoring tools through SketchUp's interaction model — single-key
tools, inference snapping, and a measurement box — without touching the IFC
layer underneath.

## Status

Early. Working: add-on registration, Bonsai detection and version guard, and a
complete SketchUp keyconfig. Not yet built: most of the tool set (see Roadmap).

Enable the add-on, then either click **Activate SketchUp Keymap** in its
preferences or pick `SketchUp` under Preferences > Keymap > Keymap Presets.

### Why a keyconfig and not an addon keymap

Blender's defaults bind the SketchUp single-key set 232 times across its
keymaps. Shadowing individual keys from an addon keymap gives unpredictable
behaviour depending on mode and editor, so this ships a full keyconfig built
the same way Blender's bundled "Industry Compatible" preset is. Conflicts are
stripped only inside 3D-View-related keymaps (17 bindings); the Outliner,
Dope Sheet and other editors keep Blender's defaults.

## Requirements

- Blender 4.2 LTS or 5.0
- Bonsai 0.8.4

Bonsai ships 17 compiled wheels tagged `cp310`/`cp311`, so it requires a
Blender built against Python 3.10 or 3.11. Newer Blender releases may ship a
Python version those wheels do not support — verify before upgrading.

## Development install

Junction this directory into Blender's user extension repository so edits are
picked up in place:

```
mklink /J "%APPDATA%\Blender Foundation\Blender\5.0\extensions\user_default\bonsai_sketchup" "C:\2026_bonsai\bonsai_sketchup"
```

Then enable **Bonsai SketchUp UI** in Preferences > Add-ons.

Headless check:

```
blender.exe -b --python-expr "import bpy; bpy.ops.preferences.addon_enable(module='bl_ext.user_default.bonsai_sketchup')"
```

## Architecture

All coupling to Bonsai is confined to `bridge.py`. Bonsai is a rolling release
with no stable public API contract, so when an upgrade breaks this add-on,
that file should be the only one needing attention. Do not `import bonsai`
anywhere else.

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
- [x] SketchUp keyconfig preset (Select/Line/Move/Rotate/Scale/Orbit/Pan/Zoom)
- [ ] Line tool over Bonsai's polyline operator and snap engine
- [ ] Rectangle
- [ ] Push/Pull — parametric for typed IFC elements, bmesh for proxies
- [ ] Offset, Tape Measure, Follow Me, Eraser
- [ ] Theme, workspace layout, condensed Entity Info panel
- [ ] Instructor panel

Keys whose SketchUp tool does not exist yet (R, P, F, T, E, B) are left
deliberately unbound. An unbound key is honest; one pointed at an
approximation teaches the wrong muscle memory.

## Licence

GPL-3.0-or-later. See [LICENSE](LICENSE).

This add-on imports Bonsai, which is GPL-3.0-or-later, and is therefore a
derivative work. If you distribute it — free or paid — you must ship the
complete source under the same terms. Internal use carries no such obligation.

Bonsai is copyright Dion Moult and contributors.
