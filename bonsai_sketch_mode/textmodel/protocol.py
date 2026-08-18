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

"""Framing, and how a client finds the channel.

One JSON object per line, in both directions. Not because a framed binary
protocol would be worse, but because the first thing anyone does with a new
socket is talk to it by hand, and this can be driven from a terminal.

Requests carry a token. It is not authentication in any serious sense -- it
stops another process on the same machine from writing to the model by
accident, which is the realistic risk on a loopback socket, and it is cheap.
"""

from __future__ import annotations

import json
import os
import secrets
from typing import Any, Optional

import bpy

#: One request or response per line.
TERMINATOR = "\n"

#: Refuse anything larger rather than buffer it. A wall run of a few thousand
#: points is well inside this; a megabyte on this socket is a mistake.
MAX_REQUEST_BYTES = 1 << 20

ENCODING = "utf-8"

DISCOVERY_NAME = "textmodel.json"


def new_token() -> str:
    return secrets.token_hex(16)


def discovery_path() -> str:
    """The file a client reads to find the port and token.

    In Blender's own config directory, because that is a per-user location
    that already exists on every platform, and is not world-writable.
    """
    config = bpy.utils.user_resource("CONFIG", path="bonsai_sketch_mode", create=True)
    return os.path.join(config, DISCOVERY_NAME)


def write_discovery(port: int, token: str) -> Optional[str]:
    """Publish the port and token. Returns the path, or None if it failed."""
    path = discovery_path()
    payload = {
        "port": port,
        "token": token,
        "pid": os.getpid(),
        "blender": bpy.app.version_string,
        "protocol": 1,
    }
    try:
        with open(path, "w", encoding=ENCODING) as handle:
            json.dump(payload, handle, indent=2)
    except OSError:
        return None
    # Best effort: on POSIX the token should not be world-readable. Windows
    # ignores the mode, and the file sits in the user's own config directory
    # there, so this is not the only thing standing between it and a reader.
    try:
        os.chmod(path, 0o600)
    except OSError:
        pass
    return path


def clear_discovery() -> None:
    """Remove the discovery file, so a stale port is never advertised."""
    try:
        os.remove(discovery_path())
    except OSError:
        pass


def encode(payload: Any) -> bytes:
    """One response, framed. Never raises on unserialisable content."""
    try:
        text = json.dumps(payload, default=str)
    except (TypeError, ValueError) as exc:
        text = json.dumps({"ok": False, "error": f"result was not serialisable: {exc}"})
    return (text + TERMINATOR).encode(ENCODING)


def decode(line: bytes) -> dict:
    """One request. Raises ValueError on anything that is not an object."""
    payload = json.loads(line.decode(ENCODING))
    if not isinstance(payload, dict):
        raise ValueError("a request must be a JSON object")
    return payload


def ok(request_id: Any, result: Any) -> dict:
    return {"id": request_id, "ok": True, "result": result}


def error(request_id: Any, message: str) -> dict:
    return {"id": request_id, "ok": False, "error": message}
