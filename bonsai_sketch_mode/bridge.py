# Bonsai Sketch Mode - direct-modelling interaction for Bonsai
# Copyright (C) 2026 Innovations & Integrations
#
# This file is part of Bonsai Sketch Mode.
#
# Bonsai Sketch Mode is free software: you can redistribute it and/or modify
# it under the terms of the GNU General Public License as published by
# the Free Software Foundation, either version 3 of the License, or
# (at your option) any later version.
#
# Bonsai Sketch Mode is distributed in the hope that it will be useful,
# but WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
# GNU General Public License for more details.
#
# You should have received a copy of the GNU General Public License
# along with Bonsai Sketch Mode.  If not, see <http://www.gnu.org/licenses/>.

"""Single point of coupling to Bonsai.

Every import of ``bonsai.*`` in this add-on goes through this module. Bonsai
is a rolling release with no stable public API contract, so when a Bonsai
upgrade breaks us, this is the only file that should need attention.

Do not ``import bonsai`` anywhere else.
"""

from __future__ import annotations

from typing import Any, Optional

# Bonsai version this add-on has actually been tested against.
TESTED_BONSAI_VERSION = "0.8.4"

_unavailable_reason: Optional[str] = None
_version: Optional[str] = None

try:
    import bonsai.tool as _tool
    import bonsai.core.tool as _core_tool
except Exception as exc:  # pragma: no cover - depends on host install
    _tool = None
    _core_tool = None
    _unavailable_reason = f"Bonsai could not be imported: {exc}"


def _detect_version() -> Optional[str]:
    """Best-effort read of the installed Bonsai version.

    Bonsai does not expose a stable ``__version__``, so we read the extension
    manifest that shipped it. Returns None if the version cannot be determined,
    which is treated as a warning rather than a hard failure.
    """
    try:
        import tomllib
        from pathlib import Path

        import bonsai

        # bonsai/__init__.py -> site-packages/bonsai; the manifest lives in the
        # extension directory, not the wheel, so walk up to find it.
        for parent in Path(bonsai.__file__).resolve().parents:
            manifest = parent / "blender_manifest.toml"
            if manifest.is_file():
                with manifest.open("rb") as f:
                    return tomllib.load(f).get("version")
    except Exception:
        return None
    return None


if _tool is not None:
    _version = _detect_version()


def is_available() -> bool:
    """True if Bonsai is importable and usable."""
    return _tool is not None


def unavailable_reason() -> Optional[str]:
    return _unavailable_reason


def version() -> Optional[str]:
    """Installed Bonsai version, or None if it could not be determined."""
    return _version


def is_untested_version() -> bool:
    """True if Bonsai is present but not the version we were built against."""
    return _version is not None and _version != TESTED_BONSAI_VERSION


def require() -> Any:
    """Return Bonsai's tool namespace, raising if unavailable."""
    if _tool is None:
        raise RuntimeError(_unavailable_reason or "Bonsai is not available")
    return _tool


# --- Verified Bonsai surface -------------------------------------------------
# Tool idnames read from bonsai/bim/module/model/workspace.py (Bonsai 0.8.4).
# Keep this list in sync when bumping the tested version.

BIM_TOOL = "bim.bim_tool"
WALL_TOOL = "bim.wall_tool"
SLAB_TOOL = "bim.slab_tool"
COLUMN_TOOL = "bim.column_tool"
BEAM_TOOL = "bim.beam_tool"
DOOR_TOOL = "bim.door_tool"
WINDOW_TOOL = "bim.window_tool"
ROOF_TOOL = "bim.roof_tool"
RAILING_TOOL = "bim.railing_tool"
STAIR_FLIGHT_TOOL = "bim.stair_flight_tool"

# Operator idnames, read from the modules named in the comments (Bonsai 0.8.4).
MEASURE_OP = "bim.measure_tool"  # bim/module/project/operator.py
MEASURE_FACE_AREA_OP = "bim.measure_face_area_tool"  # bim/module/project/operator.py
CLEAR_MEASUREMENT_OP = "bim.clear_measurement"  # bim/module/project/operator.py
ASSIGN_CLASS_OP = "bim.assign_class"  # bim/module/root/operator.py
UPDATE_REPRESENTATION_OP = "bim.update_representation"  # bim/module/geometry/operator.py
DELETE_OP = "bim.override_object_delete"  # bim/module/geometry/operator.py


# --- Bonsai's polyline engine ------------------------------------------------
# Bonsai already implements the hard parts of a direct modeller: inference
# snapping, axis and plane locking, and a measurement box that parses metric
# and imperial input. Our drawing tools subclass its PolylineOperator rather
# than reimplement any of it.
#
# These are Bonsai internals, not a public API. That is exactly why they live
# here: an upgrade that moves them breaks this file and nothing else.

_polyline_reason: Optional[str] = None
_PolylineOperator: Any = None
_PolylineDecorator: Any = None

if _tool is not None:
    try:
        from bonsai.bim.module.model.polyline import PolylineOperator as _PolylineOperator
        from bonsai.bim.module.model.decorator import PolylineDecorator as _PolylineDecorator
    except Exception as exc:  # pragma: no cover - depends on host install
        _polyline_reason = f"Bonsai's polyline engine could not be imported: {exc}"
else:
    _polyline_reason = _unavailable_reason


class _InertPolylineOperator:
    """Stand-in base class used when Bonsai's polyline engine is missing.

    The drawing tools subclass PolylineOperator at import time, so they need
    something to inherit from even on a broken install. Operators built on this
    never poll true, so they are inert rather than half-working.
    """

    @classmethod
    def poll(cls, context: Any) -> bool:
        return False

    def __init__(self) -> None:
        pass


class _InertPolylineDecorator:
    """No-op stand-in for Bonsai's viewport overlay."""

    @classmethod
    def install(cls, context: Any) -> None:
        pass

    @classmethod
    def uninstall(cls) -> None:
        pass

    @classmethod
    def update(cls, *args: Any, **kwargs: Any) -> None:
        pass


PolylineOperator: Any = _PolylineOperator or _InertPolylineOperator
PolylineDecorator: Any = _PolylineDecorator or _InertPolylineDecorator


def polyline_engine_available() -> bool:
    """True if the drawing tools can run."""
    return _PolylineOperator is not None


def polyline_unavailable_reason() -> Optional[str]:
    return _polyline_reason


# --- Bonsai tool namespaces --------------------------------------------------
# Bound once at import so callers write ``bridge.Polyline.foo()`` rather than
# threading a namespace object around. None when Bonsai is absent; the
# operators that use them do not poll true in that case.


def _namespace(name: str) -> Any:
    return getattr(_tool, name, None) if _tool is not None else None


Blender: Any = _namespace("Blender")
Cad: Any = _namespace("Cad")
Ifc: Any = _namespace("Ifc")
Model: Any = _namespace("Model")
Polyline: Any = _namespace("Polyline")
Raycast: Any = _namespace("Raycast")
Root: Any = _namespace("Root")
Snap: Any = _namespace("Snap")


# --- Convenience wrappers ----------------------------------------------------


def has_project() -> bool:
    """True if an IFC project is currently open."""
    if _tool is None:
        return False
    try:
        return _tool.Ifc.get() is not None
    except Exception:
        return False


def get_entity(obj: Any) -> Any:
    """The IFC element an object represents, or None if it is plain geometry."""
    if _tool is None or obj is None:
        return None
    try:
        return _tool.Ifc.get_entity(obj)
    except Exception:
        return None


def default_selection_keymap() -> tuple:
    """Blender's stock click and box selection bindings, for our tool keymaps."""
    if _tool is None:
        return ()
    try:
        return tuple(_tool.Blender.get_default_selection_keypmap())
    except Exception:
        return ()


def parse_length(text: str) -> Optional[float]:
    """Parse typed length input, or None if it is not valid.

    Accepts everything Bonsai's measurement box does, including imperial
    (``5' 6"``), fractions and ``=``-prefixed expressions.
    """
    if _tool is None or not text:
        return None
    try:
        is_valid, value = _tool.Polyline.validate_input(text, "D")
        return float(value) if is_valid else None
    except Exception:
        return None


def format_length(value: float) -> str:
    """Format a length in the project's unit system."""
    if _tool is None:
        return f"{value:.3f}"
    try:
        return _tool.Polyline.format_input_ui_units(value)
    except Exception:
        return f"{value:.3f}"


def update_viewport() -> None:
    if _tool is None:
        return
    try:
        _tool.Blender.update_viewport()
    except Exception:
        pass
