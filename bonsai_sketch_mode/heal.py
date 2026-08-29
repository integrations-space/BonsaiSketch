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

"""Closing the polygons a drafted plan almost draws.

CAD linework is honest about what was drawn and silent about what was meant.
A room outline arrives as four LINEs that nearly touch; a wall run as three
polylines end to end; the polygon the drafter saw is not in the file, only
its pieces. Faces need loops, so the pieces have to be reassembled before
anything can be extruded.

Two tolerances, doing two different jobs:

``weld``
    Below this, two endpoints are the same point that drafting precision
    split in half. Chains sharing a welded endpoint join into one.

``gap``
    Below this, the two free ends of an open chain are a gap the drafter
    never meant -- the almost-closed room outline -- and a closing segment
    bridges it. Above it, the chain stays open: bridging a doorway-sized gap
    because a tolerance said so would draw a wall the plan does not have.

Everything is counted -- chains joined, gaps bridged, loops already closed,
chains left open -- because a heal that changes the drawing must say what it
changed. Pure tuples throughout, no bpy: the whole module runs and is tested
anywhere.
"""

from __future__ import annotations

import math


class Report:
    """What a heal did, for the operator to say out loud."""

    __slots__ = ("closed_already", "welded", "bridged", "left_open")

    def __init__(self) -> None:
        self.closed_already = 0
        self.welded = 0
        self.bridged = 0
        self.left_open = 0

    def summary(self) -> str:
        parts = []
        if self.closed_already:
            parts.append(f"{self.closed_already} already closed")
        if self.welded:
            parts.append(f"{self.welded} chains joined")
        if self.bridged:
            parts.append(f"{self.bridged} gaps bridged")
        if self.left_open:
            parts.append(f"{self.left_open} left open")
        return ", ".join(parts) if parts else "nothing to heal"


def _distance(a: tuple, b: tuple) -> float:
    return math.hypot(a[0] - b[0], a[1] - b[1])


def _cleaned(points: list, weld: float) -> list:
    """Consecutive points closer than the weld are one point."""
    kept: list = []
    for point in points:
        if not kept or _distance(kept[-1], point) > weld:
            kept.append(point)
    return kept


def _joined(chains: list[list], weld: float, report: Report) -> list[list]:
    """Chains whose free ends meet within the weld, merged until none do.

    Greedy nearest-pair merging, deliberately: at a T-junction three ends
    share a node and only two of them can join, and taking the closest pair
    is both deterministic and what a drafter squinting at the junction would
    pick. The leftover end stays free and is the open chain the report
    counts.
    """
    chains = [list(chain) for chain in chains]
    while True:
        best = None
        best_distance = weld
        for i in range(len(chains)):
            for j in range(i + 1, len(chains)):
                for end_i in (0, -1):
                    for end_j in (0, -1):
                        d = _distance(chains[i][end_i], chains[j][end_j])
                        if d <= best_distance:
                            best = (i, j, end_i, end_j)
                            best_distance = d
        if best is None:
            return chains
        i, j, end_i, end_j = best
        first = chains[i] if end_i == -1 else list(reversed(chains[i]))
        second = chains[j] if end_j == 0 else list(reversed(chains[j]))
        # The meeting point is drawn twice, once by each chain; keep one.
        merged = first + second[1:] if _distance(first[-1], second[0]) == 0.0 else first + second
        chains[i] = merged
        del chains[j]
        report.welded += 1


def heal(
    polylines: list[tuple[list, bool]],
    weld: float,
    gap: float,
) -> tuple[list[list], list[list], Report]:
    """(closed loops, open chains, report) from drafted linework.

    ``polylines`` are (points, already_closed) pairs, as the DXF reader
    produces them. Loops come back without a repeated endpoint. ``gap`` at or
    below ``weld`` means only touching ends close anything; the useful range
    is above it.
    """
    report = Report()
    loops: list[list] = []
    opens: list[list] = []

    for points, closed in polylines:
        points = _cleaned(points, weld)
        if closed:
            if len(points) >= 3:
                loops.append(points)
                report.closed_already += 1
            continue
        # A polyline that walks back onto its own start closed itself without
        # saying so.
        if len(points) >= 4 and _distance(points[0], points[-1]) <= weld:
            loops.append(points[:-1])
            report.closed_already += 1
            continue
        if len(points) >= 2:
            opens.append(points)

    still_open: list[list] = []
    for chain in _joined(opens, weld, report):
        ends_meet = _distance(chain[0], chain[-1])
        if len(chain) >= 4 and ends_meet <= weld:
            loops.append(chain[:-1])
            report.closed_already += 1
        elif len(chain) >= 3 and ends_meet <= gap:
            # The bridge is the closing edge itself: the loop's last point
            # simply connects back to its first when it becomes a face.
            loops.append(chain)
            report.bridged += 1
        else:
            report.left_open += 1
            still_open.append(chain)
    return loops, still_open, report
