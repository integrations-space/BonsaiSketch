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

"""Reading walls out of the way a drafter actually draws them: as two lines.

A plan's wall is almost never a closed rectangle on its own. It is a pair of
parallel lines a wall's thickness apart, running together for the wall's
length and stopping where the next wall or an opening takes over. Extruding
such a plan's *loops* -- what the stand-up path does -- gives one solid per
enclosure, not one wall per wall. This module reads the drafting convention
instead: find the parallel pairs, and each pair states its own wall --
centreline, thickness and length all *measured off the drawing*, which is
what makes them values `derive.py` may later write without guessing.

What comes out is candidates, not walls. Deliberately:

* Every candidate carries its **provenance** -- the indices of the two
  source segments that state it -- and its **evidence**: the measured gap,
  the overlap, the angle. When a candidate is wrong, the drawing lines that
  misled it are one click away, which is worth more professionally than any
  confidence number. No probabilities are attached, because a number nothing
  calibrates is decoration; the evidence itself is the confidence.
* Everything that does not pair is returned by index, unread rather than
  misread. Lines out of parallel, gaps outside the plausible range of a
  wall, pairs whose gap tapers -- each is somebody's judgement, and the
  refusal is the module's answer, exactly as ``classify.py`` refuses names.
* A candidate spans only the interval where **both** lines run together.
  Extending centrelines to meet at junctions is inference about corners the
  drawing has not stated, and it belongs to the stage that builds geometry
  from these candidates, marked as its own decision -- not smuggled into a
  measurement.

Pure Python with tuples for points, like ``dxf.py`` and ``heal.py``, so the
detector runs and is tested anywhere.
"""

from __future__ import annotations

import math
from typing import Optional

#: The plausible range of a drawn wall's thickness, in metres. Narrower is a
#: doubled drafting line (heal's business), wider is two unrelated walls
#: facing each other across a corridor.
MIN_THICKNESS = 0.05
MAX_THICKNESS = 0.60

#: How far out of parallel two lines may lean and still be one wall's two
#: faces. A degree absorbs drafting jitter without absorbing intent.
ANGLE_TOLERANCE_DEGREES = 1.0

#: A pair must run together at least this far to state a wall. Shorter
#: overlaps are door jambs, column faces and drafting accidents.
MIN_OVERLAP = 0.30

#: A pair whose gap changes by more than this fraction of itself between the
#: two ends is tapering, and a tapering pair is not a wall drawn twice.
TAPER_TOLERANCE = 0.10


class WallCandidate:
    """One wall as a pair of drawn lines states it. Everything measured."""

    __slots__ = ("start", "end", "thickness", "length", "sources", "evidence")

    def __init__(self, start, end, thickness, length, sources, evidence):
        self.start = start          #: centreline start, (x, y)
        self.end = end              #: centreline end, (x, y)
        self.thickness = thickness  #: the measured gap between the pair
        self.length = length        #: the measured shared run
        self.sources = sources      #: indices of the two stating segments
        self.evidence = evidence    #: the measurements, in sentences

    def as_dict(self) -> dict:
        return {
            "start": [round(v, 6) for v in self.start],
            "end": [round(v, 6) for v in self.end],
            "thickness": round(self.thickness, 6),
            "length": round(self.length, 6),
            "sources": list(self.sources),
            "evidence": list(self.evidence),
        }


def segments(polylines) -> list:
    """Every polyline exploded to ((x1, y1), (x2, y2)) segments, in order.

    Closed polylines contribute their closing edge too -- the drawing drew
    it, whether or not it wrote it down.
    """
    out = []
    for polyline in polylines:
        points = polyline.points
        for a, b in zip(points, points[1:]):
            out.append((tuple(a), tuple(b)))
        if getattr(polyline, "closed", False) and len(points) > 2:
            out.append((tuple(points[-1]), tuple(points[0])))
    return out


def _axis(segment) -> Optional[tuple]:
    """(unit direction, length, anchor) with a canonical sign, or None.

    The sign canon (rightward, upward on ties) makes near-parallel testable
    with one cross product regardless of which way each line was drawn --
    and the anchor moves to whichever endpoint the canonical direction now
    leaves from, so projections stay in [0, length] either way round.
    """
    (x1, y1), (x2, y2) = segment
    dx, dy = x2 - x1, y2 - y1
    length = math.hypot(dx, dy)
    if length < 1e-9:
        return None
    ux, uy = dx / length, dy / length
    anchor = (x1, y1)
    if ux < 0.0 or (ux == 0.0 and uy < 0.0):
        ux, uy = -ux, -uy
        anchor = (x2, y2)
    return (ux, uy), length, anchor


def detect(
    segment_list,
    min_thickness: float = MIN_THICKNESS,
    max_thickness: float = MAX_THICKNESS,
    angle_tolerance: float = ANGLE_TOLERANCE_DEGREES,
    min_overlap: float = MIN_OVERLAP,
) -> tuple[list, list]:
    """(candidates, unpaired segment indices) for one layer's linework.

    Longest shared run wins first, and a segment states at most one wall --
    the simple exclusive reading. A boundary line that genuinely faces two
    walls in sequence pairs with the longer of them and leaves the other's
    partner unpaired, visibly, for the next pass or a person. Silent
    double-counting would be worse than a visible leftover.
    """
    axes = [_axis(seg) for seg in segment_list]
    sin_tolerance = math.sin(math.radians(angle_tolerance))
    pairs = []

    for i in range(len(segment_list)):
        if axes[i] is None:
            continue
        (uxi, uyi), length_i, (ax, ay) = axes[i]
        for j in range(i + 1, len(segment_list)):
            if axes[j] is None:
                continue
            (uxj, uyj), _length_j, _anchor_j = axes[j]
            if abs(uxi * uyj - uyi * uxj) > sin_tolerance:
                continue

            gaps = []
            spans = []
            for px, py in segment_list[j]:
                rx, ry = px - ax, py - ay
                gaps.append(uxi * ry - uyi * rx)   # signed lateral distance
                spans.append(uxi * rx + uyi * ry)  # projection along i
            if gaps[0] * gaps[1] <= 0.0:
                continue  # j crosses i's line: not a face of the same wall
            gap = (abs(gaps[0]) + abs(gaps[1])) / 2.0
            if not min_thickness <= gap <= max_thickness:
                continue
            if abs(abs(gaps[0]) - abs(gaps[1])) > TAPER_TOLERANCE * gap:
                continue  # tapering: two lines, but not one wall's two

            lo = max(0.0, min(spans))
            hi = min(length_i, max(spans))
            overlap = hi - lo
            if overlap < min_overlap:
                continue
            pairs.append((overlap, i, j, gap, lo, hi, gaps[0]))

    pairs.sort(key=lambda p: -p[0])
    used: set = set()
    candidates = []
    for overlap, i, j, gap, lo, hi, side in pairs:
        if i in used or j in used:
            continue
        used.add(i)
        used.add(j)
        (ux, uy), _length, (ax, ay) = axes[i]
        # The centreline sits half the gap toward the partner, along the
        # shared interval only -- junction extension is the geometry stage's
        # decision to make and to own.
        sign = 1.0 if side > 0.0 else -1.0
        nx, ny = -uy * sign, ux * sign
        half = gap / 2.0
        start = (ax + ux * lo + nx * half, ay + uy * lo + ny * half)
        end = (ax + ux * hi + nx * half, ay + uy * hi + ny * half)
        candidates.append(
            WallCandidate(
                start,
                end,
                gap,
                overlap,
                (i, j),
                [
                    f"two lines parallel within {ANGLE_TOLERANCE_DEGREES:g} degree(s)",
                    f"gap {gap:.3f} m, within the drawn-wall range",
                    f"running together for {overlap:.3f} m",
                ],
            )
        )

    unpaired = [i for i in range(len(segment_list)) if i not in used and axes[i] is not None]
    return candidates, unpaired
