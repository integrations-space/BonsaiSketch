"""Generate data/workspace.blend containing the "Sketch" workspace.

Run with: blender -b --factory-startup --python gen_workspace.py -- <out.blend>

A single large viewport with no outliner, properties editor or timeline is the
goal, and this script does not achieve it. What it does is tune the viewport
inside Blender's standard layout. That is a deliberate retreat from something
worse -- read on before trying again.

Blender exposes no data-level way to remove an area. The only route is
`screen.area_close`, an operator that deadlocks: verified on 5.0, under `-b`
and in a scripted GUI session alike, it hangs until the process is killed.

`screen.screen_full_area` does run headlessly, and an earlier version of this
script used it. That was wrong. It does not build a one-area screen; it
triggers Blender's *temporary fullscreen overlay*, and the workspace shipped in
that state opened with the workspace switcher replaced by a "Back to Previous"
button, no route to any other tab, and an empty viewport. Every automated check
passed, because they asked "is there a screen with one area" -- which was true,
and irrelevant.

So the layout stays normal until someone builds the stripped-down screen by
hand in a GUI session and saves it here. That is a mouse job, not a script job,
and pretending otherwise is what produced the broken build.

bpy.data.libraries.write() does NOT persist WorkSpace datablocks -- it silently
produces a file with no workspaces, which makes workspace.append_activate()
return CANCELLED. Bonsai's own data/workspace.blend is a fully saved .blend
containing every workspace, so we do the same: build ours, then
save_as_mainfile. append_activate(idname=...) picks out just the one it wants.
"""

import os
import sys

import bpy
from mathutils import Vector

OUT = sys.argv[-1]
NAME = "Sketch"

#: Where the camera sits at startup: front, right and above, which is the angle
#: SketchUp opens on and reads as "a building on the ground" at a glance.
VIEW_DIRECTION = Vector((1.0, -1.0, 0.8))
VIEW_DISTANCE = 18.0

log = []

# --- Build the workspace -----------------------------------------------------
src = bpy.data.workspaces.get("Layout") or bpy.data.workspaces[0]
win = bpy.context.window
win.workspace = src

bpy.ops.workspace.duplicate()
ws = win.workspace
ws.name = NAME
log.append(f"created workspace: {ws.name}")

# --- Tune the 3D viewport ----------------------------------------------------
tuned = 0
for screen in [ws.screens[i] for i in range(len(ws.screens))]:
    for area in screen.areas:
        if area.type != "VIEW_3D":
            continue
        for space in area.spaces:
            if space.type != "VIEW_3D":
                continue
            # The T toolbar is the closest thing Blender has to SketchUp's tool
            # palette, so it stays. The N sidebar is not: it is a properties
            # tray, and an empty one on first run is just a narrower viewport.
            space.show_region_toolbar = True
            space.show_region_ui = False

            space.region_3d.view_perspective = "PERSP"
            space.region_3d.view_rotation = VIEW_DIRECTION.normalized().to_track_quat("Z", "Y")
            space.region_3d.view_location = Vector((0.0, 0.0, 0.0))
            space.region_3d.view_distance = VIEW_DISTANCE

            # Solid with outlines is the closest match to SketchUp's default
            # face style; specular highlights on untextured massing just read
            # as noise.
            space.shading.type = "SOLID"
            space.shading.show_object_outline = True
            space.shading.show_specular_highlight = False

            # Ground plane and the red/green axes, as SketchUp draws them.
            space.overlay.show_floor = True
            space.overlay.show_axis_x = True
            space.overlay.show_axis_y = True
            # The corner readout ("User Perspective", object name, statistics)
            # is Blender explaining itself. Our tools use the status bar.
            space.overlay.show_text = False
            space.overlay.show_stats = False
            tuned += 1
log.append(f"tuned {tuned} VIEW_3D space(s)")

ws.use_filter_by_owner = False

# --- Sanity check ------------------------------------------------------------
# Whatever this produces has to be a *normal* screen. An earlier version called
# screen.screen_full_area here to get a single-area layout, which passed every
# automated check and was unusable in practice: that operator does not build a
# one-area screen, it triggers Blender's temporary fullscreen overlay. The tab
# opened with the workspace switcher replaced by a "Back to Previous" button,
# no way to reach another workspace, and an empty viewport.
#
# So the check is on the state a user actually lands in, not on area counts.
active = win.screen
log.append(f"active screen={active.name!r} areas={[a.type for a in active.areas]}")
if active.show_fullscreen:
    print("\n!! Sketch workspace is in a fullscreen overlay; that state is unusable.\n")
    sys.exit(1)
if not any(a.type == "VIEW_3D" for a in active.areas):
    print("\n!! Sketch workspace has no 3D viewport.\n")
    sys.exit(1)

# Start on a clean scene rather than shipping the default cube.
for obj in list(bpy.data.objects):
    bpy.data.objects.remove(obj, do_unlink=True)
log.append("cleared default objects")

# --- Save as a real .blend ---------------------------------------------------
os.makedirs(os.path.dirname(OUT), exist_ok=True)
bpy.ops.wm.save_as_mainfile(filepath=OUT, copy=True, compress=True)

ok = os.path.isfile(OUT)
log.append(f"wrote: {OUT} exists={ok} size={os.path.getsize(OUT) if ok else 0}")

print("\n===== GEN WORKSPACE =====")
for line in log:
    print(line)
print("===== END =====\n")
