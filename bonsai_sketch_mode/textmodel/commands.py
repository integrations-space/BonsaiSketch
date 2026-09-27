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

"""The vocabulary. Every verb here runs on Blender's main thread.

Two kinds of verb, and the difference is the whole design:

- **Parametric.** ``add_walls`` builds real walls through Bonsai's own
  generator -- material layers, thickness, joins. A wall made this way stays a
  wall: change its type and it regenerates.
- **Sketch, then name.** ``sketch_polyline`` and ``push_pull`` drive this
  add-on's own tools, and ``assign_class`` gives the result an IFC identity.
  That is the SketchUp order of work, and it is what to reach for when the
  shape is not something Bonsai has a parametric generator for.

Nothing here invents geometry of its own. Every verb is a thin, checked shell
over something a user could have done by hand, which is what keeps a typed
instruction and a drawn one producing the same model.

The verbs are deliberately few. A wide API would be a worse target for an agent
than a narrow one: fewer ways to express a thing means fewer ways to express it
wrongly, and every verb here has a test behind it.
"""

from __future__ import annotations

import os
from typing import Any, Callable, Optional

import bmesh
import bpy
from mathutils import Vector

from .. import bridge, sketchmesh
from ..ops import pushpull

#: name -> handler. Populated by the @verb decorator below.
_VERBS: dict[str, Callable[[dict], Any]] = {}


class CommandError(Exception):
    """A request that was understood and refused. Reported without a traceback."""


def verb(name: str) -> Callable:
    def register(function: Callable[[dict], Any]) -> Callable[[dict], Any]:
        _VERBS[name] = function
        return function

    return register


def run(command: str, params: dict) -> Any:
    handler = _VERBS.get(command)
    if handler is None:
        raise CommandError(
            "unknown command %r. Known: %s" % (command, ", ".join(sorted(_VERBS)))
        )
    return handler(params)


def names() -> list:
    return sorted(_VERBS)


@verb("ifc_sg_requirements")
def _sg_requirements(params: dict) -> dict:
    from .. import requirements, sg
    selected_stage = params.get("stage", sg.stage())
    return requirements.check_element(params.get("ifc_class", ""), selected_stage, {},
                                      params.get("predefined_type", ""))


@verb("check_ifc_sg")
def _check_sg(params: dict) -> dict:
    from .. import sg
    return sg.inspect(_object(params), params.get("stage"))


# --- Reading parameters ------------------------------------------------------
#
# An agent gets these wrong in predictable ways -- a number as a string, a
# 2D point where a 3D one is wanted, a missing key. Each is a clear refusal
# rather than a TypeError from four frames down.


def _points(params: dict, key: str = "points") -> list:
    raw = params.get(key)
    if not isinstance(raw, (list, tuple)) or len(raw) < 2:
        raise CommandError("%r must be a list of at least two points" % key)
    points = []
    for index, point in enumerate(raw):
        if not isinstance(point, (list, tuple)) or not 2 <= len(point) <= 3:
            raise CommandError("point %d must be [x, y] or [x, y, z]" % index)
        try:
            values = [float(v) for v in point]
        except (TypeError, ValueError):
            raise CommandError("point %d has a non-numeric coordinate" % index)
        # 2D is accepted and means "on the ground", which is how a plan is
        # described in words and saves an agent repeating a zero.
        points.append(Vector((values[0], values[1], values[2] if len(values) == 3 else 0.0)))
    return points


def _number(params: dict, key: str, default: Optional[float] = None) -> float:
    if key not in params:
        if default is None:
            raise CommandError("%r is required" % key)
        return default
    try:
        return float(params[key])
    except (TypeError, ValueError):
        raise CommandError("%r must be a number" % key)


def _object(params: dict, key: str = "object") -> bpy.types.Object:
    name = params.get(key)
    if not isinstance(name, str):
        raise CommandError("%r must be an object name" % key)
    obj = bpy.data.objects.get(name)
    if obj is None:
        raise CommandError("no object named %r" % name)
    return obj


def _require_project() -> Any:
    if not bridge.has_project():
        raise CommandError("no IFC project is open -- call create_project first")
    return bridge.Ifc.get()


def _describe(obj: bpy.types.Object) -> dict:
    entity = bridge.get_entity(obj)
    return {
        "object": obj.name,
        "ifc_class": entity.is_a() if entity else None,
        "location": [round(v, 6) for v in obj.location],
        "dimensions": [round(v, 6) for v in obj.dimensions],
    }


# --- Looking -----------------------------------------------------------------


@verb("ping")
def _ping(params: dict) -> dict:
    """Is anyone there, and what are they running."""
    return {
        "blender": bpy.app.version_string,
        "bonsai": bridge.version(),
        "bonsai_tested": bridge.TESTED_BONSAI_VERSION,
        "project_open": bridge.has_project(),
        "commands": names(),
    }


@verb("describe")
def _describe_model(params: dict) -> dict:
    """What is in the model, in one reply an agent can plan against."""
    if not bridge.has_project():
        return {"project": None, "sketch_objects": _sketch_objects()}

    ifc = bridge.Ifc.get()
    counts: dict[str, int] = {}
    for element in ifc.by_type("IfcElement"):
        counts[element.is_a()] = counts.get(element.is_a(), 0) + 1

    types = {}
    for element_type in ifc.by_type("IfcElementType"):
        types.setdefault(element_type.is_a(), []).append(
            {"id": element_type.id(), "name": element_type.Name}
        )

    return {
        "project": bridge.project_name(),
        "schema": ifc.schema,
        "elements": counts,
        "types": types,
        "sketch_objects": _sketch_objects(),
    }


def _sketch_objects() -> list:
    return [o.name for o in bpy.data.objects if sketchmesh.is_sketch_object(o)]


@verb("list_elements")
def _list_elements(params: dict) -> list:
    ifc = _require_project()
    ifc_class = params.get("ifc_class") or "IfcElement"
    if not isinstance(ifc_class, str):
        raise CommandError("'ifc_class' must be a string")
    try:
        elements = ifc.by_type(ifc_class)
    except Exception as exc:
        raise CommandError("%s is not a class in this schema: %s" % (ifc_class, exc))

    limit = int(_number(params, "limit", 200.0))
    out = []
    for element in elements[:limit]:
        obj = bridge.Ifc.get_object(element)
        entry = {"id": element.id(), "ifc_class": element.is_a(), "name": element.Name}
        if obj is not None:
            entry["object"] = obj.name
            entry["location"] = [round(v, 6) for v in obj.location]
        out.append(entry)
    return out


# --- Making it possible to build ---------------------------------------------


@verb("create_project")
def _create_project(params: dict) -> dict:
    """The gate everything else is behind."""
    if bridge.has_project():
        return {"created": False, "project": bridge.project_name()}
    bpy.ops.bim.create_project()
    if not bridge.has_project():
        raise CommandError("Bonsai reported no project after create_project")
    return {"created": True, "project": bridge.project_name()}


@verb("create_type")
def _create_type(params: dict) -> dict:
    """A construction type, which occurrences are made from.

    A fresh project has none, and Bonsai cannot place a wall without one, so
    this is the step between "new project" and "add walls".
    """
    ifc = _require_project()
    ifc_class = params.get("ifc_class")
    if not isinstance(ifc_class, str) or not ifc_class.endswith("Type"):
        raise CommandError("'ifc_class' must be a type class, such as IfcWallType")

    before = len(ifc.by_type(ifc_class))
    try:
        bpy.ops.bim.add_default_type(ifc_element_type=ifc_class)
    except Exception as exc:
        raise CommandError("Bonsai could not create %s: %s" % (ifc_class, exc))

    made = ifc.by_type(ifc_class)
    if len(made) <= before:
        raise CommandError("no %s was created" % ifc_class)
    return {"id": made[-1].id(), "ifc_class": ifc_class, "name": made[-1].Name}


# --- Building ----------------------------------------------------------------


@verb("add_walls")
def _add_walls(params: dict) -> dict:
    """Parametric walls along a run of points.

    The verb this whole package exists for: "a 6 by 4 room, 3 metres high" is
    five points and a height, and what comes back is walls with material
    layers, not a mesh box that has been told it is a wall.
    """
    ifc = _require_project()
    if not bridge.wall_generator_available():
        raise CommandError(
            bridge.wall_generator_unavailable_reason() or "Bonsai's wall generator is unavailable"
        )

    points = _points(params)
    height = _number(params, "height", 3.0)
    if height <= 0:
        raise CommandError("'height' must be greater than zero")

    wall_types = ifc.by_type("IfcWallType")
    if not wall_types:
        raise CommandError("no IfcWallType exists -- call create_type first")

    type_id = params.get("type_id")
    if type_id is None:
        relating_type = wall_types[0]
    else:
        relating_type = next((t for t in wall_types if t.id() == int(type_id)), None)
        if relating_type is None:
            raise CommandError("no IfcWallType with id %s" % type_id)

    objects = bridge.create_walls(relating_type, points, height=height)
    if not objects:
        # The generator returns nothing when the type carries no material layer
        # set, which is the one failure a caller can actually act on.
        raise CommandError(
            "no walls were made. The wall type may have no material layers, "
            "so Bonsai has no thickness to build from"
        )
    return {"count": len(objects), "walls": [_describe(o) for o in objects]}


@verb("sketch_polyline")
def _sketch_polyline(params: dict) -> dict:
    """Plain sketch geometry, exactly as the Line tool would leave it.

    Not IFC, on purpose. Draw first, name it second -- ``assign_class`` is the
    second half.
    """
    points = _points(params)
    close = bool(params.get("close", False))

    # Match the interactive tools: an explicit object continues that sketch, no
    # object starts a fresh one rather than joining whatever was last touched.
    target = params.get("object")
    if isinstance(target, str):
        obj = _object(params)
        if not sketchmesh.is_sketch_object(obj):
            raise CommandError("%r is not sketch geometry" % target)
        bpy.context.view_layer.objects.active = obj
    else:
        bpy.context.view_layer.objects.active = None

    obj, faces = sketchmesh.commit(bpy.context, points, close=close)
    if obj is None:
        raise CommandError("nothing was drawn")
    return {"object": obj.name, "faces_created": faces, "vertices": len(obj.data.vertices)}


@verb("push_pull")
def _push_pull(params: dict) -> dict:
    """Extrude one face of a sketch along its normal.

    ``distance`` follows the face normal, which is what the interactive tool
    does. A closed loop drawn flat on the ground frequently ends up pointing
    down, so the normal actually used comes back in the reply -- negate the
    distance if it went the wrong way.
    """
    obj = _object(params)
    if not sketchmesh.is_sketch_object(obj):
        # The same refusal the interactive tool makes, for the same reason: an
        # IFC element's shape is generated, and a mesh written over it is lost.
        raise CommandError(
            "%r is not sketch geometry. Push/Pull does not rewrite IFC elements" % obj.name
        )

    distance = _number(params, "distance")
    face_index = int(_number(params, "face", 0.0))

    source = bmesh.new()
    try:
        source.from_mesh(obj.data)
        source.faces.ensure_lookup_table()
        if not source.faces:
            raise CommandError("%r has no faces to push" % obj.name)
        if not 0 <= face_index < len(source.faces):
            raise CommandError(
                "face %d is out of range (%r has %d)" % (face_index, obj.name, len(source.faces))
            )

        face = source.faces[face_index]
        matrix = obj.matrix_world.to_3x3()
        world_normal = (matrix @ face.normal).normalized().copy()
        solid = pushpull.extruded(
            source, face_index, matrix.inverted(), world_normal, distance, pushpull.EXTRUDE
        )
        try:
            solid.to_mesh(obj.data)
        finally:
            solid.free()
    finally:
        source.free()

    obj.data.update()
    # obj.dimensions comes off the evaluated object, and in a GUI session the
    # depsgraph has not caught up by the time this returns -- the reply would
    # carry the size the object was *before* the push. Headless it happens to
    # be current, which is exactly how a bug like this reaches a caller.
    bpy.context.view_layer.update()

    return {
        "object": obj.name,
        "distance": distance,
        # A caller cannot see which way the face pointed, and a flat loop drawn
        # on the ground often points down -- so a plain "2.5" digs a hole. The
        # direction is reported rather than second-guessed, because the
        # interactive tool follows the same normal and the two must not differ.
        "normal": [round(v, 6) for v in world_normal],
        "dimensions": _describe(obj)["dimensions"],
    }


@verb("assign_class")
def _assign_class(params: dict) -> dict:
    """Turn finished sketch geometry into an IFC element."""
    _require_project()
    obj = _object(params)
    if not sketchmesh.is_sketch_object(obj):
        entity = bridge.get_entity(obj)
        if entity is not None:
            raise CommandError("%r is already %s" % (obj.name, entity.is_a()))
        raise CommandError("%r is not sketch geometry" % obj.name)

    ifc_class = params.get("ifc_class")
    if not isinstance(ifc_class, str) or not ifc_class:
        raise CommandError("'ifc_class' is required, such as IfcSlab")

    props = bridge.root_props()
    if props is None:
        raise CommandError("Bonsai's class properties are unavailable")

    bpy.ops.object.select_all(action="DESELECT")
    obj.select_set(True)
    bpy.context.view_layer.objects.active = obj

    # An occurrence, never a construction type -- the same correction the
    # sidebar's Assign button makes, and for the same reason.
    from .. import sidebar

    props.ifc_product = sidebar.OCCURRENCE
    try:
        props.ifc_class = ifc_class
    except TypeError:
        raise CommandError(
            "%s is not an assignable element class in this schema" % ifc_class
        )

    predefined = params.get("predefined_type")
    if isinstance(predefined, str) and predefined:
        try:
            props.ifc_predefined_type = predefined
        except TypeError:
            raise CommandError("%s is not a predefined type of %s" % (predefined, ifc_class))

    bpy.ops.bim.assign_class()
    entity = bridge.get_entity(obj)
    if entity is None:
        raise CommandError("Bonsai did not assign a class to %r" % obj.name)
    return _describe(obj)


@verb("derive_values")
def _derive_values(params: dict) -> dict:
    """Fill the geometric requirement values the element's shape states.

    The complement of ``assign_class``: once an element exists and carries
    its requirement psets, this answers the questions its geometry already
    decides -- height, thickness, a closed shell's volume -- and reports by
    name every question it leaves, which is the list an agent still owes the
    model. A machine fills a value only when the geometry states it; nothing
    here guesses.
    """
    from .. import derive

    ifc = _require_project()
    obj = _object(params)
    entity = bridge.get_entity(obj)
    if entity is None:
        raise CommandError(
            "%r is not an IFC element -- assign_class comes before derive_values" % obj.name
        )
    extents, volume, base_area = derive.measure_object(obj)
    report = derive.fill(ifc, entity, extents, volume=volume, base_area=base_area)
    report.update(object=obj.name, ifc_class=entity.is_a())
    return report


@verb("detect_walls")
def _detect_walls(params: dict) -> dict:
    """Read the parallel-line walls out of a flat plan layer.

    Candidates, not walls: each carries its centreline, measured thickness
    and length, the indices of the two drawn lines that state it, and the
    evidence in sentences. What does not pair comes back counted -- unread
    rather than misread -- for an agent or a person to judge.
    """
    from .. import walls

    obj = _object(params)
    if not sketchmesh.is_sketch_object(obj):
        raise CommandError("%r is not sketch geometry" % obj.name)

    matrix = obj.matrix_world
    zs = [(matrix @ v.co).z for v in obj.data.vertices]
    if zs and max(zs) - min(zs) > 1e-5:
        raise CommandError(
            "%r is not a flat plan -- detect walls before standing anything up" % obj.name
        )
    segs = []
    for edge in obj.data.edges:
        a = matrix @ obj.data.vertices[edge.vertices[0]].co
        b = matrix @ obj.data.vertices[edge.vertices[1]].co
        segs.append(((a.x, a.y), (b.x, b.y)))

    candidates, unpaired = walls.detect(segs)
    return {
        "object": obj.name,
        "walls": [c.as_dict() for c in candidates],
        "unpaired": len(unpaired),
        "segments": len(segs),
    }


@verb("classify_layers")
def _classify_layers(params: dict) -> dict:
    """Read layer names against the drafting conventions. Never guesses.

    Given object names, or every sketch object when none are named. The
    unresolved list is this verb's real product for an agent: those are the
    layers whose classes are somebody's judgement, to be proposed through
    the plan/approve flow rather than assigned by a table.
    """
    from .. import classify

    names = params.get("objects")
    if names is None:
        names = _sketch_objects()
    if not isinstance(names, (list, tuple)) or not all(isinstance(n, str) for n in names):
        raise CommandError("'objects' must be a list of object names")
    for name in names:
        if name not in bpy.data.objects:
            raise CommandError("no object named %r" % name)
    resolved, unresolved = classify.classify_all(names)
    return {
        "resolved": [p.as_dict() for p in resolved],
        "unresolved": [p.as_dict() for p in unresolved],
    }


@verb("auto_model")
def _auto_model(params: dict) -> dict:
    """The whole AutoModel pipeline: a drawn plan in, a reported model out.

    Composes the other verbs rather than shadowing them, so an agent that
    wants finer control runs the stages itself and gets identical results.
    ``heights`` maps a layer name to its own standing height where one
    number for the whole drawing is too blunt.
    """
    from .. import pipeline

    path = params.get("path")
    if not isinstance(path, str) or not path:
        raise CommandError("'path' is required: the DXF or DWG to model from")
    path = bpy.path.abspath(path)
    if not os.path.isfile(path):
        raise CommandError("no file at %r" % path)
    heights = params.get("heights") or {}
    if not isinstance(heights, dict):
        raise CommandError("'heights' must map layer names to heights")
    try:
        heights = {str(k): float(v) for k, v in heights.items()}
    except (TypeError, ValueError):
        raise CommandError("'heights' values must be numbers")
    return pipeline.run(
        bpy.context,
        path,
        weld=_number(params, "weld", 0.001),
        gap=_number(params, "gap", 0.01),
        height=_number(params, "height", 3.0),
        heights=heights,
    )
