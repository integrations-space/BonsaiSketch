"""Run with Blender and an isolated profile containing Bonsai and this build."""
import importlib
from pathlib import Path
import tempfile

import bpy
import ifcopenshell
import ifcopenshell.api.root
import ifcopenshell.api.pset
import ifcopenshell.api.type
import ifcopenshell.util.element

ADDON = 'bl_ext.user_default.bonsai_sketch_mode'
bpy.ops.preferences.addon_enable(module='bl_ext.blender_org.bonsai')
bpy.ops.preferences.addon_enable(module=ADDON)
addon = importlib.import_module(ADDON)
sg = importlib.import_module(ADDON + '.sg_defaults')
bridge = addon.bridge
checks = 0


def check(value, message):
    global checks
    assert value, message
    checks += 1
    print('PASS:', message)


commands = importlib.import_module(ADDON + '.textmodel.commands')
commands.run('create_project', {})
sketch = commands.run('sketch_polyline', {'points': [[0, 0], [2, 0], [0, 2]], 'close': True})
sketch_obj = bpy.data.objects[sketch['object']]
check(bridge.get_entity(sketch_obj) is None, 'plain sketch has no invented IFC classification')
classified = commands.run('assign_class', {'object': sketch['object'], 'ifc_class': 'IfcWall'})
sketch_wall = bridge.get_entity(sketch_obj)
check('SGPset_Wall' in ifcopenshell.util.element.get_psets(sketch_wall),
      'Sketch Assign IFC Class receives the same automatic fields')

file = ifcopenshell.file(schema='IFC4')
bridge.Ifc.set(file)
check(bpy.context.scene.bonsai_sketch_sg_auto, 'automatic setup defaults on')
wall = bridge.Ifc.run('root.create_entity', ifc_class='IfcWall')
fields = ifcopenshell.util.element.get_psets(wall)
check('ConstructionMethod' in fields['SGPset_Wall'], 'BIM create_entity receives exact SGPset fields')
check(fields['SGPset_Wall']['ConstructionMethod'] is None, 'unknown values remain null')
check('IsPartyWall' not in fields['SGPset_Wall'], 'subtype-only fields are not added to generic walls')
check(sg.ensure_fields(file, wall) == 0, 'repeated setup is idempotent')
check(not sg.status(), 'automatic listener reports no error')
check(bridge.require().Pset.get_pset_template('SGPset_Wall') is not None,
      'native Bonsai property editor can find the bundled typed template')

pset = file.by_id(fields['SGPset_Wall']['id'])
template = sg.templates().by_type('IfcPropertySetTemplate')
template = next(t for t in template if t.Name == 'SGPset_Wall')
ifcopenshell.api.pset.edit_pset(file, pset=pset,
    properties={'ConstructionMethod': 'PC', 'LoadBearing': False}, pset_template=template)
sg.ensure_fields(file, wall)
fields = ifcopenshell.util.element.get_psets(wall)
check(fields['SGPset_Wall']['ConstructionMethod'] == 'PC' and fields['SGPset_Wall']['LoadBearing'] is False,
      'typed editing works and existing false/text values are preserved')
check(next(p for p in pset.HasProperties if p.Name == 'LoadBearing').NominalValue.is_a('IfcBoolean'),
      'boolean values are IFC booleans rather than strings')

boundary = ifcopenshell.api.root.create_entity(file, ifc_class='IfcWall', predefined_type='BOUNDARYWALL')
check('IsPartyWall' in ifcopenshell.util.element.get_psets(boundary)['SGPset_Wall'],
      'USERDEFINED subtype receives its mapped fields')
floor = ifcopenshell.api.root.create_entity(file, ifc_class='IfcCovering', predefined_type='ROOFING')
ceiling = ifcopenshell.api.root.create_entity(file, ifc_class='IfcCovering', predefined_type='CEILING')
check('SGPset_Covering' in ifcopenshell.util.element.get_psets(floor)
      and 'SGPset_Covering' not in ifcopenshell.util.element.get_psets(ceiling),
      'roofing fields are not applied to ceilings')

wall_type = ifcopenshell.api.root.create_entity(file, ifc_class='IfcWallType', predefined_type='RETAININGWALL')
ifcopenshell.api.type.assign_type(file, related_objects=[wall], relating_type=wall_type)
check('IsPartyWall' in ifcopenshell.util.element.get_psets(wall)['SGPset_Wall'],
      'assigning a construction type adds effective-subtype fields')
check(not ifcopenshell.util.element.get_psets(wall_type), 'occurrence fields are not indiscriminately written to types')
type_pset = ifcopenshell.api.pset.add_pset(file, product=wall_type, name='SGPset_Wall')
ifcopenshell.api.pset.edit_pset(file, pset=type_pset, properties={'ConstructionMethod': 'TYPE'}, pset_template=template)
inheritor = ifcopenshell.api.root.create_entity(file, ifc_class='IfcWall')
ifcopenshell.api.type.assign_type(file, related_objects=[inheritor], relating_type=wall_type)
check(ifcopenshell.util.element.get_psets(inheritor)['SGPset_Wall']['ConstructionMethod'] == 'TYPE',
      'new placeholders do not mask design values inherited on type assignment')

bpy.context.scene.bonsai_sketch_sg_auto = False
untouched = ifcopenshell.api.root.create_entity(file, ifc_class='IfcWall')
check(not ifcopenshell.util.element.get_psets(untouched), 'project toggle disables automatic writes')
bpy.context.scene.bonsai_sketch_sg_auto = True
sg.on_load()
check(not ifcopenshell.util.element.get_psets(untouched), 'loading does not backfill existing elements')

file.begin_transaction()
undo_wall = ifcopenshell.api.root.create_entity(file, ifc_class='IfcWall')
guid = undo_wall.GlobalId
file.end_transaction()
before = len(file.by_type('IfcPropertySingleValue'))
file.undo()
check(len(file.by_type('IfcPropertySingleValue')) < before, 'new fields participate in IFC undo')
file.redo()
check('SGPset_Wall' in ifcopenshell.util.element.get_psets(file.by_guid(guid)), 'IFC redo restores fields with the element')

other = ifcopenshell.file(schema='IFC4')
other_wall = ifcopenshell.api.root.create_entity(other, ifc_class='IfcWall')
check(not ifcopenshell.util.element.get_psets(other_wall), 'library and unrelated IFC files are untouched')

copy = ifcopenshell.api.root.copy_class(file, product=wall)
copied = ifcopenshell.util.element.get_psets(copy)
check(copied['SGPset_Wall']['ConstructionMethod'] == 'PC', 'duplication preserves authored values')
check(sg.ensure_fields(file, copy) == 0, 'duplicated elements contain their mapped fields')

with tempfile.TemporaryDirectory() as directory:
    path = Path(directory) / 'sg.ifc'
    file.write(str(path))
    reopened = ifcopenshell.open(str(path))
    props = ifcopenshell.util.element.get_psets(reopened.by_guid(boundary.GlobalId))
    check('IsPartyWall' in props['SGPset_Wall'] and props['SGPset_Wall']['IsPartyWall'] is None,
          'empty mapped fields survive IFC save/reopen')

sg.unregister()
check('BonsaiSketch.IFCSG' not in ifcopenshell.api.post_listeners.get('root.create_entity', {}),
      'disabling Sketch removes its listeners')
print(f'IFC+SG DEFAULTS CHECK PASSED: {checks} checks')
