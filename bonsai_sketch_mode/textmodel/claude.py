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

"""The other end of the wire: Claude driving the verbs.

``server`` lets something outside call the verbs. This calls them from a
sentence -- "a 6 by 4 room, three metres high" -- by handing the same
vocabulary to the Messages API as tools and running the tool-use loop.

Why raw HTTP rather than the ``anthropic`` SDK
----------------------------------------------
The SDK is the right default in a Python project, and this is a Python project.
It is not the right default *here*, and the reason is in this add-on's own
manifest: Bonsai pins our supported Blender range because it ships compiled
wheels that must match the host Python. The SDK brings ``pydantic-core`` and
``jiter``, both compiled, so vendoring it would re-import exactly the fragility
that manifest comment exists to warn about -- and it would do so to make one
kind of POST request.

So: ``urllib.request`` from the standard library, which is present in every
Blender, on every platform, at every Python version. If the dependency
situation changes -- a pure-Python SDK, or wheels stop being a portability
problem -- this module is the only thing that would need rewriting, and its
tests would still pass unchanged.

What runs where
---------------
The HTTPS request happens on a worker thread, because a request that takes
twenty seconds on the main thread is twenty seconds of frozen Blender. The
verbs it calls run on the main thread, through ``mainthread.submit``. Neither
half is negotiable, and the split is the same one ``server`` makes.
"""

from __future__ import annotations

import json
import urllib.error
import urllib.request
from typing import Any, Callable, Optional

from . import mainthread, schema

ENDPOINT = "https://api.anthropic.com/v1/messages"
API_VERSION = "2023-06-01"

#: Opus 5. Chosen rather than inherited: this is spatial reasoning against a
#: tool surface, where a weaker model's failure is a wrong building rather than
#: a worse sentence.
DEFAULT_MODEL = "claude-opus-5"

#: Non-streaming, so it stays under the SDK-equivalent HTTP timeout. Nothing
#: here produces long prose -- the output is tool calls and a short report.
MAX_TOKENS = 16000

#: How many times Claude may go round the tool loop before we stop it. A room
#: is three or four calls; twenty is room to recover from mistakes without any
#: chance of an unbounded spend.
MAX_TURNS = 20

REQUEST_TIMEOUT = 120.0

#: Long enough for Bonsai to regenerate a wall run on a slow machine.
VERB_TIMEOUT = 120.0

SYSTEM = """You are modelling a building inside Bonsai, an IFC BIM authoring \
tool, through a small set of tools.

Work in metres. The ground plane is z=0, x runs east, y runs north.

Before changing anything you do not already understand, call describe. It is \
cheap and it tells you what exists.

Order matters: there is no project until create_project, no wall until an \
IfcWallType exists, and plain sketch geometry is not IFC until assign_class \
gives it one. If a tool refuses, the message says what is missing -- read it \
and do that, rather than trying the same call again.

Prefer add_walls for walls. It makes real parametric walls with material \
layers. Drawing a box and calling it a wall is worse in every way that matters \
to a BIM model, even though it looks the same on screen.

You are editing someone's live model. Build what was asked for and nothing \
else: do not tidy, embellish, or add rooms, furniture or storeys nobody asked \
for. If the instruction is ambiguous enough that two readings would give \
different buildings, make the smaller interpretation and say what you assumed.

When you are done, describe what you built in two or three sentences. Give \
real dimensions and classes, not a restatement of the instruction."""


class ClaudeError(RuntimeError):
    """Anything that stopped the request. The message is shown to the user."""


def _post(payload: dict, api_key: str, endpoint: str) -> dict:
    """One Messages API call. Raises ClaudeError with something readable."""
    body = json.dumps(payload).encode("utf-8")
    request = urllib.request.Request(
        endpoint,
        data=body,
        method="POST",
        headers={
            "content-type": "application/json",
            "x-api-key": api_key,
            "anthropic-version": API_VERSION,
        },
    )
    try:
        with urllib.request.urlopen(request, timeout=REQUEST_TIMEOUT) as response:
            return json.loads(response.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        detail = ""
        try:
            detail = json.loads(exc.read().decode("utf-8")).get("error", {}).get("message", "")
        except Exception:
            pass
        # The status codes a user can actually act on, named as such. Anything
        # else keeps the API's own message, which is usually specific.
        if exc.code == 401:
            raise ClaudeError("The API key was rejected. Check it in preferences.")
        if exc.code == 429:
            raise ClaudeError("Rate limited by the API. Wait a moment and try again.")
        if exc.code >= 500:
            raise ClaudeError("The API is having trouble (%s). Try again." % exc.code)
        raise ClaudeError("API error %s: %s" % (exc.code, detail or exc.reason))
    except urllib.error.URLError as exc:
        raise ClaudeError("Could not reach the API: %s" % exc.reason)
    except json.JSONDecodeError:
        raise ClaudeError("The API returned something that was not JSON.")


def _text_of(content: list) -> str:
    return "\n".join(
        block.get("text", "") for block in content if block.get("type") == "text"
    ).strip()


def build(
    instruction: str,
    api_key: str,
    model: str = DEFAULT_MODEL,
    endpoint: Optional[str] = None,
    on_event: Optional[Callable[[str], None]] = None,
) -> dict:
    """Run the instruction to completion. Call this from a worker thread.

    Returns a summary: the closing text, which verbs ran, and token usage.
    Raises ClaudeError for anything the user should be told about.
    """
    from . import commands

    # Read at call time rather than bound as a default, so a test can point the
    # whole add-on at a stub by setting the module attribute.
    endpoint = endpoint or ENDPOINT

    def note(message: str) -> None:
        if on_event is not None:
            try:
                on_event(message)
            except Exception:
                pass

    if not api_key:
        raise ClaudeError("No API key set. Add one in the add-on preferences.")
    if not instruction.strip():
        raise ClaudeError("Nothing to build -- type what you want first.")

    tools = schema.tool_definitions(commands.names())
    messages: list = [{"role": "user", "content": instruction}]
    called: list = []
    input_tokens = 0
    output_tokens = 0

    for turn in range(MAX_TURNS):
        payload = {
            "model": model,
            "max_tokens": MAX_TOKENS,
            "system": SYSTEM,
            "tools": tools,
            "messages": messages,
        }
        note("thinking" if turn == 0 else "thinking (step %d)" % (turn + 1))
        response = _post(payload, api_key, endpoint)

        usage = response.get("usage") or {}
        input_tokens += usage.get("input_tokens") or 0
        output_tokens += usage.get("output_tokens") or 0

        stop_reason = response.get("stop_reason")
        content = response.get("content") or []

        # Checked before reading content: a refusal returns HTTP 200 with a
        # stop_details category, and treating it as a normal empty answer would
        # report success having built nothing.
        if stop_reason == "refusal":
            details = response.get("stop_details") or {}
            raise ClaudeError(
                "The request was declined%s."
                % (" (%s)" % details.get("category") if details.get("category") else "")
            )

        messages.append({"role": "assistant", "content": content})

        if stop_reason != "tool_use":
            return {
                "text": _text_of(content) or "Done.",
                "called": called,
                "turns": turn + 1,
                "input_tokens": input_tokens,
                "output_tokens": output_tokens,
                "stop_reason": stop_reason,
            }

        # Every tool_result for this turn goes back in ONE user message.
        # Splitting them across several teaches the model to stop asking for
        # more than one thing at a time.
        results = []
        for block in content:
            if block.get("type") != "tool_use":
                continue
            name = block.get("name") or ""
            params = block.get("input")
            if not isinstance(params, dict):
                params = {}
            note(name)
            called.append(name)
            try:
                value = mainthread.submit(
                    commands.run, name, params, timeout=VERB_TIMEOUT
                )
                result = {
                    "type": "tool_result",
                    "tool_use_id": block.get("id"),
                    "content": json.dumps(value, default=str),
                }
            except Exception as exc:
                # Handed back as a failed result rather than raised: a refusal
                # is information the model can act on, and it usually does --
                # "no IfcWallType exists" is answered by creating one.
                result = {
                    "type": "tool_result",
                    "tool_use_id": block.get("id"),
                    "content": "%s: %s" % (type(exc).__name__, exc),
                    "is_error": True,
                }
            results.append(result)

        if not results:
            raise ClaudeError("The model asked to use a tool but named none.")
        messages.append({"role": "user", "content": results})

    raise ClaudeError(
        "Stopped after %d steps without finishing. Try a smaller instruction." % MAX_TURNS
    )
