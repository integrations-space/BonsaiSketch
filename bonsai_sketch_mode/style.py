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

"""The sketch render style: flat colour, carved shadow, ink lines.

A presentation sketch is three decisions stacked: flat material colour
with no photographic lighting, a little cavity shading so junctions read
as carved rather than pasted, and a drawn ink line on every silhouette
and crease. The first two are Blender's Workbench engine configured
plainly; the third is a Line Art grease pencil tracing the scene. This
module turns all three on together and, like ``theme.py`` next door,
records exactly what it changed so switching off restores what was there
rather than what we guess the defaults were.

The style is applied to every 3D viewport and to the scene's own render
settings, so what F12 saves is what the viewport shows -- one look, two
outputs. The snapshot travels as JSON in a scene property, surviving a
save in the file it styled.

Line Art's Python surface has moved between Blender generations (legacy
grease pencil to v3), so the ink layer feature-detects its way in and
reports honestly when a host offers no route -- the flat-and-cavity look
still applies without it.
"""

from __future__ import annotations

import json

import bpy

from . import theme

#: What the sketch look sets on a viewport's (or the render's) Workbench
#: shading. FLAT studio light keeps facades unshaded paper; cavity carves
#: the junctions; the outline is the near-black the wire colour uses.
SHADING = (
    ("light", "FLAT"),
    ("color_type", "MATERIAL"),
    ("show_cavity", True),
    ("cavity_type", "WORLD"),
    ("cavity_valley_factor", 1.0),
    ("cavity_ridge_factor", 0.25),
    ("show_object_outline", True),
    ("object_outline_color", theme.WIRE),
    ("show_shadows", False),
    ("show_xray", False),
)

#: The grease pencil object that carries the traced ink lines.
INK_NAME = "Sketch Ink Lines"

#: Scene property holding the pre-style snapshot while the style is on.
SAVED = "bonsai_sketch_saved_style"

#: Line Art's modifier identifier, by Blender generation. Tried in order;
#: whichever the host accepts wins.
_LINEART_KINDS = ("GREASE_PENCIL_LINEART", "LINEART", "GP_LINEART")


def _spaces():
    """Every 3D viewport space in the file, keyed stably for the snapshot."""
    for screen in bpy.data.screens:
        for index, area in enumerate(screen.areas):
            if area.type != "VIEW_3D":
                continue
            for space in area.spaces:
                if space.type == "VIEW_3D":
                    yield f"{screen.name}::{index}", space


def _read(shading, attribute):
    value = getattr(shading, attribute)
    if isinstance(value, str) or isinstance(value, (bool, int, float)):
        return value
    return list(value)


def _configure(shading) -> dict:
    """Apply the sketch look to one shading block; return what was there."""
    before = {}
    for attribute, value in SHADING:
        if not hasattr(shading, attribute):
            continue
        before[attribute] = _read(shading, attribute)
        try:
            setattr(shading, attribute, value)
        except Exception:
            # A host that rejects one field keeps its own value; the
            # snapshot recorded it, so restore still round-trips.
            pass
    return before


def _restore_block(shading, stored: dict) -> None:
    for attribute, value in stored.items():
        try:
            setattr(shading, attribute, value)
        except Exception:
            pass


def apply(scene) -> tuple[bool, str]:
    """Turn the sketch style on. Idempotent; keeps the first snapshot.

    Returns (ok, message). The message carries the ink layer's fate,
    because the flat-and-cavity look can succeed while a host offers no
    Line Art route.
    """
    if scene.get(SAVED):
        return True, "Sketch style is already on"
    snapshot = {
        "engine": scene.render.engine,
        "display": {},
        "spaces": {},
    }
    for key, space in _spaces():
        snapshot["spaces"][key] = _configure(space.shading)
        space.shading.type = "SOLID"
    # The render output takes the same look, so F12 saves the viewport's
    # picture rather than a surprise photograph.
    snapshot["display"] = _configure(scene.display.shading)
    scene.render.engine = "BLENDER_WORKBENCH"
    inked, ink_note = ink_on(scene)
    snapshot["inked"] = inked
    scene[SAVED] = json.dumps(snapshot)
    note = "Sketch style on" if inked else f"Sketch style on; {ink_note}"
    return True, note


def restore(scene) -> tuple[bool, str]:
    """Put back what apply() recorded, and take the ink lines down."""
    saved = scene.get(SAVED)
    if not saved:
        return False, "Sketch style is not on"
    try:
        snapshot = json.loads(saved)
    except ValueError as exc:
        return False, f"Recorded style values are unreadable: {exc}"
    spaces = dict(_spaces())
    for key, stored in snapshot.get("spaces", {}).items():
        if key in spaces:
            _restore_block(spaces[key].shading, stored)
    _restore_block(scene.display.shading, snapshot.get("display", {}))
    scene.render.engine = snapshot.get("engine", scene.render.engine)
    ink_off(scene)
    del scene[SAVED]
    return True, "Previous shading restored"


def is_on(scene) -> bool:
    return bool(scene.get(SAVED))


def ink_on(scene) -> tuple[bool, str]:
    """Raise the Line Art layer over the scene. Returns (ok, note)."""
    if bpy.data.objects.get(INK_NAME) is not None:
        return True, "ink lines already up"
    data_pencils = (getattr(bpy.data, "grease_pencils_v3", None)
                    or getattr(bpy.data, "grease_pencils", None))
    if data_pencils is None:
        return False, "this Blender has no grease pencil data to draw ink with"
    pencil = data_pencils.new(INK_NAME)
    obj = bpy.data.objects.new(INK_NAME, pencil)
    scene.collection.objects.link(obj)

    layer_name = "Ink"
    try:
        pencil.layers.new(layer_name)
    except Exception:
        layer_name = ""

    modifier = None
    attempts = []
    for kind in _LINEART_KINDS:
        try:
            modifier = obj.modifiers.new("Line Art", kind)
        except Exception as exc:
            attempts.append(f"{kind}: {exc}")
            continue
        if modifier is not None:
            break
        attempts.append(f"{kind}: refused")
    if modifier is None:
        bpy.data.objects.remove(obj)
        try:
            data_pencils.remove(pencil)
        except Exception:
            pass
        return False, "no Line Art modifier: " + "; ".join(attempts)

    # An ink material, where the host lets one be made; Line Art draws
    # with the first material otherwise, which several hosts default.
    try:
        material = bpy.data.materials.new(INK_NAME)
        bpy.data.materials.create_gpencil_data(material)
        material.grease_pencil.color = (0.0, 0.0, 0.0, 1.0)
        obj.data.materials.append(material)
        if hasattr(modifier, "target_material"):
            modifier.target_material = material
    except Exception:
        pass

    for attribute, value in (
        ("source_type", "SCENE"),
        ("target_layer", layer_name),
        ("use_intersection", True),
        ("use_crease", True),
        ("thickness", 3),
    ):
        if layer_name == "" and attribute == "target_layer":
            continue
        if hasattr(modifier, attribute):
            try:
                setattr(modifier, attribute, value)
            except Exception:
                pass
    return True, "ink lines up"


def ink_off(scene) -> tuple[bool, str]:
    obj = bpy.data.objects.get(INK_NAME)
    if obj is None:
        return False, "no ink lines to take down"
    pencil = obj.data
    bpy.data.objects.remove(obj)
    try:
        collection = (getattr(bpy.data, "grease_pencils_v3", None)
                      or getattr(bpy.data, "grease_pencils", None))
        if collection is not None and pencil is not None:
            collection.remove(pencil)
    except Exception:
        pass
    material = bpy.data.materials.get(INK_NAME)
    if material is not None:
        try:
            bpy.data.materials.remove(material)
        except Exception:
            pass
    return True, "ink lines down"


class BONSAI_SKETCH_MODE_OT_sketch_style(bpy.types.Operator):
    bl_idname = "bonsai_sketch_mode.sketch_style"
    bl_label = "Sketch Render Style"
    bl_description = (
        "Flat colour, cavity shading and traced ink lines, in the viewport "
        "and in the render; run again with Off to put back what was there"
    )
    bl_options = {"REGISTER", "UNDO"}

    mode: bpy.props.EnumProperty(
        name="Mode",
        items=(("ON", "On", "Apply the sketch style"),
               ("OFF", "Off", "Restore the previous shading")),
        default="ON",
    )

    def execute(self, context):
        if self.mode == "ON":
            ok, message = apply(context.scene)
        else:
            ok, message = restore(context.scene)
        self.report({"INFO"} if ok else {"ERROR"}, message)
        return {"FINISHED"} if ok else {"CANCELLED"}


def register() -> None:
    bpy.utils.register_class(BONSAI_SKETCH_MODE_OT_sketch_style)


def unregister() -> None:
    try:
        bpy.utils.unregister_class(BONSAI_SKETCH_MODE_OT_sketch_style)
    except RuntimeError:
        pass
