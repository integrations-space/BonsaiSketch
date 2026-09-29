# SPDX-License-Identifier: GPL-3.0-or-later
"""Regression checks against independent geometry and IFC relationships."""
import copy
import json
from pathlib import Path
import sys
import tempfile
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'bonsai_sketch_mode'))
from drawing_tools.repair import repair
from drawing_tools.catalogue import resolve
from drawing_tools.project import prepare
from drawing_tools.ifc import build
from drawing_tools.checks import check
from drawing_tools.shapes import sloping_slab, terrain
import ifcopenshell.geom
import ifcopenshell.util.shape
import ifcopenshell.util.element
import ifcopenshell.validate
from shapely.geometry import Polygon


def rectangle(x, y, w, d):
    return {'outer': [[x,y],[x+w,y],[x+w,y+d],[x,y+d]]}


def sample():
    evidence = {'plan': 'A101', 'section': 'A301', 'elevation': 'A201'}
    return {'schema': 'bonsai.drawing-project/1', 'name': 'Pipeline regression',
            'storeys': [{'name': 'Basement', 'elevation_m': -3}, {'name': 'L1', 'elevation_m': 0}, {'name': 'L2', 'elevation_m': 3}],
            'components': [
                {'id':'wall', 'kind':'wall', 'storey':'L1', 'height_m':3, 'profile':rectangle(0,0,6,.2), 'evidence':evidence},
                {'id':'door', 'kind':'door', 'storey':'L1', 'host':'wall', 'host_depth_m':.2, 'width_m':.9, 'origin_m':[1,0,0], 'evidence':evidence},
                {'id':'window', 'kind':'window', 'storey':'L1', 'host':'wall', 'host_depth_m':.2, 'width_m':1.2, 'height_m':1.2, 'origin_m':[3,0,1], 'evidence':evidence},
                {'id':'slab', 'kind':'slab', 'storey':'L2', 'height_m':.2, 'profile':dict(rectangle(0,0,6,5), holes=[rectangle(2,2,1,1)['outer']]), 'evidence':evidence},
                {'id':'column', 'kind':'column', 'storey':'Basement', 'height_m':3, 'radius_m':.15, 'origin_m':[0,3,0], 'evidence':evidence},
                {'id':'beam', 'kind':'beam', 'storey':'L1', 'height_m':4, 'profile':rectangle(-.1,-.2,.2,.4), 'origin_m':[0,3,2.8], 'axis':[1,0,0], 'evidence':evidence},
                {'id':'footing', 'kind':'footing', 'storey':'Basement', 'height_m':.4, 'profile':rectangle(-.5,2.5,1,1), 'origin_m':[0,0,-.4], 'evidence':evidence},
                {'id':'stair', 'kind':'stair', 'storey':'L1', 'risers':18, 'rise_m':3, 'tread_m':.25, 'width_m':1, 'origin_m':[0,6,0], 'evidence':evidence},
                {'id':'ramp', 'kind':'ramp', 'storey':'L1', 'shape':{'type':'sloping_slab', 'length_m':4, 'width_m':3, 'thickness_m':.2, 'rise_m':.5}, 'origin_m':[0,-5,0], 'evidence':evidence},
                {'id':'roof', 'kind':'pitched_roof', 'storey':'L2', 'shape':{'type':'sloping_slab', 'length_m':3, 'width_m':5, 'thickness_m':.2, 'rise_m':1}, 'origin_m':[0,0,3], 'material':'Roof tiles', 'evidence':evidence},
                {'id':'terrain', 'kind':'terrain', 'shape':{'type':'terrain', 'points':[[0,0,0],[10,0,.5],[10,10,1],[0,10,.2],[5,5,.4]], 'boundary':[[0,0],[10,0],[10,10],[0,10]]}, 'evidence':evidence},
                {'id':'boundary', 'kind':'boundary', 'polylines':[{'points':[[0,0],[10,0],[10,10],[0,10]], 'closed':True}], 'evidence':evidence},
            ]}


class RepairTests(unittest.TestCase):
    def test_multiple_small_gaps(self):
        r = repair([{'points':[[0,0],[2,0]]}, {'points':[[2,.01],[2,2]]},
                    {'points':[[1.99,2],[0,2]]}, {'points':[[0,1.99],[0,.01]]}], .02)
        self.assertTrue(r['ready'])
        self.assertEqual(len(r['bridges']), 4)
        self.assertAlmostEqual(Polygon(r['profiles'][0]['outer']).area, 4, places=3)

    def test_large_gap_remains(self):
        r = repair([{'points':[[0,0],[2,0],[2,2],[0,2],[0,.9]]}], .02)
        self.assertFalse(r['ready'])
        self.assertFalse(r['bridges'])

    def test_hole_preserved(self):
        r = repair([{'points':rectangle(0,0,5,5)['outer'], 'closed':True},
                    {'points':rectangle(1,1,3,3)['outer'], 'closed':True}])
        self.assertEqual(len(r['profiles']), 1)
        p = r['profiles'][0]
        self.assertAlmostEqual(Polygon(p['outer'], p['holes']).area, 16)

    def test_crossing_rejected(self):
        r = repair([{'points':[[0,0],[2,2],[0,2],[2,0]], 'closed':True}])
        self.assertFalse(r['ready'])
        self.assertEqual(r['invalid_polylines'], [0])

    def test_ambiguous_neighbours(self):
        r = repair([{'points':[[0,0],[1,0]]}, {'points':[[1.01,0],[2,0]]},
                    {'points':[[1,.01],[1,2]]}], .02)
        self.assertTrue(r['ambiguous_endpoints'])
        self.assertFalse(r['bridges'])


class RecipeTests(unittest.TestCase):
    def test_schedule_conflict_and_rating(self):
        c, findings = resolve({'kind':'door', 'height_m':2.1, 'schedule_tag':'D1'},
                              {'D1':{'kind':'door', 'source':'A601', 'height_m':2.4, 'fire_rating':'60 min'}})
        self.assertEqual(c['height_m'], 2.4)
        self.assertEqual(c['fire_rating'], '60 min')
        self.assertEqual(findings[0]['code'], 'SCHEDULE_CONFLICT')

    def test_full_height_requires_clearance(self):
        with self.assertRaises(ValueError):
            resolve({'kind':'door', 'height_m':'full_height'})
        c, _ = resolve({'kind':'door', 'height_m':'full_height', 'clear_height_m':2.7})
        self.assertEqual(c['height_m'], 2.7)

    def test_window_defaults(self):
        c, findings = resolve({'kind':'window'})
        self.assertEqual((c['frame_width_m'],c['frame_depth_m'],c['glass_thickness_m']), (.05,.05,.012))
        self.assertNotIn('fire_rating', c)
        self.assertTrue(findings)

    def test_unresolved_layer_blocks_build(self):
        recipe = prepare(sample(), '.')
        recipe['findings'].append({'severity':'error','code':'LINEWORK_UNRESOLVED'})
        with self.assertRaises(ValueError):
            build(recipe)

    def test_dxf_alignment_units_and_provenance(self):
        # Real DXF input: four independent lines in millimetres.
        pairs = [(0,'SECTION'),(2,'ENTITIES')]
        pts = [[0,0],[2000,0],[2000,200],[0,200],[0,0]]
        for a,b in zip(pts,pts[1:]):
            pairs += [(0,'LINE'),(8,'WALL'),(10,a[0]),(20,a[1]),(11,b[0]),(21,b[1])]
        pairs += [(0,'ENDSEC'),(0,'EOF')]
        with tempfile.TemporaryDirectory() as tmp:
            Path(tmp,'plan.dxf').write_text('\n'.join(str(v) for pair in pairs for v in pair)+'\n')
            m = {'schema':'bonsai.drawing-project/1','storeys':[{'name':'L1','elevation_m':0}],
                 'drawings':[{'id':'P1','path':'plan.dxf','scale_to_m':.001,'offset_m':[10,20]}],
                 'layers':[{'id':'walls','drawing':'P1','layer':'WALL','kind':'wall','storey':'L1','height_m':3}]}
            recipe = prepare(m,tmp)
            c = recipe['components'][0]
            self.assertEqual(Polygon(c['profile']['outer']).bounds, (10,20,12,20.2))
            self.assertEqual(len(c['evidence']['sha256']),64)
            self.assertFalse(recipe['findings'])

    def test_skipped_geometry_is_attributed_to_layer(self):
        from drawing_tools.project import _reader
        drawing = _reader().parse('0\nSECTION\n2\nENTITIES\n0\nHATCH\n8\nWALLS\n0\nSPLINE\n8\nNOTES\n0\nENDSEC\n0\nEOF\n')
        self.assertEqual(drawing.skipped_by_layer, {'WALLS':{'HATCH':1}, 'NOTES':{'SPLINE':1}})
        self.assertEqual(drawing.skipped, {'HATCH':1, 'SPLINE':1})

    def test_block_references_on_a_mapped_layer_are_flagged(self):
        # The reader keeps INSERTs as symbols, but a recipe cannot build from them.
        pairs = [(0,'SECTION'),(2,'ENTITIES'),
                 (0,'LINE'),(8,'WALL'),(10,0),(20,0),(11,2000),(21,0),
                 (0,'INSERT'),(8,'WALL'),(2,'COLUMN'),(10,0),(20,0),(0,'ENDSEC'),(0,'EOF')]
        with tempfile.TemporaryDirectory() as tmp:
            Path(tmp,'plan.dxf').write_text('\n'.join(str(v) for pair in pairs for v in pair)+'\n')
            m = {'schema':'bonsai.drawing-project/1','storeys':[{'name':'L1','elevation_m':0}],
                 'drawings':[{'id':'P1','path':'plan.dxf','scale_to_m':.001}],
                 'layers':[{'id':'walls','drawing':'P1','layer':'WALL','kind':'wall','storey':'L1','height_m':3}]}
            findings = prepare(m,tmp)['findings']
            self.assertIn({'code':'LAYER_GEOMETRY_SKIPPED','severity':'error','component':'walls',
                           'entities':{'INSERT':1}}, findings)

    def test_terrain_requires_known_boundary_heights(self):
        with self.assertRaises(ValueError):
            terrain([[0,0,0],[1,0,0],[1,1,1]], [[0,0],[1,0],[1,1],[0,1]])

    def test_negative_slope_preserves_thickness(self):
        shape = sloping_slab(5,2,.2,-1)
        self.assertEqual(len(shape['faces']),6)
        for a,b in zip(shape['vertices_m'][:4],shape['vertices_m'][4:]):
            self.assertAlmostEqual(b[2]-a[2],.2)


class IFCTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.recipe = prepare(sample(), '.')
        cls.model = build(cls.recipe)

    def test_schema_and_geometry(self):
        logger = ifcopenshell.validate.json_logger()
        ifcopenshell.validate.validate(self.model, logger)
        self.assertEqual(logger.statements, [])
        self.assertEqual(check(self.model), [])

    def test_voids_change_wall_volume(self):
        wall = self.model.by_type('IfcWall')[0]
        sh = ifcopenshell.geom.create_shape(ifcopenshell.geom.settings(),wall)
        volume = ifcopenshell.util.shape.get_volume(sh.geometry)
        self.assertAlmostEqual(volume, 6*.2*3-.9*.2*2.1-1.2*.2*1.2, places=5)
        self.assertEqual(len(wall.HasOpenings),2)

    def test_slab_hole_and_storey(self):
        slab = self.model.by_type('IfcSlab')[0]
        settings = ifcopenshell.geom.settings(); settings.set(settings.USE_WORLD_COORDS,True)
        sh = ifcopenshell.geom.create_shape(settings,slab)
        self.assertAlmostEqual(ifcopenshell.util.shape.get_volume(sh.geometry),29*.2,places=5)
        self.assertAlmostEqual(min(sh.geometry.verts[2::3]),3)

    def test_separate_glass(self):
        window = self.model.by_type('IfcWindow')[0]
        items = window.Representation.Representations[0].Items
        self.assertEqual(len(items),5)
        glass = items[-1]
        xy = [p.Coordinates for p in glass.SweptArea.OuterCurve.Points]
        self.assertAlmostEqual(max(p[1] for p in xy)-min(p[1] for p in xy), .012)
        self.assertEqual(glass.StyledByItem[0].Styles[0].Styles[0].Transparency,.75)

    def test_rebuild_identity(self):
        rebuilt = build(self.recipe)
        original = {e.Name:e.GlobalId for e in self.model.by_type('IfcElement') if not e.is_a('IfcOpeningElement')}
        repeat = {e.Name:e.GlobalId for e in rebuilt.by_type('IfcElement') if not e.is_a('IfcOpeningElement')}
        self.assertEqual(original,repeat)

    def test_missing_host_detected(self):
        m = sample(); m['components'][1]['origin_m']=[30,0,0]
        model = build(prepare(m,'.'))
        self.assertTrue(any(f['code']=='OPENING_MISSES_HOST' for f in check(model)))


if __name__ == '__main__':
    unittest.main()
