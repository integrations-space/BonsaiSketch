"""Generate data/workspace.blend containing a "Sketch" workspace.

Run with: blender -b --factory-startup --python gen_workspace.py -- <out.blend>

bpy.data.libraries.write() does NOT persist WorkSpace datablocks -- it silently
produces a file with no workspaces, which makes workspace.append_activate()
return CANCELLED. Bonsai's own data/workspace.blend is a fully saved .blend
containing every workspace, so we do the same: build ours, then
save_as_mainfile. append_activate(idname=...) picks out just the one it wants.
"""

import os
import sys

import bpy

OUT = sys.argv[-1]
NAME = "Sketch"

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
            # SketchUp shows a tool palette and a tray; Blender's equivalents
            # are the T toolbar and the N sidebar.
            space.show_region_toolbar = True
            space.show_region_ui = True
            space.region_3d.view_perspective = "PERSP"
            # Solid shading with outlines reads closest to a sketch-style
            # default face style.
            space.shading.type = "SOLID"
            space.shading.show_object_outline = True
            space.shading.show_specular_highlight = False
            space.overlay.show_floor = True
            space.overlay.show_axis_x = True
            space.overlay.show_axis_y = True
            tuned += 1
log.append(f"tuned {tuned} VIEW_3D space(s)")

ws.use_filter_by_owner = False

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
