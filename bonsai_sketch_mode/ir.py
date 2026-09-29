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

"""The compiler's own state: what AutoModel believes, and why, and from what.

The IFC file is the delivered model and stays authoritative for delivery.
But a compiler needs a working representation that is neither its input nor
its output, because both ends are the wrong shape for the questions the
middle has to answer. A DXF line does not know it is half a wall; an
IfcWall does not remember which two drawn lines caused it to exist, what
was trimmed to meet what, or which evidence would have to be re-weighed if
a section later disagrees with the plan. This module is that middle: plain
records, pure Python, serialisable to dicts, independent of Blender, Bonsai
and IFC serialisation alike -- deliberately, so the compilation state can
be tested, diffed and reported anywhere.

Two kinds of thing live here:

* **Semantic objects** -- :class:`SemanticWall`, :class:`Junction`,
  :class:`SpaceCandidate` -- each carrying its measured facts, the sources
  that state them, the evidence in sentences, and ``diagnostics`` for every
  decision a stage took on its behalf (an end extended to a junction is a
  decision, not a measurement, and the two must never blur). ``ifc_guid``
  is filled when the object is emitted, closing the loop from a delivered
  IFC element back to the drawn lines.
* **The source map** -- :class:`SourceMap`, the ledger of derivations.
  Every transformation that consumes one thing and produces another writes
  one record: which inputs, which operation, which output. Clicking a wall
  and asking "why does this exist" is a walk over these records, and a
  record nothing wrote is an answer the system honestly does not have.

Identifiers are deterministic and human-readable (``W001``, ``J002``,
``S001``): the same drawing compiles to the same names, which is what makes
two runs comparable and a regression report readable.
"""

from __future__ import annotations

from typing import Optional


class SourceMap:
    """The ledger of derivations: input handles -> operation -> output.

    Handles are strings all the way down -- a DXF entity's ``LINE:#12``, a
    wall's ``W003``, a junction's ``J001``, an emitted element's IFC
    GlobalId -- so the ledger never holds an object reference that a later
    stage could mutate behind it.
    """

    def __init__(self) -> None:
        self.records: list[dict] = []

    def record(self, op: str, inputs, output: str, note: str = "") -> None:
        self.records.append(
            {
                "op": op,
                "inputs": [str(i) for i in inputs],
                "output": str(output),
                "note": note,
            }
        )

    def about(self, handle: str) -> list[dict]:
        """Every record that mentions the handle, as input or output."""
        handle = str(handle)
        return [r for r in self.records if r["output"] == handle or handle in r["inputs"]]

    def as_list(self) -> list[dict]:
        return [dict(r) for r in self.records]


class SemanticWall:
    """One wall the compiler believes in: measured facts plus their pedigree."""

    __slots__ = (
        "id", "start", "end", "thickness", "sources",
        "junctions", "evidence", "diagnostics", "ifc_guid",
    )

    def __init__(self, id, start, end, thickness, sources, evidence):
        self.id = id
        self.start = start          #: resolved centreline start, (x, y)
        self.end = end              #: resolved centreline end, (x, y)
        self.thickness = thickness  #: measured off the drawing, always
        self.sources = list(sources)
        self.junctions: list[str] = []
        self.evidence = list(evidence)      #: what the drawing stated
        self.diagnostics: list[str] = []    #: what a stage decided
        self.ifc_guid: Optional[str] = None

    @property
    def length(self) -> float:
        return ((self.end[0] - self.start[0]) ** 2 + (self.end[1] - self.start[1]) ** 2) ** 0.5

    def as_dict(self) -> dict:
        return {
            "id": self.id,
            "start": [round(v, 6) for v in self.start],
            "end": [round(v, 6) for v in self.end],
            "thickness": round(self.thickness, 6),
            "length": round(self.length, 6),
            "sources": list(self.sources),
            "junctions": list(self.junctions),
            "evidence": list(self.evidence),
            "diagnostics": list(self.diagnostics),
            "ifc_guid": self.ifc_guid,
        }


class Junction:
    """Where walls meet: an L, a T, or an X, at a point, between named walls."""

    __slots__ = ("id", "kind", "point", "walls")

    def __init__(self, id, kind, point, walls):
        self.id = id
        self.kind = kind    #: "L", "T" or "X"
        self.point = point  #: (x, y)
        self.walls = list(walls)

    def as_dict(self) -> dict:
        return {
            "id": self.id,
            "kind": self.kind,
            "point": [round(v, 6) for v in self.point],
            "walls": list(self.walls),
        }


class DrawingCandidate:
    """One drawing's identity: what kind of view it is, and what it brings.

    Between a DXF file and a storey stands the drawing itself. A file is
    not a storey -- one sheet can hold two sections and three details --
    so the compiler first establishes what it is looking *at*: a PLAN, a
    SECTION, an ELEVATION, a DETAIL, or UNKNOWN, which is a valid answer
    and better than a guess. Alongside the identity travel the things a
    drawing contributes to the building: its units, its level labels
    (each with the reading that turned text into metres stated, or
    honestly None), and its named grid axes, which are what cross-sheet
    alignment will stand on. ``transform`` names the TransformCandidate
    that places this drawing in building coordinates, once one is earned.
    """

    __slots__ = ("id", "source_file", "view_type", "units", "level_labels",
                 "grid_axes", "storey_hint", "transform", "evidence", "diagnostics")

    def __init__(self, id, source_file, units="as drawn"):
        self.id = id
        self.source_file = source_file
        self.view_type = "UNKNOWN"
        self.units = units
        self.level_labels: list[dict] = []
        self.grid_axes: list[dict] = []
        self.storey_hint: Optional[str] = None
        self.transform: Optional[str] = None
        self.evidence: list[str] = []
        self.diagnostics: list[str] = []

    def as_dict(self) -> dict:
        return {
            "id": self.id,
            "source_file": self.source_file,
            "view_type": self.view_type,
            "units": self.units,
            "level_labels": [dict(l) for l in self.level_labels],
            "grid_axes": [dict(g) for g in self.grid_axes],
            "storey_hint": self.storey_hint,
            "transform": self.transform,
            "evidence": list(self.evidence),
            "diagnostics": list(self.diagnostics),
        }


class TransformCandidate:
    """How one drawing lands in building coordinates, and on whose word.

    A transform is a claim, so it carries the evidence that earned it --
    which grid met which grid -- the residual left over, and a status:
    ACCEPTED when the evidence agrees within tolerance, NEEDS_REVIEW when
    it fits but loosely, UNRESOLVED when nothing shared could be found
    and a person must state the correspondence. A fit computed from
    geometry matching never masquerades as surveyed truth: the evidence
    line says exactly what kind of claim this is.
    """

    __slots__ = ("id", "drawing", "rotation_degrees", "translation", "scale",
                 "evidence", "residual", "status")

    def __init__(self, id, drawing):
        self.id = id
        self.drawing = drawing
        self.rotation_degrees = 0.0
        self.translation = (0.0, 0.0)
        self.scale = 1.0
        self.evidence: list[str] = []
        self.residual: Optional[float] = None
        self.status = "UNRESOLVED"

    def apply(self, point) -> tuple:
        import math as _math

        angle = _math.radians(self.rotation_degrees)
        c, s = _math.cos(angle), _math.sin(angle)
        x, y = point
        return (self.scale * (x * c - y * s) + self.translation[0],
                self.scale * (x * s + y * c) + self.translation[1])

    def as_dict(self) -> dict:
        return {
            "id": self.id,
            "drawing": self.drawing,
            "rotation_degrees": round(self.rotation_degrees, 9),
            "translation": [round(v, 6) for v in self.translation],
            "scale": round(self.scale, 9),
            "evidence": list(self.evidence),
            "residual": None if self.residual is None else round(self.residual, 6),
            "status": self.status,
        }


class StoreyCandidate:
    """One storey, assembled from the drawings that describe it.

    ``elevation`` comes from level evidence or stays None; so does
    ``floor_to_floor``, which is only ever derived between two *known*
    elevations and says so. Unknown is valid compiler state -- the same
    principle that leaves a door's height null until a section speaks.
    """

    __slots__ = ("id", "name", "elevation", "floor_to_floor", "plans",
                 "sections", "transform", "evidence", "diagnostics", "ifc_guid")

    def __init__(self, id, name):
        self.id = id
        self.name = name
        self.elevation: Optional[float] = None
        self.floor_to_floor: Optional[float] = None
        self.plans: list[str] = []
        self.sections: list[str] = []
        self.transform: Optional[str] = None
        self.evidence: list[str] = []
        self.diagnostics: list[str] = []
        self.ifc_guid: Optional[str] = None

    def as_dict(self) -> dict:
        return {
            "id": self.id,
            "name": self.name,
            "elevation": self.elevation,
            "floor_to_floor": self.floor_to_floor,
            "plans": list(self.plans),
            "sections": list(self.sections),
            "transform": self.transform,
            "evidence": list(self.evidence),
            "diagnostics": list(self.diagnostics),
            "ifc_guid": self.ifc_guid,
        }


class MergeCandidate:
    """Two walls that might be one, judged by named predicates.

    Geometric continuity and semantic identity are different claims. Two
    collinear runs a hair apart are almost certainly one drawn wall split
    by drafting -- but they could also be two deliberately separate
    construction types butted together, and until type or material
    evidence exists nothing on the plan can tell those apart. So the
    decision here is ``MERGE_GEOMETRY``, never "same wall in every
    sense": the geometry joins, and the record says semantic identity is
    assumed, not shown. Any failed predicate makes the decision
    ``KEEP_SEMANTICALLY_SEPARATE`` with the failing predicate named --
    a refusal a person can audit, not a threshold someone tuned.
    """

    __slots__ = ("id", "walls", "predicates", "decision", "note")

    def __init__(self, id, walls, predicates, decision, note=""):
        self.id = id
        self.walls = list(walls)
        self.predicates = dict(predicates)
        self.decision = decision  #: MERGE_GEOMETRY | KEEP_SEMANTICALLY_SEPARATE
        self.note = note

    def as_dict(self) -> dict:
        return {
            "id": self.id,
            "walls": list(self.walls),
            "predicates": dict(self.predicates),
            "decision": self.decision,
            "note": self.note,
        }


class OpeningCandidate:
    """A break in a wall that several kinds of evidence may explain.

    The geometry can prove an opening exists -- two collinear wall runs,
    one gap of a doorway's width -- long before anything says what fills
    it. So the candidate exists first, ``classification`` arrives only
    when evidence converges (a swing arc, a named block, glazing lines),
    and ``status`` says where that stands: ``possible`` is a discontinuity
    awaiting judgement, ``resolved`` has one reading, ``contested`` has
    two and refuses to pick. A wall gap alone is never a door.

    ``position`` runs along the host wall's centreline from its start;
    ``connects`` is filled when the spaces on either side are known, which
    is the relationship a door actually is: two rooms and a way between.
    """

    __slots__ = ("id", "host_wall", "position", "width", "sources", "evidence",
                 "classification", "status", "connects", "diagnostics",
                 "mark", "opening_guid", "element_guid")

    def __init__(self, id, host_wall, position, width, sources, evidence):
        self.id = id
        self.host_wall = host_wall
        self.position = position    #: metres along the host's centreline
        self.width = width          #: the measured gap
        self.sources = list(sources)
        self.evidence = list(evidence)
        self.classification: Optional[str] = None   #: "DOOR", "WINDOW" or None
        self.status = "possible"    #: possible | resolved | contested
        self.connects: list[str] = []
        self.diagnostics: list[str] = []
        self.mark: Optional[str] = None  #: the drawn tag (D17) other views cite
        self.opening_guid: Optional[str] = None
        self.element_guid: Optional[str] = None

    def as_dict(self) -> dict:
        return {
            "id": self.id,
            "host_wall": self.host_wall,
            "position": round(self.position, 6),
            "width": round(self.width, 6),
            "sources": list(self.sources),
            "evidence": list(self.evidence),
            "classification": self.classification,
            "status": self.status,
            "connects": list(self.connects),
            "diagnostics": list(self.diagnostics),
            "mark": self.mark,
            "opening_guid": self.opening_guid,
            "element_guid": self.element_guid,
        }


class Conflict:
    """Evidence that disagrees, kept disagreeing until a person decides.

    Once several views contribute information, disagreement is
    inevitable, and the one wrong answer is arithmetic: averaging,
    weighting, or letting a confidence score pick a side buries exactly
    the discrepancy that matters. A Conflict holds every claim with its
    value, its source handle and the view that made it, and its action
    is HUMAN_REVIEW -- always. The measurable target is not zero
    conflicts; it is zero *silent resolutions*.
    """

    __slots__ = ("id", "object", "property", "evidence", "action")

    def __init__(self, id, object, property, evidence):
        self.id = id
        self.object = object
        self.property = property
        self.evidence = [dict(e) for e in evidence]
        self.action = "HUMAN_REVIEW"

    def as_dict(self) -> dict:
        return {
            "id": self.id,
            "object": self.object,
            "property": self.property,
            "evidence": [dict(e) for e in self.evidence],
            "action": self.action,
        }


class SpaceCandidate:
    """An enclosure the wall faces state, with the name the drawing wrote."""

    __slots__ = ("id", "boundary", "area", "label", "label_source", "walls",
                 "evidence", "diagnostics", "ifc_guid")

    def __init__(self, id, boundary, area, walls, evidence):
        self.id = id
        self.boundary = list(boundary)  #: (x, y) loop, unclosed repetition
        self.area = area                #: measured, shoelace over the boundary
        self.label: Optional[str] = None
        self.label_source: Optional[str] = None
        self.walls = list(walls)
        self.evidence = list(evidence)
        self.diagnostics: list[str] = []
        self.ifc_guid: Optional[str] = None

    def as_dict(self) -> dict:
        return {
            "id": self.id,
            "boundary": [[round(x, 6), round(y, 6)] for x, y in self.boundary],
            "area": round(self.area, 6),
            "label": self.label,
            "label_source": self.label_source,
            "walls": list(self.walls),
            "evidence": list(self.evidence),
            "diagnostics": list(self.diagnostics),
            "ifc_guid": self.ifc_guid,
        }
