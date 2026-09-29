# SPDX-License-Identifier: GPL-3.0-or-later
"""Exact IFC+SG field setup, performed inside the creating IFC transaction."""
import json
from functools import lru_cache
from pathlib import Path

import bpy
from bpy.app.handlers import persistent

from . import bridge

LISTENER = 'BonsaiSketch.IFCSG'
_before = {}
_error = ''
_templates = None


@lru_cache(maxsize=1)
def mapping():
    return json.loads((Path(__file__).parent / 'data/ifc_sg_mapping.json').read_text(encoding='utf-8'))


def applicable(entity):
    """Exact class and effective subtype match; N.A is the class-wide mapping."""
    import ifcopenshell.util.element
    subtype = ifcopenshell.util.element.get_predefined_type(entity) or ''
    result = {}
    for row in mapping()['entries']:
        if not entity.is_a(row['ifc_class']):
            continue
        # Custom subtype names are stored in ObjectType / ElementType, as read
        # by get_predefined_type. Never assign a subtype on the user's behalf.
        if 'N.A' not in row['subtypes'] and subtype not in [s.lstrip('*') for s in row['subtypes']]:
            continue
        result[row['pset'], row['name']] = row
    return list(result.values())


def templates():
    """Typed definitions for native Bonsai editing of the initially null fields."""
    global _templates
    if _templates is not None:
        return _templates
    import ifcopenshell
    import ifcopenshell.guid
    file = ifcopenshell.file(schema='IFC4')
    groups = {}
    for row in mapping()['entries']:
        if row['pset'].startswith('Pset_'):
            continue  # Keep buildingSMART's templates authoritative.
        groups.setdefault(row['pset'], {})[row['name']] = row
    for name, rows in groups.items():
        props = []
        for row in rows.values():
            props.append(file.create_entity('IfcSimplePropertyTemplate', GlobalId=ifcopenshell.guid.new(),
                Name=row['name'], TemplateType='P_SINGLEVALUE', PrimaryMeasureType=row['measure'],
                Description=f"CORENET X 2025-12-04. Source unit: {row['unit']}. Accepted values: {row['accepted_values']}"))
        classes = sorted({r['ifc_class'] for r in mapping()['entries'] if r['pset'] == name})
        file.create_entity('IfcPropertySetTemplate', GlobalId=ifcopenshell.guid.new(), Name=name,
                           TemplateType='PSET_OCCURRENCEDRIVEN', ApplicableEntity=','.join(classes),
                           HasPropertyTemplates=props)
    _templates = file
    return file


def ensure_fields(file, entity):
    """Add missing fields without overwriting local or inherited values."""
    import ifcopenshell.api.pset
    import ifcopenshell.util.element
    if file.schema != 'IFC4' or not entity.is_a('IfcObject'):
        return 0
    rows = applicable(entity)
    # Creating an occurrence precedes type assignment in Bonsai. Drop only our
    # still-empty placeholders when a type now supplies that property, so a
    # blank occurrence field cannot mask an inherited design value.
    relating_type = ifcopenshell.util.element.get_type(entity)
    inherited = ifcopenshell.util.element.get_psets(relating_type, psets_only=True) if relating_type else {}
    for name, info in ifcopenshell.util.element.get_psets(entity, psets_only=True, should_inherit=False).items():
        if name not in inherited:
            continue
        pset = file.by_id(info['id'])
        for prop in tuple(pset.HasProperties or ()):
            if (prop.is_a('IfcPropertySingleValue') and prop.NominalValue is None
                    and (prop.Description or '').startswith('IFC+SG 2025-12-04;')
                    and prop.Name in inherited[name]):
                pset.HasProperties = tuple(p for p in pset.HasProperties if p != prop)
                if not file.get_inverse(prop):
                    file.remove(prop)
        if not pset.HasProperties:
            ifcopenshell.api.pset.remove_pset(file, product=entity, pset=pset)
    existing = ifcopenshell.util.element.get_psets(entity, psets_only=True)
    local = ifcopenshell.util.element.get_psets(entity, psets_only=True, should_inherit=False)
    added = 0
    for row in rows:
        name, prop = row['pset'], row['name']
        if prop in existing.get(name, {}):
            continue
        info = local.get(name)
        if info is None:
            pset = ifcopenshell.api.pset.add_pset(file, product=entity, name=name)
            local[name] = {'id': pset.id()}
        else:
            pset = file.by_id(info['id'])
        field = file.create_entity('IfcPropertySingleValue', Name=prop, NominalValue=None,
            Description=f"IFC+SG 2025-12-04; {row['measure']}; source row {row['row']}; value required")
        pset.HasProperties = tuple(pset.HasProperties or ()) + (field,)
        existing.setdefault(name, {})[prop] = None
        added += 1
    return added


def enabled():
    return bool(getattr(bpy.context.scene, 'bonsai_sketch_sg_auto', True))


def _pre(usecase, file, settings):
    if not enabled() or file.schema != 'IFC4' or file != bridge.Ifc.get():
        return
    cls = settings.get('ifc_class')
    if cls is None and settings.get('product') is not None:
        cls = settings['product'].is_a()
    if cls and cls.endswith('StandardCase'):
        cls = cls.removesuffix('StandardCase')
    if cls not in {r['ifc_class'] for r in mapping()['entries']}:
        return
    # A post listener receives settings, not the returned entity. Capture only
    # the matching class before creation, so existing models aren't backfilled.
    if len(_before) > 32:
        _before.clear()
    _before[id(settings)] = (cls, {e.id() for e in file.by_type(cls)})


def _post(usecase, file, settings):
    global _error
    saved = _before.pop(id(settings), None)
    if not enabled() or file.schema != 'IFC4' or file != bridge.Ifc.get():
        return
    if usecase == 'type.assign_type':
        elements = settings.get('related_objects', [])
    elif saved:
        cls, ids = saved
        elements = [e for e in file.by_type(cls) if e.id() not in ids]
    else:
        return
    try:
        bridge.install_sg_templates(templates())
        for entity in elements:
            ensure_fields(file, entity)
        _error = ''
    except Exception as exc:
        _error = str(exc)
        print(f'[bonsai_sketch_mode] IFC+SG field setup failed: {exc}')


def status():
    return _error


@persistent
def on_load(*_):
    _before.clear()
    install_listeners()


def refresh_templates():
    """Bonsai rebuilds its template catalog on IFC open, separately from blend load."""
    global _error
    try:
        bridge.install_sg_templates(templates())
    except Exception as exc:
        _error = f'Could not expose IFC+SG field types: {exc}'
    return 1.0


def install_listeners():
    import ifcopenshell.api
    for name in ('root.create_entity', 'root.copy_class'):
        ifcopenshell.api.add_pre_listener(name, LISTENER, _pre)
        ifcopenshell.api.add_post_listener(name, LISTENER, _post)
    ifcopenshell.api.add_post_listener('type.assign_type', LISTENER, _post)
    bridge.install_sg_templates(templates())


def register():
    bpy.types.Scene.bonsai_sketch_sg_auto = bpy.props.BoolProperty(
        name='Set up IFC+SG fields automatically', default=True,
        description='Add mapped IFC4 fields when elements are created in BIM or Sketch; unknown values remain empty')
    install_listeners()
    if on_load not in bpy.app.handlers.load_post:
        bpy.app.handlers.load_post.append(on_load)
    if not bpy.app.timers.is_registered(refresh_templates):
        bpy.app.timers.register(refresh_templates, first_interval=1.0, persistent=True)


def unregister():
    if not hasattr(bpy.types.Scene, 'bonsai_sketch_sg_auto'):
        return
    import ifcopenshell.api
    for name in ('root.create_entity', 'root.copy_class'):
        ifcopenshell.api.remove_pre_listener(name, LISTENER, _pre)
        ifcopenshell.api.remove_post_listener(name, LISTENER, _post)
    ifcopenshell.api.remove_post_listener('type.assign_type', LISTENER, _post)
    if bpy.app.timers.is_registered(refresh_templates):
        bpy.app.timers.unregister(refresh_templates)
    if on_load in bpy.app.handlers.load_post:
        bpy.app.handlers.load_post.remove(on_load)
    if hasattr(bpy.types.Scene, 'bonsai_sketch_sg_auto'):
        del bpy.types.Scene.bonsai_sketch_sg_auto
    bridge.remove_sg_templates(_templates)
    _before.clear()
