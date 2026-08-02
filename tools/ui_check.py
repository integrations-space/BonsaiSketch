"""Verify the tools activate inside a real 3D viewport, then quit.

Run with:
    blender --python tools/ui_check.py -- <report-file>

This opens a window briefly. It has to: the checks here are precisely the ones
`smoke_test.py` cannot make, because they need a live VIEW_3D area, a region,
and Blender's tool system actually running. Poll methods, tool activation and
Bonsai's viewport decorator all read `context.space_data` or draw into a
region, and in `-b` there is neither.

Results go to a file rather than stdout. A GUI Blender's stdout is buffered and
the process is killed by `quit_blender` before it flushes, so printing here
loses the entire report -- the failure mode looks identical to the checks never
having run.

What this does not cover is the modal interaction itself: placing points,
dragging a face. Driving that needs a human at the mouse.
"""

import sys
import traceback

import bpy
from mathutils import Vector

ADDON = "bl_ext.user_default.bonsai_sketch_mode"

REPORT = sys.argv[-1] if "--" in sys.argv else "ui_check.txt"

failures = []
checks = 0
lines = []

#: Carried between ticks, since each is a separate timer callback.
state = {}

# Enabled here rather than inside the timer, so that by the time the checks run
# the add-on's own deferred workspace append has already had its tick. That
# append is exactly what one of the checks is testing.
bpy.ops.preferences.addon_enable(module="bl_ext.blender_org.bonsai")
bpy.ops.preferences.addon_enable(module=ADDON)


def check(label, condition, detail=""):
    global checks
    checks += 1
    if condition:
        lines.append(f"  ok    {label}")
    else:
        lines.append(f"  FAIL  {label}" + (f" -- {detail}" if detail else ""))
        failures.append(label)


def find_view3d():
    """(window, area, region) of the first 3D viewport, or Nones."""
    for window in bpy.context.window_manager.windows:
        for area in window.screen.areas:
            if area.type != "VIEW_3D":
                continue
            for region in area.regions:
                if region.type == "WINDOW":
                    return window, area, region
    return None, None, None


def run():
    addon = sys.modules.get(ADDON)
    if addon is None:
        check("add-on module importable", False)
        return finish()

    bridge = addon.bridge
    tools = addon.tools
    ops = addon.ops
    workspace = addon.workspace
    viewport = addon.viewport

    # The question a new user asks first: they enabled the add-on, is the tab
    # there? Enabling does not fire load_post, so this only passes because
    # register_handlers schedules a deferred append.
    check("Sketch tab exists after enabling", workspace.exists())

    # This block previously asked "is there a screen with exactly one area?".
    # It passed on a workspace that was unusable: screen_full_area had put the
    # tab into Blender's temporary fullscreen overlay, which hides the
    # workspace switcher and shows an empty viewport. One area, no way out.
    #
    # So these check the state a user is actually left in.
    if workspace.exists():
        sketch = bpy.data.workspaces[workspace.WORKSPACE_NAME]
        screens = {s.name: [a.type for a in s.areas] for s in sketch.screens}

        check(
            "no screen is stuck in a fullscreen overlay",
            not any(s.show_fullscreen for s in sketch.screens),
            f"screens {screens}",
        )
        check(
            "the workspace switcher is still reachable",
            not bpy.context.window.screen.show_fullscreen,
        )
        check(
            "workspace has a 3D viewport",
            any("VIEW_3D" in types for types in screens.values()),
            f"screens {screens}",
        )
        check(
            "the layout is a single viewport, nothing else",
            all(types == ["VIEW_3D"] for types in screens.values()),
            f"screens {screens}",
        )

        space = None
        for screen in sketch.screens:
            for area_ in screen.areas:
                if area_.type == "VIEW_3D":
                    space = next(s for s in area_.spaces if s.type == "VIEW_3D")
                    break
        check("tool palette shown", space is not None and space.show_region_toolbar)
        check("properties sidebar hidden", space is not None and not space.show_region_ui)
        check("perspective view", space is not None and space.region_3d.view_perspective == "PERSP")
        check("solid shading", space is not None and space.shading.type == "SOLID")
        # The canvas is raised when the workspace is added, so the Sketch tab
        # shows sky over ground rather than the flat colour it ships with.
        check("viewport reads the theme canvas, not a flat colour",
              space is not None and space.shading.background_type == "THEME",
              f"background_type {space.shading.background_type if space else '?'}")
        gradients = bpy.context.preferences.themes[0].view_3d.space.gradients
        check("canvas is a two-tone gradient",
              gradients.background_type == "LINEAR", gradients.background_type)
        check("sky sits above ground, and both are light",
              min(gradients.high_gradient) > 0.5 and min(gradients.gradient) > 0.5
              and gradients.high_gradient[2] > gradients.high_gradient[0],
              f"sky {list(gradients.high_gradient)} ground {list(gradients.gradient)}")
        check("grid reaches past the model",
              space is not None and space.overlay.grid_lines >= 64,
              f"grid_lines {space.overlay.grid_lines if space else '?'}")
        # Without this, Object Mode draws no mesh edges at all and Push/Pull
        # has nothing to aim at: a box is an untextured blob with no visible
        # face boundaries.
        check("mesh edges drawn over solid faces", space is not None and space.overlay.show_wireframes)
        check(
            "every edge shown, not just creases",
            space is not None and abs(space.overlay.wireframe_threshold - 1.0) < 1e-6,
            f"threshold {space.overlay.wireframe_threshold if space else '?'}",
        )

    window, area, region = find_view3d()
    check("found a 3D viewport", area is not None)
    if area is None:
        return finish()

    with bpy.context.temp_override(window=window, area=area, region=region):
        context = bpy.context
        check("context is a VIEW_3D", context.space_data.type == "VIEW_3D")

        # The poll methods that were unreachable headlessly.
        for name, op_idname in (
            ("Line", ops.LINE_OP),
            ("Rectangle", ops.RECTANGLE_OP),
            ("Push/Pull", ops.PUSH_PULL_OP),
        ):
            module, func = op_idname.split(".")
            operator = getattr(getattr(bpy.ops, module), func)
            check(f"{name} operator polls true", operator.poll())

        # Selecting each tool proves the toolbar entry resolves, its icon
        # loads, and its keymap binds to an operator that exists.
        for tool_cls in tools.tools:
            try:
                bpy.ops.wm.tool_set_by_id(name=tool_cls.bl_idname)
                active = context.workspace.tools.from_space_view3d_mode("OBJECT")
                ok = active is not None and active.idname == tool_cls.bl_idname
                detail = f"active is {active.idname if active else None!r}"
            except Exception as exc:
                ok = False
                detail = str(exc)
            check(f"{tool_cls.bl_label} activates", ok, detail)

        # Push/Pull's inference decides between candidates in pixels, which
        # needs a region to project into. Headlessly there is none, so
        # smoke_test can only check which candidates exist -- whether they can
        # be compared at all is answerable only here.
        centre = Vector((0.0, 0.0, 0.0))
        projected = viewport.project_point(context, centre)
        check("a world point projects into the region", projected is not None)
        if projected is not None:
            check(
                "the projection lands inside the region",
                0 <= projected.x <= region.width and 0 <= projected.y <= region.height,
                f"{tuple(round(v, 1) for v in projected)} in {region.width}x{region.height}",
            )
            # Two points a metre apart along the view's vertical must land in
            # different places, or every candidate would measure zero pixels
            # away and inference would snap to whichever it saw first.
            above = viewport.project_point(context, Vector((0.0, 0.0, 1.0)))
            check(
                "points a metre apart project apart",
                above is not None and (above - projected).length > 1.0,
                f"{(above - projected).length if above else '?'} px",
            )

        # A point behind the camera has no honest answer, and inference has to
        # cope with being told so rather than snapping to a mirrored ghost.
        behind = viewport.project_point(context, context.region_data.view_matrix.inverted()
                                        .translation + context.region_data.view_rotation
                                        @ Vector((0.0, 0.0, 5.0)))
        check("a point behind the camera projects to nothing", behind is None,
              f"got {behind}")

        # Bonsai's overlay is installed on every polyline tool invoke and torn
        # down on exit. A draw handler that fails to register would take the
        # whole viewport down with it.
        try:
            bridge.PolylineDecorator.install(context)
            bridge.PolylineDecorator.uninstall()
            ok, detail = True, ""
        except Exception as exc:
            ok, detail = False, str(exc)
        check("polyline decorator installs and uninstalls", ok, detail)

        # Back to a harmless tool so the check leaves no state behind.
        bpy.ops.wm.tool_set_by_id(name=tools.SELECT_TOOL)

    if not workspace.exists():
        return finish()

    # Switching to the Sketch tab is what puts a user in Sketch Mode: the
    # msgbus subscription swaps the keymap in, and swaps it back out on the way
    # past. Nothing else in the add-on makes the single-key tools live.
    #
    # This has to be driven across real event-loop ticks. Assigning
    # Window.workspace does not switch immediately -- Blender defers it to the
    # notifier phase, and msgbus fires from there too. Setting the workspace
    # and inspecting the keymap in the same tick reads a half-applied state and
    # reports whatever it happens to catch.
    state["window"] = window
    state["was"] = active_keyconfig()
    window.workspace = bpy.data.workspaces[workspace.WORKSPACE_NAME]
    return 0.5


def active_keyconfig():
    keyconfigs = bpy.context.window_manager.keyconfigs
    return keyconfigs.active.name if keyconfigs.active else None


def entered_sketch():
    """Second tick: the switch has been applied and msgbus has fired."""
    addon = sys.modules[ADDON]
    workspace = addon.workspace
    window = state["window"]

    check(
        "Sketch tab is the active workspace",
        window.workspace.name == workspace.WORKSPACE_NAME,
        f"active workspace is {window.workspace.name!r}",
    )
    active = active_keyconfig()
    check("Sketch keymap activates on the tab", active == "Sketch", f"keymap is {active!r}")

    for other in bpy.data.workspaces:
        if other.name != workspace.WORKSPACE_NAME:
            window.workspace = other
            break
    return 0.5


def left_sketch():
    """Third tick: leaving must hand the keymap back, not strand the user."""
    restored = active_keyconfig()
    check(
        "previous keymap restored on the way out",
        restored == state["was"],
        f"was {state['was']!r}, now {restored!r}",
    )
    return finish()


def finish():
    lines.append("")
    lines.append(f"{checks - len(failures)}/{checks} viewport checks passed")
    if failures:
        lines.append("failed:")
        for name in failures:
            lines.append(f"  - {name}")
        lines.append("UI CHECK FAILED")
    else:
        lines.append("UI CHECK PASSED")

    with open(REPORT, "w", encoding="utf-8") as handle:
        handle.write("\n".join(lines) + "\n")

    bpy.ops.wm.quit_blender()
    return None


#: The checks run as a sequence of timer callbacks. Each returns a delay to
#: hand control back to Blender, so deferred workspace switches and msgbus
#: notifications actually happen between steps.
STEPS = [run, entered_sketch, left_sketch]


def guarded():
    """Run the next step, and make sure Blender quits even if one explodes."""
    try:
        delay = STEPS[state.get("step", 0)]()
    except Exception:
        lines.append("check run raised:")
        lines.append(traceback.format_exc())
        failures.append("check run completed")
        return finish()

    if delay is None:
        return None
    state["step"] = state.get("step", 0) + 1
    return delay


# --python runs before the UI exists, so the checks wait for a timer tick. The
# splash screen also holds the first draw, hence the delay rather than 0.0.
bpy.app.timers.register(guarded, first_interval=2.0)
