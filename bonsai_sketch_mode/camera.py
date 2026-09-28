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

"""The camera an architect stands at: eye height, level, two-point.

What makes a perspective read as architecture rather than as a screenshot
is a discipline photographers enforce with a shift lens: the camera stays
*level*, so every vertical edge draws vertical, and the framing a tilt
would have given is recovered by sliding the lens instead of tilting the
body. Hand-drawn presentation perspectives obey the same rule -- two
vanishing points on the horizon, none in the sky.

This module is the arithmetic only, pure Python with no Blender in it, so
the sums can be checked by hand in ``tools/camera_check.py``. The
operators in ``ops/camera.py`` apply them to real cameras.

The one refusal: a view pitched past :data:`MAX_PITCH` is a bird's or a
worm's view, not a perspective of a building. Levelling it can only keep
the framing by an absurd lens shift, so the framing is *not* kept, and the
note says so instead of quietly distorting the image.
"""

from __future__ import annotations

import math
from typing import Optional

#: Beyond this pitch, recovering a levelled camera's framing needs a lens
#: shift larger than the picture itself is worth -- tan(45 degrees) of shift
#: is already a full sensor width on a normal lens. The view gets levelled,
#: the framing does not follow, and the note explains.
MAX_PITCH = math.radians(45.0)

#: Standing eye height in metres. SketchUp plants its viewer at much the
#: same height for the same reason: it is where a person sees a building.
EYE_HEIGHT = 1.6

#: Default focal length in millimetres. Wide enough to hold a house in
#: frame from across its own street, long enough not to bow the corners.
LENS = 32.0

#: The full-frame sensor width Blender defaults to, in millimetres. Lens
#: shift is expressed as a fraction of this dimension.
SENSOR = 36.0


def pitch_yaw(forward) -> tuple[float, Optional[float]]:
    """(pitch, yaw) of a view direction, in radians.

    Pitch is the angle above the horizon, negative looking down. Yaw is
    the Z rotation that makes a level camera -- ``rotation_euler =
    (pi/2, 0, yaw)`` in Blender's terms -- look along the direction's
    horizontal projection. Straight up or straight down has no horizontal
    projection to speak of, so yaw comes back None and pitch carries the
    sign.
    """
    x, y, z = forward
    horizontal = math.hypot(x, y)
    length = math.hypot(horizontal, z)
    if length < 1e-9 or horizontal < 1e-9 * max(length, 1.0):
        return math.copysign(math.pi / 2.0, z), None
    return math.atan2(z, horizontal), math.atan2(-x, y)


def two_point_shift(pitch: float, lens: float = LENS, sensor: float = SENSOR) -> float:
    """The lens shift that recovers a tilted view's framing once levelled.

    A camera tilted by ``pitch`` centres a point that, seen from the level
    camera in the same spot, sits ``tan(pitch)`` focal lengths off the
    image centre. Blender measures shift as a fraction of the sensor's fit
    dimension, hence the division. Positive pitch (looking up) needs a
    positive (upward) shift.
    """
    return math.tan(pitch) * lens / sensor


def level(forward, lens: float = LENS, sensor: float = SENSOR):
    """(yaw, shift, note) that stand a view up into two-point perspective.

    The note is empty when the framing survives. Past :data:`MAX_PITCH`
    the shift comes back zero and the note says the framing was let go;
    a vertical view has no yaw at all, and the caller should refuse.
    """
    pitch, yaw = pitch_yaw(forward)
    if yaw is None:
        return None, 0.0, ("the view looks straight up or down; "
                           "there is no horizontal direction to keep")
    if abs(pitch) > MAX_PITCH:
        return yaw, 0.0, (
            f"the view pitched {abs(math.degrees(pitch)):.0f} degrees, past the "
            "two-point range -- camera set level, framing not preserved; "
            "orbit nearer eye level for a framed conversion")
    return yaw, two_point_shift(pitch, lens, sensor), ""
