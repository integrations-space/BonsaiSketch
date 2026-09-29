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

"""Answering the requirements' geometric questions from the geometry itself.

``psets.py`` puts the Model Content Requirements onto elements as null-valued
properties -- visible unanswered questions. Most of those questions only a
person can answer: a fire rating, a manufacturer, an acquisition code. But
some of them the shape itself already answers. A wall that stands 3 metres
tall does not need anyone to type "3" into Height; the model said it first.

The governing rule, stated in AUTOMODEL.md and enforced here: **a machine
fills a value only when the geometry states it.** That splits three ways.

* **What a name means depends on what is named.** A slab's ``Area`` is its
  footprint; a wall's ``Area`` is its elevation -- same word, different
  measurements, and the standard does not say which it means where. So the
  reading is chosen per IFC class, in :data:`PROFILES`, and a class gets a
  measurement only where the reading is the plain, uncontested one. A door's
  ``OverallWidth`` is its *larger* horizontal extent (a door is a thin
  panel); a wall's ``Width`` is its *smaller* (a wall is a long prism). A
  column's ``b`` and ``h`` depend on which way the section is facing, which
  the bounding box cannot testify to -- so a column gives up its plan
  dimensions and keeps only ``Height`` and ``Volume``, whose meanings no
  orientation can change.
* **A shell that is not closed has no volume to report.** Volume comes from
  the mesh itself and only when every edge has exactly two faces; a footprint
  area is reported only when the solid actually is a prism over it, checked
  by the volume it would then have to enclose. A number that might be right
  is not a number this module writes.
* **Only a null is ever written to.** A value a person has entered -- or
  this module has already derived -- is never touched, so deriving is
  idempotent for the same reason attaching is: re-running costs time, never
  answers.

Everything left unfilled is reported by name. The unanswered questions are
the deliverable as much as the answered ones: they are exactly the list an
agent, or a person, still owes the model.

Values are written in the project's own length unit -- the measures are taken
in metres (Blender's, and this add-on's, working unit) and converted through
the file's unit assignment, squared and cubed for areas and volumes.

Pure Python except :func:`measure_object`, which is the one function that
reads a Blender object and imports bpy's types only when called -- so the
table, the profile logic and the IFC writing all run and are tested anywhere
ifcopenshell does.
"""

from __future__ import annotations

from typing import Any, Callable, Optional

from .psets import DELIVERY_PSET_NAME, PSET_NAME

_import_error: Optional[str] = None

try:
    import ifcopenshell
    import ifcopenshell.api.pset
    import ifcopenshell.util.unit
except Exception as exc:  # pragma: no cover - depends on host install
    ifcopenshell = None
    _import_error = f"ifcopenshell could not be imported: {exc}"

#: Below this, an extent is degenerate -- an unextruded outline has no height
#: worth asserting, and writing 0.0 would answer a question falsely.
EPSILON = 1e-6

#: How far the enclosed volume may differ from footprint x height before the
#: solid is not a prism and its footprint is nobody's ``Area``. One percent
#: passes mesh-precision noise and fails any actual taper, pitch or bulge.
PRISM_TOLERANCE = 0.01


def _normalise(name: str) -> str:
    """The spelling-independent key: the workbook writes ``Overall Height``,
    ``OverallHeight`` and ``Overall Width`` across sheets for the same ask."""
    return "".join(ch for ch in name if ch.isalnum()).upper()


# --- What the bounding box and shell can testify to --------------------------
#
# Each rule takes the world-axis extents in metres, the closed-shell volume
# (None when the shell is open) and the bottom-face area (None when there is
# no bottom face), and returns a measurement or None. Rules never guess: a
# rule that cannot be sure returns None and the property stays a null.


def _vertical(dx: float, dy: float, dz: float, volume, base_area) -> Optional[float]:
    return dz if dz > EPSILON else None


def _long_horizontal(dx: float, dy: float, dz: float, volume, base_area) -> Optional[float]:
    value = max(dx, dy)
    return value if value > EPSILON else None


def _short_horizontal(dx: float, dy: float, dz: float, volume, base_area) -> Optional[float]:
    value = min(dx, dy)
    return value if value > EPSILON else None


def _thinnest(dx: float, dy: float, dz: float, volume, base_area) -> Optional[float]:
    value = min(dx, dy, dz)
    return value if value > EPSILON else None


def _shell_volume(dx: float, dy: float, dz: float, volume, base_area) -> Optional[float]:
    return volume if volume is not None and volume > EPSILON**3 else None


def _footprint(dx: float, dy: float, dz: float, volume, base_area) -> Optional[float]:
    """The bottom face's area -- but only when the solid is a prism over it.

    The check is the volume: a prism over this footprint at this height
    encloses exactly ``base_area * dz``, so a solid that encloses anything
    else (a pitched roof, a tapering plinth) is not one, and its bottom face
    is not what anyone means by its Area.
    """
    if volume is None or base_area is None or base_area <= EPSILON or dz <= EPSILON:
        return None
    if abs(volume - base_area * dz) > PRISM_TOLERANCE * volume:
        return None
    return base_area


_Rule = Callable[[float, float, float, Optional[float], Optional[float]], Optional[float]]

#: What the standard's parameter names measure per class, keyed by the
#: normalised spelling. Everything a profile does not name is left null --
#: which is the point, not a gap. The prism reading: a wall or slab stood up
#: from a plan, whose length runs long, width runs short and thickness is its
#: thinnest direction.
_PRISM: dict[str, _Rule] = {
    "HEIGHT": _vertical,
    "LENGTH": _long_horizontal,
    "WIDTH": _short_horizontal,
    "THICKNESS": _thinnest,
    "VOLUME": _shell_volume,
}

#: A horizontal plate additionally owns a footprint ``Area``. A wall does
#: not join this: its ``Area`` reads as elevation, which is a different
#: number, so a wall's Area stays a question.
_PLATE: dict[str, _Rule] = dict(_PRISM, AREA=_footprint)

#: A door or window is a thin panel: its overall width is its *larger*
#: horizontal extent, the opposite reading from a prism's width. No volume --
#: the datasets never ask a panel for one, and a leaf-plus-frame shell would
#: not measure the leaf anyway.
_PANEL: dict[str, _Rule] = {
    "HEIGHT": _vertical,
    "OVERALLHEIGHT": _vertical,
    "OVERALLLEAFHEIGHT": _vertical,
    "WIDTH": _long_horizontal,
    "OVERALLWIDTH": _long_horizontal,
    "THICKNESS": _thinnest,
}

#: Free-standing fittings -- furniture, sanitary ware, equipment -- read like
#: a crate: length long, width short, in either spelling the sheets use.
_FITTING: dict[str, _Rule] = {
    "HEIGHT": _vertical,
    "OVERALLHEIGHT": _vertical,
    "LENGTH": _long_horizontal,
    "OVERALLLENGTH": _long_horizontal,
    "WIDTH": _short_horizontal,
    "OVERALLWIDTH": _short_horizontal,
}

PROFILES: dict[str, dict[str, _Rule]] = {
    "IfcWall": _PRISM,
    "IfcSlab": _PLATE,
    "IfcCovering": _PLATE,
    "IfcFooting": dict(_PRISM, BREADTH=_short_horizontal),
    # A space's geometry is its inner boundary, so its horizontal extents
    # *are* the internal dimensions the standard asks for by that name.
    "IfcSpace": {
        "HEIGHT": _vertical,
        "AREA": _footprint,
        "VOLUME": _shell_volume,
        "INTERNALLENGTH": _long_horizontal,
        "INTERNALWIDTH": _short_horizontal,
    },
    # A column's b and h depend on which way the section faces; a beam's
    # depth and width on which way it spans. The box cannot testify to
    # either, so they keep only what no orientation can change.
    "IfcColumn": {"HEIGHT": _vertical, "VOLUME": _shell_volume},
    "IfcBeam": {"LENGTH": _long_horizontal, "VOLUME": _shell_volume},
    "IfcDoor": _PANEL,
    "IfcWindow": _PANEL,
    "IfcRailing": {"HEIGHT": _vertical, "LENGTH": _long_horizontal, "VOLUME": _shell_volume},
    "IfcFurniture": _FITTING,
    "IfcSanitaryTerminal": _FITTING,
    "IfcFurnishingElement": _FITTING,
}

#: Height is vertical extent and volume is enclosed volume whatever the
#: element is; nothing else survives an unknown class. A pile's ``Length``
#: runs *down*, which is exactly the kind of reading this default refuses.
DEFAULT_PROFILE: dict[str, _Rule] = {"HEIGHT": _vertical, "VOLUME": _shell_volume}

#: How each measurement converts into project units. Lengths scale linearly,
#: areas by the square, volumes by the cube.
_POWER = {"AREA": 2, "VOLUME": 3}


def profile(ifc_class: str) -> dict[str, _Rule]:
    """The readings this class is entitled to.

    Subclasses inherit their parent's profile by name prefix --
    IfcWallStandardCase reads as IfcWall -- with the longest matching entry
    winning, so a more specific profile can be added without disturbing the
    general one.
    """
    exact = PROFILES.get(ifc_class)
    if exact is not None:
        return exact
    best = ""
    for key in PROFILES:
        if ifc_class.startswith(key) and len(key) > len(best):
            best = key
    return PROFILES[best] if best else DEFAULT_PROFILE


def measures(
    ifc_class: str,
    extents: tuple,
    volume: Optional[float] = None,
    base_area: Optional[float] = None,
) -> dict[str, float]:
    """Every measurement this class's shape states, in metres, by normalised
    parameter name. What is absent could not be said honestly."""
    dx, dy, dz = (float(v) for v in extents)
    stated = {}
    for name, rule in profile(ifc_class).items():
        value = rule(dx, dy, dz, volume, base_area)
        if value is not None:
            stated[name] = value
    return stated


def _own_psets(element: Any):
    """The element's own requirement sets -- never the type's, for the same
    reason psets.py edits only the occurrence's copy: writing through an
    inherited set would answer the question for every sibling at once."""
    for rel in getattr(element, "IsDefinedBy", None) or ():
        if not rel.is_a("IfcRelDefinesByProperties"):
            continue
        definition = rel.RelatingPropertyDefinition
        if definition is not None and definition.is_a("IfcPropertySet"):
            if definition.Name in (PSET_NAME, DELIVERY_PSET_NAME):
                yield definition


def _unit_scale(ifc_file: Any) -> float:
    """Metres per project length unit; 1.0 when the file declares no units,
    which is also what a bare in-memory test file gets."""
    try:
        return float(ifcopenshell.util.unit.calculate_unit_scale(ifc_file)) or 1.0
    except Exception:
        return 1.0


def fill(
    ifc_file: Any,
    element: Any,
    extents: tuple,
    volume: Optional[float] = None,
    base_area: Optional[float] = None,
) -> dict:
    """Answer what the shape states; report what it could not.

    Returns ``{"filled": {pset: {name: value}}, "left": {pset: [names]},
    "filled_count", "left_count", "measures"}`` -- values in project units,
    measures in metres. Only null-valued properties in the element's own
    requirement sets are candidates; everything already answered, by whoever,
    is out of bounds.
    """
    if ifcopenshell is None:
        raise RuntimeError(_import_error or "ifcopenshell is unavailable")
    stated = measures(element.is_a(), extents, volume, base_area)
    scale = _unit_scale(ifc_file)
    filled: dict[str, dict] = {}
    left: dict[str, list] = {}
    for pset in _own_psets(element):
        answers = {}
        for prop in pset.HasProperties or ():
            if not prop.is_a("IfcPropertySingleValue") or prop.NominalValue is not None:
                continue
            key = _normalise(prop.Name)
            if key in stated:
                # Divide, not multiply: the scale is metres per project unit,
                # and the measurement is in metres. Rounded so a millimetre
                # project reads 3000.0, not 2999.9999999999995.
                answers[prop.Name] = round(stated[key] / scale ** _POWER.get(key, 1), 6)
            else:
                left.setdefault(pset.Name, []).append(prop.Name)
        if answers:
            # should_purge=False for the same reason psets.py passes it: the
            # sets around these answers still hold deliberate nulls, and
            # edit_pset's default would read them as deletions. It gets a
            # copy because it empties the dict it is given as it writes,
            # which would leave the report claiming nothing was filled.
            ifcopenshell.api.pset.edit_pset(
                ifc_file, pset=pset, properties=dict(answers), should_purge=False
            )
            filled[pset.Name] = answers
    return {
        "filled": filled,
        "left": left,
        "filled_count": sum(len(v) for v in filled.values()),
        "left_count": sum(len(v) for v in left.values()),
        "measures": {k: round(v, 6) for k, v in sorted(stated.items())},
    }


def measure_object(obj: Any) -> tuple:
    """(extents, volume, base_area) of a Blender object, in world metres.

    The one bpy-touching function here, importing bmesh only when called.
    Volume is reported only for a closed shell -- every edge exactly two
    faces -- because a partial sum over an open sheet is a number, just not
    the volume of anything. The base area is the summed area of faces lying
    wholly at the lowest Z, which for a stood-up outline is its footprint;
    :func:`_footprint` decides whether it deserves the name.
    """
    import bmesh

    mesh = bmesh.new()
    try:
        mesh.from_mesh(obj.data)
        mesh.transform(obj.matrix_world)
        if not mesh.verts:
            return ((0.0, 0.0, 0.0), None, None)
        xs = [v.co.x for v in mesh.verts]
        ys = [v.co.y for v in mesh.verts]
        zs = [v.co.z for v in mesh.verts]
        extents = (max(xs) - min(xs), max(ys) - min(ys), max(zs) - min(zs))
        closed = bool(mesh.faces) and all(len(e.link_faces) == 2 for e in mesh.edges)
        # abs(): a shell whose normals point inward encloses the same space.
        volume = abs(mesh.calc_volume(signed=True)) if closed else None
        floor = min(zs) + 1e-5
        base_area = sum(
            f.calc_area() for f in mesh.faces if all(v.co.z <= floor for v in f.verts)
        )
        return (extents, volume, base_area if base_area > EPSILON else None)
    finally:
        mesh.free()
