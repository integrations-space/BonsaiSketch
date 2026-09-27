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

from . import ir

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
    return explode(polylines)[0]


def explode(polylines) -> tuple[list, list]:
    """(segments, source handles), in step: the provenance-keeping explode.

    Each segment's handle is its polyline's DXF source plus the segment's
    place in it (``LINE:#12/0``), so a wall candidate can name the drawn
    entities that state it, not just positions in a transient list. A
    polyline that arrived without a source -- built in code, in a test --
    gets an ordinal stand-in rather than an empty string, because an empty
    provenance would read as an answer instead of the absence of one.
    """
    segs = []
    handles = []
    for index, polyline in enumerate(polylines):
        source = getattr(polyline, "source", "") or f"?:{index}"
        points = polyline.points
        edges = list(zip(points, points[1:]))
        if getattr(polyline, "closed", False) and len(points) > 2:
            edges.append((points[-1], points[0]))
        for k, (a, b) in enumerate(edges):
            segs.append((tuple(a), tuple(b)))
            handles.append(f"{source}/{k}")
    return segs, handles


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
    sources: Optional[list] = None,
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
                (sources[i], sources[j]) if sources else (i, j),
                [
                    f"two lines parallel within {ANGLE_TOLERANCE_DEGREES:g} degree(s)",
                    f"gap {gap:.3f} m, within the drawn-wall range",
                    f"running together for {overlap:.3f} m",
                ],
            )
        )

    unpaired = [i for i in range(len(segment_list)) if i not in used and axes[i] is not None]
    return candidates, unpaired


# --- Junction resolution ------------------------------------------------
#
# Mid-wall, the parallel pair says everything. At a corner it goes quiet:
# each face line stops where the crossing wall's face begins, so a
# candidate's centreline ends short of where the wall actually turns. The
# resolver finishes the sentence -- where two centrelines would meet within
# reach of their thicknesses, the endpoints move to the meeting point --
# and every move is written down as the decision it is, in the wall's
# diagnostics and the source map, never blended into the measurements.
# The wall's identity (its id, sources, thickness, evidence) survives the
# adjustment untouched: a junction changes where a wall ends, not what it
# is or why it exists.

#: Walls leaning within this many degrees of each other do not meet at a
#: point worth trusting -- a near-parallel "intersection" slides metres for
#: a millimetre of jitter. Such pairs are continuations, not junctions,
#: and continuation-merging is its own future decision.
JUNCTION_MIN_ANGLE_DEGREES = 5.0


def resolve(
    candidates,
    source_map: Optional[ir.SourceMap] = None,
    first_wall: int = 1,
    first_junction: int = 1,
) -> tuple[list, list]:
    """(semantic walls, junctions) from one layer's candidates.

    Endpoints move to junction points computed from the *original*
    candidate geometry, all applied together afterwards, so the outcome
    does not depend on the order pairs were examined. An endpoint within
    reach of two junctions goes to the nearer one; L needs both ends, T an
    end against an interior, X two interiors. Every PAIR, JUNCTION and
    TRIM/EXTEND lands in ``source_map`` when one is given.

    ``first_wall`` and ``first_junction`` continue a numbering across
    calls, so a drawing with several wall layers still names every wall
    once: ids are how the source map, the report and a person refer to a
    wall, and a name that means two things is worse than no name.
    """
    semantic = []
    for n, candidate in enumerate(candidates, first_wall):
        wall = ir.SemanticWall(
            "W%03d" % n,
            tuple(candidate.start),
            tuple(candidate.end),
            candidate.thickness,
            candidate.sources,
            candidate.evidence,
        )
        semantic.append(wall)
        if source_map is not None:
            source_map.record(
                "PAIR", candidate.sources, wall.id,
                f"parallel pair, gap {candidate.thickness:.3f} m over {candidate.length:.3f} m",
            )

    min_cross = math.sin(math.radians(JUNCTION_MIN_ANGLE_DEGREES))
    proposals = []  # (point, [(wall index, role, along-axis position)], kind)
    for i in range(len(semantic)):
        a = semantic[i]
        avx, avy = a.end[0] - a.start[0], a.end[1] - a.start[1]
        a_len = math.hypot(avx, avy)
        if a_len < 1e-9:
            continue
        for j in range(i + 1, len(semantic)):
            b = semantic[j]
            bvx, bvy = b.end[0] - b.start[0], b.end[1] - b.start[1]
            b_len = math.hypot(bvx, bvy)
            if b_len < 1e-9:
                continue
            denom = avx * bvy - avy * bvx
            if abs(denom) < min_cross * a_len * b_len:
                continue  # near-parallel: no point worth trusting
            dx, dy = b.start[0] - a.start[0], b.start[1] - a.start[1]
            s = (dx * bvy - dy * bvx) / denom  # fraction along a
            t = (dx * avy - dy * avx) / denom  # fraction along b
            point = (a.start[0] + s * avx, a.start[1] + s * avy)
            reach = a.thickness + b.thickness

            def role(fraction, length):
                along = fraction * length
                if -reach <= along <= reach:
                    return "start", along
                if length - reach <= along <= length + reach:
                    return "end", along
                if reach < along < length - reach:
                    return "interior", along
                return None, along

            role_a, along_a = role(s, a_len)
            role_b, along_b = role(t, b_len)
            if role_a is None or role_b is None:
                continue
            ends = sum(1 for r in (role_a, role_b) if r != "interior")
            kind = {2: "L", 1: "T", 0: "X"}[ends]
            proposals.append((point, [(i, role_a, along_a), (j, role_b, along_b)], kind))

    # Nearest junction wins each endpoint; everything is measured against
    # the original endpoints so examination order cannot matter.
    moves: dict = {}
    contenders: dict = {}
    for index, (point, roles, _kind) in enumerate(proposals):
        for wall_index, role, along in roles:
            if role == "interior":
                continue
            wall = semantic[wall_index]
            endpoint = wall.start if role == "start" else wall.end
            distance = math.hypot(endpoint[0] - point[0], endpoint[1] - point[1])
            key = (wall_index, role)
            contenders.setdefault(key, []).append(index)
            if key not in moves or distance < moves[key][0]:
                moves[key] = (distance, index, along)

    junctions = []
    for index, (point, roles, kind) in enumerate(proposals):
        junction = ir.Junction("J%03d" % (first_junction + index), kind, point,
                               [semantic[wi].id for wi, _r, _a in roles])
        junctions.append(junction)
        for wall_index, _role, _along in roles:
            semantic[wall_index].junctions.append(junction.id)
        if source_map is not None:
            source_map.record("JUNCTION", junction.walls, junction.id, kind)

    # An end within reach of several junctions is an ambiguity the
    # nearest-wins rule resolves -- which is a decision, so it goes on
    # the record (the failure taxonomy reads it as F05) instead of
    # passing as the only possible reading.
    for (wall_index, role), proposal_indices in sorted(contenders.items()):
        if len(proposal_indices) < 2:
            continue
        wall = semantic[wall_index]
        names = [junctions[i].id for i in proposal_indices]
        note = (f"{role} within reach of {len(names)} junctions "
                f"({', '.join(names)}); nearest chosen")
        wall.diagnostics.append(note)
        if source_map is not None:
            source_map.record("AMBIGUOUS", [wall.id] + names, wall.id, note)

    original_length = [wall.length for wall in semantic]
    for (wall_index, role), (distance, proposal_index, along) in sorted(moves.items()):
        if distance < 1e-9:
            continue  # already there: nothing was decided
        wall = semantic[wall_index]
        point, _roles, _kind = proposals[proposal_index]
        junction = junctions[proposal_index]
        if role == "start":
            wall.start = tuple(point)
            grew = along < 0.0
        else:
            wall.end = tuple(point)
            grew = along > original_length[wall_index]
        verb = "extended" if grew else "trimmed"
        note = f"{role} {verb} {distance:.3f} m to {junction.id} ({junction.kind})"
        wall.diagnostics.append(note)
        if source_map is not None:
            source_map.record("EXTEND" if grew else "TRIM", [wall.id, junction.id], wall.id, note)

    return semantic, junctions


# --- Continuation merging -----------------------------------------------
#
# The stricter sibling of the opening merge. An opening justified its
# merge with independent evidence -- the gap was a doorway. Here the only
# evidence is the geometry itself, so every predicate is written down and
# any failure keeps the walls apart with the failing predicate named.
# Geometric continuity is not semantic identity: two collinear runs a
# hair apart are almost certainly one drawn wall split by drafting, but
# they could be two deliberately separate construction types butted
# together, and nothing on a plan tells those apart. A merge here is
# MERGE_GEOMETRY only, with the assumption on the record.

#: Ends this close are drafting fragmentation; anything wider is either
#: an opening (the opening detector's range starts at 0.40) or a real
#: gap that means something.
CONTINUATION_GAP = 0.05

#: Pairs whose nearest ends sit within this window are worth judging at
#: all; everything farther is not a continuation question.
CONSIDERATION_GAP = 0.30
CONSIDERATION_ANGLE_DEGREES = 3.0


def merge_continuations(
    walls_list,
    junctions=(),
    openings=(),
    source_map: Optional[ir.SourceMap] = None,
    first: int = 1,
    same_class: bool = True,
    same_storey: bool = True,
) -> tuple[list, list]:
    """(walls after merges, MergeCandidates considered) for one layer.

    Every pair whose facing ends fall inside the consideration window
    gets a :class:`~.ir.MergeCandidate` -- merged or kept, the judgement
    is on the record either way. ``same_class`` and ``same_storey`` are
    the caller's testimony (walls from one classified layer of one plan
    satisfy both); they are recorded as predicates so the record stays
    honest when a future caller mixes sources.
    """
    walls_list = list(walls_list)
    candidates_out: list = []
    sin_consider = math.sin(math.radians(CONSIDERATION_ANGLE_DEGREES))
    sin_collinear = math.sin(math.radians(ANGLE_TOLERANCE_DEGREES))

    merged = True
    while merged:
        merged = False
        for i in range(len(walls_list)):
            a = walls_list[i]
            # The wall's own drawn direction, not the canonical one: the
            # merge moves a.end, so "beyond the end" must mean this end.
            # Walls out of detect() are canonically oriented anyway; a
            # hand-built wall keeps whatever orientation it stated.
            dxa, dya = a.end[0] - a.start[0], a.end[1] - a.start[1]
            len_a = math.hypot(dxa, dya)
            if len_a < 1e-9:
                continue
            uxa, uya = dxa / len_a, dya / len_a
            ax, ay = a.start
            for j in range(len(walls_list)):
                if j == i:
                    continue
                b = walls_list[j]
                dxb, dyb = b.end[0] - b.start[0], b.end[1] - b.start[1]
                len_b = math.hypot(dxb, dyb)
                if len_b < 1e-9:
                    continue
                if abs(uxa * dyb - uya * dxb) > sin_consider * len_b:
                    continue
                alongs = []
                laterals = []
                for px, py in (b.start, b.end):
                    rx, ry = px - ax, py - ay
                    alongs.append(uxa * rx + uya * ry)
                    laterals.append(abs(uxa * ry - uya * rx))
                b_near, _b_far = sorted(alongs)
                gap = b_near - len_a
                if not -CONTINUATION_GAP <= gap <= CONSIDERATION_GAP:
                    continue  # not a continuation question at all

                joint_along = len_a + max(gap, 0.0) / 2.0
                joint = (ax + uxa * joint_along, ay + uya * joint_along)
                reach = max(a.thickness, b.thickness)
                terminating = any(
                    math.hypot(junction.point[0] - joint[0],
                               junction.point[1] - joint[1]) <= reach
                    and any(w not in (a.id, b.id) for w in junction.walls)
                    for junction in junctions
                )
                # An opening already explains geometry near the joint on
                # either wall: this break is that stage's business.
                b_near_is_start = alongs[0] <= alongs[1]
                conflicting = False
                for opening in openings:
                    if (opening.host_wall == a.id
                            and abs(opening.position - joint_along) <= opening.width):
                        conflicting = True
                    if opening.host_wall == b.id:
                        end_distance = (opening.position if b_near_is_start
                                        else b.length - opening.position)
                        if end_distance <= opening.width:
                            conflicting = True
                predicates = {
                    "collinear": (
                        abs(uxa * dyb - uya * dxb) <= sin_collinear * len_b
                        and max(laterals) <= LATERAL_TOLERANCE_MERGE
                    ),
                    "gap": round(max(gap, 0.0), 6),
                    "gap_within": -CONTINUATION_GAP <= gap <= CONTINUATION_GAP,
                    "thickness_match": abs(a.thickness - b.thickness) <= 0.1 * a.thickness,
                    "class_match": bool(same_class),
                    "storey_match": bool(same_storey),
                    "terminating_junction": terminating,
                    "conflicting_opening": conflicting,
                }
                passed = (
                    predicates["collinear"]
                    and predicates["gap_within"]
                    and predicates["thickness_match"]
                    and predicates["class_match"]
                    and predicates["storey_match"]
                    and not predicates["terminating_junction"]
                    and not predicates["conflicting_opening"]
                )
                merge_id = "M%03d" % (first + len(candidates_out))
                if not passed:
                    failed = next(
                        name for name, want in (
                            ("collinear", True), ("gap_within", True),
                            ("thickness_match", True), ("class_match", True),
                            ("storey_match", True), ("terminating_junction", False),
                            ("conflicting_opening", False),
                        )
                        if predicates[name] is not want
                    )
                    candidates_out.append(ir.MergeCandidate(
                        merge_id, [a.id, b.id], predicates,
                        "KEEP_SEMANTICALLY_SEPARATE",
                        f"predicate {failed} refused the merge",
                    ))
                    continue

                candidates_out.append(ir.MergeCandidate(
                    merge_id, [a.id, b.id], predicates, "MERGE_GEOMETRY",
                    "semantic identity assumed -- no type or material evidence either way",
                ))
                far_point = b.start if alongs[0] > alongs[1] else b.end
                for prior in openings:
                    if prior.host_wall != b.id:
                        continue
                    absolute = (b.start[0] + (b.end[0] - b.start[0])
                                * (prior.position / b.length),
                                b.start[1] + (b.end[1] - b.start[1])
                                * (prior.position / b.length))
                    prior.position = (
                        uxa * (absolute[0] - ax) + uya * (absolute[1] - ay)
                    )
                    prior.host_wall = a.id
                    prior.diagnostics.append(
                        f"host merged into {a.id} by {merge_id}; position re-anchored"
                    )
                a.end = tuple(far_point)
                a.sources = list(a.sources) + list(b.sources)
                a.junctions = list(a.junctions) + list(b.junctions)
                a.diagnostics.append(
                    f"geometry continued with {b.id} as {merge_id}; "
                    "semantic identity assumed, not shown"
                )
                if source_map is not None:
                    source_map.record(
                        "MERGE", [a.id, b.id, merge_id], a.id,
                        f"continuation across a {predicates['gap']:.3f} m break",
                    )
                del walls_list[j]
                merged = True
                break
            if merged:
                break
    return walls_list, candidates_out


#: How far off a shared line two "collinear" runs may sit. Tighter than
#: the opening merge's tolerance on purpose: an opening had independent
#: evidence, a continuation has only the geometry.
LATERAL_TOLERANCE_MERGE = 0.02
