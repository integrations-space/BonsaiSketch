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
