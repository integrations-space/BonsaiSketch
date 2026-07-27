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

"""What the Model Content Requirements ask of an element.

The published workbook carries two datasets, and both are queryable here:

The **IFC+SG** requirements (for CORENET-X regulatory submission) are one set
for every project. Backed by ``data/ifc_sg.json``, extracted from the workbook
by ``tools/extract_ifc_sg.py`` -- regenerate it; do not edit it -- and by the
hand-maintained class mapping ``data/ifc_sg_classes.json``. Hand maintained,
because the standard contains no such mapping: its own way of recording the
class is a required parameter named ``IfcExportAs``, meaning the modeller
declares it. Elements we are not confident about are mapped to nothing and say
why, so an unreviewed guess never silently attaches the wrong parameter set to
a real model.

The **Project Delivery** requirements (the workbook's filter says "for DBC
Submission") genuinely differ per building typology -- different element
vocabularies, different parameters, and an "optional" mark the regulatory set
does not have. Backed by ``data/delivery/<typology>.json`` (extracted, one
file per typology, loaded only when that typology is chosen) and the
hand-maintained ``data/delivery_classes.json`` for element names the base
mapping does not know. Which typology a project is -- like which stage it is
at -- is the user's to say, never guessed, so every delivery query takes the
typology explicitly.

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

    # A plain class name belongs to at most one element name -- shared
    # classes are disambiguated by qualified "Class/PREDEFINEDTYPE" entries
    # -- so the reverse index is a plain dict, built once rather than
    # scanned per lookup.
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


def _lookup_class(
    index: dict[str, str], ifc_class: str, predefined_type: Optional[str] = None
) -> Optional[str]:
    """A reverse-index lookup.

    A qualified entry ("IfcSlab/ROOF") wins over a plain one for instances
    carrying that predefined type -- how one class is shared between two
    element names. Supertypes are tried by name convention: an
    ``IfcWallStandardCase`` is a wall whether or not it is listed.
    """
    candidates = [ifc_class]
    # IfcWallStandardCase -> IfcWall, IfcSlabStandardCase -> IfcSlab.
    for suffix in ("StandardCase", "ElementedCase"):
        if ifc_class.endswith(suffix):
            candidates.append(ifc_class[: -len(suffix)])
    for name in candidates:
        if predefined_type:
            qualified = f"{name}/{str(predefined_type).upper()}"
            if qualified in index:
                return index[qualified]
        if name in index:
            return index[name]
    return None


def element_for_class(ifc_class: str, predefined_type: Optional[str] = None) -> Optional[str]:
    """The standard's element name for an IFC class, or None if unmapped."""
    if not _load() or not ifc_class:
        return None
    assert _by_class is not None
    return _lookup_class(_by_class, ifc_class, predefined_type)


def mapped_classes() -> list[str]:
    """Every IFC class any element name maps onto, for whole-file sweeps.

    Qualified entries collapse to their class: a sweep visits instances,
    which is where predefined types are read.
    """
    if not _load():
        return []
    assert _by_class is not None
    return sorted({key.split("/")[0] for key in _by_class})


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


def parameters_for_class(
    ifc_class: str,
    stage: Optional[str] = None,
    predefined_type: Optional[str] = None,
) -> list[dict[str, Any]]:
    """Parameters required of an IFC class at a stage. Empty if unmapped."""
    element = element_for_class(ifc_class, predefined_type)
    return parameters(element, stage) if element else []


def parameter_names(
    ifc_class: str,
    stage: Optional[str] = None,
    predefined_type: Optional[str] = None,
) -> list[str]:
    """Just the distinct parameter names, sorted.

    Sub-elements repeat names -- a fire rating is asked of several kinds of
    door -- and a user filling in a property set wants each field once.
    """
    return sorted({p["name"] for p in parameters_for_class(ifc_class, stage, predefined_type)})


def disciplines(element: str) -> list[str]:
    return sorted({p["discipline"] for p in parameters(element) if p.get("discipline")})


# --- Project Delivery (per-typology) -----------------------------------------

_DELIVERY_DIR = os.path.join(_DATA, "delivery")
_DELIVERY_INDEX = os.path.join(_DELIVERY_DIR, "index.json")
_DELIVERY_CLASSES = os.path.join(_DATA, "delivery_classes.json")

_delivery_index: Optional[list[dict[str, str]]] = None
_delivery_classes: Optional[dict[str, Any]] = None
#: typology key -> (data, by_class, warnings) once loaded, or an error string.
_delivery: dict[str, Any] = {}


def _load_delivery_index() -> list[dict[str, str]]:
    global _delivery_index, _delivery_classes
    if _delivery_index is None:
        try:
            with open(_DELIVERY_INDEX, encoding="utf-8") as handle:
                _delivery_index = json.load(handle).get("typologies", [])
            with open(_DELIVERY_CLASSES, encoding="utf-8") as handle:
                _delivery_classes = json.load(handle)
        except (OSError, ValueError):
            _delivery_index = []
            _delivery_classes = {}
    return _delivery_index


def typologies() -> list[tuple[str, str]]:
    """(key, label) for each shipped Project Delivery typology, in order."""
    return [(t["key"], t["label"]) for t in _load_delivery_index()]


def _element_classes(element: str) -> list[str]:
    """A delivery element's classes: the base mapping, then the delivery one."""
    for source_map in (_classes, _delivery_classes):
        entry = ((source_map or {}).get("elements") or {}).get(element)
        if entry is not None:
            return entry.get("classes", [])
    return []


def _load_typology(typology: str) -> Optional[tuple[dict, dict, list[str]]]:
    """One typology's data and reverse class index, cached. None on failure."""
    if not _load() or not typology:
        return None
    cached = _delivery.get(typology)
    if isinstance(cached, tuple):
        return cached
    if cached is not None:  # a recorded error string
        return None

    _load_delivery_index()
    try:
        with open(os.path.join(_DELIVERY_DIR, f"{typology}.json"), encoding="utf-8") as handle:
            data = json.load(handle)
    except (OSError, ValueError) as exc:
        _delivery[typology] = f"Delivery requirements for {typology!r} could not be read: {exc}"
        return None

    # The reverse index is per typology: element vocabularies differ, so a
    # class free in one typology may be contested in another. A contested
    # class is dropped outright -- attaching one of two plausible parameter
    # sets by luck of iteration order is exactly the silent wrongness the
    # unmapped entries exist to avoid.
    by_class: dict[str, str] = {}
    contested: set[str] = set()
    for element in data.get("elements", {}):
        for ifc_class in _element_classes(element):
            if ifc_class in by_class and by_class[ifc_class] != element:
                contested.add(ifc_class)
            else:
                by_class[ifc_class] = element
    warnings = []
    for ifc_class in sorted(contested):
        warnings.append(
            f"{ifc_class} is claimed by more than one {typology!r} element; attaching neither"
        )
        del by_class[ifc_class]

    result = (data, by_class, warnings)
    _delivery[typology] = result
    return result


def delivery_load_error(typology: str) -> Optional[str]:
    """Why a typology's data is unusable, if it is."""
    if _load_typology(typology) is None:
        cached = _delivery.get(typology)
        return cached if isinstance(cached, str) else f"No delivery data for {typology!r}"
    return None


def delivery_warnings(typology: str) -> list[str]:
    """Mapping conflicts found in a typology's class index, for reporting."""
    loaded = _load_typology(typology)
    return list(loaded[2]) if loaded else []


def delivery_element_for_class(
    ifc_class: str, typology: str, predefined_type: Optional[str] = None
) -> Optional[str]:
    """The typology's element name for an IFC class, or None if unmapped."""
    loaded = _load_typology(typology)
    if loaded is None or not ifc_class:
        return None
    return _lookup_class(loaded[1], ifc_class, predefined_type)


def delivery_mapped_classes(typology: str) -> list[str]:
    """Every IFC class the typology's elements map onto, qualifiers collapsed."""
    loaded = _load_typology(typology)
    return sorted({key.split("/")[0] for key in loaded[1]}) if loaded else []


def delivery_parameter_names(
    ifc_class: str,
    stage: Optional[str],
    typology: str,
    include_optional: bool = False,
    predefined_type: Optional[str] = None,
) -> list[str]:
    """Distinct delivery parameter names for a class at a stage, sorted.

    Optional-marked parameters ("O" in the workbook) are excluded unless
    asked for: optional means the standard permits omitting them, and quietly
    promoting them to required would over-ask.
    """
    loaded = _load_typology(typology)
    if loaded is None or not ifc_class:
        return []
    data, by_class, _warnings = loaded
    element = _lookup_class(by_class, ifc_class, predefined_type)
    if element is None:
        return []
    found = data["elements"].get(element, {}).get("parameters", [])
    names = set()
    for p in found:
        applies = stage is None or stage in p.get("stages", ())
        if not applies and include_optional:
            applies = stage in p.get("optional_stages", ())
        if applies:
            names.add(p["name"])
    return sorted(names)


def delivery_summary(typology: str) -> dict[str, int]:
    """Counts for one typology, mirroring summary()."""
    loaded = _load_typology(typology)
    if loaded is None:
        return {"elements": 0, "parameters": 0, "mapped": 0, "classes": 0}
    data, by_class, _warnings = loaded
    elements = data.get("elements", {})
    return {
        "elements": len(elements),
        "parameters": sum(len(e.get("parameters", [])) for e in elements.values()),
        "mapped": len({e for e in by_class.values()}),
        "classes": len(by_class),
    }


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
