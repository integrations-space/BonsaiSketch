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

"""Text to model: a command channel into a running Blender.

Why this is a package rather than a module
------------------------------------------
Everything else in this add-on is interaction -- a tool, a key, a face under
the cursor. This is not. It is a second way in, for a caller that is not a
person at a mouse: an LLM agent, a script, a CI job.

That difference is why it is boxed off behind its own ``__init__``:

- **It is optional, and off unless asked for.** A socket that can write to the
  model is not something to open because an add-on happened to be installed.
  The preference defaults to off, the listener is bound to loopback, and every
  request carries a token generated for that session.
- **It has one entry point.** ``register`` and ``unregister`` here are the
  whole surface. Nothing outside imports ``server`` or ``commands``, so this
  can be lifted out, shipped separately, or left out of a build without
  touching a line of the drawing tools.
- **It is a candidate for extraction.** The user's own IDD stack already
  declares a ``bonsai_adapter`` -- local-service transport, geometry-write,
  headless, currently offline. This package is the shape of that adapter's
  missing half. Keeping it self-contained is what makes wrapping it later a
  wrapping job rather than a rewrite.

What it deliberately is not
---------------------------
There is no model, no prompt, and no API key here. This does not talk to
Claude; it is the thing Claude talks *to*. The reasoning stays outside, where
it can be swapped, audited or run by a person instead. All this package owns is
a small vocabulary of verbs with an IFC model behind them, and the discipline
that Blender's API is single-threaded so the socket may never touch it.

Governance is also outside. Every verb here writes when told to. Routing those
writes through a proposal and a human gate is the adapter's job, not the
socket's, and putting it here would only mean building it twice.
"""

from __future__ import annotations

from typing import Optional

from . import server, ui

#: Re-exported so callers need only this package.
DEFAULT_PORT = server.DEFAULT_PORT


def register(port: int = DEFAULT_PORT) -> tuple[bool, str]:
    """Open the socket channel. Returns (ok, message). Never raises."""
    return server.start(port)


def unregister() -> None:
    """Close the socket channel. The panel is registered separately."""
    server.stop()


def register_ui() -> tuple[bool, str]:
    """Add the Describe panel. Independent of the socket, and always on.

    The panel costs nothing until it is used and asks for no permission --
    unlike the socket, which is a listener and stays shut until asked for.
    """
    return ui.register()


def unregister_ui() -> None:
    ui.unregister()


def is_running() -> bool:
    return server.is_running()


def status() -> str:
    return server.status()


def discovery_file() -> Optional[str]:
    """Where a client finds the port and token, or None when not running."""
    return server.discovery_file()
