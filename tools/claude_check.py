"""Drive the Claude tool-use loop against a stub Messages API, then quit.

Run with:
    blender -b --python tools/claude_check.py

No API key, no network, no spend. A local HTTP server speaks the shape the
Messages API speaks, and `claude.build` is pointed at it. What is under test is
everything we actually wrote: the loop, the tool definitions, the batching of
tool results, the refusal path, the error paths, and the rule that verbs run on
the main thread and the HTTP call does not.

This runs headless because the test drives the main-thread pump itself rather
than waiting for `bpy.app.timers` -- which is the same thing the modal operator
does, and the reason it can be checked without a GUI.

The stub also records every request, so the checks can assert what went *out*,
not only what came back. Two of those rules are invisible from the outside and
easy to break: all tool results for a turn must go back in one user message,
and the tool list must be byte-stable across calls or the prompt cache misses.
"""

import json
import sys
import threading
import traceback
from http.server import BaseHTTPRequestHandler, HTTPServer

import bpy

ADDON = "bl_ext.user_default.bonsai_sketch_mode"

failures = []
checks = 0
requests_seen = []
script = []


def check(label, condition, detail=""):
    global checks
    checks += 1
    if condition:
        print("  ok    %s" % label)
    else:
        print("  FAIL  %s%s" % (label, " -- %s" % detail if detail else ""))
        failures.append(label)


def section(title):
    print("\n%s" % title)


bpy.ops.preferences.addon_enable(module="bl_ext.blender_org.bonsai")
bpy.ops.preferences.addon_enable(module=ADDON)

import importlib

addon = sys.modules[ADDON]
claude = addon.textmodel.claude
mainthread = addon.textmodel.mainthread
schema = addon.textmodel.schema
# commands is imported lazily by server and claude, so it is not an attribute
# of the package until one of them has run. Import it directly.
commands = importlib.import_module(ADDON + ".textmodel.commands")
bridge = addon.bridge

import bonsai.tool as tool


# --- The stub -----------------------------------------------------------------


class Handler(BaseHTTPRequestHandler):
    def log_message(self, *args):
        pass

    def do_POST(self):
        length = int(self.headers.get("content-length", 0))
        payload = json.loads(self.rfile.read(length).decode("utf-8"))
        # Lower-cased because HTTP header names are case-insensitive and
        # urllib title-cases them on the wire ("X-api-key"). Comparing the raw
        # dict would fail on a request that is perfectly correct.
        headers = {k.lower(): v for k, v in self.headers.items()}
        requests_seen.append({"headers": headers, "body": payload})

        if script:
            status, body = script.pop(0)
        else:
            status, body = 200, message_stop("Nothing scripted.")

        raw = json.dumps(body).encode("utf-8")
        self.send_response(status)
        self.send_header("content-type", "application/json")
        self.send_header("content-length", str(len(raw)))
        self.end_headers()
        self.wfile.write(raw)


def tool_turn(calls):
    """An assistant turn that asks for one or more tools."""
    content = [{"type": "text", "text": "Working on it."}]
    for index, (name, params) in enumerate(calls):
        content.append(
            {"type": "tool_use", "id": "toolu_%d" % index, "name": name, "input": params}
        )
    return 200, {
        "id": "msg_x",
        "type": "message",
        "role": "assistant",
        "model": "claude-opus-5",
        "content": content,
        "stop_reason": "tool_use",
        "usage": {"input_tokens": 100, "output_tokens": 50},
    }


def message_stop(text):
    return {
        "id": "msg_x",
        "type": "message",
        "role": "assistant",
        "model": "claude-opus-5",
        "content": [{"type": "text", "text": text}],
        "stop_reason": "end_turn",
        "usage": {"input_tokens": 100, "output_tokens": 50},
    }


server = HTTPServer(("127.0.0.1", 0), Handler)
threading.Thread(target=server.serve_forever, daemon=True).start()
ENDPOINT = "http://127.0.0.1:%d/v1/messages" % server.server_address[1]


def run_build(instruction, key="test-key"):
    """Run claude.build on a worker thread while this thread pumps."""
    outcome = {}

    def work():
        try:
            outcome["result"] = claude.build(instruction, api_key=key, endpoint=ENDPOINT)
        except Exception as exc:
            outcome["error"] = exc

    mainthread.acquire()
    try:
        worker = threading.Thread(target=work, daemon=True)
        worker.start()
        # Exactly what the modal operator does on each TIMER event.
        for _ in range(4000):
            mainthread.pump_once()
            worker.join(0.01)
            if not worker.is_alive():
                break
        mainthread.pump_once()
    finally:
        mainthread.release()
    return outcome


# --- The vocabulary it offers -------------------------------------------------

section("Tool definitions")

missing = schema.undescribed(commands.names())
check(
    "every verb is described to the model",
    not missing,
    "undescribed: %s" % missing,
)
definitions = schema.tool_definitions(commands.names())
check("one definition per verb", len(definitions) == len(commands.names()))
check(
    "each has a name, description and schema",
    all(d.get("name") and d.get("description") and d.get("input_schema") for d in definitions),
)
check(
    "the order is stable across calls",
    definitions == schema.tool_definitions(list(reversed(commands.names()))),
    "an unstable tool list would miss the prompt cache on every request",
)


# --- Refusals before anything is sent ----------------------------------------

section("Refusing before spending anything")

outcome = run_build("build me a house", key="")
check(
    "an empty API key is refused locally",
    isinstance(outcome.get("error"), claude.ClaudeError),
    str(outcome),
)
check("and nothing was sent", not requests_seen, "%d requests" % len(requests_seen))

outcome = run_build("   ")
check("an empty instruction is refused", isinstance(outcome.get("error"), claude.ClaudeError))
check("and still nothing was sent", not requests_seen)


# --- The loop ------------------------------------------------------------------

section("Building a room from a sentence")

script.extend(
    [
        tool_turn([("describe", {}), ("create_project", {})]),
        tool_turn([("create_type", {"ifc_class": "IfcWallType"})]),
        tool_turn([("add_walls", {"points": [[0, 0], [6, 0], [6, 4], [0, 4], [0, 0]], "height": 3})]),
        (200, message_stop("Built a 6 by 4 metre room with four 3m walls.")),
    ]
)
requests_seen.clear()

outcome = run_build("a 6 by 4 metre room, 3 metres high")
check("the loop completed", "result" in outcome, str(outcome.get("error")))

if "result" in outcome:
    result = outcome["result"]
    check(
        "it ran the verbs the model asked for",
        result["called"] == ["describe", "create_project", "create_type", "add_walls"],
        str(result["called"]),
    )
    check("it took four turns", result["turns"] == 4, str(result["turns"]))
    check("it returned the closing text", "6 by 4" in result["text"], result["text"])
    check("it totalled usage across turns", result["input_tokens"] == 400)

ifc = tool.Ifc.get()
check("a project really exists", ifc is not None)
if ifc is not None:
    walls = ifc.by_type("IfcWall")
    check("four real IfcWalls were built", len(walls) == 4, "got %d" % len(walls))
    objects = [o for o in bpy.data.objects if (e := tool.Ifc.get_entity(o)) and e.is_a("IfcWall")]
    check(
        "at the sizes asked for",
        sorted(round(o.dimensions[0], 2) for o in objects) == [4.0, 4.0, 6.0, 6.0]
        and all(round(o.dimensions[2], 2) == 3.0 for o in objects),
        str([tuple(round(v, 2) for v in o.dimensions) for o in objects]),
    )


# --- What went out over the wire ----------------------------------------------

section("The requests it sent")

check("one request per turn", len(requests_seen) == 4, "%d" % len(requests_seen))
if requests_seen:
    first = requests_seen[0]
    check("the API key is sent as x-api-key", first["headers"].get("x-api-key") == "test-key")
    check(
        "the API version header is set",
        first["headers"].get("anthropic-version") == claude.API_VERSION,
    )
    body = first["body"]
    check("the model is Opus 5", body["model"] == "claude-opus-5", body["model"])
    check("tools are declared", len(body.get("tools", [])) == len(commands.names()))
    check("a system prompt is sent", bool(body.get("system")))
    check(
        "no removed parameters are sent",
        not any(k in body for k in ("temperature", "top_p", "top_k")),
        "these return 400 on Opus 5",
    )
    check(
        "no budget_tokens is sent",
        "budget_tokens" not in json.dumps(body.get("thinking") or {}),
        "budget_tokens returns 400 on Opus 5",
    )

    # The rule that is invisible from outside: two tools were asked for in one
    # turn, so both results must come back in a single user message. Splitting
    # them teaches the model to stop asking for more than one thing at a time.
    second = requests_seen[1]["body"]["messages"]
    tool_result_messages = [
        m
        for m in second
        if m["role"] == "user"
        and isinstance(m["content"], list)
        and any(b.get("type") == "tool_result" for b in m["content"])
    ]
    check(
        "both results from a parallel turn came back in one user message",
        len(tool_result_messages) == 1,
        "%d user messages carried tool results" % len(tool_result_messages),
    )
    check(
        "and it carried both of them",
        len(tool_result_messages[0]["content"]) == 2 if tool_result_messages else False,
    )
    check(
        "the assistant turn was echoed back unchanged",
        any(m["role"] == "assistant" for m in second),
    )


# --- Failure paths -------------------------------------------------------------

section("When things go wrong")

script.clear()
requests_seen.clear()
script.extend(
    [
        # A verb that will refuse: no such class. The model should see the
        # refusal as a result rather than the run dying.
        tool_turn([("assign_class", {"object": "nope", "ifc_class": "IfcSlab"})]),
        (200, message_stop("That object does not exist, so I stopped.")),
    ]
)
outcome = run_build("classify something that is not there")
check("a refused verb does not kill the run", "result" in outcome, str(outcome.get("error")))
if len(requests_seen) > 1:
    results = [
        block
        for message in requests_seen[1]["body"]["messages"]
        if isinstance(message["content"], list)
        for block in message["content"]
        if block.get("type") == "tool_result"
    ]
    check("the failure was handed back as a tool result", bool(results))
    check("marked as an error", results and results[0].get("is_error") is True)
    check(
        "with a message naming the problem",
        results and "nope" in str(results[0].get("content")),
        str(results[0].get("content")) if results else "",
    )

script.clear()
requests_seen.clear()
script.append(
    (
        200,
        {
            "id": "msg_x",
            "type": "message",
            "role": "assistant",
            "model": "claude-opus-5",
            "content": [],
            "stop_reason": "refusal",
            "stop_details": {"type": "refusal", "category": "cyber"},
            "usage": {"input_tokens": 10, "output_tokens": 0},
        },
    )
)
outcome = run_build("something declined")
check("a refusal stop_reason is surfaced", isinstance(outcome.get("error"), claude.ClaudeError))
check(
    "and names the category",
    "cyber" in str(outcome.get("error", "")),
    str(outcome.get("error")),
)

script.clear()
requests_seen.clear()
script.append((401, {"error": {"message": "invalid x-api-key"}}))
outcome = run_build("anything")
check("a 401 becomes a readable message", isinstance(outcome.get("error"), claude.ClaudeError))
check(
    "that says to check the key",
    "key" in str(outcome.get("error", "")).lower(),
    str(outcome.get("error")),
)

script.clear()
requests_seen.clear()
script.append((429, {"error": {"message": "slow down"}}))
outcome = run_build("anything")
check(
    "a 429 says to wait rather than showing a stack trace",
    "Rate limited" in str(outcome.get("error", "")),
    str(outcome.get("error")),
)

section("Runaway protection")
script.clear()
requests_seen.clear()
# Never stops asking for tools.
for _ in range(claude.MAX_TURNS + 5):
    script.append(tool_turn([("ping", {})]))
outcome = run_build("loop forever")
check(
    "a model that never finishes is stopped",
    isinstance(outcome.get("error"), claude.ClaudeError)
    and "Stopped after" in str(outcome["error"]),
    str(outcome.get("error")),
)
check(
    "after exactly MAX_TURNS requests",
    len(requests_seen) == claude.MAX_TURNS,
    "%d" % len(requests_seen),
)


# --- Result --------------------------------------------------------------------

server.shutdown()
print("\n%d/%d checks passed" % (checks - len(failures), checks))
if failures:
    print("failed:")
    for name in failures:
        print("  - %s" % name)
    sys.exit(1)
print("CLAUDE CHECK PASSED")
sys.exit(0)
