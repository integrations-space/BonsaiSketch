# SPDX-License-Identifier: GPL-3.0-or-later
"""IFC+SG checklist and model context. All functions run on Blender's thread."""
import hashlib
import json

import bpy

from . import bridge, requirements, sketchmesh


def stage():
    return bpy.context.scene.bonsai_sketch_sg_stage


def inspect(obj, selected_stage=None):
    entity = bridge.get_entity(obj)
    if entity is None:
        return {"object": obj.name if obj else None, "status": "unclassified"}
    properties = bridge.element_properties(entity)
    result = requirements.check_element(entity.is_a(), selected_stage or stage(), properties,
                                        getattr(entity, "PredefinedType", "") or "")
    result.update(object=obj.name, id=entity.id(), global_id=getattr(entity, "GlobalId", None))
    return result


def fingerprint():
    """Bind approval to the full IFC, meshes, scene, stage and selection.

    Counts/positions alone miss edits to properties, topology and wall types.
    No IFC content leaves the process through this digest.
    """
    digest = hashlib.sha256()
    if bridge.has_project():
        digest.update(bridge.Ifc.get().to_string().encode("utf-8"))
    digest.update(str((bpy.context.mode, bpy.context.view_layer.name, bpy.data.filepath, bpy.context.scene.as_pointer(), stage(), bpy.context.scene.unit_settings.scale_length,
                       bpy.context.active_object.name if bpy.context.active_object else None,
                       sorted(o.name for o in bpy.context.selected_objects))).encode())
    depsgraph = bpy.context.evaluated_depsgraph_get()
    for obj in sorted(bpy.context.scene.objects, key=lambda o: o.name):
        digest.update(str((obj.name, list(map(tuple, obj.matrix_world)))).encode())
        if obj.type == "MESH":
            digest.update(str(([tuple(v.co) for v in obj.data.vertices],
                               [tuple(e.vertices) for e in obj.data.edges],
                               [tuple(p.vertices) for p in obj.data.polygons])).encode())
            if obj.modifiers or obj.data.shape_keys:
                evaluated = obj.evaluated_get(depsgraph)
                mesh = evaluated.to_mesh()
                try:
                    digest.update(str(([tuple(v.co) for v in mesh.vertices],
                                       [tuple(p.vertices) for p in mesh.polygons])).encode())
                finally:
                    evaluated.to_mesh_clear()
    return digest.hexdigest()


def snapshot():
    from .textmodel import commands
    if bpy.context.mode != "OBJECT":
        raise ValueError("Switch to Object Mode before generating a plan")
    if abs(bpy.context.scene.unit_settings.scale_length - 1.0) > 1e-9:
        raise ValueError("Agent modelling currently requires a scene unit scale of 1 metre")
    objects = list(bpy.context.scene.objects)
    # Explicitly bounded context. Large models require a narrower selection.
    selected = list(bpy.context.selected_objects)
    scope = selected or objects
    if len(scope) > 200:
        raise ValueError("Select at most 200 objects for agent review")
    items = []
    for obj in scope:
        entity = bridge.get_entity(obj)
        item = {"object": obj.name, "dimensions": list(obj.dimensions),
                "matrix_world": list(map(list, obj.matrix_world)),
                "sketch": sketchmesh.is_sketch_object(obj)}
        if entity:
            item.update(id=entity.id(), ifc_class=entity.is_a(),
                        properties=bridge.element_properties(entity), ifc_sg=inspect(obj))
        items.append(item)
    context = {"model": commands.run("describe", {}), "stage": stage(),
               "source": requirements.source(), "scope": "selection" if selected else "scene",
               "objects": items, "units": "Blender coordinates; command inputs are metres",
               "scene_unit_scale": bpy.context.scene.unit_settings.scale_length,
               "requirements": {name: requirements.parameters(name, stage())
                                for name in requirements.elements()}}
    if len(json.dumps(context)) > 700000:
        raise ValueError("Model context is too large; select fewer objects")
    return {"fingerprint": fingerprint(), "context": context}
