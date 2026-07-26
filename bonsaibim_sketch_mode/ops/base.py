# BonsaiBIM Sketch Mode - direct-modelling interaction for Bonsai
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

"""Shared modal skeleton for the polyline-based drawing tools.

Bonsai's ``PolylineOperator`` supplies inference snapping, axis and plane
locking, and the measurement box, but it leaves the modal event order to each
tool -- and that order matters. Lock-axis handling has to run before the
navigation pass-through or middle-mouse orbit swallows it; the finish check has
to run before keyboard input or a typed distance gets committed twice.

Getting that wrong is subtle and silent, so the sequence lives in one place and
Line and Rectangle differ only in what ends the stroke and what it produces.
"""

from __future__ import annotations

from typing import Any, Optional

import bpy
from mathutils import Vector

from .. import bridge

#: Distance below which two polyline points are the same point, in Blender
#: units. Only ever compares values the polyline engine produced, so this is a
#: float-equality guard rather than a modelling tolerance.
COINCIDENT = 1e-6


class PolylineToolBase(bridge.PolylineOperator):
    """Common behaviour for Sketch tools that draw with the polyline engine."""

    #: Fields offered in the measurement box, cycled with Tab.
    input_options = ["D", "A", "X", "Y", "Z"]

    #: Extra rows for the status bar, merged over Bonsai's own.
    custom_instructions: dict[str, Any] = {}

    @classmethod
    def poll(cls, context: bpy.types.Context) -> bool:
        space = context.space_data
        return (
            bridge.polyline_engine_available()
            and space is not None
            and space.type == "VIEW_3D"
            and context.mode == "OBJECT"
        )

    def init_polyline(self) -> None:
        """Call from __init__, after bpy.types.Operator.__init__."""
        bridge.PolylineOperator.__init__(self)
        self.input_options = list(type(self).input_options)
        self.input_ui = bridge.Polyline.create_input_ui(input_options=self.input_options)

    # --- Reading the polyline back -------------------------------------------

    def polyline_vectors(self) -> list[Vector]:
        """The points placed so far, in world space."""
        props = bridge.Model.get_polyline_props()
        data = props.insertion_polyline
        points = data[0].polyline_points if data else []
        return [Vector((p.x, p.y, p.z)) for p in points]

    @staticmethod
    def is_closed(points: list[Vector]) -> bool:
        """True if the last point landed back on the first."""
        return len(points) > 2 and (points[0] - points[-1]).length <= COINCIDENT

    # --- Modal plumbing -------------------------------------------------------

    def teardown(self, context: bpy.types.Context) -> None:
        """Put the viewport back the way we found it."""
        context.workspace.status_text_set(text=None)
        self.tool_state.axis_method = None
        self.tool_state.plane_method = None
        bridge.PolylineDecorator.uninstall()
        bridge.Polyline.clear_polyline()
        bridge.update_viewport()

    def handle_common(
        self, context: bpy.types.Context, event: bpy.types.Event
    ) -> Optional[set[str]]:
        """Snapping, navigation and input handling shared by every drawing tool.

        Returns a modal result to return immediately, or None to carry on.
        """
        bridge.PolylineDecorator.update(
            event, self.tool_state, self.input_ui, self.snapping_points[0]
        )
        bridge.update_viewport()

        # Must precede the navigation pass-through: shift+wheel adjusts the
        # locked angle, and PASS_THROUGH would hand it to the zoom instead.
        self.handle_lock_axis(context, event)

        if event.type in {"MIDDLEMOUSE", "WHEELUPMOUSE", "WHEELDOWNMOUSE"}:
            self.handle_mouse_move(context, event)
            return {"PASS_THROUGH"}

        self.handle_instructions(context, type(self).custom_instructions)
        self.handle_mouse_move(context, event, should_round=True)
        self.choose_axis(event, z=True)
        self.choose_plane(event)
        self.handle_snap_selection(context, event)
        return None

    def wants_finish(self, event: bpy.types.Event) -> bool:
        """True when the user has asked to end the stroke.

        Only meaningful while the measurement box is closed -- with it open the
        same keys commit the typed value instead.
        """
        return (
            not self.tool_state.is_input_on
            and event.value == "RELEASE"
            and event.type in {"RET", "NUMPAD_ENTER", "RIGHTMOUSE"}
        )

    def invoke(self, context: bpy.types.Context, event: bpy.types.Event) -> set[str]:
        if not bridge.polyline_engine_available():
            self.report(
                {"ERROR"},
                bridge.polyline_unavailable_reason() or "Bonsai's polyline engine is unavailable",
            )
            return {"CANCELLED"}
        super().invoke(context, event)
        return {"RUNNING_MODAL"}
