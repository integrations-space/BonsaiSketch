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

"""Reading the drafting subset of DXF, without a dependency.

A floor plan is lines, polylines, arcs and circles on named layers. That is
the whole subset this reads, and it is read with a parser this add-on owns
rather than a shipped library, on purpose:

- ezdxf would have to travel as a wheel in the extension and keep step with
  Blender's Python. The group-code format underneath is line pairs from 1982;
  the subset a plan needs is a few hundred lines to read ourselves.
- Blender's own DXF importer became a separate extension in the extensions
  era, so there is nothing bundled to lean on, and depending on another
  extension is exactly the thing the manifest cannot declare.
- A parser we own fails loudly on precisely the entities it ignores, instead
  of importing an approximation of them. What is skipped is counted and
  reported, never dropped in silence.

Everything here is pure Python with tuples for points -- no bpy, no mathutils
-- so the whole module runs anywhere, including the headless suite and the
machine this was written on.

DWG is deliberately not parsed. It is proprietary, with no reliable free
reader; the honest route is ODA File Converter producing a DXF, and the
import operator drives that when the user has pointed preferences at it.
"""

from __future__ import annotations

import math
from typing import Iterator, Optional

#: Arcs and circles become chords every this-many degrees. 15 gives the
#: 24-sided circle SketchUp draws by default, which is the look a SketchUp
#: user reads as "a circle" rather than "a polygon".
ARC_STEP_DEGREES = 15.0

#: DXF $INSUNITS values worth understanding, as factors to metres. Anything
#: else -- including 0, "unitless" -- imports as-is and says so in the report.
_UNIT_FACTORS = {
    1: 0.0254,   # inches
    2: 0.3048,   # feet
    4: 0.001,    # millimetres
    5: 0.01,     # centimetres
    6: 1.0,      # metres
}

_UNIT_NAMES = {1: "inches", 2: "feet", 4: "millimetres", 5: "centimetres", 6: "metres"}


class Polyline:
    """A run of 2D points on a layer, closed or not. Points are (x, y) tuples."""

    __slots__ = ("layer", "points", "closed")

    def __init__(self, layer: str, points: list, closed: bool) -> None:
        self.layer = layer
        self.points = points
        self.closed = closed


class Drawing:
    """What a DXF file said, reduced to what a sketch can use."""

    def __init__(self) -> None:
        #: Layer name -> polylines on it, in file order.
        self.layers: dict[str, list[Polyline]] = {}
        #: Entity types read past because this subset does not cover them,
        #: with counts. Reported, never silently dropped.
        self.skipped: dict[str, int] = {}
        #: The factor applied to every coordinate, and the unit name it came
        #: from -- "as drawn" when the file declared nothing usable.
        self.scale: float = 1.0
        self.unit_name: str = "as drawn"

    def add(self, polyline: Polyline) -> None:
        self.layers.setdefault(polyline.layer, []).append(polyline)

    def skip(self, entity_type: str) -> None:
        self.skipped[entity_type] = self.skipped.get(entity_type, 0) + 1


def _pairs(text: str) -> Iterator[tuple[int, str]]:
    """DXF's one structure: a group code line, then a value line."""
    lines = text.splitlines()
    for index in range(0, len(lines) - 1, 2):
        code = lines[index].strip()
        try:
            yield int(code), lines[index + 1].strip()
        except ValueError:
            # A malformed code line. The pair walk stays in step by skipping
            # the pair, which is the recoverable reading of a broken file.
            continue


def _arc_points(cx: float, cy: float, radius: float, start_deg: float, end_deg: float) -> list:
    """Chords along an arc, endpoints included. DXF arcs run counter-clockwise."""
    sweep = (end_deg - start_deg) % 360.0
    if sweep == 0.0:
        sweep = 360.0
    steps = max(1, int(math.ceil(sweep / ARC_STEP_DEGREES)))
    points = []
    for step in range(steps + 1):
        angle = math.radians(start_deg + sweep * step / steps)
        points.append((cx + radius * math.cos(angle), cy + radius * math.sin(angle)))
    return points


def _bulge_points(start: tuple, end: tuple, bulge: float) -> list:
    """The arc a polyline bulge describes, as chords. Start excluded, end included.

    A bulge is tan of a quarter of the included angle, signed by direction --
    drafting's most compact arc encoding. The centre falls out of the chord
    and the angle; from there it is an ordinary arc walk.
    """
    theta = 4.0 * math.atan(bulge)
    chord_x = end[0] - start[0]
    chord_y = end[1] - start[1]
    chord = math.hypot(chord_x, chord_y)
    if chord == 0.0 or theta == 0.0:
        return [end]
    radius = chord / (2.0 * math.sin(abs(theta) / 2.0))
    # The centre sits perpendicular to the chord's midpoint, on the side the
    # sign of the bulge picks.
    mid_x = (start[0] + end[0]) / 2.0
    mid_y = (start[1] + end[1]) / 2.0
    lift = math.sqrt(max(radius * radius - (chord / 2.0) ** 2, 0.0))
    side = 1.0 if theta > 0.0 else -1.0
    cx = mid_x - side * lift * (chord_y / chord)
    cy = mid_y + side * lift * (chord_x / chord)

    start_angle = math.atan2(start[1] - cy, start[0] - cx)
    steps = max(1, int(math.ceil(abs(math.degrees(theta)) / ARC_STEP_DEGREES)))
    points = []
    for step in range(1, steps + 1):
        angle = start_angle + theta * step / steps
        points.append((cx + radius * math.cos(angle), cy + radius * math.sin(angle)))
    # Land exactly on the endpoint rather than on trigonometry's version of it.
    points[-1] = end
    return points


#: Entity types this reader understands. Everything else is counted, not read.
_HANDLED = {"LINE", "LWPOLYLINE", "POLYLINE", "ARC", "CIRCLE", "VERTEX", "SEQEND"}


def parse(text: str) -> Drawing:
    """A Drawing from DXF text. Coordinates come out in metres where the file
    declares its units, as drawn where it does not."""
    drawing = Drawing()

    section = None
    entity: Optional[str] = None
    fields: dict[int, list[str]] = {}
    # Old-style POLYLINE arrives as a header entity followed by VERTEX
    # entities and a SEQEND, so its accumulation spans several entities.
    poly_layer: Optional[str] = None
    poly_closed = False
    poly_points: list = []
    in_polyline = False
    insunits: Optional[int] = None

    def flush() -> None:
        """Turn the accumulated fields of the finished entity into geometry."""
        nonlocal in_polyline, poly_layer, poly_closed, poly_points
        if entity is None or section != "ENTITIES":
            return
        layer = fields.get(8, ["0"])[0]
        try:
            if entity == "LINE":
                start = (float(fields[10][0]), float(fields[20][0]))
                end = (float(fields[11][0]), float(fields[21][0]))
                drawing.add(Polyline(layer, [start, end], closed=False))
            elif entity == "LWPOLYLINE":
                xs = [float(v) for v in fields.get(10, [])]
                ys = [float(v) for v in fields.get(20, [])]
                closed = bool(int(fields.get(70, ["0"])[0]) & 1)
                # Bulges are per-vertex but optional per vertex only in
                # theory; writers that use them at all write one per vertex.
                bulges = [float(v) for v in fields.get(42, [])]
                points: list = []
                count = min(len(xs), len(ys))
                for i in range(count):
                    here = (xs[i], ys[i])
                    if points:
                        bulge = bulges[i - 1] if i - 1 < len(bulges) else 0.0
                        if bulge:
                            points.extend(_bulge_points(points[-1], here, bulge))
                        else:
                            points.append(here)
                    else:
                        points.append(here)
                if closed and count > 1 and len(bulges) >= count and bulges[count - 1]:
                    # A bulge on the last vertex arcs back to the first;
                    # keep the arc, drop its duplicate landing point.
                    points.extend(_bulge_points(points[-1], points[0], bulges[count - 1])[:-1])
                if len(points) >= 2:
                    drawing.add(Polyline(layer, points, closed))
            elif entity == "POLYLINE":
                in_polyline = True
                poly_layer = layer
                poly_closed = bool(int(fields.get(70, ["0"])[0]) & 1)
                poly_points = []
            elif entity == "VERTEX" and in_polyline:
                poly_points.append((float(fields[10][0]), float(fields[20][0])))
            elif entity == "SEQEND" and in_polyline:
                if len(poly_points) >= 2 and poly_layer is not None:
                    drawing.add(Polyline(poly_layer, list(poly_points), poly_closed))
                in_polyline = False
                poly_points = []
            elif entity == "ARC":
                points = _arc_points(
                    float(fields[10][0]), float(fields[20][0]),
                    float(fields[40][0]), float(fields[50][0]), float(fields[51][0]),
                )
                drawing.add(Polyline(layer, points, closed=False))
            elif entity == "CIRCLE":
                points = _arc_points(
                    float(fields[10][0]), float(fields[20][0]),
                    float(fields[40][0]), 0.0, 360.0,
                )
                # The walk returns to its start; a closed polyline stores
                # that point once.
                drawing.add(Polyline(layer, points[:-1], closed=True))
            elif entity not in _HANDLED:
                drawing.skip(entity)
        except (KeyError, IndexError, ValueError):
            # An entity missing the fields its type promises. Skipping it is
            # the recoverable reading; counting it keeps it visible.
            drawing.skip(entity)

    pending_header: Optional[str] = None
    for code, value in _pairs(text):
        if code == 0:
            flush()
            if value == "SECTION":
                entity = None
                fields = {}
                section = "PENDING"
                continue
            if value == "ENDSEC":
                section = None
                entity = None
                continue
            if value == "EOF":
                break
            entity = value
            fields = {}
            continue
        if section == "PENDING" and code == 2:
            section = value
            continue
        if section == "HEADER":
            if code == 9:
                pending_header = value
            elif pending_header == "$INSUNITS" and code == 70:
                try:
                    insunits = int(value)
                except ValueError:
                    insunits = None
                pending_header = None
            continue
        fields.setdefault(code, []).append(value)
    flush()

    if insunits in _UNIT_FACTORS:
        drawing.scale = _UNIT_FACTORS[insunits]
        drawing.unit_name = _UNIT_NAMES[insunits]
        if drawing.scale != 1.0:
            for polylines in drawing.layers.values():
                for polyline in polylines:
                    polyline.points = [
                        (x * drawing.scale, y * drawing.scale) for x, y in polyline.points
                    ]
    return drawing
