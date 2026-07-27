# BonsaiBIM Sketch Mode - direct-modelling interaction for Bonsai
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

"""What the IFC+SG Model Content Requirements ask of an element.

Two shipped files back this, and the split is deliberate:

``data/ifc_sg.json``
    Extracted from the published workbook by ``tools/extract_ifc_sg.py``.
    Regenerate it; do not edit it.

``data/ifc_sg_classes.json``
    Which IFC classes each of the standard's element names covers. Hand
    maintained, because the standard contains no such mapping -- its own way of
    recording the class is a required parameter named ``IfcExportAs``, meaning
    the modeller declares it. Elements we are not confident about are mapped to
    nothing and say why, so an unreviewed guess never silently attaches the
    wrong parameter set to a real model.

Requirements are per project stage, and they grow: a door needs four parameters
at Schematic and sixteen by Detailed Design. Nothing here decides which stage a
project is at -- that is the user's to set, and asking for As-Built parameters
during concept design would be worse than asking for none.
"""

from __future__ import annotations

import json
import os
from typing import Any, Optional

_DATA = os.path.join(os.path.dirname(__file__), "data")
_REQUIREMENTS = os.path.join(_DATA, "ifc_sg.json")
_CLASSES = os.path.join(_DATA, "ifc_sg_classes.json")

_requirements: Optional[dict[str, Any]] = None
_classes: Optional[dict[str, Any]] = None
_by_class: Optional[dict[str, str]] = None
_load_error: Optional[str] = None


def _load() -> bool:
    """Read both files once. False if either is missing or malformed."""
    global _requirements, _classes, _by_class, _load_error
    if _requirements is not None and _classes is not None:
        return True
    if _load_error is not None:
        return False

    try:
        with open(_REQUIREMENTS, encoding="utf-8") as handle:
            _requirements = json.load(handle)
        with open(_CLASSES, encoding="utf-8") as handle:
            _classes = json.load(handle)
    except (OSError, ValueError) as exc:
        _load_error = f"IFC+SG requirements could not be read: {exc}"
        return False

    # One IFC class belongs to at most one element name, so the reverse index
    # is a plain dict. Built once rather than scanned per lookup.
    _by_class = {}
    for element, entry in _classes.get("elements", {}).items():
        for ifc_class in entry.get("classes", []):
            _by_class[ifc_class] = element
    return True


def load_error() -> Optional[str]:
    _load()
    return _load_error


def source() -> str:
    """The standard and revision these requirements came from."""
    return _requirements.get("source", "unknown") if _load() else "unavailable"


def stages() -> list[tuple[str, str]]:
    """(key, label) for each project stage, in order."""
    if not _load():
        return []
    return [(s["key"], s["label"]) for s in _requirements.get("stages", [])]


def elements() -> list[str]:
    """Every element name the standard defines."""
    return sorted(_requirements.get("elements", {})) if _load() else []


def element_for_class(ifc_class: str) -> Optional[str]:
    """The standard's element name for an IFC class, or None if unmapped.

    Also tries the class's supertypes by name convention -- an
    ``IfcWallStandardCase`` is a wall whether or not it is listed.
    """
    if not _load() or not ifc_class:
        return None
    assert _by_class is not None
    if ifc_class in _by_class:
        return _by_class[ifc_class]
    # IfcWallStandardCase -> IfcWall, IfcSlabStandardCase -> IfcSlab.
    for suffix in ("StandardCase", "ElementedCase"):
        if ifc_class.endswith(suffix):
            base = ifc_class[: -len(suffix)]
            if base in _by_class:
                return _by_class[base]
    return None


def mapped_classes() -> list[str]:
    """Every IFC class any element name maps onto, for whole-file sweeps."""
    if not _load():
        return []
    assert _by_class is not None
    return sorted(_by_class)


def unmapped_reason(element: str) -> Optional[str]:
    """Why an element has no IFC classes, if that is deliberate."""
    if not _load():
        return None
    assert _classes is not None
    entry = _classes.get("elements", {}).get(element)
    if entry is None:
        return f"{element!r} is not in the class mapping"
    if entry.get("classes"):
        return None
    return entry.get("review") or entry.get("note") or "deliberately unmapped"


def needs_review(element: str) -> Optional[str]:
    """A caution attached to a mapping that is mapped but uncertain."""
    if not _load():
        return None
    assert _classes is not None
    entry = _classes.get("elements", {}).get(element) or {}
    return entry.get("review") if entry.get("classes") else None


def parameters(element: str, stage: Optional[str] = None) -> list[dict[str, Any]]:
    """Parameters required for an element, optionally filtered to one stage.

    Without a stage this returns everything the standard ever asks for, which
    is the wrong thing to put in front of a user mid-project -- pass the stage.
    """
    if not _load():
        return []
    assert _requirements is not None
    entry = _requirements.get("elements", {}).get(element)
    if entry is None:
        return []
    found = entry.get("parameters", [])
    if stage is None:
        return list(found)
    return [p for p in found if stage in p.get("stages", ())]


def parameters_for_class(ifc_class: str, stage: Optional[str] = None) -> list[dict[str, Any]]:
    """Parameters required of an IFC class at a stage. Empty if unmapped."""
    element = element_for_class(ifc_class)
    return parameters(element, stage) if element else []


def parameter_names(ifc_class: str, stage: Optional[str] = None) -> list[str]:
    """Just the distinct parameter names, sorted.

    Sub-elements repeat names -- a fire rating is asked of several kinds of
    door -- and a user filling in a property set wants each field once.
    """
    return sorted({p["name"] for p in parameters_for_class(ifc_class, stage)})


def disciplines(element: str) -> list[str]:
    return sorted({p["discipline"] for p in parameters(element) if p.get("discipline")})


def summary() -> dict[str, int]:
    """Counts, for reporting that the data loaded and how much of it there is."""
    if not _load():
        return {"elements": 0, "parameters": 0, "mapped": 0}
    assert _requirements is not None and _by_class is not None
    total = sum(len(e.get("parameters", [])) for e in _requirements["elements"].values())
    mapped = sum(
        1
        for name in _requirements["elements"]
        if (_classes or {}).get("elements", {}).get(name, {}).get("classes")
    )
    return {
        "elements": len(_requirements["elements"]),
        "parameters": total,
        "mapped": mapped,
        "classes": len(_by_class),
    }
