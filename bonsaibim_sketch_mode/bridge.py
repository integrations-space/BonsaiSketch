# BonsaiBIM Sketch Mode - direct-modelling interaction for Bonsai
# Copyright (C) 2026 TODO
#
# This file is part of BonsaiBIM Sketch Mode.
#
# BonsaiBIM Sketch Mode is free software: you can redistribute it and/or modify
# it under the terms of the GNU General Public License as published by
# the Free Software Foundation, either version 3 of the License, or
# (at your option) any later version.
#
# BonsaiBIM Sketch Mode is distributed in the hope that it will be useful,
# but WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
# GNU General Public License for more details.
#
# You should have received a copy of the GNU General Public License
# along with BonsaiBIM Sketch Mode.  If not, see <http://www.gnu.org/licenses/>.

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
