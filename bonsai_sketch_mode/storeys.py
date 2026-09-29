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

"""Storeys assembled from drawings, with unknown as a valid state.

A storey is not a filename. It is a claim assembled from evidence: a
plan drawing describes it, a level label states its elevation, a name
comes from the label's words or the sheet's hint -- and anything no
evidence states stays None. ``floor_to_floor`` in particular is only
ever *derived*, between two storeys whose elevations are both known,
and the derivation says which two. A storey whose elevation nobody
stated sorts to the end and says why, rather than borrowing a number.

One plan drawing, one storey candidate: the plan is the storey's
geometric description, and a building with two plans of the same storey
is a reconciliation question for a later pass, not something to blur
here by guessing which plan wins.
"""

from __future__ import annotations

from . import ir


def build(drawing_candidates) -> list:
    """StoreyCandidates from the PLAN drawings, in elevation order.

    Elevation evidence: a plan's level labels, when they agree. Several
    labels stating different levels on one plan is a diagnostic, not a
    vote -- level marks on a plan usually state its own floor, and when
    they disagree a person knows why and this pass does not.
    """
    candidates = []
    plans = [d for d in drawing_candidates if d.view_type == "PLAN"]
    for index, plan in enumerate(plans, 1):
        storey = ir.StoreyCandidate(
            "S%02d" % index,
            plan.storey_hint or plan.source_file,
        )
        storey.plans.append(plan.id)
        storey.transform = plan.transform
        levels = sorted({
            label["metres"] for label in plan.level_labels
            if label["metres"] is not None
        })
        if len(levels) == 1:
            storey.elevation = levels[0]
            stated = next(l for l in plan.level_labels if l["metres"] == levels[0])
            storey.evidence.append(
                f"elevation {levels[0]:g} m from {stated['text']!r} ({stated['source']})")
        elif len(levels) > 1:
            storey.diagnostics.append(
                "plan states several levels (" + ", ".join(f"{v:g}" for v in levels)
                + ") -- which is this floor's is a person's call")
        else:
            storey.diagnostics.append(
                "no level label read -- elevation unknown, which is a valid state")
        if plan.storey_hint:
            storey.evidence.append(f"named from the sheet's hint {plan.storey_hint!r}")
        candidates.append(storey)

    # Elevation order where known; the unknowable go last, visibly.
    candidates.sort(key=lambda s: (s.elevation is None, s.elevation or 0.0))
    for below, above in zip(candidates, candidates[1:]):
        if below.elevation is None or above.elevation is None:
            continue
        below.floor_to_floor = round(above.elevation - below.elevation, 6)
        below.evidence.append(
            f"floor-to-floor {below.floor_to_floor:g} m derived from "
            f"{below.id} -> {above.id} elevations")
    return candidates
