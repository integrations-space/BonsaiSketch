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

"""The rooms the walls enclose, named by the words the drawing wrote.

Once junctions are resolved, the walls and their meeting points form a
graph, and a room is a cycle in it: walls for edges, junctions for nodes.
This module traces those cycles, then pulls each one's boundary in from
the wall centrelines to the walls' *inner faces* -- offset per edge by
that wall's own half thickness -- because the area a room reports is the
area you can stand in, not the area to the middle of its walls. The area
is then plain shoelace arithmetic over that boundary: measured, in the
sense this pipeline uses the word everywhere.

Naming reuses the drawing's own words. A TEXT or MTEXT label sitting
inside a boundary names that space, by point-in-polygon and nothing
cleverer; a space no label sits in stays unnamed rather than borrowing a
nearby one, and a space with two labels keeps the first and says so in
its diagnostics. The label's source handle travels with the name, so
BEDROOM 2 can point back to the entity that wrote it.

What this does not do, on purpose: walls whose ends meet no junction
cannot bound a cycle and are left out (their dangling pieces are pruned,
not bridged); an enclosure broken by a doorway-sized gap in the wall
network is not closed by guesswork -- opening detection is a later stage
with its own evidence, and temporarily closing its gaps belongs there,
where the closure can be recorded against the opening that justifies it.

Pure Python throughout, like the wall reading it builds on.
"""

from __future__ import annotations

import math
from typing import Optional

from . import ir

#: Cycles enclosing less than this are corner slivers between offset
#: lines, not rooms. A tenth of a square metre is smaller than any
#: enclosure a plan means.
MIN_AREA = 0.1


def _shoelace(points) -> float:
    """Signed area, positive counter-clockwise."""
    total = 0.0
    for (x1, y1), (x2, y2) in zip(points, points[1:] + points[:1]):
        total += x1 * y2 - x2 * y1
    return total / 2.0


def contains(polygon, point) -> bool:
    """Ray-cast point-in-polygon, boundary-exclusive enough for labels."""
    x, y = point
    inside = False
    for (x1, y1), (x2, y2) in zip(polygon, polygon[1:] + polygon[:1]):
        if (y1 > y) != (y2 > y):
            crossing = x1 + (y - y1) * (x2 - x1) / (y2 - y1)
            if x < crossing:
                inside = not inside
    return inside


def _split_walls(walls, junctions):
    """(nodes, edges): walls cut at their junction points.

    A T's bar carries a junction mid-length, and a cycle can turn there,
    so the graph's edges are wall *pieces* between consecutive junction
    points, each remembering which wall it is a piece of. Pieces past a
    wall's last junction dangle by construction and are dropped here --
    a dangling piece cannot bound a room.
    """
    nodes = {j.id: tuple(j.point) for j in junctions}
    # Membership reads from the wall's side, not the junction's: a wall
    # merged across an opening carries its absorbed piece's junctions
    # forward under its own name, while the junction's record keeps the
    # id it historically met -- history in one place, current truth in
    # the other.
    by_id = {j.id: j for j in junctions}
    on_wall: dict = {}
    for wall in walls:
        seen = set()
        stations = []
        for junction_id in wall.junctions:
            if junction_id in by_id and junction_id not in seen:
                seen.add(junction_id)
                stations.append(by_id[junction_id])
        on_wall[wall.id] = stations

    edges = []
    for wall in walls:
        dx, dy = wall.end[0] - wall.start[0], wall.end[1] - wall.start[1]
        length = math.hypot(dx, dy)
        if length < 1e-9 or len(on_wall[wall.id]) < 2:
            continue
        ux, uy = dx / length, dy / length
        stations = sorted(
            on_wall[wall.id],
            key=lambda j: (j.point[0] - wall.start[0]) * ux + (j.point[1] - wall.start[1]) * uy,
        )
        for a, b in zip(stations, stations[1:]):
            if math.hypot(b.point[0] - a.point[0], b.point[1] - a.point[1]) > 1e-9:
                edges.append((a.id, b.id, wall))
    return nodes, edges


def _prune(nodes, edges):
    """Drop edges that end at a degree-one node, repeatedly.

    A stub corridor wall hangs off the room graph; it is real, but no
    cycle can pass through it, and leaving it in makes face tracing walk
    out and back along it for nothing.
    """
    edges = list(edges)
    while True:
        degree: dict = {}
        for a, b, _w in edges:
            degree[a] = degree.get(a, 0) + 1
            degree[b] = degree.get(b, 0) + 1
        kept = [(a, b, w) for a, b, w in edges if degree[a] > 1 and degree[b] > 1]
        if len(kept) == len(edges):
            return kept
        edges = kept


def _cycles(nodes, edges):
    """The interior faces of the planar wall graph, as node-id cycles.

    Standard half-edge face tracing: at each node the outgoing edges are
    ordered by angle, and arriving along one leaves along the next one
    clockwise. Traced this way the interior faces come out
    counter-clockwise -- positive shoelace -- and the single outer face
    comes out negative, which is how it is recognised and dropped.
    """
    outgoing: dict = {}
    for index, (a, b, _wall) in enumerate(edges):
        outgoing.setdefault(a, []).append((b, index))
        outgoing.setdefault(b, []).append((a, index))
    for node, neighbours in outgoing.items():
        nx, ny = nodes[node]
        neighbours.sort(key=lambda entry: math.atan2(nodes[entry[0]][1] - ny,
                                                     nodes[entry[0]][0] - nx))

    seen = set()  # directed (from, to, edge index)
    faces = []
    for start_node, neighbours in outgoing.items():
        for target, edge_index in neighbours:
            if (start_node, target, edge_index) in seen:
                continue
            cycle_nodes = []
            cycle_edges = []
            here, there, via = start_node, target, edge_index
            while (here, there, via) not in seen:
                seen.add((here, there, via))
                cycle_nodes.append(here)
                cycle_edges.append(via)
                options = outgoing[there]
                back = next(i for i, (n, e) in enumerate(options)
                            if n == here and e == via)
                nxt, nxt_edge = options[(back - 1) % len(options)]
                here, there, via = there, nxt, nxt_edge
            if _shoelace([nodes[n] for n in cycle_nodes]) > 1e-9:
                faces.append((cycle_nodes, cycle_edges))
    return faces


def _inner_boundary(points, thicknesses):
    """The cycle pulled in to the walls' inner faces.

    Each edge's line moves toward the interior by that wall's half
    thickness; each boundary corner is where consecutive moved lines
    cross. Interior is the left of travel on a counter-clockwise cycle,
    so the offset normal is the left normal. Consecutive edges that are
    collinear -- a T's bar contributing two pieces -- get the moved
    line's own point, since parallel lines cross nowhere.
    """
    count = len(points)
    offset_lines = []
    for i in range(count):
        x1, y1 = points[i]
        x2, y2 = points[(i + 1) % count]
        length = math.hypot(x2 - x1, y2 - y1)
        ux, uy = (x2 - x1) / length, (y2 - y1) / length
        nx, ny = -uy, ux  # left of travel: the interior of a CCW cycle
        shift = thicknesses[i] / 2.0
        offset_lines.append(((x1 + nx * shift, y1 + ny * shift), (ux, uy)))

    boundary = []
    for i in range(count):
        (px, py), (ux, uy) = offset_lines[i - 1]
        (qx, qy), (vx, vy) = offset_lines[i]
        denom = ux * vy - uy * vx
        if abs(denom) < 1e-9:
            boundary.append((qx, qy))  # collinear neighbours share the line
            continue
        t = ((qx - px) * vy - (qy - py) * vx) / denom
        boundary.append((px + ux * t, py + uy * t))
    return boundary


def detect(
    walls,
    junctions,
    labels=None,
    source_map: Optional[ir.SourceMap] = None,
    first: int = 1,
) -> list:
    """Space candidates from resolved walls, named by the drawing's labels."""
    nodes, edges = _split_walls(walls, junctions)
    edges = _prune(nodes, edges)
    candidates = []
    for cycle_nodes, cycle_edges in _cycles(nodes, edges):
        points = [nodes[n] for n in cycle_nodes]
        thicknesses = [edges[e][2].thickness for e in cycle_edges]
        boundary = _inner_boundary(points, thicknesses)
        area = _shoelace(boundary)
        if area < MIN_AREA:
            continue
        wall_ids = []
        for e in cycle_edges:
            wall_id = edges[e][2].id
            if wall_id not in wall_ids:
                wall_ids.append(wall_id)
        space = ir.SpaceCandidate(
            "S%03d" % (first + len(candidates)),
            boundary,
            area,
            wall_ids,
            [
                f"enclosed by {len(wall_ids)} wall(s)",
                f"boundary offset to the walls' inner faces; area {area:.3f} m2",
            ],
        )
        if source_map is not None:
            source_map.record("ENCLOSE", wall_ids, space.id,
                              f"cycle of {len(cycle_nodes)} junction(s)")
        for label in labels or ():
            if not contains(boundary, label.position):
                continue
            if space.label is None:
                space.label = label.text
                space.label_source = getattr(label, "source", "") or None
                if source_map is not None:
                    source_map.record(
                        "LABEL", [space.label_source or "?"], space.id, label.text
                    )
            else:
                space.diagnostics.append(
                    f"also contains label {label.text!r}; kept {space.label!r}"
                )
        candidates.append(space)
    return candidates
