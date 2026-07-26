"""Generate data/workspace.blend containing the "Sketch" workspace.

Run with: blender -b --factory-startup --python gen_workspace.py -- <out.blend>

SketchUp puts one large viewport on screen and nothing else: no outliner, no
properties editor, no timeline. Blender's "Layout" carries all three, and for
someone who came here to draw a wall they are the clutter that makes Blender
feel like Blender. So the Sketch workspace ships maximized.

Getting there is not obvious. Blender exposes no data-level way to remove an
area -- only `screen.area_close`, an operator that deadlocks under `-b` and in
a scripted GUI session alike (verified on 5.0, both hang indefinitely).
`screen.screen_full_area` does work headlessly, and it reaches the same place
by a different route: it parks the full layout on a second screen and makes a
single-area screen active. Ctrl+Space restores the full layout, so nothing is
taken away -- it is just not in the way.

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

# --- Maximize the viewport ---------------------------------------------------
maximized = False
for screen in [ws.screens[i] for i in range(len(ws.screens))]:
    view3d = next((a for a in screen.areas if a.type == "VIEW_3D"), None)
    if view3d is None:
        continue
    with bpy.context.temp_override(window=win, screen=screen, area=view3d):
        bpy.ops.screen.screen_full_area(use_hide_panels=False)
    maximized = True
    break

active = win.screen
log.append(f"maximized={maximized} active screen={active.name!r} areas={[a.type for a in active.areas]}")
if not maximized or len(active.areas) != 1:
    print("\n!! Sketch workspace is not a single maximized viewport; aborting.\n")
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
