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

"""Openings: where independent pieces of drawing evidence must converge.

A doorway is the first thing this compiler reads that no single entity
states. The wall pairing sees two collinear runs with a gap of a
doorway's width; a swing arc's radius happens to equal that gap; a block
named DOOR sits in it; glazing lines cross it. Each alone is a hint.
This module makes the hint an :class:`~.ir.OpeningCandidate` *first* --
the geometry can prove an opening exists long before anything says what
fills it -- and classifies only when evidence converges:

* a gap alone is ``possible``, never a door;
* a gap plus a swing arc or a door-named block is a resolved DOOR;
* a gap plus glazing lines or a window-named block is a resolved WINDOW;
* door evidence and window evidence together are ``contested``, and the
  refusal names both, because picking one would bury the disagreement.

The gap is also what justifies the merge the continuation rule refused:
two collinear same-thickness walls separated by a doorway are one wall
interrupted, so the host is merged *because of the opening*, recorded as
a MERGE against the opening's id in the source map -- never a silent
edit. The merged wall spans the gap; the opening will void it in IFC
through the proper chain (IfcRelVoidsElement, then IfcRelFillsElement),
which is emission's business, not this module's.

And the opening finally answers the question space detection honestly
left open: with the host merged, enclosures close across doorways, and
:func:`connects` says which two spaces an opening joins -- the
relationship a door actually is.

Pure Python, like everything upstream of the pipeline.
"""

from __future__ import annotations

import math
from typing import Optional

from . import ir
from .walls import ANGLE_TOLERANCE_DEGREES

#: The plausible range of a drawn opening's clear width. Narrower is a
#: drafting break for the continuation rule; wider is a missing wall.
MIN_WIDTH = 0.40
MAX_WIDTH = 3.00

#: How far two collinear runs' centrelines may sit apart laterally and
#: still be one interrupted wall.
LATERAL_TOLERANCE = 0.05

#: A swing arc testifies when its radius is the gap's width, near enough:
#: the leaf is as wide as the opening it swings through.
ARC_RADIUS_TOLERANCE = 0.15

#: Block-name tokens, matched as whole tokens the way classify.py matches
#: layer names. The table is data so an office's own library extends it.
DOOR_TOKENS = {"DOOR", "DOORS", "DR", "PORTE", "TUER", "TUR"}
WINDOW_TOKENS = {"WIN", "WINDOW", "WINDOWS", "WD", "FENETRE", "FENSTER"}


def _tokens(name: str) -> list:
    out = []
    word = []
    for ch in name.upper():
        if ch.isalnum():
            word.append(ch)
        elif word:
            out.append("".join(word))
            word = []
    if word:
        out.append("".join(word))
    return out


def block_reading(name: str) -> Optional[str]:
    """DOOR, WINDOW, or None -- what a block's name claims to be."""
    tokens = set(_tokens(name))
    door = bool(tokens & DOOR_TOKENS)
    window = bool(tokens & WINDOW_TOKENS)
    if door and not window:
        return "DOOR"
    if window and not door:
        return "WINDOW"
    return None


def _axis(wall):
    dx, dy = wall.end[0] - wall.start[0], wall.end[1] - wall.start[1]
    length = math.hypot(dx, dy)
    if length < 1e-9:
        return None
    return (dx / length, dy / length), length


def detect(
    walls_list,
    arcs=(),
    inserts=(),
    glazing_segments=(),
    glazing_sources=(),
    source_map: Optional[ir.SourceMap] = None,
    first: int = 1,
) -> tuple[list, list]:
    """(openings, walls after host merges) for one layer's resolved walls.

    ``walls_list`` is consumed conceptually, not literally: the returned
    list is the caller's new truth, with each interrupted wall merged
    across its gaps and every merge in the source map. Openings come back
    with whatever classification the evidence earned.
    """
    walls_list = list(walls_list)
    openings: list = []
    sin_tolerance = math.sin(math.radians(ANGLE_TOLERANCE_DEGREES))

    # Gaps first: the anchor evidence. Repeated until quiet, because a
    # wall broken by two doors merges pairwise.
    merged = True
    while merged:
        merged = False
        for i in range(len(walls_list)):
            a = walls_list[i]
            axis_a = _axis(a)
            if axis_a is None:
                continue
            (uxa, uya), len_a = axis_a
            for j in range(len(walls_list)):
                if j == i:
                    continue
                b = walls_list[j]
                axis_b = _axis(b)
                if axis_b is None:
                    continue
                (uxb, uyb), _len_b = axis_b
                if abs(uxa * uyb - uya * uxb) > sin_tolerance:
                    continue
                if abs(a.thickness - b.thickness) > 0.1 * a.thickness:
                    continue
                # b must lie on a's line, wholly past a's end, whichever
                # way round it happened to be drawn.
                alongs = []
                for px, py in (b.start, b.end):
                    rel = (px - a.start[0], py - a.start[1])
                    if abs(uxa * rel[1] - uya * rel[0]) > LATERAL_TOLERANCE:
                        alongs = None
                        break
                    alongs.append(uxa * rel[0] + uya * rel[1])
                if alongs is None:
                    continue
                b_near, b_far = sorted(alongs)
                gap = b_near - len_a
                if not MIN_WIDTH <= gap <= MAX_WIDTH:
                    continue
                far_point = b.start if alongs[0] > alongs[1] else b.end

                opening = ir.OpeningCandidate(
                    "O%03d" % (first + len(openings)),
                    a.id,
                    len_a + gap / 2.0,
                    gap,
                    [],
                    [
                        f"wall discontinuity: {a.id} and {b.id} collinear, "
                        f"same {a.thickness:.3f} m thickness",
                        f"{gap:.3f} m gap, a drawn opening's width",
                    ],
                )
                openings.append(opening)
                # The merge is the opening's doing and says so.
                old_end = a.end
                a.end = tuple(far_point)
                a.sources = list(a.sources) + list(b.sources)
                a.junctions = list(a.junctions) + list(b.junctions)
                a.evidence = list(a.evidence) + [
                    f"continued across {opening.id}'s {gap:.3f} m gap"
                ]
                a.diagnostics.append(
                    f"merged with {b.id} across {opening.id}; "
                    f"end moved from {tuple(round(v, 6) for v in old_end)}"
                )
                if source_map is not None:
                    source_map.record(
                        "MERGE", [a.id, b.id, opening.id], a.id,
                        f"one wall interrupted by {opening.id}",
                    )
                del walls_list[j]
                merged = True
                break
            if merged:
                break

    # The other evidence converges onto the anchored gaps.
    for opening in openings:
        host = next(w for w in walls_list if w.id == opening.host_wall)
        (ux, uy), _length = _axis(host)
        centre = (
            host.start[0] + ux * opening.position,
            host.start[1] + uy * opening.position,
        )
        readings = set()

        for arc in arcs:
            if abs(arc.radius - opening.width) > ARC_RADIUS_TOLERANCE * opening.width:
                continue
            reach = opening.width + host.thickness
            if math.hypot(arc.center[0] - centre[0], arc.center[1] - centre[1]) > reach:
                continue
            opening.sources.append(getattr(arc, "source", "") or "?")
            opening.evidence.append(
                f"swing arc, radius {arc.radius:.3f} m matches the gap"
            )
            readings.add("DOOR")

        for insert in inserts:
            reading = block_reading(insert.name)
            if reading is None:
                continue
            reach = max(opening.width, 1.0)
            if math.hypot(insert.position[0] - centre[0],
                          insert.position[1] - centre[1]) > reach:
                continue
            opening.sources.append(getattr(insert, "source", "") or "?")
            opening.evidence.append(f"block {insert.name!r} placed in the gap")
            readings.add(reading)

        half_gap = opening.width / 2.0
        half_wall = host.thickness / 2.0 + 1e-6
        for segment, handle in zip(glazing_segments, glazing_sources):
            (x1, y1), (x2, y2) = segment
            sx, sy = x2 - x1, y2 - y1
            seg_len = math.hypot(sx, sy)
            if seg_len < 1e-9:
                continue
            if abs((sx / seg_len) * uy - (sy / seg_len) * ux) > sin_tolerance:
                continue  # not running with the wall: a jamb, not glazing
            inside = True
            for px, py in segment:
                rx, ry = px - centre[0], py - centre[1]
                if abs(rx * ux + ry * uy) > half_gap or abs(rx * uy - ry * ux) > half_wall:
                    inside = False
                    break
            if inside:
                opening.sources.append(handle)
                opening.evidence.append("glazing line drawn across the gap")
                readings.add("WINDOW")

        if readings == {"DOOR"}:
            opening.classification, opening.status = "DOOR", "resolved"
        elif readings == {"WINDOW"}:
            opening.classification, opening.status = "WINDOW", "resolved"
        elif readings:
            opening.status = "contested"
            opening.diagnostics.append(
                "door and window evidence both present; refusing to pick"
            )
        else:
            opening.diagnostics.append(
                "a gap alone: an opening, but nobody has said of what kind"
            )
        if source_map is not None:
            source_map.record(
                "OPEN", [opening.host_wall] + opening.sources, opening.id,
                f"{opening.classification or 'unclassified'} ({opening.status})",
            )
    return openings, walls_list


def connects(opening, host, space_candidates) -> list:
    """The spaces on either side of the opening, by name.

    Probes one point just past each wall face at the opening's midpoint;
    an exterior door finds one space, a door in a freestanding wall none.
    """
    axis = _axis(host)
    if axis is None:
        return []
    (ux, uy), _length = axis
    centre = (
        host.start[0] + ux * opening.position,
        host.start[1] + uy * opening.position,
    )
    probe = host.thickness / 2.0 + 0.05
    from .spaces import contains

    found = []
    for side in (1.0, -1.0):
        point = (centre[0] - uy * probe * side, centre[1] + ux * probe * side)
        for space in space_candidates:
            if contains(space.boundary, point) and space.id not in found:
                found.append(space.id)
    return found
