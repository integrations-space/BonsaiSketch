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

"""What a drawing is, before anyone asks what storey it shows.

A DXF file is not a storey. One sheet holds two sections and three
details; another holds a plan whose name says so nowhere. So before
storeys are even a question, each file becomes a
:class:`~.ir.DrawingCandidate`: a view identity read from what the sheet
itself says -- its title text first, its filename second, UNKNOWN when
neither speaks, because UNKNOWN is an answer and a guessed PLAN is a
defect -- plus the things a drawing contributes to a building:

* **Level labels.** ``FFL +3.600`` is how a drawing states an elevation.
  The number is text, not geometry, so the reading that turned it into
  metres is written down beside the value -- and a magnitude the reading
  rules cannot place honestly stays None with the ambiguity named.
* **Grid axes.** Lines on a grid layer, named by the short label drawn
  at their ends. Grids are the drawing's own statement of shared
  reference, which is exactly what cross-sheet alignment stands on.

Pure Python over a parsed :class:`~.dxf.Drawing`, like every reader
before it.
"""

from __future__ import annotations

import math
import re
from typing import Optional

from . import ir

#: What a view calls itself, in titles and filenames alike.
VIEW_TOKENS = {
    "PLAN": "PLAN", "PLANS": "PLAN",
    "SECTION": "SECTION", "SECTIONS": "SECTION", "SEC": "SECTION",
    "ELEVATION": "ELEVATION", "ELEVATIONS": "ELEVATION", "ELEV": "ELEVATION",
    "DETAIL": "DETAIL", "DETAILS": "DETAIL", "DET": "DETAIL",
}

#: Storey hints a filename or title carries: L1, 01, GF, RF, B2, MEZZ.
_STOREY_PATTERN = re.compile(r"^(?:L\d{1,2}|B\d{1,2}|\d{2}|GF|RF|MEZZ)$")

#: A level annotation: FFL/SSL/RL/LVL/LEVEL then a signed number, or a
#: bare surveyor's mark like +3.600.
_LEVEL_PATTERN = re.compile(
    r"(?:\b(?:FFL|SSL|RL|LVL|LEVEL)\b\s*[:=]?\s*([+-]?\d+(?:\.\d+)?))", re.IGNORECASE)
_BARE_LEVEL_PATTERN = re.compile(r"^[+-]\d+\.\d{2,3}$")

#: A grid axis name: A, B, AA, 1, 12 -- the short token in the bubble.
_GRID_NAME_PATTERN = re.compile(r"^[A-Z]{1,2}$|^\d{1,2}$")

#: How far from a grid line's end its name bubble may sit, in metres.
GRID_LABEL_REACH = 2.0


def _tokens(text: str) -> list:
    out = []
    word = []
    for ch in text.upper():
        if ch.isalnum():
            word.append(ch)
        elif word:
            out.append("".join(word))
            word = []
    if word:
        out.append("".join(word))
    return out


def _read_level(value_text: str) -> tuple:
    """(metres or None, the reading in words).

    A level mark's number is text and carries no units, so the reading
    is a stated rule, not a conversion: small magnitudes are drawn in
    metres (+3.600, RL 104.5), thousands are millimetres. The band
    between is genuinely ambiguous, and an ambiguous mark stays unread
    rather than misread.
    """
    value = float(value_text)
    if abs(value) <= 200.0:
        return value, f"read {value_text} as metres, as level marks are drawn"
    if abs(value) >= 1000.0:
        return value / 1000.0, f"read {value_text} as millimetres: {value / 1000.0:g} m"
    return None, f"magnitude of {value_text} is ambiguous between metres and millimetres"


def classify(id: str, source_file: str, drawing) -> ir.DrawingCandidate:
    """One parsed drawing's identity and contributions."""
    candidate = ir.DrawingCandidate(id, source_file, units=drawing.unit_name)

    # View identity: the sheet's own words outrank its filename, and two
    # different view words on one sheet mean a mixed sheet, which is
    # UNKNOWN with the reason -- splitting it is a person's decision.
    title_views = {}
    for label in drawing.texts:
        for token in _tokens(label.text):
            if token in VIEW_TOKENS:
                title_views.setdefault(VIEW_TOKENS[token], label.text)
    stem_views = {VIEW_TOKENS[t] for t in _tokens(source_file) if t in VIEW_TOKENS}
    if len(title_views) == 1:
        candidate.view_type = next(iter(title_views))
        candidate.evidence.append(
            f"titled {title_views[candidate.view_type]!r} on the sheet")
    elif len(title_views) > 1:
        candidate.diagnostics.append(
            "sheet names several views (" + ", ".join(sorted(title_views))
            + "); likely a mixed sheet -- split it before aligning")
    elif len(stem_views) == 1:
        candidate.view_type = next(iter(stem_views))
        candidate.evidence.append(f"filename {source_file!r} says {candidate.view_type}")
    elif stem_views:
        candidate.diagnostics.append(
            "filename names several views; nothing on the sheet decides")
    else:
        candidate.diagnostics.append(
            "view type unstated -- name the sheet or confirm it by hand")

    for token in _tokens(source_file):
        if _STOREY_PATTERN.match(token) and token not in VIEW_TOKENS:
            candidate.storey_hint = token
            candidate.evidence.append(f"filename hints at storey {token}")
            break

    for label in drawing.texts:
        matched = _LEVEL_PATTERN.search(label.text)
        value_text = matched.group(1) if matched else (
            label.text.strip() if _BARE_LEVEL_PATTERN.match(label.text.strip()) else None)
        if value_text is None:
            continue
        metres, reading = _read_level(value_text)
        entry = {
            "text": label.text,
            "metres": metres,
            "position": list(label.position),
            "source": getattr(label, "source", "") or "?",
            "reading": reading,
        }
        candidate.level_labels.append(entry)
        if metres is None:
            candidate.diagnostics.append(f"level {label.text!r}: {reading}")

    # Grid axes: straight lines on a layer that calls itself a grid,
    # named by the short label nearest either end.
    short_labels = [
        label for label in drawing.texts
        if _GRID_NAME_PATTERN.match(label.text.strip())
    ]
    for layer_name, polylines in drawing.layers.items():
        if "GRID" not in _tokens(layer_name):
            continue
        for polyline in polylines:
            if len(polyline.points) != 2:
                continue
            start, end = polyline.points
            name = None
            best = GRID_LABEL_REACH
            for label in short_labels:
                for anchor in (start, end):
                    distance = math.hypot(label.position[0] - anchor[0],
                                          label.position[1] - anchor[1])
                    if distance < best:
                        best = distance
                        name = label.text.strip()
            axis = {
                "name": name,
                "start": list(start),
                "end": list(end),
                "source": getattr(polyline, "source", "") or "?",
            }
            candidate.grid_axes.append(axis)
            if name is None:
                candidate.diagnostics.append(
                    f"grid line {axis['source']} has no name bubble within reach")
    named = sum(1 for g in candidate.grid_axes if g["name"])
    if named:
        candidate.evidence.append(f"{named} named grid axis/axes for alignment")
    return candidate


def intersections(candidate) -> dict:
    """Named grid crossings: {(axis name, axis name): (x, y)}.

    Only named axes intersect for alignment purposes -- an anonymous
    line cannot correspond to anything on another sheet.
    """
    named = [g for g in candidate.grid_axes if g["name"]]
    crossings = {}
    for i in range(len(named)):
        a = named[i]
        ax, ay = a["start"]
        avx, avy = a["end"][0] - ax, a["end"][1] - ay
        for j in range(i + 1, len(named)):
            b = named[j]
            bx, by = b["start"]
            bvx, bvy = b["end"][0] - bx, b["end"][1] - by
            denom = avx * bvy - avy * bvx
            if abs(denom) < 1e-9:
                continue
            t = ((bx - ax) * bvy - (by - ay) * bvx) / denom
            key = tuple(sorted((a["name"], b["name"])))
            crossings[key] = (ax + avx * t, ay + avy * t)
    return crossings
