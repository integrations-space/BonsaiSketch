"""Generate data/workspace.blend containing the "Sketch" workspace.

Run with:
    blender --factory-startup --python tools/gen_workspace.py -- <out.blend>

Note there is no `-b`. This needs a GUI session, and that is the whole trick.

SketchUp puts one large viewport on screen and nothing else: no outliner, no
properties editor, no timeline. Blender's "Layout" carries all three, and for
someone who came here to draw a wall they are the clutter that makes Blender
feel like Blender. So the Sketch workspace is joined down to a single viewport.

Why this took three attempts
----------------------------
Blender exposes no data-level way to remove an area; it has to be done with an
operator, and the operators appear not to work:

- `screen.area_close` hangs until the process is killed, headless or GUI.
- `screen.screen_full_area` runs, but does not build a one-area screen -- it
  triggers the *temporary fullscreen overlay*, which hides the workspace
  switcher and shows an empty viewport. 0.2.0 shipped that. It was a real bug.
- `screen.area_join` returns FINISHED under `-b` while the area list *grows*.

The common cause is that screen surgery is applied by Blender's event loop, not
by the operator call. Under `-b` there is no loop, so nothing is ever applied
and repeated calls pile up unresolved areas. In a GUI session there is a loop,
but calling the operators back-to-back inside one callback never yields to it,
which is what made `area_close` look like a deadlock.

So: a GUI session, and exactly one join per timer tick, each returning control
to Blender before the next. Then the operators behave.

bpy.data.libraries.write() does NOT persist WorkSpace datablocks -- it silently
produces a file with no workspaces, which makes workspace.append_activate()
return CANCELLED. Bonsai's own data/workspace.blend is a fully saved .blend
containing every workspace, so we do the same: build ours, then
save_as_mainfile. append_activate(idname=...) picks out just the one it wants.
"""

import os
import tempfile
import sys
import traceback

import bpy
from mathutils import Vector

OUT = sys.argv[-1] if "--" in sys.argv else "workspace.blend"
NAME = "Sketch"

#: Areas are separated by a few pixels of border, so edges that should line up
#: exactly do not. Anything under this counts as touching.
EDGE_TOLERANCE = 6

#: Where the camera sits at startup: front, right and above, which reads as
#: "a building on the ground" at a glance.
VIEW_DIRECTION = Vector((1.0, -1.0, 0.8))
VIEW_DISTANCE = 18.0

log = []
state = {"step": 0}


def say(message):
    log.append(message)
    print(f"[gen_workspace] {message}")


def finish(ok):
    say(f"{'DONE' if ok else 'FAILED'}")
    # Deliberately not next to OUT: that directory is inside the add-on and
    # everything in it ships in the built zip. A GUI Blender's stdout is
    # buffered and quit_blender kills the process before it flushes, so the
    # log has to go to a file -- just not one a user would receive.
    report = os.path.join(tempfile.gettempdir(), "gen_workspace.log")
    try:
        with open(report, "w", encoding="utf-8") as handle:
            handle.write("\n".join(log) + f"\n{'OK' if ok else 'FAILED'}\n")
    except OSError:
        pass
    bpy.ops.wm.quit_blender()
    return None


def midpoint(area):
    return (area.x + area.width // 2, area.y + area.height // 2)


def touching(a, b):
    """True if a and b share a full edge, so Blender can merge them."""
    aligned_x = abs(a.x - b.x) <= EDGE_TOLERANCE and abs(a.width - b.width) <= EDGE_TOLERANCE
    aligned_y = abs(a.y - b.y) <= EDGE_TOLERANCE and abs(a.height - b.height) <= EDGE_TOLERANCE
    stacked = abs(a.y + a.height - b.y) <= EDGE_TOLERANCE or abs(b.y + b.height - a.y) <= EDGE_TOLERANCE
    beside = abs(a.x + a.width - b.x) <= EDGE_TOLERANCE or abs(b.x + b.width - a.x) <= EDGE_TOLERANCE
    return (aligned_x and stacked) or (aligned_y and beside)


def next_join(screen):
    """(doomed, keeper) for the next merge, or None when only the viewport is left.

    Prefers absorbing into the 3D viewport. When nothing else touches it -- the
    right-hand column has to be collapsed into one area before it lines up --
    any two matching neighbours will do, and the viewport becomes reachable on a
    later pass.
    """
    areas = list(screen.areas)
    viewport = next((a for a in areas if a.type == "VIEW_3D"), None)
    others = [a for a in areas if a is not viewport]
    if not others or viewport is None:
        return None

    for area in others:
        if touching(area, viewport):
            return area, viewport
    for source in others:
        for target in others:
            if source is not target and touching(source, target):
                return source, target
    return None


def tune(workspace):
    tuned = 0
    for screen in workspace.screens:
        for area in screen.areas:
            if area.type != "VIEW_3D":
                continue
            for space in area.spaces:
                if space.type != "VIEW_3D":
                    continue
                # The T toolbar is the closest thing Blender has to SketchUp's
                # tool palette, so it stays. The N sidebar is a properties tray,
                # and an empty one on first run is just a narrower viewport.
                space.show_region_toolbar = True
                space.show_region_ui = False

                space.region_3d.view_perspective = "PERSP"
                space.region_3d.view_rotation = VIEW_DIRECTION.normalized().to_track_quat("Z", "Y")
                space.region_3d.view_location = Vector((0.0, 0.0, 0.0))
                space.region_3d.view_distance = VIEW_DISTANCE

                # Solid with outlines is closest to a sketch-style face
                # default; specular highlights on untextured massing read as
                # noise.
                space.shading.type = "SOLID"
                space.shading.show_object_outline = True
                space.shading.show_specular_highlight = False

                # Every mesh edge drawn over the solid faces. This is not
                # decoration -- it is what makes Push/Pull usable. Blender
                # draws no mesh edges in Object Mode, and `show_object_outline`
                # only rings the whole object, so a box reads as an untextured
                # blob with no visible face boundaries: nothing tells you which
                # face is under the cursor or where it ends. It is also the
                # look a direct modeller expects, where edges are geometry you
                # can see rather than a mode you switch into.
                space.overlay.show_wireframes = True
                space.overlay.wireframe_threshold = 1.0  # every edge, not just creases
                space.overlay.wireframe_opacity = 1.0

                # Ground plane and the red/green axes.
                space.overlay.show_floor = True
                space.overlay.show_axis_x = True
                space.overlay.show_axis_y = True
                # The corner readout is Blender explaining itself; our tools
                # use the status bar.
                space.overlay.show_text = False
                space.overlay.show_stats = False
                tuned += 1
    return tuned


# --- Steps, one per event-loop tick ------------------------------------------


def step_duplicate():
    win = bpy.context.window
    source = bpy.data.workspaces.get("Layout") or bpy.data.workspaces[0]
    state["source"] = source.name
    win.workspace = source
    bpy.ops.workspace.duplicate()
    say(f"duplicated {source.name!r}")
    state["step"] += 1
    return 0.3


def step_rename():
    """Rename on a later tick, once the duplicate is actually active.

    Assigning Window.workspace -- and switching to a freshly duplicated one --
    is applied by Blender's notifier phase, not by the call. Reading
    win.workspace immediately after `workspace.duplicate()` returns the *old*
    workspace, so renaming there names the original and leaves the duplicate
    holding the layout. That produced a shipped file whose "Sketch" workspace
    still had all four areas while the joined single-viewport screen sat on an
    orphan named "Layout.001".
    """
    win = bpy.context.window
    workspace = win.workspace
    if workspace.name == state["source"]:
        say("duplicate not active yet; waiting another tick")
        return 0.3

    workspace.name = NAME
    workspace.use_filter_by_owner = False
    say(f"renamed to {workspace.name!r}, areas {[a.type for a in win.screen.areas]}")
    state["step"] += 1
    return 0.3


def step_join():
    """One merge per tick. Reschedules itself until only the viewport is left."""
    screen = bpy.context.window.screen
    pair = next_join(screen)
    if pair is None:
        say(f"joins complete, areas {[a.type for a in screen.areas]}")
        state["step"] += 1
        return 0.3

    doomed, keeper = pair
    # Counter-intuitively, area_join removes the area at target_xy and keeps
    # the one at source_xy. Passing these the other way round merges the
    # viewport into the timeline and deletes it.
    with bpy.context.temp_override(window=bpy.context.window, screen=screen, area=keeper):
        bpy.ops.screen.area_join(
            "EXEC_DEFAULT", source_xy=midpoint(keeper), target_xy=midpoint(doomed)
        )
    say(f"absorb {doomed.type} into {keeper.type}")

    state["joins"] = state.get("joins", 0) + 1
    if state["joins"] > 12:
        say("too many joins; giving up rather than looping forever")
        return finish(False)
    # Do not advance the step: run this again next tick, on the updated screen.
    return 0.3


def step_save():
    win = bpy.context.window
    workspace = bpy.data.workspaces.get(NAME)
    screen = win.screen
    areas = [a.type for a in screen.areas]

    if screen.show_fullscreen:
        say("screen is a fullscreen overlay; that state hides the workspace switcher")
        return finish(False)
    if areas != ["VIEW_3D"]:
        say(f"expected a single VIEW_3D, got {areas}")
        return finish(False)

    say(f"tuned {tune(workspace)} viewport(s)")

    for obj in list(bpy.data.objects):
        bpy.data.objects.remove(obj, do_unlink=True)
    say("cleared default objects")

    os.makedirs(os.path.dirname(os.path.abspath(OUT)), exist_ok=True)

    # Saving normally leaves a .blend1 backup beside the target. That directory
    # is inside the add-on, and the packager reads the disk rather than git --
    # so a gitignored backup would still ship to every user.
    bpy.context.preferences.filepaths.save_version = 0
    bpy.ops.wm.save_as_mainfile(filepath=OUT, copy=True, compress=True)

    stray = OUT + "1"
    if os.path.isfile(stray):
        os.remove(stray)
        say(f"removed stray backup {os.path.basename(stray)}")

    size = os.path.getsize(OUT) if os.path.isfile(OUT) else 0
    say(f"wrote {OUT} ({size} bytes), areas {areas}")
    return finish(size > 0)


STEPS = [step_duplicate, step_rename, step_join, step_save]


def tick():
    try:
        return STEPS[state["step"]]()
    except Exception:
        say(traceback.format_exc())
        return finish(False)


if bpy.app.background:
    print("gen_workspace.py needs a GUI session: drop -b", file=sys.stderr)
    sys.exit(1)

bpy.app.timers.register(tick, first_interval=1.5)
