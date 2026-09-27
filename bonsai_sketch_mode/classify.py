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

"""What a drafting layer's name says about the IFC class it wants to be.

A plan's layers are named by convention -- AIA's ``A-WALL`` and ``A-GLAZ``,
ISO 13567's coded fields, or plainly ``WALLS`` and ``COLUMNS`` in whichever
language the office drafts in. The conventions are stable enough to read
deterministically, and this module does only that: a keyword table, matched
against a layer name's tokens, proposing an IFC class and where it matters a
PredefinedType (a FLOOR slab is not a ROOF slab).

Two refusals carry the module's honesty:

* **No match proposes nothing.** ``EQUIPMENT`` could be a pump or a fridge;
  a name in a language the table does not know could be anything. Unresolved
  layers are returned by name with the reason, and they are the seam where
  the Sketch agents plug in -- an agent can *propose* a class through the
  existing plan/QA/approve flow, with a human's eye on it. A wrong wall is
  worse than an unclassified sketch, which every tool still works on.
* **Two matches that disagree also propose nothing.** ``WALL-DOOR-TRIM`` is
  somebody's decision, not this table's.

Pure Python throughout -- tuples and strings, no bpy -- so the table and the
matcher run and are tested anywhere.
"""

from __future__ import annotations

import re
from typing import Optional

#: keyword -> (IFC class, PredefinedType or None). Keywords are matched as
#: whole tokens of the layer name, never as substrings -- GLAZING earns a
#: window, GLA does not. AIA minor-group codes sit beside plain English and
#: the common European drafting words; the table is data so an office's own
#: convention can extend it without touching the matcher.
CONVENTIONS: dict[str, tuple[str, Optional[str]]] = {
    # Walls.
    "WALL": ("IfcWall", None), "WALLS": ("IfcWall", None),
    "PARTITION": ("IfcWall", "PARTITIONING"), "PARTITIONS": ("IfcWall", "PARTITIONING"),
    "MUR": ("IfcWall", None), "MURS": ("IfcWall", None), "WAND": ("IfcWall", None),
    # Slabs and floors.
    "SLAB": ("IfcSlab", "FLOOR"), "SLABS": ("IfcSlab", "FLOOR"),
    "FLOOR": ("IfcSlab", "FLOOR"), "FLOORS": ("IfcSlab", "FLOOR"),
    "FLR": ("IfcSlab", "FLOOR"), "DALLE": ("IfcSlab", "FLOOR"),
    # Roofs: the plane is an IfcSlab with PredefinedType ROOF, which is also
    # how the IFC+SG mapping's qualified entry reads it.
    "ROOF": ("IfcSlab", "ROOF"), "ROOFS": ("IfcSlab", "ROOF"),
    "TOIT": ("IfcSlab", "ROOF"), "DACH": ("IfcSlab", "ROOF"),
    # Structure.
    "COL": ("IfcColumn", None), "COLS": ("IfcColumn", None),
    "COLUMN": ("IfcColumn", None), "COLUMNS": ("IfcColumn", None),
    "BEAM": ("IfcBeam", None), "BEAMS": ("IfcBeam", None),
    "POUTRE": ("IfcBeam", None),
    "FOOTING": ("IfcFooting", None), "FOOTINGS": ("IfcFooting", None),
    "FNDN": ("IfcFooting", None), "FOUNDATION": ("IfcFooting", None),
    "PILE": ("IfcPile", None), "PILES": ("IfcPile", None),
    # Openings.
    "DOOR": ("IfcDoor", None), "DOORS": ("IfcDoor", None),
    "PORTE": ("IfcDoor", None), "PORTES": ("IfcDoor", None), "TUER": ("IfcDoor", None),
    "WIN": ("IfcWindow", None), "WINDOW": ("IfcWindow", None),
    "WINDOWS": ("IfcWindow", None), "GLAZ": ("IfcWindow", None),
    "GLAZING": ("IfcWindow", None), "FENETRE": ("IfcWindow", None),
    "FENSTER": ("IfcWindow", None),
    # Circulation.
    "STAIR": ("IfcStair", None), "STAIRS": ("IfcStair", None),
    "ESCALIER": ("IfcStair", None), "TREPPE": ("IfcStair", None),
    "RAMP": ("IfcRamp", None), "RAMPS": ("IfcRamp", None),
    "RAIL": ("IfcRailing", None), "RAILING": ("IfcRailing", None),
    "RAILINGS": ("IfcRailing", None), "HANDRAIL": ("IfcRailing", "HANDRAIL"),
    "BALUSTRADE": ("IfcRailing", "GUARDRAIL"),
    # Finishes and fittings.
    "CLNG": ("IfcCovering", "CEILING"), "CEIL": ("IfcCovering", "CEILING"),
    "CEILING": ("IfcCovering", "CEILING"), "CEILINGS": ("IfcCovering", "CEILING"),
    "PLAFOND": ("IfcCovering", "CEILING"),
    "FURN": ("IfcFurniture", None), "FURNITURE": ("IfcFurniture", None),
    "MOBILIER": ("IfcFurniture", None),
    "SANR": ("IfcSanitaryTerminal", None), "SANITARY": ("IfcSanitaryTerminal", None),
    "PLMB": ("IfcSanitaryTerminal", None), "WC": ("IfcSanitaryTerminal", None),
}

#: Tokens that carry no element meaning on their own: AIA discipline letters
#: and the modifiers that describe a layer's role rather than its contents.
#: They neither match nor disqualify -- A-WALL-FULL is still a wall.
_NOISE = {
    "A", "S", "M", "P", "E", "C", "I", "F", "G", "L", "T", "Q", "X", "Z",
    "FULL", "PRHT", "NEW", "EXST", "EXIST", "EXISTING", "DEMO", "TEMP",
    "OTLN", "PATT", "IDEN", "ANNO", "TEXT", "DIMS", "GRID", "LEVL",
    "0", "00", "1", "2", "3",
}


class Proposal:
    """One layer's reading: a class to assign, or the reason there is none."""

    __slots__ = ("layer", "ifc_class", "predefined_type", "matched", "reason")

    def __init__(self, layer, ifc_class=None, predefined_type=None, matched=None, reason=None):
        self.layer = layer
        self.ifc_class = ifc_class
        self.predefined_type = predefined_type
        self.matched = matched
        self.reason = reason

    @property
    def resolved(self) -> bool:
        return self.ifc_class is not None

    def as_dict(self) -> dict:
        return {
            "layer": self.layer,
            "ifc_class": self.ifc_class,
            "predefined_type": self.predefined_type,
            "matched": self.matched,
            "reason": self.reason,
        }


def tokens(name: str) -> list[str]:
    """A layer name's words, upper-cased, split on everything non-alphanumeric."""
    return [t for t in re.split(r"[^A-Za-z0-9]+", name.upper()) if t]


def classify(layer: str) -> Proposal:
    """Read one layer name against the conventions. Never guesses.

    A DXF layer name may arrive with the file's stem prefixed
    (``plan/WALLS``, as the importer names its objects); every ``/``-separated
    segment is read and the last resolving one wins, since the convention
    lives at the end of such a path.
    """
    name = layer.rsplit("/", 1)[-1]
    found: list[tuple[str, tuple[str, Optional[str]]]] = []
    for token in tokens(name):
        if token in _NOISE:
            continue
        if token in CONVENTIONS:
            found.append((token, CONVENTIONS[token]))

    if not found:
        return Proposal(layer, reason="no convention matches this name")

    classes = {target for _t, target in found}
    if len(classes) > 1:
        named = ", ".join(sorted(f"{t} ({c[0]})" for t, c in found))
        return Proposal(layer, reason=f"conventions disagree: {named}")

    token, (ifc_class, predefined) = found[0]
    return Proposal(layer, ifc_class, predefined, matched=token)


def classify_all(layers) -> tuple[list[Proposal], list[Proposal]]:
    """(resolved, unresolved) for a drawing's layers, order preserved."""
    proposals = [classify(layer) for layer in layers]
    return (
        [p for p in proposals if p.resolved],
        [p for p in proposals if not p.resolved],
    )
