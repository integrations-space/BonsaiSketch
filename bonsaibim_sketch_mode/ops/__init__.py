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

"""Sketch Mode's modal tools.

Each module here is one tool. They register even when Bonsai's polyline engine
is missing -- their poll methods return False in that case, so the toolbar
shows them greyed out with a reason rather than the tool silently vanishing.
"""

from __future__ import annotations

import bpy

from .line import BONSAIBIM_SKETCH_OT_line
from .pushpull import BONSAIBIM_SKETCH_OT_push_pull
from .rectangle import BONSAIBIM_SKETCH_OT_rectangle

LINE_OP = BONSAIBIM_SKETCH_OT_line.bl_idname
RECTANGLE_OP = BONSAIBIM_SKETCH_OT_rectangle.bl_idname
PUSH_PULL_OP = BONSAIBIM_SKETCH_OT_push_pull.bl_idname

classes = (
    BONSAIBIM_SKETCH_OT_line,
    BONSAIBIM_SKETCH_OT_rectangle,
    BONSAIBIM_SKETCH_OT_push_pull,
)


def register() -> None:
    for cls in classes:
        bpy.utils.register_class(cls)


def unregister() -> None:
    for cls in reversed(classes):
        try:
            bpy.utils.unregister_class(cls)
        except RuntimeError:
            pass
