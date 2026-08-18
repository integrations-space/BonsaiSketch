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

"""Run something on Blender's main thread, from a thread that is not it.

Blender's Python API is not thread-safe, and there are now two callers that
need this: the socket server, and the Claude client. Both do their waiting off
the main thread -- one on a socket, one on an HTTPS request -- and both must
touch the model only from it.

    worker thread     submit(fn) -> queued, then blocks
    main thread       a timer drains the queue and runs fn
    worker thread     wakes with the return value, or the exception

The pump is reference counted. Two independent features share one timer, and
the last one to let go is what stops it -- so closing the socket does not
strand a Claude request that is still mid-flight.
"""

from __future__ import annotations

import queue
import threading
import traceback
from typing import Any, Callable, Optional

import bpy

#: How often the main thread drains the queue.
PUMP_INTERVAL = 0.05

#: Default ceiling on how long a caller waits. The main thread may be busy
#: drawing, and a modal operator blocks the timer outright.
TIMEOUT = 60.0


class Timeout(RuntimeError):
    """The main thread did not get to the call in time."""


class Cancelled(RuntimeError):
    """The pump stopped while the call was still queued."""


class _Call:
    __slots__ = ("function", "args", "kwargs", "done", "result", "error")

    def __init__(self, function: Callable, args: tuple, kwargs: dict) -> None:
        self.function = function
        self.args = args
        self.kwargs = kwargs
        self.done = threading.Event()
        self.result: Any = None
        self.error: Optional[BaseException] = None


_queue: "queue.Queue[_Call]" = queue.Queue()
_users = 0
_lock = threading.Lock()
_running = False


def _pump() -> Optional[float]:
    if not _running:
        return None
    while True:
        try:
            call = _queue.get_nowait()
        except queue.Empty:
            break
        try:
            call.result = call.function(*call.args, **call.kwargs)
        except BaseException as exc:  # noqa: BLE001 - handed back to the caller
            call.error = exc
            traceback.print_exc()
        finally:
            call.done.set()
    return PUMP_INTERVAL


def pump_once() -> int:
    """Drain the queue now, on whatever thread is calling. Returns how many ran.

    For callers that already have the main thread and cannot rely on the timer
    getting it: a modal operator owns the event loop while it runs, and a
    ``bpy.app.timers`` callback is not guaranteed a slot underneath one. A modal
    that waits on ``submit`` while the pump never fires would deadlock until the
    timeout, so it drives the pump from its own TIMER event instead.

    Safe to call alongside the timer -- both take from the same queue, and an
    item is only ever handed to one of them.
    """
    ran = 0
    while True:
        try:
            call = _queue.get_nowait()
        except queue.Empty:
            return ran
        try:
            call.result = call.function(*call.args, **call.kwargs)
        except BaseException as exc:  # noqa: BLE001 - handed back to the caller
            call.error = exc
            traceback.print_exc()
        finally:
            call.done.set()
            ran += 1


def acquire() -> None:
    """Claim the pump. Starts it on the first caller."""
    global _users, _running
    with _lock:
        _users += 1
        if _running:
            return
        _running = True
    if not bpy.app.timers.is_registered(_pump):
        bpy.app.timers.register(_pump, first_interval=PUMP_INTERVAL, persistent=True)


def release() -> None:
    """Give the pump back. Stops it when nobody is left."""
    global _users, _running
    with _lock:
        _users = max(0, _users - 1)
        if _users:
            return
        if not _running:
            return
        _running = False

    # Nothing will run these now, so let their callers go rather than leaving
    # them on a timeout.
    while True:
        try:
            call = _queue.get_nowait()
        except queue.Empty:
            break
        call.error = Cancelled("the main-thread pump stopped")
        call.done.set()

    if bpy.app.timers.is_registered(_pump):
        try:
            bpy.app.timers.unregister(_pump)
        except ValueError:
            pass


def is_running() -> bool:
    return _running


def submit(function: Callable, *args: Any, timeout: float = TIMEOUT, **kwargs: Any) -> Any:
    """Run ``function`` on the main thread and return its result.

    Raises whatever it raised, so a caller sees the same failure it would have
    seen calling it directly. Never call this *from* the main thread: it would
    queue work that only the main thread can run, and then wait for it.
    """
    if not _running:
        raise Cancelled("the main-thread pump is not running")

    call = _Call(function, args, kwargs)
    _queue.put(call)
    if not call.done.wait(timeout):
        raise Timeout("timed out after %.0fs -- Blender may be in a modal tool" % timeout)
    if call.error is not None:
        raise call.error
    return call.result
