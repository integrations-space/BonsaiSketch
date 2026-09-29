"""Drive the text-to-model channel over a real socket, then quit.

Run with:
    blender --python tools/textmodel_check.py -- <report-file>

There is no `-b`. The channel is built on `bpy.app.timers`, and background mode
has no event loop to fire them -- the socket would accept a connection and then
never answer it. That is not a bug in the channel; it is what "drive a running
Blender" means. A headless caller wants `bonsai_check.py`, which calls the same
operators directly.

The client half runs in a worker thread inside this same Blender. That is not a
shortcut, it is the check: the worker only ever touches the socket, the main
thread only ever touches `bpy`, and if that separation were wrong this is where
it would show.
"""

import json
import socket
import sys
import threading
import traceback

import bpy

ADDON = "bl_ext.user_default.bonsai_sketch_mode"
REPORT = sys.argv[-1] if "--" in sys.argv else "textmodel_check.txt"

lines = []
failures = []
checks = 0
state = {"thread": None, "done": threading.Event()}

bpy.ops.preferences.addon_enable(module="bl_ext.blender_org.bonsai")
bpy.ops.preferences.addon_enable(module=ADDON)


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
    addon = sys.modules.get(ADDON)
    if addon is not None:
        addon.textmodel.unregister()
        check("channel closes cleanly", not addon.textmodel.is_running())
        # The discovery file must not outlive the socket, or the next client
        # connects to a port that is no longer listening.
        import os

        check(
            "discovery file is removed on close",
            not os.path.exists(addon.textmodel.server.protocol.discovery_path()),
        )

    lines.append("\n%d/%d checks passed" % (checks - len(failures), checks))
    if failures:
        lines.append("failed:")
        for name in failures:
            lines.append("  - %s" % name)
    lines.append("TEXTMODEL CHECK %s" % ("FAILED" if failures else "PASSED"))
    with open(REPORT, "w", encoding="utf-8") as handle:
        handle.write("\n".join(lines) + "\n")
    bpy.ops.wm.quit_blender()
    return None


# --- The client half, on a worker thread -------------------------------------


class Client:
    def __init__(self, port, token):
        self.port = port
        self.token = token
        self.connection = socket.create_connection(("127.0.0.1", port), timeout=70.0)
        self.buffer = b""
        self.next_id = 0

    def call(self, command, params=None, token=None):
        self.next_id += 1
        request = {
            "id": self.next_id,
            "token": self.token if token is None else token,
            "command": command,
            "params": params or {},
        }
        self.connection.sendall((json.dumps(request) + "\n").encode("utf-8"))
        while b"\n" not in self.buffer:
            chunk = self.connection.recv(8192)
            if not chunk:
                raise RuntimeError("connection closed")
            self.buffer += chunk
        line, _, self.buffer = self.buffer.partition(b"\n")
        return json.loads(line.decode("utf-8"))

    def close(self):
        try:
            self.connection.close()
        except OSError:
            pass


def exercise(port, token):
    """Everything a caller would do, in the order they would do it."""
    try:
        client = Client(port, token)
    except Exception as exc:
        check("client can connect", False, str(exc))
        state["done"].set()
        return

    check("client can connect", True)

    try:
        section("Refusals")
        bad = client.call("ping", token="not-the-token")
        check("a wrong token is refused", bad.get("ok") is False, json.dumps(bad))
        check("and says why", "token" in (bad.get("error") or ""))

        unknown = client.call("nonsense")
        check("an unknown command is refused", unknown.get("ok") is False)

        section("Looking, before anything exists")
        pong = client.call("ping")
        check("ping answers", pong.get("ok") is True, json.dumps(pong))
        result = pong.get("result", {})
        check("ping reports Bonsai", bool(result.get("bonsai")), json.dumps(result))
        check("ping reports no project yet", result.get("project_open") is False)
        check("ping lists its vocabulary", len(result.get("commands", [])) >= 8)

        gated = client.call("add_walls", {"points": [[0, 0], [1, 0]]})
        check("add_walls refuses without a project", gated.get("ok") is False)
        check(
            "and names the fix",
            "create_project" in (gated.get("error") or ""),
            gated.get("error", ""),
        )

        section("Text to model")
        made = client.call("create_project")
        check("create_project works", made.get("ok") is True, json.dumps(made))

        typed = client.call("create_type", {"ifc_class": "IfcWallType"})
        check("create_type makes an IfcWallType", typed.get("ok") is True, json.dumps(typed))

        # The verb this package exists for: a room, described as words would.
        room = client.call(
            "add_walls",
            {"points": [[0, 0], [6, 0], [6, 4], [0, 4], [0, 0]], "height": 3.0},
        )
        check("add_walls builds a room", room.get("ok") is True, json.dumps(room))
        walls = (room.get("result") or {}).get("walls", [])
        check("four walls, one per side", len(walls) == 4, "got %d" % len(walls))
        check(
            "every one is a real IfcWall",
            all(w.get("ifc_class") == "IfcWall" for w in walls),
            json.dumps(walls),
        )
        check(
            "they are 3m high and 6m/4m long",
            sorted(round(w["dimensions"][0], 2) for w in walls) == [4.0, 4.0, 6.0, 6.0]
            and all(round(w["dimensions"][2], 2) == 3.0 for w in walls),
            json.dumps([w["dimensions"] for w in walls]),
        )

        section("Sketch, then name")
        drawn = client.call(
            "sketch_polyline",
            {"points": [[10, 0], [14, 0], [14, 3], [10, 3]], "close": True},
        )
        check("sketch_polyline draws", drawn.get("ok") is True, json.dumps(drawn))
        name = (drawn.get("result") or {}).get("object")
        check("a closed loop becomes a face", (drawn.get("result") or {}).get("faces_created") == 1)

        pushed = client.call("push_pull", {"object": name, "distance": 2.5})
        check("push_pull extrudes it", pushed.get("ok") is True, json.dumps(pushed))
        result = pushed.get("result") or {}
        # This read used to come back as 0.0 in a GUI session and correct
        # headlessly, because obj.dimensions lags the depsgraph. Worth keeping.
        check(
            "the reply reports the height it actually made",
            round(result.get("dimensions", [0, 0, 0])[2], 3) == 2.5,
            json.dumps(result),
        )
        check(
            "and which way the face pointed",
            len(result.get("normal") or []) == 3,
            json.dumps(result),
        )

        named = client.call("assign_class", {"object": name, "ifc_class": "IfcSlab"})
        check("assign_class makes it IFC", named.get("ok") is True, json.dumps(named))
        check(
            "and it is the class asked for",
            (named.get("result") or {}).get("ifc_class") == "IfcSlab",
            json.dumps(named.get("result")),
        )

        again = client.call("push_pull", {"object": name, "distance": 1.0})
        check("push_pull then refuses the IFC element", again.get("ok") is False)

        section("Looking, after")
        described = client.call("describe")
        check("describe answers", described.get("ok") is True)
        model = described.get("result") or {}
        check("it counts the walls", model.get("elements", {}).get("IfcWall") == 4, json.dumps(model.get("elements")))
        check("it counts the slab", model.get("elements", {}).get("IfcSlab") == 1)

        listed = client.call("list_elements", {"ifc_class": "IfcWall"})
        check("list_elements returns the walls", len(listed.get("result") or []) == 4)

    except Exception:
        check("client ran without raising", False, traceback.format_exc())
    finally:
        client.close()
        state["done"].set()


# --- Main thread -------------------------------------------------------------


def begin():
    addon = sys.modules.get(ADDON)
    if addon is None:
        check("add-on importable", False)
        return finish()

    section("Opening the channel")
    check("closed until asked", not addon.textmodel.is_running())

    ok, message = addon.textmodel.register()
    check("channel opens", ok, message)
    if not ok:
        return finish()
    lines.append("  note  %s" % message)

    path = addon.textmodel.discovery_file()
    check("a discovery file is published", bool(path), "no path returned")
    if not path:
        return finish()
    with open(path, encoding="utf-8") as handle:
        info = json.load(handle)
    check("it carries a port", isinstance(info.get("port"), int))
    check("it carries a token", isinstance(info.get("token"), str) and len(info["token"]) >= 32)

    worker = threading.Thread(target=exercise, args=(info["port"], info["token"]), daemon=True)
    worker.start()
    state["thread"] = worker

    bpy.app.timers.register(wait, first_interval=0.2)
    return None


def wait():
    """Let the main thread keep running the pump until the client is done."""
    if state["done"].is_set():
        return finish()
    return 0.2


bpy.app.timers.register(begin, first_interval=1.0)
