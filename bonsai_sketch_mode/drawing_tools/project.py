# SPDX-License-Identifier: GPL-3.0-or-later
"""Prepare a repeatable building recipe from explicitly mapped drawing layers."""
from copy import deepcopy
import hashlib
import importlib.util
import math
from pathlib import Path

from .catalogue import resolve
from .repair import repair


def _reader():
    # Loading the pure reader directly also supports Python without bpy.
    spec = importlib.util.spec_from_file_location('sketch_dxf_reader', Path(__file__).parents[1] / 'dxf.py')
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def prepare(manifest, base_dir):
    """Pure preparation: writes no IFC and never modifies source drawings.

    Stable component IDs and file hashes let an agent compare successive runs.
    Coordinates and heights after source alignment are always metres.
    """
    if manifest.get('schema') != 'bonsai.drawing-project/1':
        raise ValueError('Expected schema bonsai.drawing-project/1')
    result = {'schema': 'bonsai.building-recipe/1', 'name': manifest.get('name', 'Drawing model'),
              'storeys': deepcopy(manifest['storeys']), 'components': [], 'findings': [], 'repairs': {}}
    names = [s['name'] for s in result['storeys']]
    if len(names) != len(set(names)):
        raise ValueError('Storey names must be unique')
    for s in result['storeys']:
        if not math.isfinite(s['elevation_m']):
            raise ValueError('Storey elevations must be finite metres')
    sources = {}
    for source in manifest.get('drawings', []):
        if source['id'] in sources:
            raise ValueError('Drawing IDs must be unique')
        path = (Path(base_dir) / source['path']).resolve()
        if path.suffix.lower() != '.dxf':
            raise ValueError('Convert DWG with the CAD importer/ODA first; drawing recipes read DXF')
        data = path.read_bytes()
        if data.startswith(b'AutoCAD Binary DXF'):
            raise ValueError('Convert binary DXF to ASCII DXF first')
        drawing = _reader().parse(data.decode(source.get('encoding', 'utf-8-sig'), errors='strict'))
        scale = source.get('scale_to_m', 1.0)
        if drawing.unit_name == 'as drawn' and 'scale_to_m' not in source:
            raise ValueError(f"{source['id']}: unspecified drawing units; set scale_to_m")
        if 'scale_to_m' in source:
            scale /= drawing.scale  # explicit unit override, not a second unit conversion
        if not math.isfinite(scale) or scale <= 0:
            raise ValueError('scale_to_m must be positive and finite')
        angle = math.radians(source.get('rotation_deg', 0))
        ox, oy = source.get('offset_m', [0, 0])
        if not all(math.isfinite(v) for v in (angle, ox, oy)):
            raise ValueError('Drawing alignment must be finite')
        ca, sa = math.cos(angle), math.sin(angle)
        layers = {name: [{'points': [(ox + scale * (ca*x - sa*y), oy + scale * (sa*x + ca*y))
                                    for x, y in p.points], 'closed': p.closed} for p in polylines]
                  for name, polylines in drawing.layers.items()}
        # The reader keeps block references as symbols rather than skipping
        # them, but a recipe still cannot build from a block: count them as
        # unconverted geometry on their layer.
        unconverted = {layer: dict(counts) for layer, counts in drawing.skipped_by_layer.items()}
        for insert in drawing.inserts:
            counts = unconverted.setdefault(insert.layer, {})
            counts['INSERT'] = counts.get('INSERT', 0) + 1
        sources[source['id']] = (layers, {'drawing': source['id'], 'path': source['path'],
                                         'sha256': hashlib.sha256(data).hexdigest(),
                                         'references': source.get('references', [])}, unconverted)
        if drawing.skipped:
            result['findings'].append({'code': 'DXF_ENTITIES_SKIPPED', 'severity': 'warning',
                                       'drawing': source['id'], 'entities': drawing.skipped})
    candidates = deepcopy(manifest.get('components', []))
    for mapping in manifest.get('layers', []):
        layers, evidence, skipped = sources[mapping['drawing']]
        missing_geometry = {k: v for k, v in skipped.get(mapping['layer'], {}).items()
                            if k not in ('TEXT', 'MTEXT', 'DIMENSION', 'HATCH', 'ATTRIB', 'ATTDEF')}
        if missing_geometry:
            result['findings'].append({'code': 'LAYER_GEOMETRY_SKIPPED', 'severity': 'error',
                                       'component': mapping['id'], 'entities': missing_geometry})
        if mapping['layer'] not in layers:
            raise ValueError(f"Layer not found: {mapping['drawing']}/{mapping['layer']}")
        linework = layers[mapping['layer']]
        evidence = dict(evidence, layer=mapping['layer'])
        common = {k: deepcopy(v) for k, v in mapping.items()
                  if k not in ('drawing', 'layer', 'gap_m', 'mode')}
        common['evidence'] = evidence
        mode = mapping.get('mode', 'footprint')
        if mode == 'reference':
            common['polylines'] = linework
            candidates.append(common)
            continue
        if mode != 'footprint':
            raise ValueError('Layer mode must be footprint or reference; centreline walls need a measured thickness')
        healed = repair(linework, mapping.get('gap_m', 0.02))
        if mapping['id'] in result['repairs']:
            raise ValueError('Layer mapping IDs must be unique')
        result['repairs'][mapping['id']] = healed
        if not healed['ready']:
            result['findings'].append({'code': 'LINEWORK_UNRESOLVED', 'severity': 'error', 'component': mapping['id']})
        for i, profile in enumerate(healed['profiles']):
            candidates.append(dict(common, id=f"{mapping['id']}:{i + 1}", profile=profile))
    ids = set()
    for c in candidates:
        if not isinstance(c.get('id'), str) or not c['id'] or c['id'] in ids:
            raise ValueError('Every component needs a unique, nonempty id')
        ids.add(c['id'])
        if c['kind'] not in ('boundary', 'setback', 'terrain', 'entrance') and c.get('storey') not in names:
            raise ValueError(f"{c['id']}: unknown storey")
        values, findings = resolve(c, manifest.get('schedules'), manifest.get('defaults'))
        if 'shape' in values:
            from .shapes import sloping_slab, terrain
            shape = values['shape']
            if shape['type'] == 'sloping_slab':
                values.update(sloping_slab(shape['length_m'], shape['width_m'], shape['thickness_m'], shape['rise_m']))
            elif shape['type'] == 'terrain':
                values.update(terrain(shape['points'], shape['boundary']))
            else:
                raise ValueError(f"Unknown shape: {shape['type']}")
        result['components'].append(values)
        result['findings'].extend(dict(f, component=c['id'], severity='error' if f['code'] == 'SCHEDULE_CONFLICT' else 'warning')
                                  for f in findings)
        if not c.get('evidence'):
            result['findings'].append({'code': 'SOURCE_MISSING', 'severity': 'warning', 'component': c['id']})
    for c in result['components']:
        if c['kind'] in ('door', 'window') and c.get('host') not in ids:
            result['findings'].append({'code': 'HOST_MISSING', 'severity': 'error', 'component': c['id']})
        if c['kind'] == 'stair' and not all(c.get('evidence', {}).get(k) for k in ('plan', 'section', 'elevation')):
            result['findings'].append({'code': 'STAIR_REFERENCES_INCOMPLETE', 'severity': 'warning', 'component': c['id']})
    return result
