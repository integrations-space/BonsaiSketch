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

"""Reading a section's drawn geometry as evidence, not as a second model.

The assertion grammar (``D1 H=2100``) is a note a drafter writes; this
module reads what a section *draws*: the level lines that carry its
vertical datum, and the jamb pairs that stand where a marked opening
cuts through. What comes out is the same currency the grammar produces
-- :class:`~.reconcile.Assertion` objects joined to plan openings by
their mark -- so drawn heights flow through the same reconciliation,
corroborate the same measurements, and disagree into the same Conflicts.
A view contributes evidence; it never authors a duplicate object.

The datum comes first, because a drawn height means nothing until the
sheet says where zero is. Each level label (``FFL +3.600``) pairs with
the long horizontal line beside it; every such line states one offset
between drawn y and real elevation, and the offsets must agree -- a
section not drawn 1:1 in model space, or with mislabelled levels, is
refused whole, with the spread named, rather than read at a guessed
scale. One level line is enough for a datum; two or more must concur.

Then the openings: near each drawn mark, the two nearest vertical jamb
runs a plausible opening-width apart give head, sill and width --
measured off the drawing, with the jambs' entity handles as sources.
``OverallHeight`` is head minus sill; ``SillHeight`` is sill above the
nearest level line at or below it; ``OverallWidth`` joins the plan's
measured gap in reconciliation, where agreement corroborates and
disagreement escalates. A mark with no jamb pair in reach contributes
nothing, and says so.

Pure Python, like every reader before it.
"""

from __future__ import annotations

import math
from typing import Optional

from . import ir
from .openings import MARK_PATTERN
from .reconcile import Assertion

#: A level line is a long horizontal; anything shorter is a tick.
LEVEL_LINE_MIN_LENGTH = 1.0

#: How far a level label may sit from its line, vertically (drawn metres).
LEVEL_MATCH_TOLERANCE = 0.2

#: All level lines must state the same drawn-y-to-elevation offset
#: within this, or the sheet's datum is refused.
DATUM_CONSISTENCY = 0.005

#: How far from a mark the jamb search looks, horizontally.
JAMB_WINDOW = 1.5

#: Verticals within this of each other are one jamb drawn in strokes.
JAMB_X_CLUSTER = 0.01

#: A jamb shorter than this is a tick or a leader, not an opening's side.
MIN_JAMB_HEIGHT = 0.3

#: The plausible range of a drawn opening's width, as the plan reads it.
MIN_WIDTH = 0.30
MAX_WIDTH = 3.00


def _segments(drawing):
    horizontals = []
    verticals = []
    for polylines in drawing.layers.values():
        for polyline in polylines:
            source = getattr(polyline, "source", "") or "?"
            points = polyline.points
            for (x1, y1), (x2, y2) in zip(points, points[1:]):
                if abs(y1 - y2) <= 1e-3 and abs(x1 - x2) > 1e-3:
                    horizontals.append((min(x1, x2), max(x1, x2), (y1 + y2) / 2, source))
                elif abs(x1 - x2) <= 1e-3 and abs(y1 - y2) > 1e-3:
                    verticals.append(((x1 + x2) / 2, min(y1, y2), max(y1, y2), source))
    return horizontals, verticals


def extract_geometry(candidate, drawing) -> tuple[list, list]:
    """(assertions, level lines) a section's drawn geometry states.

    ``candidate`` is the sheet's DrawingCandidate; its parsed level
    labels anchor the datum and its diagnostics receive every refusal.
    Level lines come back as ``{"metres", "y", "source"}`` for the
    storey corroboration pass.
    """
    horizontals, verticals = _segments(drawing)

    level_lines = []
    for label in candidate.level_labels:
        if label["metres"] is None:
            continue
        nearby = [h for h in horizontals
                  if h[1] - h[0] >= LEVEL_LINE_MIN_LENGTH
                  and abs(h[2] - label["position"][1]) <= LEVEL_MATCH_TOLERANCE]
        if not nearby:
            continue
        line = min(nearby, key=lambda h: abs(h[2] - label["position"][1]))
        level_lines.append({"metres": label["metres"], "y": line[2], "source": line[3]})

    if not level_lines:
        return [], []
    offsets = [line["metres"] - line["y"] for line in level_lines]
    spread = max(offsets) - min(offsets)
    if spread > DATUM_CONSISTENCY:
        candidate.diagnostics.append(
            f"drawn levels disagree about the datum by {spread * 1000:.1f} mm -- "
            "the section is not drawn 1:1 in model space, or a level is "
            "mislabelled; its geometry is not read")
        return [], level_lines
    datum = sum(offsets) / len(offsets)

    assertions = []
    view = f"{candidate.id}:{candidate.view_type}:drawn"
    for label in drawing.texts:
        matched = MARK_PATTERN.match(label.text.strip())
        if matched is None:
            continue
        mark = label.text.strip()
        mark_x = label.position[0]
        jambs = [v for v in verticals
                 if abs(v[0] - mark_x) <= JAMB_WINDOW
                 and v[2] - v[1] >= MIN_JAMB_HEIGHT]
        clusters: list = []
        for jamb in sorted(jambs, key=lambda v: v[0]):
            if clusters and abs(jamb[0] - clusters[-1]["x"]) <= JAMB_X_CLUSTER:
                cluster = clusters[-1]
                cluster["bottom"] = min(cluster["bottom"], jamb[1])
                cluster["top"] = max(cluster["top"], jamb[2])
                cluster["sources"].append(jamb[3])
            else:
                clusters.append({"x": jamb[0], "bottom": jamb[1], "top": jamb[2],
                                 "sources": [jamb[3]]})
        if len(clusters) < 2:
            candidate.diagnostics.append(
                f"mark {mark!r} has no jamb pair in reach; "
                "the drawn geometry contributes nothing for it")
            continue
        clusters.sort(key=lambda c: abs(c["x"] - mark_x))
        first, second = clusters[0], clusters[1]
        width = abs(second["x"] - first["x"])
        if not MIN_WIDTH <= width <= MAX_WIDTH:
            candidate.diagnostics.append(
                f"mark {mark!r}: nearest jambs are {width:.3f} m apart, "
                "outside a drawn opening's range")
            continue
        head = min(first["top"], second["top"])
        sill = max(first["bottom"], second["bottom"])
        if head - sill < MIN_JAMB_HEIGHT:
            continue
        sources = first["sources"] + second["sources"]
        head_elev = head + datum
        sill_elev = sill + datum
        reading = (f"measured off drawn jambs between {sill_elev:+.3f} "
                   f"and {head_elev:+.3f}, datum from "
                   + ", ".join(l["source"] for l in level_lines))
        assertions.append(Assertion(
            mark, "OverallHeight", round(head - sill, 6),
            ", ".join(sources), view, reading))
        assertions.append(Assertion(
            mark, "OverallWidth", round(width, 6),
            ", ".join(sources), view, reading))
        below = [l for l in level_lines if l["metres"] <= sill_elev + 1e-3]
        if below:
            floor = max(below, key=lambda l: l["metres"])
            assertions.append(Assertion(
                mark, "SillHeight", round(sill_elev - floor["metres"], 6),
                ", ".join(sources), view,
                f"sill {sill_elev:+.3f} above the {floor['metres']:+.3f} level"))
    if assertions:
        candidate.evidence.append(
            f"{len(assertions)} assertion(s) measured off drawn section geometry")
    return assertions, level_lines


def corroborate_storeys(
    storey_candidates,
    level_lines,
    candidate,
    first_conflict: int = 1,
) -> list:
    """Drawn levels against the storeys: corroboration, or a Conflict.

    A drawn level within drafting tolerance of a storey's elevation
    backs it; one that *nearly* matches contests it -- the disagreement
    a mislabelled section causes, escalated rather than averaged. A
    level matching nothing at all is noted as an unmodelled level (a
    roof line, a datum), which is information, not failure.
    """
    conflicts = []
    for line in level_lines:
        nearest = min(
            (s for s in storey_candidates if s.elevation is not None),
            key=lambda s: abs(s.elevation - line["metres"]),
            default=None,
        )
        if nearest is None:
            continue
        difference = abs(nearest.elevation - line["metres"])
        if difference <= 0.005:
            nearest.evidence.append(
                f"elevation corroborated by drawn level on {candidate.id} "
                f"({line['source']})")
        elif difference <= 0.2:
            conflict = ir.Conflict(
                "C%03d" % (first_conflict + len(conflicts)),
                nearest.id, "Elevation",
                [{"value": nearest.elevation, "source": "level label on the plan",
                  "view": "PLAN"},
                 {"value": line["metres"], "source": line["source"],
                  "view": f"{candidate.id}:{candidate.view_type}:drawn"}])
            conflicts.append(conflict)
            nearest.diagnostics.append(
                f"elevation contested by drawn level on {candidate.id} "
                f"({conflict.id}): {nearest.elevation:g} vs {line['metres']:g}")
        else:
            candidate.diagnostics.append(
                f"drawn level {line['metres']:+.3f} matches no storey -- "
                "a roof line or an unmodelled level")
    return conflicts
