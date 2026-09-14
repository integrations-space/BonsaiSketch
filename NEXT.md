# What to do next

State as of 2026-08-18. The add-on has been renamed from BonsaiBIM to Bonsai,
which changed every file path and every identifier — that reshapes the merge
order below, so **read section 1 before touching the open PRs**. Two feature PRs
are open and green; eight issues carry the SketchUp gap list.

`next-steps` has diverged from its own remote — **read section 0 before
pushing anything.** Five commits are local and unpushed, two are on the remote
and not local, and three files conflict.

Four of those five landed on 08-18 and are new ground: the Sketch tab could not
reach IFC at all (8b), a text-to-model channel (8c), Claude wired under Sketch
(8d), and what the Wall Tool does when a wall type has no material layers (8e).

Suites are green on Blender 5.0 and 5.2: 253 headless — `smoke_test` 166,
`bonsai_check` 49, `claude_check` 38 — and 102 in the viewport across
`ui_check` 52, `textmodel_check` 35 and `describe_check` 15. 355 in total, up
from 192, and three of the six suites did not exist a fortnight ago.

**Start at section 0.** Nothing else can be published until that is settled.

## 0. `next-steps` has diverged from itself, 2026-08-18

Nothing from 08-18 has been pushed. The branch is `ahead 5, behind 2`, so a
plain `git push` is refused.

On the remote and not local — Push/Pull inference, continued:

| | |
| --- | --- |
| `234a3bc` | Draw the inference dot Push/Pull's header could only describe |
| `64ccd4c` | Let Push/Pull stop level with a sloped plane, not just level with points |

Local and not on the remote:

| | |
| --- | --- |
| `337dd1e` | Add face-plane inference and nested regional push-pull tests |
| `4b6df31` | Give the Sketch tab a way into IFC at all |
| `401c0b2` | Let something other than a mouse drive Sketch Mode |
| `b850072` | Open the sidebar on our tab, not on Transform |
| `101bde8` | Wire Claude under Sketch, so a sentence becomes a building |

`git merge-tree` says three files conflict, and they are two different problems
that should not be conflated:

- **`bonsai_sketch_mode/__init__.py`** — mechanical. Both sides added a
  registration and some preferences; the remote adds `marks.py`, the local
  commits add the sidebar, the Describe panel, and the Anthropic key. Nothing
  disagrees, the edits merely landed in the same place.
- **`bonsai_sketch_mode/ops/pushpull.py` and `tools/smoke_test.py`** — not
  mechanical, and nothing to do with the 08-18 work, which never touched either
  file. This is `337dd1e` against `234a3bc`/`64ccd4c`: *two parallel
  implementations of Push/Pull inference*, developed on two machines. Deciding
  which survives is a design call about that feature, not a merge chore. Read
  both before resolving; taking either side wholesale is likely wrong, since one
  draws the indicator section 8 asks for and the other infers the face plane.

`NEXT.md` auto-merges despite both sides editing it.

Order, then: settle the Push/Pull question first, because it is the one that
needs judgement. `__init__.py` can be resolved by keeping both blocks.

## 1. Merge order, now that the rename has landed

The rename (`8367949`, on `next-steps` / [#11](https://github.com/integrations-space/BonsaiSketch/pull/11)) moved
`bonsaibim_sketch_mode/` to `bonsai_sketch_mode/` and renamed the extension id,
the operator idnames, the `BONSAI_SKETCH_OT_` class prefixes and the
sketch-geometry marker. Both feature PRs were written before it.

| PR | Head | What it is | Files under the old path |
| --- | --- | --- | --- |
| [#1](https://github.com/integrations-space/BonsaiSketch/pull/1) | `116046b` | Model Content Requirements on creation, Offset, Eraser, and four review fixes | 22 |
| [#2](https://github.com/integrations-space/BonsaiSketch/pull/2) | `20663d4` | Claim `A`, `C`, `G` so they stop running Blender's operators | 2 |

GitHub still reports both mergeable, because both are measured against `main`
and the rename is not on `main` yet. That is misleading.

**Merge #1, then #2, then the rename last.** Re-running the rename over a larger
tree is mechanical; resolving the rename inside two feature branches is not.

The trap if the rename goes first: #1 *adds* thirteen files —
`psets.py`, `ops/eraser.py`, `ops/offset.py`, `data/delivery_classes.json` and
nine `data/delivery/*.json`. Additions do not conflict. Git would merge them
happily into a `bonsaibim_sketch_mode/` directory it recreates alongside the
renamed one, and the suite would still pass while the tree carried both names.
No conflict marker would ever appear. There are also about fifty old-name
occurrences inside #1's diff and two inside #2's, in headers and idnames that
would come back silently.

So: land #1 and #2 on `main` first, then rebase `next-steps` onto `main` and
re-run the sweep across everything, protecting the `bonsaibim.org` links:

```text
grep -rli "bonsaibim" --exclude-dir=.git . | while read f; do
  sed -i 's/bonsaibim\.org/@@KEEP@@/g; s/BonsaiBIM/Bonsai/g; s/BONSAIBIM/BONSAI/g; s/bonsaibim/bonsai/g; s/@@KEEP@@/bonsaibim.org/g' "$f"
done
```

Then check that every changed line contains `bonsai` and nothing else moved:

```text
git diff -M --unified=0 | grep "^[+-]" | grep -v "^+++\|^---" | grep -vi bonsai
```

PRs #1 and #2 still conflict with each other exactly as before — three files, all
the same disagreement about which keys are deliberately unbound. #2 was written
against a `main` where Offset and Eraser did not exist, so its wording lists them
as unbuilt; #1 builds them. Resolving #2 after #1 lands:

- `bonsai_sketch_mode/keyconfig.py` — take #2's `_su_bindings` docstring, then
  drop `Offset,` from its list of tools still to build. `CLAIMED_KEYS` and
  `UNBUILT_KEYS` need no change: `F` and `E` are already claimed on both sides,
  and neither is in `UNBUILT_KEYS`.
- `tools/smoke_test.py` — take #2's block wholesale. It reads
  `keyconfig.UNBUILT_KEYS` from the module rather than repeating a literal, so
  it adjusts itself.
- `bonsai_sketch_mode/README.md` — take #2's paragraph, but open it with
  ``` `B`, `A`, `C` and `G` ``` instead of ``` `F`, `B`, `E`, `A`, `C` and `G` ```,
  since `F` and `E` are bound once #1 is in.

One loose end the rename created, now half closed. README Step 3 named
`bonsai_sketch_mode-0.3.0.zip`, a file no release carries — the published v0.3.0
asset is still `bonsaibim_sketch_mode-0.3.0.zip`. Step 3 no longer hardcodes a
version, and both READMEs now explain what the id change does to an existing
install: it arrives *beside* the old one rather than replacing it, with the old
entry still switched on pointing at nothing and the new one switched off.

What is left is the release itself. A version bump and a fresh build, not a
re-uploaded asset, with the id change and the remove-the-old-one step called out
in the notes. Until that ships, the install instructions describe a file nobody
can download.

## 2. Rebind Select All, deliberately

PR #2 strips Blender's `A` (Select All) as a side effect of claiming the key for
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

## 4. Done: configurable canvas colours

Built in `bb97923`. Sky, ground, background, grid and the three axes are
preference fields on `BONSAI_SKETCH_MODE_Preferences`, grouped as SketchUp
groups them, repainting live while the picker is open, with a Reset All. In
`056278b` the canvas also stopped waiting to be switched on: it goes up with the
Sketch tab, and `canvas_on_setup` turns that off.

Kept here because three facts cost time to establish and would cost it again:

- Axis colours are on `preferences.themes[0].user_interface.axis_x` / `_y` / `_z`.
  **Not** `view_3d`, which carries only `grid`, `wire` and `wire_edit`.
- Blender stores theme colours as **bytes**. Writing `0.1` reads back
  `26/255 = 0.10196`, so any comparison needs a tolerance of a full 8-bit step --
  `theme.SAME_COLOUR`. The shipped defaults sit near byte boundaries, which hid
  this until a user-chosen colour made `looks_applied()` report the canvas as
  off while it was plainly on.
- Blender **auto-saves preferences** by default, and the theme is a preference.
  The canvas therefore persists across sessions and every file until restored.
  That also broke the theme suite, which had been asserting a clean starting
  theme against whatever the previous run left behind; it now builds its own
  baseline.

Grid, wire and axis colours are global theme values with no per-workspace
override, so they restyle every viewport in Blender. Sky and ground need not
be -- see section 5.

The floor grid's *visibility* is the exception, and is a plain toggle:
`show_floor_grid` drives `overlay.show_floor`, an overlay rather than a theme
value, so it is genuinely per-viewport and scoped to the Sketch tab. Visibility
only -- Blender's grid snapping is a scene setting and keeps working with the
grid hidden.

SketchUp's magenta parallel/perpendicular and cyan tangent are *inference*
colours. There is no inference indicator to colour yet -- that is issue
[#7](https://github.com/integrations-space/BonsaiSketch/issues/7) below -- so
they were deliberately left out rather than shipped as dead preferences.

## 5. In progress: a real horizon, drawn rather than themed

`ground.py` exists, is wired to a `show_ground` preference, and **defaults to
off because it does not work yet**. Start here tomorrow: it is the closest thing
to finished and the most visible.

Why it exists at all. The theme gradient is not what SketchUp looks like, and
the difference is structural rather than a matter of colour -- the fade is
screen-space, so it does not move as you orbit, and there is no opaque ground
and therefore no horizon. Our colours are already SketchUp's own: sky
`(163, 190, 218)`, ground `(224, 221, 211)`.

Three routes were tried. Do not re-litigate the first two.

**The scene world does not work.** A world with a constant-interpolation ramp is
the obvious way to a hard, world-locked horizon scoped to the tab. In Solid
shading Blender draws the world's flat viewport colour and never evaluates the
node tree. Proved by giving the world a magenta fallback and watching the
viewport turn entirely magenta.

**A ground-plane object works but is wrong.** It would be geometry in an IFC
project -- selectable, movable, exportable.

**A GPU draw handler is the right shape, and half works.** The quad draws. That
much is settled, and it is why `ground.py` is committed rather than a note
saying it cannot be done. What it does not do is compose with the rest of the
viewport:

- In `POST_VIEW` the quad paints opaquely but does not respect the depth
  buffer. It covers the floor grid, and geometry that should be in front of it
  gets painted over. `depth_mask_set(False)` changes nothing, so the mask is
  not the problem.
- In `PRE_VIEW` the quad is drawn and then erased -- Blender clears the
  background after the handler runs, so nothing survives to the frame.

Next thing to try: `POST_VIEW` is probably the right pass and the depth state
needs setting differently, or this belongs in an overlay pass rather than
either. Worth reading how Bonsai's own viewport decorators bind depth, since
they solve the same problem in the same Blender.

Screenshots are the only honest way to check this, and getting one of the
*Sketch* tab is fiddly: workspace assignment is deferred, and Bonsai's own
load handler can take the window back. `scratchpad/shot2.py` forces the switch
and retries until `window.workspace.name` sticks before it captures.

The prize is worth it. With the ground drawn and the sky as the viewport's own
flat background colour, sky and ground become per-workspace and the canvas stops
needing the global theme change at all -- section 4's warning would shrink to
just the grid, wire and axis colours that genuinely have nowhere else to live.

## 6. Built: CAD import — DXF native, DWG through ODA, healed and stood up

File > Import > CAD Drawing now exists. The open question above got the
answer the drawing tools already embody: imported linework is **sketch
geometry**, one object per layer named `<file>/<layer>` and carrying our
marker — so "which layers matter" is ordinary object selection, every
existing tool works on what arrives, and Assign IFC Class gives it meaning
when a shape is right. The import chains three steps, each an adjustable
unit-aware value in the redo panel, so a plan can be re-cut without
re-importing:

1. **Heal** (`heal.py`, pure Python): endpoints within *Weld* are one point
   and chains join across them; an open chain whose free ends are within
   *Close Gaps Up To* is enclosed — the n-sided polygon the drafter saw but
   the file only almost drew. Wider gaps stay open: a doorway is not a
   drafting error. Everything is counted and reported — joined, bridged,
   already closed, left open.
2. **Face**: closed loops become n-gon faces. A healed loop that crosses
   itself stays as edges and is counted, not guessed at.
3. **Extrude**: a non-zero height stands every faced loop up into a solid —
   room outlines become massing in one import. The suite asserts volumes on
   the results, per the membrane lesson.

Per-layer heights come after the import: **Object > Stand Up Outlines** runs
the same heal-face-extrude on the *selected* sketch layers with its own
height, weld and gap — one run, one height, selection says which layers, so
WALLS can stand 3m and PARTITIONS 2.4m. Standing geometry is declined, not
doubled: the operator exists to be re-run with different numbers, and only
flat sketch objects carrying our marker are touched.

The parser (`dxf.py`, pure Python, no dependency) reads the drafting subset:
LINE, LWPOLYLINE with bulges (positive bulge is counter-clockwise — the spec's
sign, pinned by a check), old-style POLYLINE, ARC, CIRCLE at SketchUp's 24
chords, layer names, and `$INSUNITS` scaling to metres. Entities outside the
subset are counted and reported, never silently dropped. `ezdxf` was
deliberately not taken on: it would ship as a wheel and track Blender's
Python, the needed subset is a few hundred lines, and Blender's own DXF
importer is a separate extension now — nothing bundled to lean on.

- **DWG** — reads through ODA File Converter (free, opendesign.com), pointed
  at by a preference; without it the import says exactly what to install.
  The conversion path needs a machine with the converter on it — untested by
  CI, worth one manual run.
- **SKP** — unchanged: C++ SDK, licence-restricted, no Python binding. Not a
  weekend job.

Still open here: the healed-but-unfaceable report could offer the loop for
inspection (it is findable today — the object with edges and no faces), and
arcs import as chords, so a healed arc-walled room extrudes faceted.

## 7. Agreed: wire the IFC+SG requirements to something

[`requirements.py`](bonsai_sketch_mode/requirements.py) is complete and tested —
21 elements, 853 parameters, ordered stages, class mapping with base-class
fallback, stated reasons for unmapped elements, review notes on broad mappings.
Fifteen checks cover it.

It is also connected to nothing. `requirements` is imported at
[`__init__.py:35`](bonsai_sketch_mode/__init__.py#L35) and read only by
`tools/smoke_test.py`. No panel shows it, and nothing writes those parameters
onto an element.

PR #1 closes half of this: it attaches the required parameters to every element
as it is created, via `psets.py`, and adds the per-typology Project Delivery
data under `data/delivery/`. So **merge #1 before planning any of this**, or the
same work gets done twice in two different shapes.

What remains after #1 lands is the read side — a user who has parameters
attached still cannot see or fill them without going into Bonsai's own property
panels. The condensed Entity Info panel is the natural home, and it is already
on the README roadmap. It is the panel a SketchUp user checks reflexively, and
it is where the property sets #1 attaches become visible. Worth pulling forward
ahead of the gap-list items below.

## 8. The SketchUp gap list

Eleven of SketchUp's roughly thirty tools exist. The gaps are filed as issues,
each naming the Bonsai operator or module that backs it where one exists.

Ordered by value per unit of work, not by size:

1. **[#3](https://github.com/integrations-space/BonsaiSketch/issues/3) Curve tools — Circle (`C`), Arc (`A`).** The largest hole in the toolset:
   nothing curved can be drawn at all. Cheapest real feature on this list,
   because Bonsai already has the geometry — `bim.add_ifccircle`,
   `bim.cad_arc_from_2_points`, `bim.cad_arc_from_3_points`. The work is modal
   UX over proven operators. Also unblocks the two keys #2 just silenced.
2. **[#4](https://github.com/integrations-space/BonsaiSketch/issues/4) Modifier and double-click behaviours.** *Push/Pull's two are done*
   (section 10); the rest of the vocabulary is not. Still missing:
   `Ctrl`-drag on Move and Rotate to copy, then `3x` or `/3` for arrays
   (Bonsai has `model/array.py`); `Ctrl` on the Eraser to soften and `Shift`
   to hide; `Ctrl` with the Tape Measure to lay a guide, which is also item 4
   below; double-click Select for a face and its edges, triple for everything
   connected; arrow keys to lock an axis mid-tool. For a project whose premise
   is familiar muscle memory this is felt more than any single missing tool,
   and each piece is independent of the others.
3. **[#7](https://github.com/integrations-space/BonsaiSketch/issues/7) Inference in two of six tools.** *Push/Pull now infers* (section 10),
   which leaves Offset and Eraser — both of which live in #1 and so cannot be
   fixed until it lands. Neither has indicators, and neither does Push/Pull:
   it reports an alignment as `(aligned)` in the header rather than drawing
   anything. Section 4's colour work stops short of SketchUp's magenta and
   cyan until inference is drawn rather than described.
4. **[#6](https://github.com/integrations-space/BonsaiSketch/issues/6) Construction tools, guides first.** `Ctrl` with the Tape Measure lays
   down a guide, and guide-driven layout is how much of the modelling actually
   gets done. Dimension and Text can produce real IFC annotation through
   Bonsai's `drawing` module rather than throwaway overlay geometry.
5. **[#5](https://github.com/integrations-space/BonsaiSketch/issues/5) Groups and Components.** Conceptually the largest absence — SketchUp
   modelling *is* grouping and instancing. Decide early whether a group is a
   Blender collection, an `IfcGroup`, or an `IfcElementAssembly`; that answer
   shapes every tool built afterwards, and section 6's import question with it.
6. **[#8](https://github.com/integrations-space/BonsaiSketch/issues/8) Follow Me**, **[#9](https://github.com/integrations-space/BonsaiSketch/issues/9) camera tools**, **[#10](https://github.com/integrations-space/BonsaiSketch/issues/10) Paint Bucket.** Follow Me is a
   genuinely large build. The camera tools are individually small but
   collectively most of how a SketchUp user moves around a model. Paint Bucket
   needs its IFC question answered first (viewport material on sketch geometry,
   defer to Bonsai for anything with an entity behind it — the same line
   Push/Pull and the Eraser already draw).

Still on the README roadmap and not filed as issues, because they are this
project's own ideas rather than SketchUp parity: live rectangle preview while
dragging, Push/Pull driving Bonsai's parametric depth on typed IFC elements, the
condensed Entity Info panel (see section 7), and the Instructor panel.

## 8b. Fixed, 2026-08-18: the Sketch tab had no route into IFC

Reported as "difficulties inserting walls, or simple IFC content". Nothing was
broken. `tools/bonsai_check.py` walked Bonsai's whole authoring path headlessly
and passed 38/38 -- project, types, occurrences, voids, assign class. The fault
was that none of it was reachable from the tab the user was sitting on.

The measurements, taken against Bonsai 0.8.5:

- The Sketch workspace is exactly one `VIEW_3D` area. No Properties editor, no
  Outliner. That is deliberate and still right.
- Bonsai's UI is 202 `PROPERTIES` panels against 38 `VIEW_3D` ones, and most of
  the latter are gizmos. The two that matter here are both Properties panels:
  `BIM_PT_new_project_wizard` (`bl_context = "scene"`) and `BIM_PT_class`
  (`bl_context = "object"`).
- Bonsai adds nothing to the top bar or the File menu, so there was no second
  route either.
- The workspace does not filter tools by owner, so all thirteen BIM tools sit
  in the Sketch toolbar. They activate fine. They then draw `No IFC Project`
  and return (`model/workspace.py:478`), and nothing on the tab could create
  the project that would unblock them.

So: a gated tool that looks identical to a broken one, and a README step 5 that
resolved to "leave this tab".

`sidebar.py` is the fix -- the two missing buttons, and deliberately nothing
else. New IFC Project when there is none; class dropdown and Assign when there
is one and a sketch is selected. The workspace now opens the sidebar at append
time, behind an **IFC sidebar** preference for anyone who wants the bare
viewport back.

One trap found while building it and closed: Bonsai's class list is filtered by
`ifc_product`, which defaults to `IfcElementType`. A panel showing only the
class would happily assign a *construction type* to a drawn shape. So Assign
goes through `bonsai_sketch_mode.assign_class`, which pins the product to
`IfcElement` first -- Bonsai's own update callback then maps `IfcWallType` to
`IfcWall`. `bonsai_check.py` asserts that mapping.

Checked, not assumed, along the way: Bonsai's tool hotkeys are all
Shift/Ctrl/Alt-modified, so they do **not** collide with the Sketch tab's bare
letter keys. The `Sketch` keyconfig does lack the add-on tool keymaps that live
in `Blender`/`Blender addon` (95 tool keymaps against 129), but Blender resolves
tools through the merged user config, so both our tools and Bonsai's bind
correctly with `Sketch` active. Neither was the bug.

Still true, and still the next question: nothing here creates walls *as walls*.
Draw-then-assign gives an `IfcWall` with a mesh body, not a parametric wall with
material layers. Bonsai's own Wall tool in the shared toolbar does that, and now
that a project can be created from this tab it works -- verified placing an
occurrence from the Sketch viewport, landing in `IfcBuildingStorey/My Storey`.

## 8c. New, 2026-08-18: text to model, as a package under Sketch Mode

Asked directly: is Claude wired into Bonsai, and if not can Sketch set up the
wire. Checked rather than recalled -- Bonsai 0.8.5 contains no reference to
anthropic, claude, openai, mcp or langchain. Nothing is wired. There is a
precedent for the transport though: Bonsai already runs websocket servers in
process for its own web UI (`bim.connect_websocket_server`, `IfcTesterWebSocketServer`).

More usefully, our own IDD stack already declares the counterpart. `list_adapters`
returns a `bonsai_adapter` -- "BonsaiBIM Adapter", transport `local-service`,
capabilities `context-extraction`, `action-execution`, `headless`,
`geometry-write`, handles `*` -- and its status is **offline**. The contract
exists. What is missing is the thing on the Blender end for it to talk to.

### Why it is a package, not a module

Agreed explicitly, and worth writing down because it constrains what goes in it.
`bonsai_sketch_mode/textmodel/` is a self-contained subpackage with `register`
and `unregister` as its whole surface. Nothing outside it imports `server` or
`commands`.

- It is a *second way in*, for a caller that is not a person at a mouse.
  Everything else in this add-on is interaction; this is not, and mixing the two
  would leave the drawing tools carrying a socket they never use.
- It is off unless switched on, bound to loopback, and every request carries a
  per-session token. A socket that can rewrite the model is not something to
  open because an add-on happens to be installed.
- It is a candidate for extraction. Wrapping it as the IDD `bonsai_adapter`
  should be a wrapping job, not a rewrite. Keeping the boundary sharp now is
  what buys that.
- No model, no prompt, no API key lives here. This is not Claude; it is the
  thing Claude talks *to*. Governance -- propose, critique, human gate -- belongs
  to the adapter, and building it here would mean building it twice.

### What it does

Nine verbs, each a thin checked shell over something a user could do by hand:
`ping`, `describe`, `list_elements`, `create_project`, `create_type`,
`add_walls`, `sketch_polyline`, `push_pull`, `assign_class`.

`add_walls` is the one that makes this worth having. It reaches
`DumbWallGenerator` through the bridge and drives its POLYLINE insertion, which
is the non-modal half of the wall tool: real walls with material layers and
thickness, not a mesh box called a wall. Verified from a terminal against a live
Blender -- an L-shaped plan of six points became six parametric `IfcWall`s at the
right lengths, and a sketched slab became an `IfcSlab`.

The rest is the sketch-then-name path the product already believes in, which is
what to reach for when Bonsai has no parametric generator for the shape.

### Two things that shaped the code

- **Blender's API is single threaded.** The socket thread never touches `bpy`.
  It queues, a `bpy.app.timers` pump drains the queue on the main thread, and
  the socket thread wakes to write the reply. This is also why the channel does
  not work under `-b`: no event loop, so no pump. `textmodel_check.py` needs a
  GUI for that reason and says so.
- **`obj.dimensions` lags the depsgraph.** `push_pull` reported a height of zero
  in a GUI session while reading correctly headless -- the reply carried the size
  from *before* the push. A `view_layer.update()` fixes it, and the check now
  pins the value rather than only the `ok` flag. Worth remembering: the headless
  suites cannot see this class of bug at all.

### Not done

The channel has no undo verb, no delete, and no way to edit an element once
placed -- an agent can build but not revise. It also writes immediately, with no
proposal step: that is the deliberate line between this and the adapter, and it
is why running the governed path is still the better default for anything real.

## 8d. New, 2026-08-18: Claude wired under Sketch

Agreed: wire Claude in directly, so a user types a sentence on the Sketch tab
and gets a building. The socket channel (8c) is the thing Claude talks *to*;
this is the half that does the talking, and it lives in the same package.

`Describe` panel in the Sketch sidebar -> worker thread -> Messages API with the
nine verbs as tools -> tool-use loop -> verbs on the main thread. Verified from
"a 5 by 5 room, 2.7m high" to four parametric `IfcWall`s at 5.00m x 2.70m.

### Raw HTTP, and why that is not laziness

The Anthropic Python SDK is the right default in a Python project. It is the
wrong default here, for a reason this repo already documented: the manifest pins
our Blender range because *Bonsai* ships compiled wheels that must match the host
Python. The SDK brings `pydantic-core` and `jiter`, both compiled. Vendoring it
would re-import exactly the fragility that comment exists to warn about, to make
one kind of POST request.

So `urllib.request`, and `claude.py` is the only module that would need
rewriting if that ever changes. Stated here because it is a deliberate
divergence from the house rule, not an oversight.

### What the API actually wants (checked, not recalled)

- `claude-opus-5`, thinking adaptive and on by default.
- `budget_tokens` is **removed** -- 400 on Opus 5. So are `temperature`,
  `top_p`, `top_k`. `claude_check.py` asserts none of them are ever sent,
  because they are exactly the kind of thing that gets re-added from memory.
- `stop_reason: "refusal"` returns **HTTP 200**. Read it before reading
  `content`, or a decline reports as a successful build of nothing.
- Assistant prefill is removed too. Nothing here used it; worth not adding.

### Three things that shaped the code

- **One user message per turn.** Every `tool_result` for a turn goes back in a
  single user message. Splitting them teaches the model to stop asking for more
  than one thing at a time, and it is invisible from the outside -- so the test
  asserts on what went *out*, not just what came back.
- **A failed verb is a result, not an exception.** "no IfcWallType exists" comes
  back as `is_error` and the model creates one. Raising instead would turn every
  recoverable mistake into a dead run.
- **The modal operator drives the pump itself.** A modal owns Blender's event
  loop and `bpy.app.timers` is not promised a slot underneath one. The worker
  waits on `mainthread.submit` for every verb, so without `pump_once()` in the
  modal's TIMER handler, every build would hang to its timeout. `describe_check.py`
  exists specifically to catch that, and it needs a GUI to do so.

`mainthread.py` came out of `server.py` in the process -- both halves need the
same trick, and two copies of it would have been one too many. It is reference
counted, so closing the socket cannot strand a Claude request mid-flight.

### The line this does not cross

There is still no proposal step, no critique and no human gate: the panel writes
straight to the model. That remains the difference between this and the IDD
`bonsai_adapter`, and it is the reason the governed path is still the right
default for anything that matters. `Ctrl+Z` is the whole safety story here, and
the README says so.

Also absent: streaming (so a long build shows "thinking" and no detail until it
finishes), any way to revise what was built rather than add to it, and prompt
caching -- the tool list is deliberately order-stable so caching can be switched
on later without a cache-miss-per-call, but nothing sets `cache_control` yet.

## 8e. Diagnosed, not ours, 2026-08-18: the Wall Tool's two personalities

Reported as "when I click on screen, a panel appears immediately, I cannot
select the second point to determine the length?" -- clicking with the Wall
Tool produced an **Add Type Occurrence** dialog offering "No Geometry", instead
of letting a wall run be drawn.

Two separate things, and only the second is interesting.

**The Wall Tool does not draw on click.** Its `bl_keymap` binds LEFTMOUSE to
`view3d.select`. The polyline drawer only starts from **Add** (or `Shift+A`),
and once it is running, each click places a *point* -- nothing becomes a wall
until the run is confirmed with `Enter`, `Numpad Enter` or right-click
(`wall.py:700`). Points on screen and no geometry is the expected midpoint of
that interaction, not a failure.

**`Add` does completely different things depending on the wall type.** From
`workspace.py:1183`:

```python
if tool.Model.get_usage_type(relating_type) == "LAYER2":
    return bpy.ops.bim.draw_polyline_wall(...)   # click points, Enter
...
return bpy.ops.bim.draw_occurrence(...)          # single point + a dialog
```

and `get_usage_type` returns `LAYER2` only when the type carries an
`IfcMaterialLayerSet`. A wall type without one has no layer geometry to sweep
along a path, so it falls through to generic occurrence placement. There is no
second point to pick because that code path never runs.

### Is it a bug

Not in the logic -- the fallback is the correct behaviour for a type that
genuinely has no layers. It is a real usability defect: the same button on the
same tool with a same-looking type silently swaps the entire interaction model,
and nothing in the tool header says which one is in force. "No Geometry" names
the symptom and never the cause. Worth filing upstream as *"Add silently
changes interaction model when the wall type has no material layer set"*.

Not ours either, and that was checked rather than assumed. Both normal creation
routes produce a layered type in a clean project:

```text
Quick Create (add_default_type)   usage=LAYER2   material=IfcMaterialLayerSet
Create New   (add_element)        usage=LAYER2   material=IfcMaterialLayerSet
```

`commands.create_type` calls the first of those, and the sidebar's Assign pins
the product to an occurrence so it cannot create a type at all. A layerless
wall type has to have come from a Type Manager template or from a class
assigned to mesh geometry through Bonsai's own panel.

To tell them apart:

```python
import bonsai.tool as tool, ifcopenshell.util.element as ue
for t in tool.Ifc.get().by_type("IfcWallType"):
    print(t.Name, tool.Model.get_usage_type(t), ue.get_material(t, should_inherit=False))
```

`bpy.ops.bim.add_default_type(ifc_element_type="IfcWallType")` makes a good one.
Note that Quick Create will not reappear in the tool header to offer this --
it only shows while *no* wall types exist.

### Agreed follow-up

The fair criticism of our side is that the Sketch sidebar was on screen
throughout and said nothing useful. The IFC panel should warn when the selected
wall type has no material layers, naming the cause and offering
`add_default_type`, so this is read rather than discovered through a mystery
dialog. Small -- roughly twenty lines and a check. Not yet built.

## 9. Development environment note

The installed extension in Blender's user repository goes stale silently, and it
has now caused trouble twice. A stale copy made `tools/smoke_test.py` test old
code and die at the keymap section, which reads as a broken suite rather than a
stale install. Then the rename left Blender 5.0's junction dangling and Blender
5.2 holding a real zip install of #1's branch under the old id — Blender keys
extensions by id, so it would never have been upgraded in place.

Current state, after the rename:

- **Blender 5.0** — junction to `bonsai_sketch_mode`, repointed. 253 headless
  checks pass, re-run on 2026-08-18 including the two new suites. Python 3.11
  there against 3.13 on 5.2, which is the reason to keep running it: it is the
  only check that the 08-18 code is not quietly 3.13-only.
- **Blender 5.2 LTS** — uninstalled and reinstalled on 2026-07-28 from
  `blender-5.2.0-windows-x64.msi` (build 2026-07-14), replacing the stale zip
  install with a junction. 253 headless and 102 viewport checks pass, re-run on
  2026-08-18. Bonsai survived the reinstall, because extensions live in the user
  config directory rather than under Program Files, so the 0.8.5 pairing is
  intact.
- **Blender 4.2** — installed but below `blender_version_min = "5.0.0"`, so it
  is not a target.

That keeps `blender_manifest.toml`'s claim of "5.0 and 5.2 tested, 5.1 assumed"
honest, and section 1's claim that both PRs were run against 5.2 LTS with Bonsai
0.8.5 re-verifiable. CI still only runs 5.0, so 5.2 remains a local-only check —
run it by hand before trusting `blender_version_max`.

The 5.2 suite reports `running against Bonsai 0.8.5, built against 0.8.4 --
everything below is therefore also an untested-version report`. That guard is
working as designed, not a failure, but it does mean every 5.2 result carries
that caveat until the built-against version is raised.

Prefer the junction from the README over a zip install, on every version:

```text
mklink /J "%APPDATA%\Blender Foundation\Blender\5.0\extensions\user_default\bonsai_sketch_mode" "C:\2026_bonsai\bonsai_sketch_mode"
```

A junction cannot go stale. The packaged-zip path is still covered — CI builds,
validates, `install-file`s and then runs the suite against the installed zip, so
nothing is lost by not doing that locally.

Whichever route, check the suite is loading what you think: it reports the module
path it imported. On `main` today that is 111 headless checks plus 27 viewport
checks; on `next-steps` it is 253 and 102. Any older figure in this file's
history — 160/32, or the 181 quoted two versions ago against #1's branch —
describes none of them.

Three of the six suites are new as of 08-18, and where they can run differs:

| Suite | Needs | Why |
| --- | --- | --- |
| `smoke_test` 166 | headless | |
| `bonsai_check` 49 | headless | Bonsai's authoring path, which `smoke_test` deliberately never touches |
| `claude_check` 38 | headless | drives its own main-thread pump, so no event loop is needed |
| `ui_check` 52 | GUI | tool activation and the sidebar need a real region |
| `textmodel_check` 35 | GUI | the socket's pump is a `bpy.app.timers` callback, and `-b` has no event loop to fire it |
| `describe_check` 15 | GUI | the Describe panel is a modal operator |

CI runs 5.0 only and cannot run the three GUI suites at all, so half the checks
are local-only. Run them by hand before trusting anything about the viewport.

One trap the junction does not cover: enabling an add-on is a *saved preference*,
keyed by module path. The rename changed that path, so both Blenders went on
listing `bl_ext.user_default.bonsaibim_sketch_mode` as enabled — a module that no
longer exists — while the renamed add-on sat discoverable but switched off. The
suites hid it completely, because both enable the add-on themselves at runtime.
Opening the GUI would have shown no Sketch tab and a "not loaded" line in the
console. Fixed on 5.0 and 5.2 on 2026-07-28: dead entry dropped, real one
enabled, `wm.save_userpref()`. Worth remembering the next time an id changes —
a green suite says nothing about what the GUI will do.

A fresh Blender also has no Sketch workspace in its startup file, since the
workspace is appended by the operator rather than created on enable. On 5.2 the
tab therefore has to be added once from Preferences > Add-ons > Bonsai Sketch
Mode. 5.0 already carries it in its saved startup file.

The same trap had already fired once, years-old-looking but self-inflicted.
`bl_ext.user_default.bonsai_sketchup` sat enabled on 5.0, logging a dead-module
line on every launch. It looked like some unrelated add-on, but it came from
this project: the initial scaffold's README (`c8d1cc4`) gave a `mklink` and an
`addon_enable` against `bonsai_sketchup`, a name left over from before the
repository existed. The next commit corrected the docs — by which point Blender
had the enable saved, where no later doc fix could reach it. Cleared on
2026-07-28.

Both Blenders now start with no "not loaded" lines and list exactly
`bl_ext.blender_org.bonsai` and `bl_ext.user_default.bonsai_sketch_mode`. The
lesson generalises past this add-on: a wrong module path in an instruction
someone follows once outlives every correction made afterwards, because it lands
in their preferences rather than in the repository.

## 10. Push/Pull, 2026-08-02

Three commits, all on `next-steps`, closing the Push/Pull half of #4 and the
Push/Pull third of #7.

**`1fc2a71` — regional push.** A face divided by drawn lines can be pushed one
region at a time: a step or a notch is now a line and a drag. What the face
itself does had only two answers, move or keep-as-cap, and needs three. A
region of a *sheet* keeps it — nothing is behind it. A region of a *solid's*
surface must not: the interior is behind it, and keeping it seals a membrane
inside the result. `push_mode` names all three; `CUT` is the new one.

The membrane was invisible from outside. Face counts, vertex heights and
manifoldness were all satisfied by the wrong shape — only the volume gave it
away, 14 where a 2x2x3 box with one half of its top raised by 2 should measure
16. **Assert volumes, not just topology**, on anything that closes a shell.

**`21bfa39` — `Ctrl` and double-click.** `Ctrl` stacks a new solid on the
face; double-click repeats the last distance. Two traps, both worth keeping in
mind for the modifiers still to build:

- `Ctrl` leaves the shell non-manifold *on purpose*, so "which way is out" has
  no answer and `recalc_face_normals` must not run — left in, it turned the
  outer surface of a box inside out on an inward push.
- Blender only falls a double click back to a press if nothing handled it, and
  a modal handler that returns `RUNNING_MODAL` has. A double click with nothing
  to repeat therefore has to arm the click itself or the click vanishes.

Telling a drag from a click was also wrong, and had been since before either
modifier: the test was "has the extrusion become non-zero", where zero means
`1e-9`, so any tremor counted and the first click's release confirmed a sliver.
It now uses Blender's own `drag_threshold_mouse`, in pixels.

**`81be34e` — inference.** Push/Pull stops where geometry already is, and says
`(aligned)` in the header while it is held there. Candidates are the distances
that bring the face level with an existing point, read from every visible mesh
once as the push begins rather than per mouse move; anything past
`VERTEX_BUDGET` contributes its bounding box instead. Choosing happens in
pixels, not metres — a metre tolerance is a different size at every zoom — and
only the two candidates bracketing the drag can win, so it stays cheap however
large the model.

### What this leaves

- **The indicator exists now, for Push/Pull.** `marks.py` draws the inference
  dot at the snapped point — `POST_PIXEL`, deliberately: the dot is a
  screen-space cue, the same seven pixels at every zoom, and 2D drawing after
  the frame has no depth buffer to negotiate with, which is exactly the
  negotiation that has `ground.py` unfinished. Its colour is
  `inference_colour`, grouped with the canvas colours and covered by Reset
  All, defaulting to SketchUp's on-point green. Whether the dot lands where
  the eye expects needs a viewport — headless pins the lifecycle, the
  arithmetic and the colour plumbing. The drawing tools still have no marks
  of their own (their snapping is Bonsai's, which draws its own indicators),
  so #7's mark work continues with Offset and Eraser when they land.
- **Offset and Eraser still have no inference**, and cannot get it here: both
  live in #1. Their inference should reuse `axis_offsets` and `bracketing`
  from `ops/pushpull.py`, which are pure functions for that reason. If a third
  caller appears they should move to their own module.
- **Planes snap now; edges still reduce to their endpoints.** The point pass
  gained a plane pass — `plane_offsets` and `inference_planes`, same shape as
  the pair it joins: gathered once at push start, deduplicated so a
  tessellated roof is one plane, reduced to scalar offsets, merged into the
  same candidate list, chosen in pixels. The drag stops where a *corner* of
  the moving face touches a sloped plane, near corner or far, since a rigidly
  travelling face can never become coplanar with a slope — it can only touch
  it, and it touches corner-first. A sloped *edge* still contributes only its
  endpoints: between them it crosses the moving plane continuously, so there
  is no distinguished distance to offer.
- **The modal is still untested by machine.** Both suites cover the geometry
  and the projection under it; placing points and dragging a face needs a
  human. Worth a pass by hand before this branch merges — particularly the
  double-click, whose timing no headless check can reach.

### Not started, and asked about on 08-02

**Booleans — union, subtract, trim, intersect — do not exist**, are not filed
as an issue, and are not on the roadmap. Nor is shell/solidify. Worth knowing
that SketchUp's Solid Tools are Pro-only: free SketchUp gets the same results
by intersecting geometry and erasing, so the absence tracks the thing this
add-on is imitating rather than being an oversight. `CUT` above is the nearest
thing that exists, and it does step-and-notch subtraction on a single mesh
without a boolean anywhere.

**Offset** is written but unmerged, in #1, under the old path — so it needs
section 1's rename sweep before it can land.
