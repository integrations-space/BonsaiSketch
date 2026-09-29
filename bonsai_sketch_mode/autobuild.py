# SPDX-License-Identifier: GPL-3.0-or-later
"""Author a native IFC from a building description read off drawings.

The description (schema ``openshrimp.building/1``) is what an interpreter read from a drawing set:
storeys and levels, and one proposal per element with the sheet, layer and measurement it came
from, the assumptions it rests on, and the facts the drawings state. This module does not read
drawings and does not guess: it authors exactly what the description says, the way Bonsai would
author it by hand -

  * walls with a wall type per measured thickness and a material layer set on the type
  * openings that are real voids, filled with parametric doors and windows
  * columns from their profile, slabs and roofs as extrusions with slab types
  * a spiral stair and a curved wall as ONE element each, however many pieces they are drawn in
  * the terrain as an IfcGeographicElement on the site

and on every element: Pset_OS_Provenance (evidence, assumptions, draft status), the facts as typed
properties, and the IFC+SG fields of the bundled CORENET X mapping as empty placeholders - the
same fields, the same matching rule and the same description text as sg_defaults.ensure_fields,
so Sketch's checklist reads them as its own. A placeholder is never filled with a guess.

Runs anywhere IfcOpenShell imports - headless for tests, or inside Blender:

    python bonsai_sketch_mode/autobuild.py building-description.json model.ifc
"""
import json
import math
import re
import sys
from pathlib import Path

import numpy as np
import ifcopenshell
import ifcopenshell.api
import ifcopenshell.api.aggregate
import ifcopenshell.api.context
import ifcopenshell.api.feature
import ifcopenshell.api.geometry
import ifcopenshell.api.material
import ifcopenshell.api.project
import ifcopenshell.api.pset
import ifcopenshell.api.root
import ifcopenshell.api.spatial
import ifcopenshell.api.style
import ifcopenshell.api.type
import ifcopenshell.api.unit
import ifcopenshell.util.element
import ifcopenshell.util.placement
from ifcopenshell.util.shape_builder import ShapeBuilder

MAPPING = Path(__file__).parent / 'data' / 'ifc_sg_mapping.json'
LOOK = {  # display colours by class (RGB 0-1, transparency 0-1)
    'IfcWall': ((.93, .91, .87), 0), 'IfcCurtainWall': ((.55, .73, .88), .55), 'IfcSlab': ((.83, .81, .77), 0),
    'IfcRoof': ((.37, .40, .43), 0), 'IfcRailing': ((.20, .22, .24), 0), 'IfcColumn': ((.79, .76, .71), 0),
    'IfcStair': ((.69, .54, .42), 0), 'IfcDoor': ((.56, .38, .25), 0), 'IfcWindow': ((.61, .80, .92), .5),
    'IfcGeographicElement': ((.61, .72, .48), 0),
}


class Author:
    def __init__(self, description):
        self.d = description
        self.f = ifcopenshell.api.project.create_file(version='IFC4')
        self.report = {'built': {}, 'refused': [], 'placeholders': 0, 'facts': 0}
        self.by_id = {}
        self.walls = {}
        self.types = {}
        self.materials = {}
        self.styles = {}
        self.assembled = {}
        self.sg = json.loads(MAPPING.read_text(encoding='utf-8'))['entries'] if MAPPING.exists() else []

    # ---- setup ------------------------------------------------------------------------------
    def run(self):
        f = self.f
        project = ifcopenshell.api.root.create_entity(f, ifc_class='IfcProject', name='Automated model (DRAFT)')
        units = [ifcopenshell.api.unit.add_si_unit(f, unit_type=t) for t in ('LENGTHUNIT', 'AREAUNIT', 'VOLUMEUNIT')]
        units.append(ifcopenshell.api.unit.add_si_unit(f, unit_type='PLANEANGLEUNIT'))
        ifcopenshell.api.unit.assign_unit(f, units=units)
        model = ifcopenshell.api.context.add_context(f, context_type='Model')
        self.body = ifcopenshell.api.context.add_context(f, context_type='Model', context_identifier='Body', target_view='MODEL_VIEW', parent=model)
        self.site = ifcopenshell.api.root.create_entity(f, ifc_class='IfcSite', name='Site')
        self.building = ifcopenshell.api.root.create_entity(f, ifc_class='IfcBuilding', name='Building')
        ifcopenshell.api.aggregate.assign_object(f, products=[self.site], relating_object=project)
        ifcopenshell.api.aggregate.assign_object(f, products=[self.building], relating_object=self.site)
        for x in (self.site, self.building):
            ifcopenshell.api.geometry.edit_object_placement(f, product=x)
        self.storeys = {}
        for s in self.d['storeys']:
            st = ifcopenshell.api.root.create_entity(f, ifc_class='IfcBuildingStorey', name=s['name'])
            st.Elevation = s['elevation_m']
            ifcopenshell.api.aggregate.assign_object(f, products=[st], relating_object=self.building)
            ifcopenshell.api.geometry.edit_object_placement(f, product=st, matrix=self.matrix((0, 0, s['elevation_m'])))
            self.storeys[s['name']] = st
        for p in self.d['proposals']:
            self.by_id[p['id']] = p
        self.build_all()
        self.facts()
        self.terrain()
        for el in self.f.by_type('IfcElement'):
            if not el.is_a('IfcOpeningElement'):
                self.report['placeholders'] += self.ensure_sg(el)
        return self.f

    @staticmethod
    def matrix(origin, xaxis=(1, 0, 0)):
        x = np.array(xaxis, dtype=float); x /= np.linalg.norm(x)
        z = np.array((0, 0, 1.0)); y = np.cross(z, x)
        m = np.eye(4); m[:3, 0], m[:3, 1], m[:3, 2], m[:3, 3] = x, y, z, origin
        return m

    def element(self, cls, name, storey, proposal, predefined=None):
        el = ifcopenshell.api.root.create_entity(self.f, ifc_class=cls, name=name, predefined_type=predefined)
        container = self.storeys.get(storey) or self.building
        ifcopenshell.api.spatial.assign_container(self.f, products=[el], relating_structure=container)
        if proposal is not None:
            self.provenance(el, proposal)
        self.report['built'][cls] = self.report['built'].get(cls, 0) + 1
        return el

    def provenance(self, el, p):
        ev = p.get('evidence') or {}
        props = {'ProposalId': p['id'], 'Gate': p.get('gate', ''), 'Source': (p.get('provenance') or {}).get('Source', ''),
                 'Evidence': json.dumps(ev, ensure_ascii=True)[:2000], 'Assumptions': '; '.join(p.get('assumptions') or []) or 'none',
                 'ApprovalState': 'DRAFT - NOT APPROVED'}
        pset = ifcopenshell.api.pset.add_pset(self.f, product=el, name='Pset_OS_Provenance')
        ifcopenshell.api.pset.edit_pset(self.f, pset=pset, properties=props)

    def style(self, rep, cls):
        look = LOOK.get(cls)
        if not look or rep is None:
            return
        if cls not in self.styles:
            st = ifcopenshell.api.style.add_style(self.f, name=cls[3:])
            ifcopenshell.api.style.add_surface_style(self.f, style=st, ifc_class='IfcSurfaceStyleShading',
                attributes={'SurfaceColour': {'Name': None, 'Red': look[0][0], 'Green': look[0][1], 'Blue': look[0][2]}, 'Transparency': look[1]})
            self.styles[cls] = st
        ifcopenshell.api.style.assign_representation_styles(self.f, shape_representation=rep, styles=[self.styles[cls]])

    def material(self, name):
        if name not in self.materials:
            self.materials[name] = ifcopenshell.api.material.add_material(self.f, name=name)
        return self.materials[name]

    def layered_type(self, cls, thickness, label):
        """One type per measured thickness, with a single-layer material set. The layer's material is
        named as unconfirmed: the drawings give the thickness, not the build-up."""
        # types are nominal: a drawn 149 or 154 mm wall is a 150 mm wall type (the measured value stays
        # in the element's evidence); the geometry keeps the measured thickness
        mm = int(round(thickness * 100)) * 10
        key = (cls, mm)
        if key not in self.types:
            t = ifcopenshell.api.root.create_entity(self.f, ifc_class=cls, name=f'{label} {mm}', predefined_type='NOTDEFINED')
            ls = ifcopenshell.api.material.add_material_set(self.f, name=f'{label} {mm}', set_type='IfcMaterialLayerSet')
            layer = ifcopenshell.api.material.add_layer(self.f, layer_set=ls, material=self.material(f'{mm} mm - material to be confirmed'))
            ifcopenshell.api.material.edit_layer(self.f, layer=layer, attributes={'LayerThickness': mm / 1000})
            ifcopenshell.api.material.assign_material(self.f, products=[t], type='IfcMaterialLayerSet', material=ls)
            self.types[key] = t
        return self.types[key]

    # ---- elements ---------------------------------------------------------------------------
    def build_all(self):
        groups = {}
        for p in self.d['proposals']:
            m = re.match(r'^(E-.+-(?:SPIR|SPRL|CWAL)-[0-9A-Z]+)-', p['id'])
            if m:  # the pieces of one spiral stair / curved wall are one element
                groups.setdefault(m.group(1), []).append(p)
        grouped = {q['id'] for g in groups.values() for q in g}
        for p in self.d['proposals']:
            try:
                if p['id'] in grouped:
                    continue
                if p['command'] == 'create_wall':
                    self.wall(p) if p['args']['ifc_class'] == 'IfcWall' else self.column(p)
                elif p['command'] == 'create_loft':
                    self.prism(p)
                elif p['command'] == 'create_hosted_opening':
                    self.opening(p)
            except Exception as e:
                self.report['refused'].append({'id': p['id'], 'why': f'{type(e).__name__}: {e}'})
        for key, parts in groups.items():
            try:
                self.assembly(key, parts)
            except Exception as e:
                self.report['refused'].append({'id': key, 'why': f'{type(e).__name__}: {e}'})

    def wall(self, p):
        a = p['args']
        el = self.element('IfcWall', a.get('name') or p['id'], p['storey'], p, 'STANDARD')
        ifcopenshell.api.type.assign_type(self.f, related_objects=[el], relating_type=self.layered_type('IfcWallType', a['thickness'], 'Wall'))
        # the wall's own axis, from the storey it stands on; the layer set is centred on it
        st = self.storeys[p['storey']]
        rep = ifcopenshell.api.geometry.create_2pt_wall(self.f, element=el, context=self.body, p1=tuple(a['start']), p2=tuple(a['end']),
                                                        elevation=a['base_z'], height=a['height'], thickness=a['thickness'])
        # create_2pt_wall returns the body; it does not attach it
        ifcopenshell.api.geometry.assign_representation(self.f, product=el, representation=rep)
        self.shift_to_centre(el, a)
        self.style(rep, 'IfcWall')
        self.walls[p['id']] = (el, a)

    def shift_to_centre(self, el, a):
        # create_2pt_wall puts the axis on the wall's face; the description measures the centreline
        m = ifcopenshell.util.placement.get_local_placement(el.ObjectPlacement)
        y = m[:3, 1]
        m[:3, 3] = m[:3, 3] - y * (a['thickness'] / 2)
        ifcopenshell.api.geometry.edit_object_placement(self.f, product=el, matrix=m, is_si=True)

    def column(self, p):
        a = p['args']
        s, e = np.array(a['start'], float), np.array(a['end'], float)
        c, u, L = (s + e) / 2, e - s, np.linalg.norm(e - s)
        el = self.element('IfcColumn', a.get('name') or p['id'], p['storey'], p, 'COLUMN')
        prof = self.f.create_entity('IfcRectangleProfileDef', ProfileType='AREA', XDim=float(L), YDim=float(a['thickness']))
        rep = ifcopenshell.api.geometry.add_profile_representation(self.f, context=self.body, profile=prof, depth=a['height'])
        ifcopenshell.api.geometry.assign_representation(self.f, product=el, representation=rep)
        ifcopenshell.api.geometry.edit_object_placement(self.f, product=el, matrix=self.matrix((c[0], c[1], a['base_z']), (u[0], u[1], 0)))
        self.style(rep, 'IfcColumn')

    def prism_rep(self, rings):
        """A prism from a loft whose two profiles share their plan: the only kind the description holds."""
        lo, hi = rings[0], rings[-1]
        z0, z1 = lo[0][2], hi[0][2]
        b = ShapeBuilder(self.f)
        pts = [(q[0], q[1]) for q in lo]
        curve = b.polyline(pts, closed=True)
        solid = b.extrude(b.profile(curve), magnitude=z1 - z0)
        return b.get_representation(self.body, [solid]), z0

    def prism(self, p):
        a = p['args']
        cls = a['ifc_class']
        predefined = {'IfcSlab': 'FLOOR', 'IfcRoof': 'FLAT_ROOF', 'IfcCurtainWall': None, 'IfcRailing': 'BALUSTRADE', 'IfcWall': 'STANDARD', 'IfcColumn': 'COLUMN'}.get(cls)
        el = self.element(cls, a.get('name') or p['id'], p['storey'], p, predefined)
        rep, z0 = self.prism_rep(a['profiles'])
        ifcopenshell.api.geometry.assign_representation(self.f, product=el, representation=rep)
        ifcopenshell.api.geometry.edit_object_placement(self.f, product=el, matrix=self.matrix((0, 0, z0)))
        if cls == 'IfcSlab':
            depth = a['profiles'][-1][0][2] - a['profiles'][0][0][2]
            ifcopenshell.api.type.assign_type(self.f, related_objects=[el], relating_type=self.layered_type('IfcSlabType', depth, 'Slab'))
        self.style(rep, cls)

    def assembly(self, key, parts):
        cls = 'IfcStair' if '-SPIR-' in key else 'IfcRailing' if '-SPRL-' in key else 'IfcWall'
        first = parts[0]
        name = {'IfcStair': 'Spiral stair', 'IfcRailing': 'Spiral stair rail'}.get(cls) or first['args'].get('name', 'Curved wall')
        el = self.element(cls, name, first['storey'], first, {'IfcStair': 'SPIRAL', 'IfcRailing': 'HANDRAIL'}.get(cls, 'STANDARD'))
        b = ShapeBuilder(self.f)
        items = []
        for q in parts:
            lo, hi = q['args']['profiles'][0], q['args']['profiles'][-1]
            curve = b.polyline([(v[0], v[1]) for v in lo], closed=True)
            items.append(b.extrude(b.profile(curve), magnitude=hi[0][2] - lo[0][2], position=np.array((0, 0, lo[0][2]))))
        rep = b.get_representation(self.body, items)
        ifcopenshell.api.geometry.assign_representation(self.f, product=el, representation=rep)
        ifcopenshell.api.geometry.edit_object_placement(self.f, product=el, matrix=self.matrix((0, 0, 0)))
        self.assembled[key] = el
        pset = ifcopenshell.util.element.get_pset(el, 'Pset_OS_Provenance')
        ifcopenshell.api.pset.edit_pset(self.f, pset=self.f.by_id(pset['id']), properties={'Evidence': f'{len(parts)} pieces: ' + json.dumps(first.get('evidence') or {})[:1800]})
        self.style(rep, cls)

    def opening(self, p):
        a = p['args']
        host = self.walls.get(a['wall'].lstrip('@'))
        if not host:
            raise ValueError('host wall was not built')
        wall, w = host
        s, e = np.array(w['start'], float), np.array(w['end'], float)
        u = (e - s) / np.linalg.norm(e - s)
        n = np.array((-u[1], u[0]))
        t = w['thickness']
        o = s + u * a['along']
        z = w['base_z'] + a['sill']
        # the void: through the whole wall, a little proud of both faces
        b = ShapeBuilder(self.f)
        rect = b.polyline([(0, -t / 2 - .05), (a['width'], -t / 2 - .05), (a['width'], t / 2 + .05), (0, t / 2 + .05)], closed=True)
        rep = b.get_representation(self.body, [b.extrude(b.profile(rect), magnitude=a['height'])])
        op = ifcopenshell.api.root.create_entity(self.f, ifc_class='IfcOpeningElement', name=p['id'], predefined_type='OPENING')
        ifcopenshell.api.geometry.assign_representation(self.f, product=op, representation=rep)
        ifcopenshell.api.geometry.edit_object_placement(self.f, product=op, matrix=self.matrix((o[0], o[1], z), (u[0], u[1], 0)))
        ifcopenshell.api.feature.add_feature(self.f, feature=op, element=wall)
        door = a['kind'] == 'door'
        cls = 'IfcDoor' if door else 'IfcWindow'
        el = self.element(cls, a.get('name') or ('Door' if door else 'Window'), p['storey'], p, 'DOOR' if door else 'WINDOW')
        el.OverallWidth, el.OverallHeight = a['width'], a['height']
        if door:
            frep = ifcopenshell.api.geometry.add_door_representation(self.f, context=self.body, overall_height=a['height'], overall_width=a['width'], operation_type='SINGLE_SWING_LEFT')
        else:
            frep = ifcopenshell.api.geometry.add_window_representation(self.f, context=self.body, overall_height=a['height'], overall_width=a['width'], partition_type='SINGLE_PANEL')
        ifcopenshell.api.geometry.assign_representation(self.f, product=el, representation=frep)
        # the parametric frame is drawn from its origin into +Y: sit it in the wall's thickness
        fo = o - n * (t / 2)
        ifcopenshell.api.geometry.edit_object_placement(self.f, product=el, matrix=self.matrix((fo[0], fo[1], z), (u[0], u[1], 0)))
        ifcopenshell.api.feature.add_filling(self.f, opening=op, element=el)
        self.style(frep, cls)

    # ---- facts, site, IFC+SG ----------------------------------------------------------------
    def facts(self):
        for fct in self.d.get('facts', []):
            el = self.element_of(fct['proposal'])
            if el is None:
                continue
            value = fct['value']
            if fct['type'] == 'IfcBoolean':
                value = bool(value)
            pset = ifcopenshell.util.element.get_pset(el, fct['pset'], should_inherit=False)
            pset = self.f.by_id(pset['id']) if pset else ifcopenshell.api.pset.add_pset(self.f, product=el, name=fct['pset'])
            ifcopenshell.api.pset.edit_pset(self.f, pset=pset, properties={fct['property']: value})
            src = [x for x in pset.HasProperties if x.Name == fct['property']]
            for x in src:
                x.Description = f"{fct['source']}; {fct['method']} by {fct['by']}"[:250]
            if fct['property'] == 'Material' and isinstance(fct['value'], str):
                ifcopenshell.api.material.assign_material(self.f, products=[el], type='IfcMaterial', material=self.material(fct['value']))
            self.report['facts'] += 1

    def element_of(self, proposal_id):
        m = re.match(r'^(E-.+-(?:SPIR|SPRL|CWAL)-[0-9A-Z]+)-', proposal_id)
        if m and m.group(1) in self.assembled:
            return self.assembled[m.group(1)]
        for el in self.f.by_type('IfcElement'):
            ps = ifcopenshell.util.element.get_pset(el, 'Pset_OS_Provenance')
            if ps and ps.get('ProposalId') == proposal_id:
                return el
        return None

    def terrain(self):
        s = self.d.get('site')
        if not s or not s.get('triangles'):
            return
        P, base = s['points'], s['base']
        verts = [tuple(p) for p in P] + [(p[0], p[1], base) for p in P]
        n, faces, edges = len(P), [], {}
        for t in s['triangles']:
            a, b, c = t
            cr = (P[b][0] - P[a][0]) * (P[c][1] - P[a][1]) - (P[b][1] - P[a][1]) * (P[c][0] - P[a][0])
            if cr < 0:
                b, c = c, b
            faces.append([a, b, c]); faces.append([n + a, n + c, n + b])
            for e0, e1 in ((a, b), (b, c), (c, a)):
                edges.pop((e1, e0), None) if (e1, e0) in edges else edges.__setitem__((e0, e1), 1)
        for e0, e1 in edges:
            faces.append([e0, n + e0, n + e1, e1])
        el = ifcopenshell.api.root.create_entity(self.f, ifc_class='IfcGeographicElement', name='Terrain', predefined_type='TERRAIN')
        ifcopenshell.api.spatial.assign_container(self.f, products=[el], relating_structure=self.site)
        rep = ifcopenshell.api.geometry.add_mesh_representation(self.f, context=self.body, vertices=[verts], faces=[faces])
        ifcopenshell.api.geometry.assign_representation(self.f, product=el, representation=rep)
        ifcopenshell.api.geometry.edit_object_placement(self.f, product=el)
        pset = ifcopenshell.api.pset.add_pset(self.f, product=el, name='Pset_OS_Provenance')
        ifcopenshell.api.pset.edit_pset(self.f, pset=pset, properties={'Source': s.get('source') or 'spot levels', 'Evidence': f'{n} points, {len(s["triangles"])} triangles', 'ApprovalState': 'DRAFT - NOT APPROVED'})
        self.style(rep, 'IfcGeographicElement')
        self.report['built']['IfcGeographicElement'] = 1

    def ensure_sg(self, entity):
        """The bundled CORENET X mapping's fields, as empty placeholders (same rule as sg_defaults)."""
        subtype = ifcopenshell.util.element.get_predefined_type(entity) or ''
        rows = {}
        for row in self.sg:
            if not entity.is_a(row['ifc_class']):
                continue
            if 'N.A' not in row['subtypes'] and subtype not in [x.lstrip('*') for x in row['subtypes']]:
                continue
            rows[row['pset'], row['name']] = row
        existing = ifcopenshell.util.element.get_psets(entity, psets_only=True)
        added = 0
        for (pname, prop), row in rows.items():
            if prop in existing.get(pname, {}):
                continue
            info = ifcopenshell.util.element.get_pset(entity, pname, should_inherit=False)
            pset = self.f.by_id(info['id']) if info else ifcopenshell.api.pset.add_pset(self.f, product=entity, name=pname)
            field = self.f.create_entity('IfcPropertySingleValue', Name=prop, NominalValue=None,
                                         Description=f"IFC+SG 2025-12-04; {row['measure']}; source row {row['row']}; value required")
            pset.HasProperties = tuple(pset.HasProperties or ()) + (field,)
            existing.setdefault(pname, {})[prop] = None
            added += 1
        return added


def build(description):
    a = Author(description)
    return a.run(), a.report


def main(argv):
    if len(argv) != 3:
        print(__doc__)
        return 2
    d = json.loads(Path(argv[1]).read_text(encoding='utf-8'))
    f, rep = build(d)
    f.write(argv[2])
    print(json.dumps(rep, indent=1)[:4000])
    return 0


if __name__ == '__main__':
    import ifcopenshell.util.placement  # noqa: F401
    sys.exit(main(sys.argv))
