"""Talk to a running Blender's text-to-model channel from a terminal.

    python tools/textmodel_client.py ping
    python tools/textmodel_client.py create_project
    python tools/textmodel_client.py create_type '{"ifc_class": "IfcWallType"}'
    python tools/textmodel_client.py add_walls '{"points": [[0,0],[6,0],[6,4],[0,4],[0,0]], "height": 3}'
    python tools/textmodel_client.py describe

Open the channel first: Preferences > Add-ons > Bonsai Sketch Mode > Text to
Model > Open. The port and token are published to a discovery file, which this
finds on its own, so there is nothing to copy between the two.

This is a client, not a library -- it is here so the channel can be driven and
tested by hand, and so an agent has a worked example of the wire format.
"""

import json
import os
import socket
import sys

DISCOVERY = os.path.join(
    os.path.expanduser("~"),
    "AppData",
    "Roaming",
    "Blender Foundation",
    "Blender",
)

TIMEOUT = 70.0


def find_discovery(explicit=None):
    """The newest textmodel.json Blender has published, or the one given."""
    if explicit:
        return explicit
    candidates = []
    for root, _dirs, files in os.walk(DISCOVERY):
        if "textmodel.json" in files:
            candidates.append(os.path.join(root, "textmodel.json"))
    if not candidates:
        raise SystemExit(
            "No text-to-model channel found. Open it in the add-on preferences, "
            "or pass the discovery file path with --discovery"
        )
    return max(candidates, key=os.path.getmtime)


def call(command, params=None, discovery=None):
    path = find_discovery(discovery)
    with open(path, encoding="utf-8") as handle:
        info = json.load(handle)

    request = {
        "id": 1,
        "token": info["token"],
        "command": command,
        "params": params or {},
    }

    try:
        connection = socket.create_connection(("127.0.0.1", info["port"]), timeout=TIMEOUT)
    except OSError as exc:
        # The channel removes this file when it closes, but a Blender that was
        # killed never got the chance -- so the file outlives the port it
        # advertises. That is the common case in practice, and a raw traceback
        # reads as "the tool is broken" rather than "that Blender is gone".
        raise SystemExit(
            "Nothing is listening on 127.0.0.1:%s (%s).\n"
            "That channel was published by Blender pid %s. If it has quit, this "
            "file is stale -- reopen the channel in the add-on preferences, or "
            "delete it:\n  %s" % (info["port"], exc, info.get("pid"), path)
        )

    with connection:
        connection.sendall((json.dumps(request) + "\n").encode("utf-8"))
        buffer = b""
        while b"\n" not in buffer:
            chunk = connection.recv(4096)
            if not chunk:
                raise SystemExit("Blender closed the connection without replying")
            buffer += chunk
    return json.loads(buffer.split(b"\n")[0].decode("utf-8"))


def main(argv):
    if not argv or argv[0] in ("-h", "--help"):
        print(__doc__)
        return 0

    discovery = None
    if "--discovery" in argv:
        index = argv.index("--discovery")
        discovery = argv[index + 1]
        argv = argv[:index] + argv[index + 2 :]

    command = argv[0]
    params = json.loads(argv[1]) if len(argv) > 1 else {}

    response = call(command, params, discovery)
    print(json.dumps(response, indent=2))
    return 0 if response.get("ok") else 1


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
