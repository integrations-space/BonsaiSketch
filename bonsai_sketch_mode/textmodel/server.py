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

"""The listener, and the one rule that shapes all of it.

Blender's Python API is not thread-safe. Touching ``bpy`` from a socket thread
does not raise -- it corrupts state, or crashes the process minutes later
somewhere unrelated, which is the worst failure mode available. So no code in
this module calls into the model.

The shape that follows from that:

    socket thread     reads a request, puts it on a queue, waits
    main thread       a timer drains the queue, runs the verb, sets the result
    socket thread     wakes, writes the response

A request therefore costs at least one timer interval, which is the price of
never touching ``bpy`` off the main thread. It is not a slow price -- the pump
runs at 20 Hz -- and it is the only correct one.

The pump itself lives in ``mainthread``, because the Claude client needs the
same trick and two copies of it would be one too many.

The listener binds to loopback and nothing else. Blender has no notion of a
privileged operation, so anything that can reach this socket can rewrite the
model; that is a local development channel by construction, not a service.
"""

from __future__ import annotations

import hmac
import socket
import threading
import traceback
from typing import Any, Optional

from . import mainthread, protocol

#: Chosen high and unassigned. Configurable in preferences.
DEFAULT_PORT = 4271

#: Loopback only, and not configurable. A listener that can rewrite the user's
#: model has no business being reachable from another machine.
HOST = "127.0.0.1"

#: How long a client waits for the main thread. Generous, because the main
#: thread may be busy drawing, and a modal operator blocks the pump entirely.
REQUEST_TIMEOUT = 60.0

#: Read timeout on an idle connection, so a client that goes away is dropped.
SOCKET_TIMEOUT = 300.0

_state: dict[str, Any] = {
    "socket": None,
    "thread": None,
    "token": None,
    "port": None,
    "path": None,
    "running": False,
    "served": 0,
}

# --- Socket threads ----------------------------------------------------------


def _matches_token(candidate: str) -> bool:
    expected = _state["token"]
    return isinstance(expected, str) and hmac.compare_digest(candidate, expected)


def _dispatch(payload: dict) -> dict:
    """Validate one request and run it through the main thread."""
    request_id = payload.get("id")

    token = payload.get("token")
    if not isinstance(token, str) or not _matches_token(token):
        return protocol.error(request_id, "bad or missing token")

    command = payload.get("command")
    if not isinstance(command, str) or not command:
        return protocol.error(request_id, "no command given")

    params = payload.get("params") or {}
    if not isinstance(params, dict):
        return protocol.error(request_id, "params must be an object")

    # commands reaches into the rest of the add-on, so it is imported here
    # rather than at module scope: the socket layer stays importable on its own.
    from . import commands

    try:
        result = mainthread.submit(commands.run, command, params, timeout=REQUEST_TIMEOUT)
    except Exception as exc:
        return protocol.error(request_id, "%s: %s" % (type(exc).__name__, exc))
    _state["served"] += 1
    return protocol.ok(request_id, result)


def _serve(connection: socket.socket) -> None:
    """One client, until it goes away. Several may be open at once."""
    connection.settimeout(SOCKET_TIMEOUT)
    buffer = b""
    try:
        with connection:
            while _state["running"]:
                try:
                    chunk = connection.recv(4096)
                except (socket.timeout, OSError):
                    return
                if not chunk:
                    return
                buffer += chunk
                if len(buffer) > protocol.MAX_REQUEST_BYTES:
                    connection.sendall(protocol.encode(protocol.error(None, "request too large")))
                    return
                while b"\n" in buffer:
                    line, _, buffer = buffer.partition(b"\n")
                    if not line.strip():
                        continue
                    try:
                        payload = protocol.decode(line)
                    except Exception as exc:
                        response = protocol.error(None, "could not read request: %s" % exc)
                    else:
                        response = _dispatch(payload)
                    try:
                        connection.sendall(protocol.encode(response))
                    except OSError:
                        return
    except Exception:  # pragma: no cover - a client hanging up mid-write
        traceback.print_exc()


def _accept(listener: socket.socket) -> None:
    """Accept loop. Ends when the listener is closed by stop()."""
    while _state["running"]:
        try:
            connection, _address = listener.accept()
        except OSError:
            return
        worker = threading.Thread(target=_serve, args=(connection,), daemon=True)
        worker.start()


# --- Lifecycle ---------------------------------------------------------------


def start(port: int = DEFAULT_PORT) -> tuple[bool, str]:
    """Open the channel. Returns (ok, message). Never raises."""
    if _state["running"]:
        return True, "Text-to-model already listening on %s:%s" % (HOST, _state["port"])

    token = protocol.new_token()
    try:
        listener = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        # Deliberately no SO_REUSEADDR: a port already in use should be
        # reported, not quietly shared with whatever else is on it.
        listener.bind((HOST, int(port)))
        listener.listen(4)
    except OSError as exc:
        return False, "Could not listen on %s:%s: %s" % (HOST, port, exc)

    _state.update(
        socket=listener,
        token=token,
        port=listener.getsockname()[1],
        running=True,
        served=0,
    )

    thread = threading.Thread(
        target=_accept, args=(listener,), daemon=True, name="bonsai-sketch-textmodel"
    )
    thread.start()
    _state["thread"] = thread

    mainthread.acquire()

    _state["path"] = protocol.write_discovery(_state["port"], token)
    where = _state["path"] or "(discovery file could not be written)"
    return True, "Text-to-model listening on %s:%s -- %s" % (HOST, _state["port"], where)


def stop() -> None:
    """Close the channel. Safe to call when it was never started."""
    if not _state["running"]:
        protocol.clear_discovery()
        return

    _state["running"] = False

    listener = _state["socket"]
    if listener is not None:
        try:
            listener.close()
        except OSError:
            pass

    # Anything still queued is released by the pump when the last user lets go.
    mainthread.release()

    protocol.clear_discovery()
    _state.update(socket=None, thread=None, token=None, port=None, path=None)


def is_running() -> bool:
    return bool(_state["running"])


def port() -> Optional[int]:
    return _state["port"]


def discovery_file() -> Optional[str]:
    return _state["path"]


def status() -> str:
    if not _state["running"]:
        return "Not listening"
    return "Listening on %s:%s (%s requests served)" % (HOST, _state["port"], _state["served"])
