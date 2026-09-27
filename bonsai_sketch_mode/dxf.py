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

A floor plan is lines, polylines, arcs and circles on named layers, plus the
words written on it -- room names, level marks. That is the whole subset this
reads, and it is read with a parser this add-on owns rather than a shipped
library, on purpose:

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
    """A run of 2D points on a layer, closed or not. Points are (x, y) tuples.

    ``source`` names the DXF entity this came from -- its type plus the
    file's own handle (group code 5) where the file wrote one, or an
    ordinal (``LINE:#12``) where it did not -- so everything derived from
    this geometry can say which drawn entity caused it to exist.
    """

    __slots__ = ("layer", "points", "closed", "source")

    def __init__(self, layer: str, points: list, closed: bool, source: str = "") -> None:
        self.layer = layer
        self.points = points
        self.closed = closed
        self.source = source


class Label:
    """A piece of drawn text and where it sits: a room name, a level mark.

    Text is evidence, not geometry -- a label inside an enclosure is how a
    plan says what the room is, and reading it is what will let a detected
    space call itself BEDROOM 2 instead of Space_005. MTEXT's inline
    formatting codes are left as written, except the paragraph break, which
    becomes a space so a two-line name reads as one.
    """

    __slots__ = ("layer", "text", "position", "source")

    def __init__(self, layer: str, text: str, position: tuple, source: str = "") -> None:
        self.layer = layer
        self.text = text
        self.position = position
        self.source = source


class Arc:
    """An arc kept as an arc -- centre and radius -- beside its chords.

    The chords in ``layers`` are what an import draws; this record is what
    an *interpreter* needs, because a door's swing arc is evidence exactly
    through its radius matching an opening's width, and no amount of
    chord-walking states that as plainly as the arc itself does.
    """

    __slots__ = ("layer", "center", "radius", "source")

    def __init__(self, layer: str, center: tuple, radius: float, source: str = "") -> None:
        self.layer = layer
        self.center = center
        self.radius = radius
        self.source = source


class Insert:
    """A block reference: a named symbol placed at a point.

    The block's own geometry is deliberately not expanded -- a symbol's
    meaning is its name and its position, which is all the evidence an
    opening detector needs, and expanding definitions would drag half of
    DXF's block machinery in for nothing this add-on reads.
    """

    __slots__ = ("layer", "name", "position", "source")

    def __init__(self, layer: str, name: str, position: tuple, source: str = "") -> None:
        self.layer = layer
        self.name = name
        self.position = position
        self.source = source


class Drawing:
    """What a DXF file said, reduced to what a sketch can use."""

    def __init__(self) -> None:
        #: Layer name -> polylines on it, in file order.
        self.layers: dict[str, list[Polyline]] = {}
        #: The drawing's words -- TEXT and MTEXT -- in file order.
        self.texts: list[Label] = []
        #: Arcs as arcs, for the interpreters; their chords are in layers.
        self.arcs: list[Arc] = []
        #: Block references by name and position, unexpanded.
        self.inserts: list[Insert] = []
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
    """DXF's one structure: a group code line, then a value line.

    The value comes through as written: a text chunk's trailing space is
    the space between two words that a chunk boundary happened to split,
    and stripping it here would eat it. Consumers that compare identities
    -- entity names, section names, layers -- strip for themselves, and
    the number parsers never minded whitespace.
    """
    lines = text.splitlines()
    for index in range(0, len(lines) - 1, 2):
        code = lines[index].strip()
        try:
            yield int(code), lines[index + 1]
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
_HANDLED = {"LINE", "LWPOLYLINE", "POLYLINE", "ARC", "CIRCLE", "VERTEX", "SEQEND",
            "TEXT", "MTEXT", "INSERT"}


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
    poly_source = ""
    in_polyline = False
    insunits: Optional[int] = None
    ordinal = 0

    def flush() -> None:
        """Turn the accumulated fields of the finished entity into geometry."""
        nonlocal in_polyline, poly_layer, poly_closed, poly_points, poly_source, ordinal
        if entity is None or section != "ENTITIES":
            return
        layer = fields.get(8, ["0"])[0].strip()
        # The entity's own name for itself: the handle the file wrote, or
        # its position in the entity stream where the file wrote none.
        ordinal += 1
        handle = fields.get(5, [""])[0].strip()
        source = f"{entity}:{handle}" if handle else f"{entity}:#{ordinal}"
        try:
            if entity == "LINE":
                start = (float(fields[10][0]), float(fields[20][0]))
                end = (float(fields[11][0]), float(fields[21][0]))
                drawing.add(Polyline(layer, [start, end], closed=False, source=source))
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
                    drawing.add(Polyline(layer, points, closed, source=source))
            elif entity == "POLYLINE":
                in_polyline = True
                poly_layer = layer
                poly_closed = bool(int(fields.get(70, ["0"])[0]) & 1)
                poly_points = []
                poly_source = source
            elif entity == "VERTEX" and in_polyline:
                poly_points.append((float(fields[10][0]), float(fields[20][0])))
            elif entity == "SEQEND" and in_polyline:
                if len(poly_points) >= 2 and poly_layer is not None:
                    drawing.add(
                        Polyline(poly_layer, list(poly_points), poly_closed, source=poly_source)
                    )
                in_polyline = False
                poly_points = []
            elif entity == "ARC":
                cx, cy = float(fields[10][0]), float(fields[20][0])
                radius = float(fields[40][0])
                points = _arc_points(cx, cy, radius,
                                     float(fields[50][0]), float(fields[51][0]))
                drawing.add(Polyline(layer, points, closed=False, source=source))
                drawing.arcs.append(Arc(layer, (cx, cy), radius, source=source))
            elif entity == "CIRCLE":
                points = _arc_points(
                    float(fields[10][0]), float(fields[20][0]),
                    float(fields[40][0]), 0.0, 360.0,
                )
                # The walk returns to its start; a closed polyline stores
                # that point once.
                drawing.add(Polyline(layer, points[:-1], closed=True, source=source))
            elif entity in ("TEXT", "MTEXT"):
                # MTEXT longer than a group's 250 characters arrives as code-3
                # chunks with the tail in code 1; TEXT is code 1 alone. Either
                # way the words come out in drawing order.
                value = "".join(fields.get(3, [])) + fields.get(1, [""])[0]
                value = value.replace("\\P", " ").strip()
                if value:
                    position = (float(fields[10][0]), float(fields[20][0]))
                    drawing.texts.append(Label(layer, value, position, source=source))
            elif entity == "INSERT":
                name = fields.get(2, [""])[0].strip()
                if name:
                    position = (float(fields[10][0]), float(fields[20][0]))
                    drawing.inserts.append(Insert(layer, name, position, source=source))
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
            token = value.strip()
            if token == "SECTION":
                entity = None
                fields = {}
                section = "PENDING"
                continue
            if token == "ENDSEC":
                section = None
                entity = None
                continue
            if token == "EOF":
                break
            entity = token
            fields = {}
            continue
        if section == "PENDING" and code == 2:
            section = value.strip()
            continue
        if section == "HEADER":
            if code == 9:
                pending_header = value.strip()
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
            for label in drawing.texts:
                label.position = (
                    label.position[0] * drawing.scale,
                    label.position[1] * drawing.scale,
                )
            for arc in drawing.arcs:
                arc.center = (arc.center[0] * drawing.scale, arc.center[1] * drawing.scale)
                arc.radius *= drawing.scale
            for insert in drawing.inserts:
                insert.position = (
                    insert.position[0] * drawing.scale,
                    insert.position[1] * drawing.scale,
                )
    return drawing
