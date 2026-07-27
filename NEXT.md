# What to do next

State as of 2026-07-27. Two pull requests are open, green, and mergeable; eight
issues carry the SketchUp gap list. Nothing here is blocked on anything except
the merge order below.

## 1. Merge the two open PRs, in this order

Both pass CI, and both were also run locally against Blender 5.2 LTS with
Bonsai 0.8.5 — a newer pair than CI's Blender 5.0 / Bonsai 0.8.4, so the
untested-version guard is exercised as well.

| PR | Head | What it is |
| --- | --- | --- |
| [#1](https://github.com/integrations-space/BonsaiSketch/pull/1) | `116046b` | Model Content Requirements on creation, Offset, Eraser, and four review fixes |
| [#2](https://github.com/integrations-space/BonsaiSketch/pull/2) | `20663d4` | Claim `A`, `C`, `G` so they stop running Blender's operators |

**Merge #1 first, then #2.** They conflict — three files, all the same
disagreement: each branch rewrote the same prose about which keys are
deliberately unbound. #2 was written against `main`, where Offset and Eraser did
not exist, so its wording lists them as unbuilt. #1 builds them.

Resolving #2 after #1 lands:

- `bonsaibim_sketch_mode/keyconfig.py` — take #2's `_su_bindings` docstring, then
  drop `Offset,` from its list of tools still to build. `CLAIMED_KEYS` and
  `UNBUILT_KEYS` need no change: `F` and `E` are already claimed on both sides,
  and neither is in `UNBUILT_KEYS`.
- `tools/smoke_test.py` — take #2's block wholesale. It reads
  `keyconfig.UNBUILT_KEYS` from the module rather than repeating a literal, so
  it adjusts itself.
- `bonsaibim_sketch_mode/README.md` — take #2's paragraph, but open it with
  ``` `B`, `A`, `C` and `G` ``` instead of ``` `F`, `B`, `E`, `A`, `C` and `G` ```,
  since `F` and `E` are bound once #1 is in.

Merging #2 first works too, but then the same three conflicts land on #1, which
is the much larger branch — cheaper to resolve them on the small one.

## 2. Rebind Select All, deliberately

#2 strips Blender's `A` (Select All) as a side effect of claiming the key for
Arc, and deliberately does not replace it — Select All remains on the 3D View's
Select menu, but the shortcut is gone. This was left out of #2 because it is a
decision about Blender's keymap, not a detail of an unbuilt Arc tool.

SketchUp's own bindings are `Ctrl+A` for Select All and `Ctrl+T` for Deselect
All. Blender gives `Ctrl+A` to the Apply menu. Injected bindings are prepended
and matched first, so adding them shadows Apply inside the Sketch keyconfig
without stripping anything — but shadowing Apply is a real cost to anyone who
uses it, so make the call knowingly.

## 3. Known bug, deferred on purpose

`sketchmesh.commit` runs `contextual_create` over every stroke, and on an open
multi-segment Line stroke this appears to add closing geometry the user never
asked for. Found while writing the Eraser's polyline check — which is why that
check builds its two bare strokes directly instead of going through `commit`.

It is a Line-tool question, not an Eraser one, so it was kept out of #1 rather
than smuggled in. Worth reproducing first: draw an open three-point collinear
polyline and count the edges against the arithmetic.

## 4. The SketchUp gap list

Eleven of SketchUp's roughly thirty tools exist. The gaps are filed as issues,
each naming the Bonsai operator or module that backs it where one exists.

Ordered by value per unit of work, not by size:

1. **[#3](https://github.com/integrations-space/BonsaiSketch/issues/3) Curve tools — Circle (`C`), Arc (`A`).** The largest hole in the toolset:
   nothing curved can be drawn at all. Cheapest real feature on this list,
   because Bonsai already has the geometry — `bim.add_ifccircle`,
   `bim.cad_arc_from_2_points`, `bim.cad_arc_from_3_points`. The work is modal
   UX over proven operators. Also unblocks the two keys #2 just silenced.
2. **[#4](https://github.com/integrations-space/BonsaiSketch/issues/4) Modifier and double-click behaviours.** A grep for `event.ctrl`,
   `event.shift`, `event.alt` and `DOUBLE_CLICK` across the add-on returns
   nothing, so none of SketchUp's modifier vocabulary works — Push/Pull `Ctrl`
   for a new face, double-click to repeat a distance, `Ctrl`-drag to copy,
   arrow keys to lock an axis. For a project whose premise is familiar muscle
   memory, this is felt more than any single missing tool, and each piece is
   independent.
3. **[#7](https://github.com/integrations-space/BonsaiSketch/issues/7) Inference in three of six tools.** Line, Rectangle and Tape inherit
   Bonsai's snapping; Push/Pull, Offset and Eraser each pick their own way with
   no inference and no indicators. Users learn to trust inference while drawing
   and lose it the moment they push a face.
4. **[#6](https://github.com/integrations-space/BonsaiSketch/issues/6) Construction tools, guides first.** `Ctrl` with the Tape Measure lays
   down a guide, and guide-driven layout is how much of the modelling actually
   gets done. Dimension and Text can produce real IFC annotation through
   Bonsai's `drawing` module rather than throwaway overlay geometry.
5. **[#5](https://github.com/integrations-space/BonsaiSketch/issues/5) Groups and Components.** Conceptually the largest absence — SketchUp
   modelling *is* grouping and instancing. Decide early whether a group is a
   Blender collection, an `IfcGroup`, or an `IfcElementAssembly`; that answer
   shapes every tool built afterwards.
6. **[#8](https://github.com/integrations-space/BonsaiSketch/issues/8) Follow Me**, **[#9](https://github.com/integrations-space/BonsaiSketch/issues/9) camera tools**, **[#10](https://github.com/integrations-space/BonsaiSketch/issues/10) Paint Bucket.** Follow Me is a
   genuinely large build. The camera tools are individually small but
   collectively most of how a SketchUp user moves around a model. Paint Bucket
   needs its IFC question answered first (viewport material on sketch geometry,
   defer to Bonsai for anything with an entity behind it — the same line
   Push/Pull and the Eraser already draw).

Still on the README roadmap and not filed as issues, because they are this
project's own ideas rather than SketchUp parity: live rectangle preview while
dragging, Push/Pull driving Bonsai's parametric depth on typed IFC elements, the
condensed Entity Info panel, and the Instructor panel. Entity Info is worth
pulling forward — it is the panel a SketchUp user checks reflexively, and it is
where the property sets #1 attaches become visible to them.

## 5. Development environment note

The installed extension in Blender's user repository goes stale silently. A
stale copy caused `tools/smoke_test.py` to test old code and die at the keymap
section, which reads as a broken suite rather than a stale install.

Either rebuild and reinstall before running the suite:

```text
blender --command extension build --source-dir bonsaibim_sketch_mode --output-dir dist
blender --command extension install-file --repo user_default --enable dist/*.zip
```

or use the junction described in the README so edits are picked up in place.
Whichever, check the suite is loading what you think: it reports the module path
it imported, and 181 checks is the current full count.
