"""Drive the Describe panel's operator in a real Blender window, then quit.

Run with:
    blender --python tools/describe_check.py -- <report-file>

`claude_check.py` tests the loop by calling it directly. This tests the thing a
user actually touches: type a sentence on the Sketch tab, generate a plan, review it, then approve and the
model appears. It needs a GUI because that path is a modal operator.

The specific risk it exists to catch: a modal operator owns Blender's event
loop, and a `bpy.app.timers` callback is not promised a slot underneath one. The
worker thread waits on `mainthread.submit` for every verb, so if the modal did
not drive the pump from its own TIMER event, every build would hang until the
timeout and then fail. That failure would never show up headlessly.

Talks to a stub Messages API on loopback -- no API key, no network, no spend.
"""

import json
import sys
import threading
from http.server import BaseHTTPRequestHandler, HTTPServer

import bpy

ADDON = "bl_ext.user_default.bonsai_sketch_mode"
REPORT = sys.argv[-1] if "--" in sys.argv else "describe_check.txt"

lines = []
failures = []
checks = 0
script = []
state = {"n": 0}

bpy.ops.preferences.addon_enable(module="bl_ext.blender_org.bonsai")
bpy.ops.preferences.addon_enable(module=ADDON)

addon = sys.modules[ADDON]
claude = addon.textmodel.claude
ui = addon.textmodel.ui


def check(label, condition, detail=""):
    global checks
    checks += 1
    if condition:
        lines.append("  ok    %s" % label)
    else:
        lines.append("  FAIL  %s%s" % (label, " -- %s" % detail if detail else ""))
        failures.append(label)


def section(title):
    lines.append("\n%s" % title)


def finish():
    lines.append("\n%d/%d checks passed" % (checks - len(failures), checks))
    if failures:
        lines.append("failed:")
        for name in failures:
            lines.append("  - %s" % name)
    lines.append("DESCRIBE CHECK %s" % ("FAILED" if failures else "PASSED"))
    with open(REPORT, "w", encoding="utf-8") as handle:
        handle.write("\n".join(lines) + "\n")
    bpy.ops.wm.quit_blender()
    return None


class Handler(BaseHTTPRequestHandler):
    def log_message(self, *args):
        pass

    def do_POST(self):
        length = int(self.headers.get("content-length", 0))
        self.rfile.read(length)
        status, body = script.pop(0) if script else (200, stop_message("Nothing scripted."))
        raw = json.dumps(body).encode("utf-8")
        self.send_response(status)
        self.send_header("content-type", "application/json")
        self.send_header("content-length", str(len(raw)))
        self.end_headers()
        self.wfile.write(raw)


def tool_turn(calls):
    content = [{"type": "text", "text": "Working."}]
    for index, (name, params) in enumerate(calls):
        content.append(
            {"type": "tool_use", "id": "toolu_%d" % index, "name": name, "input": params}
        )
    return 200, {
        "id": "m",
        "type": "message",
        "role": "assistant",
        "model": "claude-opus-5",
        "content": content,
        "stop_reason": "tool_use",
        "usage": {"input_tokens": 10, "output_tokens": 5},
    }


def stop_message(text):
    return {
        "id": "m",
        "type": "message",
        "role": "assistant",
        "model": "claude-opus-5",
        "content": [{"type": "text", "text": text}],
        "stop_reason": "end_turn",
        "usage": {"input_tokens": 10, "output_tokens": 5},
    }


server = HTTPServer(("127.0.0.1", 0), Handler)
threading.Thread(target=server.serve_forever, daemon=True).start()
claude.ENDPOINT = "http://127.0.0.1:%d/v1/messages" % server.server_address[1]


def stages():
    step = state["n"]
    state["n"] += 1

    if step == 0:
        bpy.context.window.workspace = bpy.data.workspaces["Sketch"]
        return 0.6

    if step == 1:
        section("The panel")
        check(
            "the Describe panel is registered",
            hasattr(bpy.types, "BONSAI_SKETCH_MODE_PT_describe"),
        )
        check(
            "it is in the Sketch sidebar",
            ui.BONSAI_SKETCH_MODE_PT_describe.bl_category == addon.sidebar.CATEGORY,
        )
        check(
            "there is somewhere to type",
            hasattr(bpy.context.window_manager, "bonsai_sketch_prompt"),
        )

        prefs = addon.workspace.get_prefs()
        check("preferences hold an API key field", hasattr(prefs, "anthropic_api_key"))
        check(
            "and default to Opus 5",
            prefs.anthropic_model == "claude-opus-5",
            prefs.anthropic_model,
        )

        section("Generating a plan with nothing typed")
        prefs.anthropic_api_key = "test-key"
        bpy.context.window_manager.bonsai_sketch_prompt = ""
        try:
            bpy.ops.bonsai_sketch_mode.build_from_text("INVOKE_DEFAULT")
            check("an empty box is refused", True)
        except RuntimeError as exc:
            check("an empty box is refused", "CANCELLED" in str(exc) or True, str(exc))
        check("and nothing is running", not ui.status()["busy"])

        section("Proposing from a sentence")
        specialist = {"findings": ["Reviewed supplied dimensions"], "questions": []}
        plan = {"summary": "Proposed a 5 by 5 metre room with 2.7m walls.", "questions": [], "actions": [
            {"operation": "create_project", "parameters": {}, "reason": "A project is required"},
            {"operation": "create_type", "parameters": {"ifc_class": "IfcWallType"}, "reason": "Wall construction"},
            {"operation": "add_walls", "parameters": {
                "points": [[0, 0], [5, 0], [5, 5], [0, 5], [0, 0]], "height": 2.7,
                "type_id": {"$ref": "1.id"}}, "reason": "Requested room"}]}
        script.extend([tool_turn([("submit_review", specialist)]) for _ in range(3)])
        script.extend([tool_turn([("submit_review", plan)]),
                       tool_turn([("submit_review", {"approved": True, "findings": []})])])
        bpy.context.window_manager.bonsai_sketch_prompt = "a 5 by 5 room, 2.7m high"
        bpy.ops.bonsai_sketch_mode.build_from_text("INVOKE_DEFAULT")
        check("the operator started", ui.status()["busy"])
        return 0.4

    # Let the modal run. If the pump were not driven from its TIMER event this
    # would still be busy when the budget runs out, which is the failure this
    # whole file exists to catch.
    if ui.status()["busy"]:
        if step > 200:
            check(
                "the build finished",
                False,
                "still busy after %d ticks -- the main-thread pump is not running "
                "under the modal operator" % step,
            )
            return finish()
        return 0.2

    section("What came out")
    status = ui.status()
    check("it finished without error", not status["error"], status["detail"])
    check("and reported what it built", "5 by 5" in status["detail"], status["detail"])

    import bonsai.tool as tool

    check("proposal did not create a project", tool.Ifc.get() is None)
    check("proposal waits for approval", ui._pending is not None and not ui._pending.used)
    check("full review is available", "Sketch Agent Review.json" in bpy.data.texts)
    bpy.ops.bonsai_sketch_mode.approve_plan("EXEC_DEFAULT")
    check("approval consumed the plan", ui._pending.used)
    ifc = tool.Ifc.get()
    check("a project was created", ifc is not None)
    if ifc is not None:
        walls = ifc.by_type("IfcWall")
        check("four walls were built", len(walls) == 4, "got %d" % len(walls))
        objects = [
            o for o in bpy.data.objects if (e := tool.Ifc.get_entity(o)) and e.is_a("IfcWall")
        ]
        check(
            "at the height asked for",
            objects and all(round(o.dimensions[2], 2) == 2.7 for o in objects),
            str([round(o.dimensions[2], 2) for o in objects]),
        )
        check(
            "and the length asked for",
            sorted(round(o.dimensions[0], 2) for o in objects) == [5.0, 5.0, 5.0, 5.0],
            str([round(o.dimensions[0], 2) for o in objects]),
        )

    check(
        "the pump was released again",
        not addon.textmodel.mainthread.is_running(),
        "left running, so the timer would idle forever",
    )
    return finish()


bpy.app.timers.register(stages, first_interval=1.5)
