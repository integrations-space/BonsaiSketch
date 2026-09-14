"""Isolated Blender checks, without enabling or changing installed extensions.

blender --background --factory-startup --python tools/agents_blender_check.py
"""
from pathlib import Path
import importlib
import json
import sys
import types
import bpy

root = Path(__file__).resolve().parents[1]
for name, path in [('bonsai_sketch_mode', root / 'bonsai_sketch_mode'),
                   ('bonsai_sketch_mode.textmodel', root / 'bonsai_sketch_mode/textmodel')]:
    module = types.ModuleType(name)
    module.__path__ = [str(path)]
    sys.modules[name] = module
sidebar = importlib.import_module('bonsai_sketch_mode.sidebar')
ui = importlib.import_module('bonsai_sketch_mode.textmodel.ui')
sg = importlib.import_module('bonsai_sketch_mode.sg')
commands = importlib.import_module('bonsai_sketch_mode.textmodel.commands')
agents = ui.agents
assert sidebar.register()[0]
assert ui.register()[0]
assert bpy.context.scene.bonsai_sketch_sg_stage == 'conceptual'
assert hasattr(bpy.types, 'BONSAI_SKETCH_MODE_PT_sg')
assert hasattr(bpy.types, 'BONSAI_SKETCH_MODE_OT_approve_plan')

before = sg.fingerprint()
bpy.context.scene.bonsai_sketch_sg_stage = 'detailed'
assert before != sg.fingerprint(), 'Stage change must invalidate approval'
before = sg.fingerprint()
bpy.context.active_object.data.vertices[0].co.x += 0.1
assert before != sg.fingerprint(), 'Vertex changes must invalidate approval'

plan = {'summary': 'Sketch triangle', 'questions': [], 'actions': [
    {'operation': 'sketch_polyline', 'parameters': {'points': [[0, 0], [2, 0], [0, 2]], 'close': True}, 'reason': 'Test'},
    {'operation': 'push_pull', 'parameters': {'object': {'$ref': '0.object'}, 'distance': 1}, 'reason': 'Test'}]}
proposal = {'plan': plan, 'reports': {'QA': {'approved': True, 'findings': []}},
            'ready': True, 'fingerprint': sg.fingerprint()}
count = len(bpy.data.objects)
pending = agents.PendingPlan(proposal)
assert len(bpy.data.objects) == count, 'Review must not change geometry'
execution = pending.execute(sg.fingerprint(), commands.run)
assert execution['ok'], execution
assert len(bpy.data.objects) == count + 1
obj = bpy.data.objects[execution['completed'][0]['object']]
assert len(obj.data.polygons) > 1
assert round(obj.dimensions.z, 5) == 1
assert pending.used
assert set(commands.names()) == set(ui.claude.schema.TOOLS)
# Exercise real IfcOpenShell evidence and IFC property-change invalidation.
import ifcopenshell
import ifcopenshell.guid
ifc = ifcopenshell.file(schema="IFC4")
ifc.create_entity("IfcProject", GlobalId=ifcopenshell.guid.new(), Name="Fixture")
wall = ifc.create_entity("IfcWall", GlobalId=ifcopenshell.guid.new(), Name="Wall")
value = ifc.create_entity("IfcPropertySingleValue", Name="FireRating",
                          NominalValue=ifc.create_entity("IfcLabel", "60"))
pset = ifc.create_entity("IfcPropertySet", GlobalId=ifcopenshell.guid.new(),
                         Name="Pset_WallCommon", HasProperties=[value])
ifc.create_entity("IfcRelDefinesByProperties", GlobalId=ifcopenshell.guid.new(),
                  RelatedObjects=[wall], RelatingPropertyDefinition=pset)
assert sg.bridge.element_properties(wall)["Pset_WallCommon"]["FireRating"] == "60"
# No installed add-on is enabled in this isolated suite. Supply its file accessor.
original_tool, original_ifc = sg.bridge._tool, sg.bridge.Ifc
sg.bridge.Ifc = types.SimpleNamespace(get=lambda: ifc)
sg.bridge._tool = types.SimpleNamespace(Ifc=sg.bridge.Ifc)
before = sg.fingerprint()
value.NominalValue = ifc.create_entity("IfcLabel", "90")
assert before != sg.fingerprint(), "IFC property changes must invalidate approval"
sg.bridge._tool, sg.bridge.Ifc = original_tool, original_ifc
ui.unregister()
sidebar.unregister()
assert not hasattr(bpy.types.Scene, 'bonsai_sketch_sg_stage')
print('AGENTS BLENDER CHECK PASSED: registration, fingerprint, actual sketch/extrusion, IFC property evidence, cleanup')
