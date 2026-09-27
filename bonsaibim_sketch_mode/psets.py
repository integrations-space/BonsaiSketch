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

"""Writing the standard's requirements onto elements as they are created.

``requirements.py`` answers what the Model Content Requirements ask of an
element; this module puts the questions onto the elements themselves. Each
covered element gets up to two property sets, one per dataset: the IFC+SG
regulatory requirements in :data:`PSET_NAME`, and -- when the user has said
which building typology the project is -- the typology's Project Delivery
requirements in :data:`DELIVERY_PSET_NAME`. Each holds one property per
required parameter, added with a null value. The standard prescribes the
questions, not the answers -- and a null property is a visible unanswered
question, in Bonsai's property panels and in the exported IFC, where an
absent one is invisible.

The two sets stay separate because the submissions are separate: IFC+SG is
what CORENET-X checks, Project Delivery is what a DBC handover asks, and a
reviewer of either should not have to know the other's vocabulary to read a
property panel.

Two invariants make this safe to run at any moment:

* Only missing names are ever written. A property the user has filled in --
  or deliberately blanked -- is never touched again, so attaching is
  idempotent and sweeping the whole file is always harmless.
* An element whose class the standard does not cover gets nothing, including
  the property set container itself.

Attachment is automatic because creation is centralised: every element Bonsai
makes -- its wall tool, Assign IFC Class on a finished sketch, all of it --
passes through ``ifcopenshell.api.root.create_entity``, so one post listener
on that call covers every way an element comes into being. The listener is
handed the call's settings rather than the created entity, so it re-checks
every element of the created class; idempotence is what makes that correct
rather than merely convenient. Running synchronously inside the listener also
keeps the attachment inside the same undo transaction as the creation it
belongs to.

Which stage to attach at, which typology the project is, whether optional
delivery parameters count, and whether to attach at all -- all of that is the
caller's state, not this module's: :func:`install` takes a provider callable
returning :class:`AttachSettings` and asks it at each creation.

ifcopenshell is imported here directly rather than through ``bridge.py``.
bridge.py exists to quarantine the coupling to Bonsai's unstable internals;
ifcopenshell is the opposite case, a library with a documented and stable API
contract, and nothing in this module touches Bonsai at all.
"""

from __future__ import annotations

from typing import Any, Callable, NamedTuple, Optional

from . import requirements

#: The property set the IFC+SG parameters are written into. The standard
#: names the parameters but no set to put them in -- its workbook is
#: organised by element, not by pset -- so they are gathered under one
#: clearly-owned name rather than scattered across guesses at Pset_*
#: conventions.
PSET_NAME = "IFCSG_Parameters"

#: The property set the per-typology Project Delivery parameters go into.
DELIVERY_PSET_NAME = "MCR_ProjectDelivery"


class AttachSettings(NamedTuple):
    """What to attach, as answered by the caller's provider at each creation.

    ``typology`` None means the user has not said what the project is, so no
    delivery parameters attach -- guessing a typology would attach a wrong
    set somewhere. ``include_optional`` covers the delivery dataset's "O"
    marks; the IFC+SG dataset has no optional parameters.
    """

    stage: str
    typology: Optional[str] = None
    include_optional: bool = False

#: Listener registration name, namespaced so nothing else removes it.
LISTENER = "bonsaibim_sketch_mode.psets"

_import_error: Optional[str] = None

try:
    import ifcopenshell
    import ifcopenshell.api
    import ifcopenshell.api.pset
    import ifcopenshell.util.element
except Exception as exc:  # pragma: no cover - depends on host install
    ifcopenshell = None
    _import_error = f"ifcopenshell could not be imported: {exc}"

_settings_provider: Optional[Callable[[], Optional[AttachSettings]]] = None
_installed = False
_attaching = False

#: Which elements have already been examined, per AttachSettings, for the file
#: in :data:`_checked_file`. The listener cannot see the entity a creation made
#: -- ifcopenshell hands a post listener the call's settings, not its result --
#: so it re-examines the created class, and without this that is a full scan of
#: every instance of the class on every single creation. Measured on a plain
#: IfcWall loop: 11 ms for the first hundred walls, 81 ms each by the fourth
#: hundred, still climbing. Remembering what has been examined makes the
#: listener's cost flat instead.
#:
#: Recording only ever *skips work already done*, so it cannot change an
#: outcome: ensure() is idempotent and adds solely missing names. Keying on the
#: settings means a stage change, a typology being chosen, or optional
#: parameters being switched on all start their own tally and sweep afresh.
_checked_file: Any = None
_checked: dict[AttachSettings, set[int]] = {}


def is_available() -> bool:
    """True if parameters can be attached at all."""
    return ifcopenshell is not None and requirements.load_error() is None


def unavailable_reason() -> Optional[str]:
    return _import_error or requirements.load_error()


def _required_names(element: Any, settings: AttachSettings) -> dict[str, list[str]]:
    """pset name -> required parameter names, for each dataset that applies."""
    ifc_class = element.is_a()
    try:
        # Distinguishes a roof slab from a floor slab, a finish from a
        # ceiling: qualified class mappings key off this.
        predefined = ifcopenshell.util.element.get_predefined_type(element)
    except Exception:
        predefined = None
    required = {
        PSET_NAME: requirements.parameter_names(ifc_class, settings.stage, predefined)
    }
    if settings.typology:
        required[DELIVERY_PSET_NAME] = requirements.delivery_parameter_names(
            ifc_class,
            settings.stage,
            settings.typology,
            settings.include_optional,
            predefined,
        )
    return required


def missing_names(element: Any, settings: AttachSettings) -> dict[str, list[str]]:
    """pset name -> required names neither the element nor its type answers.

    Presence is judged against the element's *own* set, matching where
    :func:`ensure` writes. Counting an inherited placeholder as present would
    leave an occurrence permanently short of its own copy: a door typed to a
    library type that already holds the whole set gets nothing at creation,
    and no later sweep tops it up, because every name looks accounted for.
    The standard asks its questions of the element.

    With one exception: a name the type has *answered* -- filled, not just
    listed -- is never re-asked on the occurrence. A null written beside a
    filled answer hides it from the merged views: ``get_psets`` and the dict
    form of ``get_pset`` let an occurrence's null shadow the type's value,
    and only the single-property accessor falls back through it. An answered
    question needs no placeholder; an unanswered one gets the occurrence's
    own. The check suite pins the shadowing rather than trusting either
    accessor to keep behaving.
    """
    element_type = None
    try:
        element_type = ifcopenshell.util.element.get_type(element)
    except Exception:
        element_type = None
    missing = {}
    for pset_name, required in _required_names(element, settings).items():
        if not required:
            continue
        own = (
            ifcopenshell.util.element.get_pset(element, pset_name, should_inherit=False) or {}
        )
        names = [name for name in required if name not in own]
        if names and element_type is not None:
            answered = {
                key
                for key, value in (
                    ifcopenshell.util.element.get_pset(element_type, pset_name) or {}
                ).items()
                if value is not None
            }
            names = [name for name in names if name not in answered]
        if names:
            missing[pset_name] = names
    return missing


def _own_pset(ifc_file: Any, element: Any, pset_name: str) -> Optional[Any]:
    """The element's own set of that name, ignoring anything inherited from
    its type.

    The distinction matters: get_pset follows type inheritance by default,
    and editing an inherited set from an occurrence would write onto the type
    -- and through it, onto every other occurrence.
    """
    info = ifcopenshell.util.element.get_pset(element, pset_name, should_inherit=False)
    return ifc_file.by_id(info["id"]) if info else None


def ensure(ifc_file: Any, element: Any, settings: AttachSettings) -> int:
    """Attach whatever parameters the element is missing. Returns how many.

    Never overwrites: a name already present keeps its value, filled or not.
    """
    added = 0
    for pset_name, names in missing_names(element, settings).items():
        pset = _own_pset(ifc_file, element, pset_name) or ifcopenshell.api.pset.add_pset(
            ifc_file, product=element, name=pset_name
        )
        # should_purge=False is what keeps a null-valued property: edit_pset's
        # default treats None as "delete this", and these Nones mean
        # "required, not yet answered".
        ifcopenshell.api.pset.edit_pset(
            ifc_file, pset=pset, properties={name: None for name in names}, should_purge=False
        )
        added += len(names)
    return added


def forget() -> None:
    """Drop the record of what has been examined.

    Called when a file is swept by hand, and when attachment is installed or
    removed. Forgetting only ever costs time, never correctness.
    """
    global _checked_file, _checked
    _checked_file = None
    _checked = {}


def _examined(ifc_file: Any, settings: AttachSettings) -> set[int]:
    """The set of element ids already examined under these settings."""
    global _checked_file, _checked
    if ifc_file is not _checked_file:
        # A different file: nothing carries over, and ids certainly do not.
        _checked_file = ifc_file
        _checked = {}
    return _checked.setdefault(settings, set())


def sweep(
    ifc_file: Any,
    settings: AttachSettings,
    only_class: Optional[str] = None,
    remember: bool = False,
) -> tuple[int, int]:
    """Attach missing parameters across a file. Returns (elements, parameters).

    With ``only_class``, only elements of that class are visited -- what the
    creation listener does, since it knows what was just created. Without it,
    every class either dataset maps is visited: that is the "apply to
    existing elements" path, for elements that predate the add-on, a stage
    change, or the typology being set.

    ``remember`` skips elements already examined under the same settings, and
    records the ones it examines. That is for the listener, which is called
    once per creation and would otherwise rescan the whole class each time.
    The by-hand sweep leaves it False and looks at everything: it is the
    escape hatch a user reaches for precisely when something has been changed
    behind this module's back, so it must never trust a previous verdict.
    """
    if only_class:
        classes = [only_class]
    else:
        classes = set(requirements.mapped_classes())
        if settings.typology:
            classes |= set(requirements.delivery_mapped_classes(settings.typology))
        classes = sorted(classes)
    examined = _examined(ifc_file, settings) if remember else None
    touched = added = 0
    for ifc_class in classes:
        try:
            entities = ifc_file.by_type(ifc_class)
        except Exception:
            continue  # not a class in this file's schema
        for entity in entities:
            if examined is not None:
                if entity.id() in examined:
                    continue
                examined.add(entity.id())
            count = ensure(ifc_file, entity, settings)
            if count:
                touched += 1
                added += count
    return touched, added


def _on_entity_created(usecase_path: str, ifc_file: Any, call_settings: dict) -> None:
    """Post listener on root.create_entity: give the new element its parameters."""
    global _attaching
    if _attaching or ifc_file is None:
        return
    settings = _settings_provider() if _settings_provider else None
    if settings is None:
        return  # attachment is turned off, or there is nowhere to read from
    # call_settings are the creation call's keyword arguments. A class neither
    # dataset covers is the overwhelmingly common case -- types, contexts, the
    # project itself -- so that exits before touching the file. A caller
    # passing ifc_class positionally leaves it unknown here; the sweep then
    # covers every mapped class, which idempotence makes merely slower -- and
    # only once, since what it examines is remembered.
    ifc_class = call_settings.get("ifc_class")
    if ifc_class is not None:
        covered = requirements.element_for_class(ifc_class) is not None or (
            settings.typology is not None
            and requirements.delivery_element_for_class(ifc_class, settings.typology) is not None
        )
        if not covered:
            return
    _attaching = True
    try:
        sweep(ifc_file, settings, only_class=ifc_class, remember=True)
    except Exception as exc:
        # A failure here must never break the creation it rode in on.
        print(f"[bonsaibim_sketch_mode] MCR parameter attachment failed: {exc}")
    finally:
        _attaching = False


def install(settings_provider: Callable[[], Optional[AttachSettings]]) -> tuple[bool, str]:
    """Attach parameters to every element created from now on. (ok, message).

    ``settings_provider`` is called at each creation and returns what to
    attach -- stage, typology, whether optional parameters count -- or None
    to attach nothing. All of that lives with the caller, because all of it
    is the user's state, not this module's.
    """
    global _settings_provider, _installed
    if ifcopenshell is None:
        return False, _import_error or "ifcopenshell is unavailable"
    error = requirements.load_error()
    if error:
        return False, error
    _settings_provider = settings_provider
    forget()  # a fresh install knows nothing about any file
    if not _installed:
        ifcopenshell.api.add_post_listener("root.create_entity", LISTENER, _on_entity_created)
        _installed = True
    counts = requirements.summary()
    return True, (
        f"Attaching on creation: up to {counts['parameters']} IFC+SG parameters "
        f"across {counts['mapped']} mapped elements, plus Project Delivery "
        f"parameters once a typology is chosen"
    )


def remove() -> None:
    """Stop attaching. Safe to call however far install() got."""
    global _settings_provider, _installed
    if _installed and ifcopenshell is not None:
        try:
            ifcopenshell.api.remove_post_listener(
                "root.create_entity", LISTENER, _on_entity_created
            )
        except Exception:
            pass
        _installed = False
    _settings_provider = None
    forget()
