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

"""Five-agent proposal and approval controls on the Sketch tab.

Proposal requests run on a worker thread; approved commands run on the main
thread in a separate undo-aware operator. Proposal generation is modal: it starts the thread, then drives the pump
from its own timer until the thread is done. Driving the pump here rather than
leaving it to ``bpy.app.timers`` is deliberate -- a modal operator owns the
event loop, and a timer is not promised a slot underneath one.

Escape leaves the read-only proposal request running until its HTTP timeout.
No geometry changes during generation. Reject discards a completed proposal.
"""

from __future__ import annotations

import os
import json
import threading
import traceback

import bpy

from .. import bridge, sidebar
from . import claude, mainthread, agents

#: Where the last run's outcome is kept for the panel to draw.
_pending = None

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
    bl_label = "Plan with Agents"
    bl_description = "Ask five agents for a plan to review before changing the model"
    bl_options = {"REGISTER"}

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
        from .. import sg
        global _pending
        try:
            self._snapshot = sg.snapshot()
        except Exception as exc:
            self.report({"ERROR"}, str(exc))
            return {"CANCELLED"}
        _pending = None
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
                "result": agents.propose(
                    instruction,
                    snapshot=self._snapshot,
                    api_key=key,
                    model=model,
                    on_event=lambda message: _status.update(message=message),
                ),
            }
        except (claude.ClaudeError, agents.PlanError) as exc:
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

        global _pending
        result = outcome["result"]
        _pending = agents.PendingPlan(result)
        review = bpy.data.texts.get("Sketch Agent Review.json") or bpy.data.texts.new("Sketch Agent Review.json")
        review.clear()
        review.write(json.dumps(result, indent=2))
        _status.update(message="Ready for review" if result["ready"] else "Questions need answers",
                       detail=result["plan"]["summary"], error=False)
        self.report({"INFO"}, "Agent proposal ready. Review it before approving")
        return {"FINISHED"}


class BONSAI_SKETCH_MODE_OT_approve_plan(bpy.types.Operator):
    bl_idname = "bonsai_sketch_mode.approve_plan"
    bl_label = "Approve and Apply"
    bl_description = "Apply the reviewed commands once to the unchanged model"
    bl_options = {"REGISTER", "UNDO"}

    @classmethod
    def poll(cls, context):
        return _pending is not None and not _pending.used and not _status["busy"] and _pending.review()["ready"]

    def invoke(self, context, event):
        return context.window_manager.invoke_props_dialog(self, width=650)

    def draw(self, context):
        if _pending is None:
            return
        result = _pending.review()
        self.layout.label(text="Apply these changes to the current model:")
        for i, action in enumerate(result["plan"]["actions"]):
            box = self.layout.box()
            box.label(text=f"{i + 1}. {action['operation']}")
            for line in _wrap(json.dumps(action["parameters"]), 85):
                box.label(text=line)
        self.layout.label(text="Full parameters and specialist findings: Sketch Agent Review.json")

    transaction_key = ""
    transaction_data = None

    def execute(self, context):
        from .. import sg
        if _pending is None:
            return {"CANCELLED"}
        if sg.fingerprint() != _pending.review()["fingerprint"]:
            _pending.used = True
            self.report({"ERROR"}, "The model or stage changed. Generate a new plan")
            return {"CANCELLED"}
        return bridge.execute_ifc_operator(self, context)

    def _execute(self, context):
        from .. import sg
        from . import commands
        try:
            def dispatch(name, params):
                target = bpy.data.objects.get(params.get("object", ""))
                if name in {"push_pull", "sketch_polyline", "assign_class"} and target is not None:
                    if target.modifiers or (target.type == "MESH" and target.data.shape_keys):
                        raise agents.PlanError("Apply or remove modifiers/shape keys before agent editing")
                return commands.run(name, params)
            result = _pending.execute(sg.fingerprint(), dispatch)
        except Exception as exc:
            self.report({"ERROR"}, str(exc))
            return {"CANCELLED"}
        log = bpy.data.texts.get("Sketch Agent Execution.json") or bpy.data.texts.new("Sketch Agent Execution.json")
        log.clear()
        log.write(json.dumps(result, indent=2, default=str))
        if result["ok"]:
            message = f"Applied {len(result['completed'])} commands"
        else:
            message = f"Stopped at action {result['failed_action'] + 1}: {result['error']}. Check execution log for partial changes."
        _status.update(message=message, detail=message, error=not result["ok"])
        self.report({"INFO"} if result["ok"] else {"WARNING"}, message)
        # FINISHED preserves Blender undo registration even after a partial run.
        return {"FINISHED"}


class BONSAI_SKETCH_MODE_OT_reject_plan(bpy.types.Operator):
    bl_idname = "bonsai_sketch_mode.reject_plan"
    bl_label = "Reject Plan"

    def execute(self, context):
        global _pending
        if _pending:
            _pending.used = True
        _pending = None
        _status.update(message="Rejected", detail="Edit your request and generate another plan", error=False)
        return {"FINISHED"}


class BONSAI_SKETCH_MODE_OT_review_plan(bpy.types.Operator):
    bl_idname = "bonsai_sketch_mode.review_plan"
    bl_label = "Open Full Review"

    def execute(self, context):
        text = bpy.data.texts.get("Sketch Agent Review.json")
        if text is None:
            return {"CANCELLED"}
        context.area.type = "TEXT_EDITOR"
        context.area.spaces.active.text = text
        return {"FINISHED"}



class BONSAI_SKETCH_MODE_PT_describe(bpy.types.Panel):
    bl_space_type = "VIEW_3D"
    bl_region_type = "UI"
    bl_category = sidebar.CATEGORY
    bl_label = "Sketch Agents"
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
                BONSAI_SKETCH_MODE_OT_build_from_text.bl_idname, text="Plan with Agents", icon="PLAY"
            )

        if _pending is not None and not _pending.used:
            result = _pending.review()
            box = layout.box()
            box.label(text=f"{len(result['plan']['actions'])} proposed commands")
            for role in ("Geometry", "BIM/IFC", "Compliance", "QA"):
                box.label(text=role + " reviewed", icon="CHECKMARK")
            for question in result["plan"]["questions"]:
                for line in _wrap(question, 34):
                    box.label(text=line, icon="QUESTION")
            if not result["reports"]["QA"]["approved"]:
                box.label(text="QA blocked this plan", icon="ERROR")
                for finding in result["reports"]["QA"]["findings"]:
                    for line in _wrap(finding, 34):
                        box.label(text=line)
            box.operator("bonsai_sketch_mode.review_plan")
            row = box.row(align=True)
            row.operator("bonsai_sketch_mode.approve_plan")
            row.operator("bonsai_sketch_mode.reject_plan")

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
    BONSAI_SKETCH_MODE_OT_approve_plan,
    BONSAI_SKETCH_MODE_OT_reject_plan,
    BONSAI_SKETCH_MODE_OT_review_plan,
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
    global _pending
    _pending = None
    try:
        del bpy.types.WindowManager.bonsai_sketch_prompt
    except AttributeError:
        pass
    for cls in reversed(classes):
        try:
            bpy.utils.unregister_class(cls)
        except Exception:
            pass
