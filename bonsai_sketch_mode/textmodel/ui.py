# Bonsai Sketch Mode - direct-modelling interaction for Bonsai
# Copyright (C) 2026 Innovations & Integrations
#
# This program is free software: you can redistribute it and/or modify
# it under the terms of the GNU General Public License as published by
# the Free Software Foundation, either version 3 of the License, or
# (at your option) any later version.
#
# This program is distributed in the hope that it will be useful,
# but WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
# GNU General Public License for more details.
#
# You should have received a copy of the GNU General Public License
# along with this program.  If not, see <http://www.gnu.org/licenses/>.

"""A box to type in, on the Sketch tab.

The request runs on a worker thread and the verbs it calls run on the main
thread, so the operator is modal: it starts the thread, then drives the pump
from its own timer until the thread is done. Driving the pump here rather than
leaving it to ``bpy.app.timers`` is deliberate -- a modal operator owns the
event loop, and a timer is not promised a slot underneath one.

Escape leaves the request running rather than pretending to cancel it. There is
no way to un-send an HTTPS request, and half-built geometry from a request the
user thinks they stopped is worse than waiting.
"""

from __future__ import annotations

import os
import threading
import traceback

import bpy

from .. import bridge, sidebar
from . import claude, mainthread

#: Where the last run's outcome is kept for the panel to draw.
_status = {"busy": False, "message": "", "detail": "", "error": False}


def status() -> dict:
    return _status


def _api_key(prefs) -> str:
    """The key from preferences, or the environment.

    The environment is checked second but wins nothing -- it is there so a
    developer can run without typing a key into a .blend-adjacent config, and
    so CI never needs one stored.
    """
    key = (getattr(prefs, "anthropic_api_key", "") or "").strip()
    return key or os.environ.get("ANTHROPIC_API_KEY", "").strip()


class BONSAI_SKETCH_MODE_OT_build_from_text(bpy.types.Operator):
    bl_idname = "bonsai_sketch_mode.build_from_text"
    bl_label = "Build"
    bl_description = "Describe what to build, and let Claude build it with the Sketch tools"
    bl_options = {"REGISTER", "UNDO"}

    _timer = None
    _thread = None
    _outcome: dict

    @classmethod
    def poll(cls, context: bpy.types.Context) -> bool:
        return bridge.is_available() and not _status["busy"]

    def invoke(self, context: bpy.types.Context, event):
        from .. import workspace

        prefs = workspace.get_prefs()
        instruction = (context.window_manager.bonsai_sketch_prompt or "").strip()
        if not instruction:
            self.report({"ERROR"}, "Type what you want built first")
            return {"CANCELLED"}

        key = _api_key(prefs)
        if not key:
            self.report({"ERROR"}, "No Anthropic API key -- add one in the add-on preferences")
            return {"CANCELLED"}

        model = getattr(prefs, "anthropic_model", claude.DEFAULT_MODEL) or claude.DEFAULT_MODEL
        self._outcome = {}

        _status.update(busy=True, message="thinking", detail="", error=False)
        # Claimed before the thread starts, so the first submit cannot arrive
        # before the pump is running.
        mainthread.acquire()

        self._thread = threading.Thread(
            target=self._work,
            args=(instruction, key, model),
            daemon=True,
            name="bonsai-sketch-claude",
        )
        self._thread.start()

        self._timer = context.window_manager.event_timer_add(0.1, window=context.window)
        context.window_manager.modal_handler_add(self)
        return {"RUNNING_MODAL"}

    def _work(self, instruction: str, key: str, model: str) -> None:
        """Worker thread. Touches no bpy state except through mainthread."""
        try:
            self._outcome = {
                "ok": True,
                "result": claude.build(
                    instruction,
                    api_key=key,
                    model=model,
                    on_event=lambda message: _status.update(message=message),
                ),
            }
        except claude.ClaudeError as exc:
            self._outcome = {"ok": False, "error": str(exc)}
        except Exception as exc:  # pragma: no cover - unexpected, still reported
            traceback.print_exc()
            self._outcome = {"ok": False, "error": "%s: %s" % (type(exc).__name__, exc)}

    def modal(self, context: bpy.types.Context, event):
        if event.type != "TIMER":
            return {"PASS_THROUGH"}

        # This is what actually runs the verbs. Without it the worker would
        # wait on submit() until its timeout while we sat here doing nothing.
        mainthread.pump_once()

        for area in context.screen.areas:
            if area.type == "VIEW_3D":
                area.tag_redraw()

        if self._thread is not None and self._thread.is_alive():
            return {"RUNNING_MODAL"}

        return self._finish(context)

    def _finish(self, context: bpy.types.Context):
        # One last drain: the worker can finish between two ticks with a result
        # still queued behind it.
        mainthread.pump_once()

        window_manager = context.window_manager
        if self._timer is not None:
            window_manager.event_timer_remove(self._timer)
            self._timer = None
        mainthread.release()

        outcome = self._outcome or {"ok": False, "error": "the request ended without a result"}
        _status["busy"] = False

        if not outcome.get("ok"):
            _status.update(message="Failed", detail=outcome.get("error", ""), error=True)
            self.report({"ERROR"}, outcome.get("error", "failed"))
            return {"CANCELLED"}

        result = outcome["result"]
        _status.update(
            message="Done",
            detail=result.get("text", ""),
            error=False,
        )
        self.report(
            {"INFO"},
            "%s (%d tool calls, %d in / %d out tokens)"
            % (
                result.get("text", "Done."),
                len(result.get("called", [])),
                result.get("input_tokens", 0),
                result.get("output_tokens", 0),
            ),
        )
        return {"FINISHED"}


class BONSAI_SKETCH_MODE_PT_describe(bpy.types.Panel):
    bl_space_type = "VIEW_3D"
    bl_region_type = "UI"
    bl_category = sidebar.CATEGORY
    bl_label = "Describe"
    bl_idname = "BONSAI_SKETCH_MODE_PT_describe"
    bl_options = {"DEFAULT_CLOSED"}

    def draw(self, context: bpy.types.Context) -> None:
        from .. import workspace

        layout = self.layout
        prefs = workspace.get_prefs()

        if not _api_key(prefs):
            box = layout.box()
            box.label(text="No API key", icon="ERROR")
            column = box.column(align=True)
            column.scale_y = 0.8
            column.label(text="Add one in the add-on preferences")
            column.label(text="to build from a description.")
            return

        column = layout.column(align=True)
        column.prop(context.window_manager, "bonsai_sketch_prompt", text="")

        row = layout.row(align=True)
        row.scale_y = 1.3
        if _status["busy"]:
            row.enabled = False
            row.label(text=_status["message"] or "working", icon="SORTTIME")
        else:
            row.operator(
                BONSAI_SKETCH_MODE_OT_build_from_text.bl_idname, text="Build", icon="PLAY"
            )

        if _status["detail"]:
            box = layout.box()
            box.alert = _status["error"]
            column = box.column(align=True)
            column.scale_y = 0.8
            # Blender labels do not wrap, so the report is broken into lines
            # rather than trailing off the edge of the panel.
            for line in _wrap(_status["detail"], 34):
                column.label(text=line)


def _wrap(text: str, width: int) -> list:
    lines: list = []
    for paragraph in text.split("\n"):
        current = ""
        for word in paragraph.split():
            if current and len(current) + 1 + len(word) > width:
                lines.append(current)
                current = word
            else:
                current = "%s %s" % (current, word) if current else word
        if current:
            lines.append(current)
    return lines[:12]


classes = (
    BONSAI_SKETCH_MODE_OT_build_from_text,
    BONSAI_SKETCH_MODE_PT_describe,
)


def register() -> tuple[bool, str]:
    """Add the Describe panel. Returns (ok, message). Never raises."""
    added = []
    try:
        for cls in classes:
            bpy.utils.register_class(cls)
            added.append(cls)
        bpy.types.WindowManager.bonsai_sketch_prompt = bpy.props.StringProperty(
            name="Describe",
            description="What to build, in plain words. For example: a 6 by 4 metre room, 3m high",
            default="",
            options={"TEXTEDIT_UPDATE"},
        )
    except Exception as exc:  # pragma: no cover - depends on host Blender
        for cls in reversed(added):
            try:
                bpy.utils.unregister_class(cls)
            except Exception:
                pass
        return False, "Could not add the Describe panel: %s" % exc
    return True, "Describe panel in the Sketch sidebar"


def unregister() -> None:
    try:
        del bpy.types.WindowManager.bonsai_sketch_prompt
    except AttributeError:
        pass
    for cls in reversed(classes):
        try:
            bpy.utils.unregister_class(cls)
        except Exception:
            pass
