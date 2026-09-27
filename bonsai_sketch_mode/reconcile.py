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

"""Several views, one object: evidence reconciled, never averaged.

A plan states a door's width and host; a section states its height. The
section must not create Door D52 -- it contributes evidence to the D17
the plan already made, joined by the mark both views wrote. This module
is that join:

* :func:`extract` reads a section or elevation sheet's assertions -- the
  tight grammar ``D17 H=2100`` (or ``W=...``), a mark citing an opening
  and a value whose text-to-metres reading is stated like every level
  label's. A sheet asserting nothing contributes nothing, honestly.
* :func:`reconcile` brings each (mark, property) group of claims
  together with what the plan itself measured. Claims that agree within
  drafting tolerance become one **fill**, carrying every corroborating
  source. Claims that disagree become a :class:`~.ir.Conflict` whose
  action is HUMAN_REVIEW -- there is no confidence arithmetic here, no
  weighting, no vote, because averaging 900 against 1000 buries exactly
  the discrepancy that matters. An assertion citing a mark no opening
  carries is returned unmatched, because evidence about nothing is a
  question, not an error to drop.

The measurable target this sets is not zero conflicts -- disagreeing
drawings are the industry's weather -- but **zero silent resolutions**,
and the metrics report both counts so the difference stays visible.
"""

from __future__ import annotations

import re
from typing import Optional

from . import ir
from .drawings import _read_level

#: The assertion grammar a section sheet speaks: mark, property, value.
_ASSERTION_PATTERN = re.compile(
    r"^([DW]\d{1,3})\s+(H|W)\s*=?\s*([+-]?\d+(?:\.\d+)?)$", re.IGNORECASE)

_PROPERTIES = {"H": "OverallHeight", "W": "OverallWidth"}

#: Two claims of the same dimension within this are the same claim,
#: drawn twice; farther apart they are a disagreement.
AGREEMENT_TOLERANCE = 0.005


class Assertion:
    """One view's claim about one property of one marked opening."""

    __slots__ = ("mark", "property", "value", "source", "view", "reading")

    def __init__(self, mark, property, value, source, view, reading):
        self.mark = mark
        self.property = property
        self.value = value
        self.source = source
        self.view = view
        self.reading = reading

    def as_dict(self) -> dict:
        return {
            "mark": self.mark,
            "property": self.property,
            "value": self.value,
            "source": self.source,
            "view": self.view,
            "reading": self.reading,
        }


def extract(candidate, drawing) -> list:
    """The assertions a section or elevation sheet makes, by its grammar."""
    out = []
    for label in drawing.texts:
        matched = _ASSERTION_PATTERN.match(label.text.strip())
        if matched is None:
            continue
        metres, reading = _read_level(matched.group(3))
        if metres is None:
            candidate.diagnostics.append(
                f"assertion {label.text!r}: {reading}")
            continue
        out.append(Assertion(
            matched.group(1).upper(),
            _PROPERTIES[matched.group(2).upper()],
            metres,
            getattr(label, "source", "") or "?",
            f"{candidate.id}:{candidate.view_type}",
            reading,
        ))
    if out:
        candidate.evidence.append(f"{len(out)} assertion(s) about marked openings")
    return out


def reconcile(
    openings_list,
    assertions,
    source_map: Optional[ir.SourceMap] = None,
    first_conflict: int = 1,
) -> tuple[list, list, list]:
    """(fills, conflicts, unmatched) across every marked opening.

    A fill is ``(opening, property, value, sources)`` -- what agreeing
    evidence earned, for the caller to write into the model with the
    sources on record. For OverallWidth the plan's own measured gap
    joins the evidence, so a section contradicting the geometry is a
    conflict between views, not a silent overwrite of a measurement.
    """
    by_mark = {}
    for opening in openings_list:
        if opening.mark:
            by_mark.setdefault(opening.mark, opening)

    fills = []
    conflicts = []
    unmatched = []
    grouped: dict = {}
    for assertion in assertions:
        if assertion.mark not in by_mark:
            unmatched.append(assertion)
            continue
        grouped.setdefault((assertion.mark, assertion.property), []).append(assertion)

    for (mark, property), claims in sorted(grouped.items()):
        opening = by_mark[mark]
        evidence = [
            {"value": round(c.value, 6), "source": c.source, "view": c.view}
            for c in claims
        ]
        if property == "OverallWidth":
            evidence.insert(0, {
                "value": round(opening.width, 6),
                "source": "measured off the plan's wall gap",
                "view": "PLAN:measured",
            })
        values = [e["value"] for e in evidence]
        if max(values) - min(values) <= AGREEMENT_TOLERANCE:
            value = values[0]  # first by the hierarchy: measured, then cited
            fills.append((opening, property, value,
                          [e["source"] for e in evidence]))
            opening.evidence.append(
                f"{property} {value:g} m corroborated by "
                + ", ".join(e["view"] for e in evidence))
            if source_map is not None:
                source_map.record(
                    "ASSERT", [e["source"] for e in evidence], opening.id,
                    f"{property} = {value:g} m, views agree")
        else:
            conflict = ir.Conflict(
                "C%03d" % (first_conflict + len(conflicts)),
                opening.id, property, evidence)
            conflicts.append(conflict)
            opening.diagnostics.append(
                f"{property} is contested ({conflict.id}): "
                + " vs ".join(f"{e['value']:g} from {e['view']}" for e in evidence))
            if source_map is not None:
                source_map.record(
                    "CONFLICT", [e["source"] for e in evidence], conflict.id,
                    f"{opening.id}.{property}: human review")
    return fills, conflicts, unmatched
