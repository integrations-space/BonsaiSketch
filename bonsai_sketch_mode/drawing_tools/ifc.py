# SPDX-License-Identifier: GPL-3.0-or-later
"""Build a separate IFC4 from a prepared recipe. Nothing touches an open model."""
import json
import math

import numpy as np
import ifcopenshell
import ifcopenshell.api as api
import ifcopenshell.guid
from shapely.geometry import Polygon

from .catalogue import GLASS_COLOURS


CLASSES = {
    'wall': ('IfcWall', 'STANDARD'), 'shelter': ('IfcWall', 'STANDARD'),
    'column': ('IfcColumn', 'COLUMN'), 'beam': ('IfcBeam', 'BEAM'),
    'slab': ('IfcSlab', 'FLOOR'), 'platform': ('IfcSlab', 'BASESLAB'),
    'foundation': ('IfcFooting', 'STRIP_FOOTING'), 'footing': ('IfcFooting', 'PAD_FOOTING'),
    'flat_roof': ('IfcRoof', 'FLAT_ROOF'), 'pitched_roof': ('IfcRoof', 'NOTDEFINED'),
    'ramp': ('IfcRampFlight', 'STRAIGHT'), 'stair': ('IfcStairFlight', 'STRAIGHT'),
    'door': ('IfcDoor', 'DOOR'), 'window': ('IfcWindow', 'WINDOW'),
    'terrain': ('IfcGeographicElement', 'TERRAIN'),
    'boundary': ('IfcAnnotation', None), 'setback': ('IfcAnnotation', None),
    'entrance': ('IfcAnnotation', None),
}


def positive(value, name):
    if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value) or value <= 0:
        raise ValueError(f'{name} must be positive finite metres')
    return float(value)


class Builder:
    def __init__(self, recipe):
        self.recipe = recipe
        self.f = api.run('project.create_file', version='IFC4')
        self.entities, self.materials = {}, {}

    def root(self, cls, name, predefined=None):
        return api.run('root.create_entity', self.f, ifc_class=cls, name=name, predefined_type=predefined)

    def run(self):
        if self.recipe.get('schema') != 'bonsai.building-recipe/1':
            raise ValueError('Expected a prepared building recipe')
        if any(f['severity'] == 'error' for f in self.recipe['findings']):
            raise ValueError('Resolve error findings before building the IFC')
        project = self.root('IfcProject', self.recipe['name'])
        units = [api.run('unit.add_si_unit', self.f, unit_type=t) for t in ('LENGTHUNIT', 'AREAUNIT', 'VOLUMEUNIT')]
        api.run('unit.assign_unit', self.f, units=units)
        model = api.run('context.add_context', self.f, context_type='Model')
        self.body = api.run('context.add_context', self.f, context_type='Model', context_identifier='Body', target_view='MODEL_VIEW', parent=model)
        self.reference = api.run('context.add_context', self.f, context_type='Model', context_identifier='Annotation', target_view='MODEL_VIEW', parent=model)
        site = self.root('IfcSite', 'Site')
        building = self.root('IfcBuilding', self.recipe['name'])
        api.run('aggregate.assign_object', self.f, products=[site], relating_object=project)
        api.run('aggregate.assign_object', self.f, products=[building], relating_object=site)
        self.site = site
        self.storeys, self.levels = {}, {}
        for s in self.recipe['storeys']:
            st = self.root('IfcBuildingStorey', s['name'])
            st.Elevation = float(s['elevation_m'])
            api.run('aggregate.assign_object', self.f, products=[st], relating_object=building)
            self.place(st, [0, 0, st.Elevation])
            self.storeys[s['name']], self.levels[s['name']] = st, st.Elevation
        components = self.recipe['components']
        ids = [c['id'] for c in components]
        if len(ids) != len(set(ids)):
            raise ValueError('Duplicate component IDs')
        # Hosted elements are always last, independent of source file order.
        for c in sorted(components, key=lambda c: c['kind'] in ('door', 'window')):
            try:
                self.component(c)
            except Exception as exc:
                raise ValueError(f"{c['id']}: {exc}") from exc
        return self.f

    def place(self, el, origin, angle=0, axis=None):
        m = np.eye(4)
        if len(origin) != 3 or not all(math.isfinite(v) for v in origin):
            raise ValueError('origin_m must contain three finite coordinates')
        if axis is not None:
            z = np.array(axis, dtype=float)
            if z.shape != (3,) or not np.all(np.isfinite(z)) or np.linalg.norm(z) == 0:
                raise ValueError('axis must be a nonzero finite XYZ vector')
            z /= np.linalg.norm(z)
            ref = np.array([0., 1., 0.]) if abs(z[2]) > .9 else np.array([0., 0., 1.])
            x = np.cross(ref, z); x /= np.linalg.norm(x)
            m[:3, 0], m[:3, 1], m[:3, 2] = x, np.cross(z, x), z
        else:
            if not math.isfinite(angle):
                raise ValueError('rotation_deg must be finite')
            a = math.radians(angle)
            m[:3, :3] = [[math.cos(a), -math.sin(a), 0], [math.sin(a), math.cos(a), 0], [0, 0, 1]]
        m[:3, 3] = origin
        api.run('geometry.edit_object_placement', self.f, product=el, matrix=m, is_si=True)

    def polyline(self, points, close=True):
        points = [list(map(float, p)) for p in points]
        if close and points[0] != points[-1]:
            points.append(points[0])
        return self.f.create_entity('IfcPolyline', Points=[self.f.create_entity('IfcCartesianPoint', Coordinates=p) for p in points])

    def profile(self, c):
        if 'radius_m' in c:
            return self.f.create_entity('IfcCircleProfileDef', ProfileType='AREA', Radius=positive(c['radius_m'], 'radius_m'))
        p = c['profile']
        poly = Polygon(p['outer'], p.get('holes', []))
        if poly.is_empty or not poly.is_valid or poly.area <= 1e-10:
            raise ValueError('Invalid, crossing or zero-area profile')
        outer = self.polyline(p['outer'])
        holes = p.get('holes', [])
        if holes:
            return self.f.create_entity('IfcArbitraryProfileDefWithVoids', ProfileType='AREA', OuterCurve=outer,
                                        InnerCurves=[self.polyline(h) for h in holes])
        return self.f.create_entity('IfcArbitraryClosedProfileDef', ProfileType='AREA', OuterCurve=outer)

    def extrude(self, profile, depth, position=(0, 0, 0)):
        return self.f.create_entity('IfcExtrudedAreaSolid', SweptArea=profile,
                                    Position=self.f.create_entity('IfcAxis2Placement3D', Location=self.f.create_entity('IfcCartesianPoint', Coordinates=list(map(float, position)))),
                                    ExtrudedDirection=self.f.create_entity('IfcDirection', DirectionRatios=[0., 0., 1.]),
                                    Depth=positive(depth, 'extrusion depth'))

    def box(self, x, y, width, depth, height, z=0):
        profile = self.profile({'profile': {'outer': [[x,y], [x+width,y], [x+width,y+depth], [x,y+depth]]}})
        return self.extrude(profile, height, [0, 0, z])

    def representation(self, el, items, kind='SweptSolid', context=None):
        rep = self.f.create_entity('IfcShapeRepresentation', ContextOfItems=context or self.body,
                                   RepresentationIdentifier='Annotation' if context else 'Body', RepresentationType=kind, Items=items)
        api.run('geometry.assign_representation', self.f, product=el, representation=rep)
        return rep

    def material(self, el, names):
        materials = []
        for name in names:
            if not name:
                continue
            if name not in self.materials:
                self.materials[name] = api.run('material.add_material', self.f, name=name)
            materials.append(self.materials[name])
        if len(materials) == 1:
            api.run('material.assign_material', self.f, products=[el], type='IfcMaterial', material=materials[0])
        elif materials:
            ms = api.run('material.add_material_set', self.f, name=el.Name, set_type='IfcMaterialConstituentSet')
            for m in materials:
                api.run('material.add_constituent', self.f, constituent_set=ms, material=m, name=m.Name)
            api.run('material.assign_material', self.f, products=[el], type='IfcMaterialConstituentSet', material=ms)

    def style(self, item, colour, transparency=0):
        st = api.run('style.add_style', self.f)
        api.run('style.add_surface_style', self.f, style=st, ifc_class='IfcSurfaceStyleShading',
                attributes={'SurfaceColour': dict(zip(('Red', 'Green', 'Blue'), colour)), 'Transparency': transparency})
        api.run('style.assign_item_style', self.f, item=item, style=st)

    def component(self, c):
        kind = c['kind']
        cls, predefined = CLASSES[kind]
        el = self.root(cls, c.get('name', c['id']), predefined)
        # Deterministic identity across rebuilds; project name forms a namespace.
        import uuid
        el.GlobalId = ifcopenshell.guid.compress(uuid.uuid5(uuid.NAMESPACE_URL, self.recipe['name'] + '/' + c['id']).hex)
        self.entities[c['id']] = el
        container = self.storeys[c['storey']] if c.get('storey') else self.site
        api.run('spatial.assign_container', self.f, products=[el], relating_structure=container)
        origin = list(c.get('origin_m', [0, 0, 0]))
        if len(origin) != 3:
            raise ValueError('origin_m needs XYZ')
        origin[2] += self.levels.get(c.get('storey'), 0)
        self.place(el, origin, c.get('rotation_deg', 0), c.get('axis'))
        if kind in ('boundary', 'setback', 'entrance'):
            items = [self.polyline(p['points'], p.get('closed', False)) for p in c['polylines']]
            self.representation(el, items, 'GeometricCurveSet', self.reference)
        elif kind in ('door', 'window'):
            self.opening(el, c, origin)
        elif kind in ('ramp', 'pitched_roof', 'terrain'):
            self.mesh(el, c)
        elif kind == 'stair':
            count = c['risers']
            if isinstance(count, bool) or not isinstance(count, int) or count < 2:
                raise ValueError('Stair needs at least two integer risers')
            rise = positive(c['rise_m'], 'rise_m') / count
            tread = positive(c['tread_m'], 'tread_m')
            width = positive(c['width_m'], 'width_m')
            # The destination landing is the final tread, supplied as a slab.
            items = [self.box(i*tread, 0, tread, width, (i+1)*rise) for i in range(count-1)]
            self.representation(el, items)
            el.NumberOfRisers, el.NumberOfTreads, el.RiserHeight, el.TreadLength = count, count-1, rise, tread
        else:
            self.representation(el, [self.extrude(self.profile(c), c['height_m'])])
        self.material(el, [c.get('frame_material'), c.get('material')] if kind == 'window' else [c.get('material')])
        ps = api.run('pset.add_pset', self.f, product=el, name='Pset_SketchRecipe')
        api.run('pset.edit_pset', self.f, pset=ps, properties={'ComponentId': c['id'], 'Parameters': json.dumps(c, sort_keys=True),
                                                            'Status': 'DRAFT', 'DefaultedFields': ', '.join(c.get('defaulted_fields', []))})
        if 'fire_rating' in c and kind in ('door', 'window'):
            ps = api.run('pset.add_pset', self.f, product=el, name=f'Pset_{cls[3:]}Common')
            api.run('pset.edit_pset', self.f, pset=ps, properties={'FireRating': str(c['fire_rating'])})

    def mesh(self, el, c):
        vertices = c['vertices_m']
        faces = c['faces']
        if not vertices or not faces or any(len(v) != 3 or not all(math.isfinite(x) for x in v) for v in vertices):
            raise ValueError('Mesh needs finite XYZ vertices and faces')
        for face in faces:
            if len(face) < 3 or len(set(face)) != len(face) or any(isinstance(i, bool) or not isinstance(i, int) or i < 0 or i >= len(vertices) for i in face):
                raise ValueError('Invalid mesh face indices')
            pts = np.array([vertices[i] for i in face], dtype=float)
            normal = np.cross(pts[1]-pts[0], pts[2]-pts[0])
            if np.linalg.norm(normal) < 1e-10 or np.max(np.abs((pts-pts[0]) @ normal)) > 1e-7 * np.linalg.norm(normal):
                raise ValueError('Faces must be nondegenerate and planar; triangulate undulating surfaces')
        rep = api.run('geometry.add_mesh_representation', self.f, context=self.body, vertices=[vertices], faces=[faces])
        api.run('geometry.assign_representation', self.f, product=el, representation=rep)

    def opening(self, el, c, origin):
        host = self.entities[c['host']]
        if not host.is_a('IfcWall'):
            raise ValueError('Opening host must be a wall')
        w, h = positive(c['width_m'], 'width_m'), positive(c['height_m'], 'height_m')
        depth = positive(c['host_depth_m'], 'host_depth_m')
        op = self.root('IfcOpeningElement', c['id'] + '/void', 'OPENING')
        self.representation(op, [self.box(0, -0.01, w, depth+0.02, h)])
        self.place(op, origin, c.get('rotation_deg', 0))
        api.run('feature.add_feature', self.f, feature=op, element=host)
        if c['kind'] == 'window':
            f, d, g = c['frame_width_m'], c['frame_depth_m'], c['glass_thickness_m']
            if 2*f >= min(w, h) or g > d:
                raise ValueError('Window frame/glass dimensions do not fit')
            items = [self.box(0,0,f,d,h), self.box(w-f,0,f,d,h),
                     self.box(f,0,w-2*f,d,f), self.box(f,0,w-2*f,d,f,z=h-f)]
            glass = self.box(f,(d-g)/2,w-2*f,g,h-2*f,z=f)
            for item in items:
                self.style(item, (.55,.55,.57))
            self.style(glass, GLASS_COLOURS[c['glass_colour']], .75)
            self.representation(el, items + [glass])
        else:
            rep = api.run('geometry.add_door_representation', self.f, context=self.body, overall_width=w, overall_height=h,
                          operation_type=c.get('operation', 'SINGLE_SWING_LEFT'), panel_properties={'PanelDepth': c['panel_depth_m']})
            if rep is None:
                raise ValueError('Door representation could not be created')
            api.run('geometry.assign_representation', self.f, product=el, representation=rep)
        el.OverallWidth, el.OverallHeight = w, h
        api.run('feature.add_filling', self.f, opening=op, element=el)


def build(recipe):
    return Builder(recipe).run()
