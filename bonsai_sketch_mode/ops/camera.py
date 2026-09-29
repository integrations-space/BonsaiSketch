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

"""Perspective camera operators, on the arithmetic in ``camera.py``.

Two verbs. *Camera From View* plants a named camera where the viewport
stands -- levelled, at eye height, framing recovered by lens shift -- so
one click turns an orbited view into a presentation viewpoint. *Two-Point
Perspective* repairs an existing camera the same way, and refuses a
camera pitched past the point where levelling stops being a repair.

Both read and write plain object transforms, so a camera parented into
some rig keeps its parent but takes a world-aligned rotation; the rare
user who has rigged their presentation camera has opinions this operator
should not overrule anyway.

Headless Blender has no active viewport in the context, so *Camera From
View* falls back to the first 3D viewport it can find in the file's
screens -- which is also what lets the smoke suite and the textmodel
agents drive it without a window.
"""

from __future__ import annotations

import math

import bpy
from mathutils import Vector

from .. import camera as arithmetic

#: One camera per file, reused on every call, so repeated framing does not
#: litter the outliner with Camera.001 through Camera.041.
CAMERA_NAME = "Sketch Camera"


def _view_region():
    """An active 3D viewport's region data, or any viewport's, or None."""
    space = getattr(bpy.context, "space_data", None)
    region = getattr(space, "region_3d", None) if space is not None else None
    if region is not None:
        return region
    for screen in bpy.data.screens:
        for area in screen.areas:
            if area.type != "VIEW_3D":
                continue
            for space in area.spaces:
                if space.type == "VIEW_3D" and space.region_3d is not None:
                    return space.region_3d
    return None


def _sketch_camera(scene):
    """The named camera object, created and linked on first use."""
    obj = bpy.data.objects.get(CAMERA_NAME)
    if obj is not None and obj.type != "CAMERA":
        # Someone named a mesh after our camera; leave theirs alone.
        obj = None
    if obj is None:
        data = bpy.data.cameras.new(CAMERA_NAME)
        obj = bpy.data.objects.new(CAMERA_NAME, data)
    if obj.name not in scene.collection.all_objects:
        scene.collection.objects.link(obj)
    return obj


class BONSAI_SKETCH_MODE_OT_camera_from_view(bpy.types.Operator):
    bl_idname = "bonsai_sketch_mode.camera_from_view"
    bl_label = "Camera From View"
    bl_description = (
        "Place a level, eye-height camera where the viewport stands, keeping "
        "verticals vertical (two-point perspective)"
    )
    bl_options = {"REGISTER", "UNDO"}

    lens: bpy.props.FloatProperty(
        name="Lens (mm)", default=arithmetic.LENS, min=10.0, max=250.0,
        description="Focal length; around 32 mm holds a house without bowing it")
    eye_height: bpy.props.FloatProperty(
        name="Eye Height (m)", default=arithmetic.EYE_HEIGHT, min=0.0,
        description="Camera height above zero; 0 keeps the viewport's own height")

    def execute(self, context):
        region = _view_region()
        if region is None:
            self.report({"ERROR"}, "No 3D viewport to read a view from")
            return {"CANCELLED"}
        matrix = region.view_matrix.inverted()
        position = matrix.translation.copy()
        forward = (matrix.to_3x3() @ Vector((0.0, 0.0, -1.0))).normalized()
        yaw, shift, note = arithmetic.level(tuple(forward), self.lens)
        if yaw is None:
            self.report({"ERROR"}, note)
            return {"CANCELLED"}

        obj = _sketch_camera(context.scene)
        obj.data.type = "PERSP"
        obj.data.lens = self.lens
        obj.data.shift_x = 0.0
        obj.data.shift_y = shift
        obj.rotation_euler = (math.pi / 2.0, 0.0, yaw)
        if self.eye_height > 0.0:
            position.z = self.eye_height
        obj.location = position
        context.scene.camera = obj
        self.report({"INFO"}, note or "Camera placed level at eye height")
        return {"FINISHED"}


class BONSAI_SKETCH_MODE_OT_camera_two_point(bpy.types.Operator):
    bl_idname = "bonsai_sketch_mode.camera_two_point"
    bl_label = "Two-Point Perspective"
    bl_description = (
        "Level the scene's camera and recover its framing with lens shift, "
        "so every vertical edge draws vertical"
    )
    bl_options = {"REGISTER", "UNDO"}

    def execute(self, context):
        obj = context.scene.camera
        if obj is None or obj.type != "CAMERA":
            self.report({"ERROR"}, "The scene has no camera to level")
            return {"CANCELLED"}
        forward = (obj.matrix_world.to_3x3() @ Vector((0.0, 0.0, -1.0))).normalized()
        pitch, yaw = arithmetic.pitch_yaw(tuple(forward))
        if yaw is None:
            self.report({"ERROR"},
                        "The camera looks straight up or down; "
                        "there is no horizontal direction to keep")
            return {"CANCELLED"}
        if abs(pitch) > arithmetic.MAX_PITCH:
            self.report({"ERROR"},
                        f"The camera pitches {abs(math.degrees(pitch)):.0f} degrees, "
                        "past the two-point range -- frame the view nearer eye "
                        "level first, or use Camera From View")
            return {"CANCELLED"}
        data = obj.data
        data.type = "PERSP"
        # Additive: a camera already carrying shift keeps it and gains only
        # what the removed tilt was contributing.
        data.shift_y += arithmetic.two_point_shift(pitch, data.lens, data.sensor_width)
        obj.rotation_euler = (math.pi / 2.0, 0.0, yaw)
        self.report({"INFO"}, "Camera levelled; verticals are vertical")
        return {"FINISHED"}
