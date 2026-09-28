# SPDX-License-Identifier: GPL-3.0-or-later
"""Rules that read a finished IFC and say what is missing or wrong - it repairs nothing.

    python bonsai_sketch_mode/modelcheck.py model.ifc report.json [plan.png]

Every rule reads the IFC only (the deliverable), never the tool that made it, so it checks an
automated model and a hand-made one the same way. Findings carry a code, the storey, the element
and, where there is one, a plan location, so a person can walk to each.

  ENVELOPE_OPEN      a stretch of a storey's floor edge with no wall, curtain wall, window, door,
                     railing or column standing on it (walked every 0.25 m, 0.35 m reach)
  STOREY_EMPTY_BAND  a storey whose walls stop well short of the floor above
  NO_MATERIAL        a physical element with no material at all
  MATERIAL_UNCONFIRMED  a material named as unconfirmed (the drawings gave a thickness, not a build-up)
  MATERIAL_IMPLAUSIBLE  glass on a solid wall, slab or column; a curtain wall or window with no glass
  LAYER_THICKNESS    a wall whose layer set is thicker or thinner than its geometry by > 10 mm
  EXTERNAL_MISMATCH  IsExternal says external for a wall away from the envelope, or internal on it
  UNFILLED_OPENING   a void with no door or window in it; a door or window filling no void
  OPENING_SIZE       a door narrower than 0.6 m or wider than 2.6 m; a window under 0.3 m
  OUTSIDE_STOREY     an element whose geometry sits below its storey or above the next one
  SG_EMPTY           (summary) IFC+SG fields still empty, per class
"""
import collections
import json
import math
import sys

import numpy as np
import ifcopenshell
import ifcopenshell.geom
import ifcopenshell.util.element as ue
from shapely.geometry import Polygon, Point, LineString
from shapely.ops import unary_union

ENVELOPE = ('IfcWall', 'IfcCurtainWall', 'IfcWindow', 'IfcDoor', 'IfcRailing', 'IfcColumn', 'IfcPlate', 'IfcMember')
NEEDS_MATERIAL = ('IfcWall', 'IfcSlab', 'IfcColumn', 'IfcBeam', 'IfcRoof', 'IfcCurtainWall', 'IfcRailing', 'IfcStair', 'IfcDoor', 'IfcWindow')
SOLID = ('IfcWall', 'IfcSlab', 'IfcColumn', 'IfcBeam')


def footprints(f):
    """World-space plan footprint and z range of every product, from the geometry engine."""
    s = ifcopenshell.geom.settings()
    s.set(s.USE_WORLD_COORDS, True)
    it = ifcopenshell.geom.iterator(s, f, 1)
    out = {}
    if it.initialize():
        while True:
            sh = it.get()
            v = np.array(sh.geometry.verts).reshape(-1, 3)
            fa = np.array(sh.geometry.faces).reshape(-1, 3)
            if len(v) and len(fa):
                tris = [Polygon(v[t, :2]) for t in fa]
                tris = [t for t in tris if t.is_valid and t.area > 1e-8]
                fp = unary_union(tris).buffer(0) if tris else None
                out[sh.id] = {'fp': fp, 'z': (float(v[:, 2].min()), float(v[:, 2].max()))}
            if not it.next():
                break
    return out


def materials_of(el):
    m = ue.get_material(el, should_skip_usage=True)
    if m is None:
        return []
    if m.is_a('IfcMaterial'):
        return [m.Name or '']
    if m.is_a('IfcMaterialLayerSet'):
        return [l.Material.Name or '' for l in m.MaterialLayers if l.Material]
    if m.is_a('IfcMaterialConstituentSet'):
        return [c.Material.Name or '' for c in m.MaterialConstituents or () if c.Material]
    if m.is_a('IfcMaterialList'):
        return [x.Name or '' for x in m.Materials]
    if m.is_a('IfcMaterialProfileSet'):
        return [p.Material.Name or '' for p in m.MaterialProfiles if p.Material]
    return []


def check(path):
    f = ifcopenshell.open(path)
    geo = footprints(f)
    storeys = sorted(f.by_type('IfcBuildingStorey'), key=lambda s: s.Elevation or 0)
    elev = [s.Elevation or 0 for s in storeys]
    find, summary = [], collections.OrderedDict()

    def add(code, storey, el, msg, at=None):
        find.append({'code': code, 'storey': storey, 'element': (el.is_a() + ' ' + (el.Name or '') + ' ' + el.GlobalId) if el else None,
                     'message': msg, 'at': [round(at[0], 2), round(at[1], 2)] if at else None})

    container = {}
    for s in storeys:
        for el in ue.get_decomposition(s):
            container[el.id()] = s

    # ---- envelope, per storey -----------------------------------------------------------------
    open_lines = collections.defaultdict(list)
    for i, s in enumerate(storeys):
        els = [e for e in ue.get_decomposition(s) if e.is_a('IfcElement')]
        floors = [geo[e.id()]['fp'] for e in els if e.id() in geo and (e.is_a('IfcSlab') or e.is_a('IfcRoof')) and geo[e.id()]['fp'] is not None]
        if not floors:
            summary.setdefault('envelope', {})[s.Name] = 'no floor or roof element to take an edge from'
            continue
        floor = unary_union(floors).buffer(0)
        top = elev[i + 1] if i + 1 < len(elev) else elev[i] + 1.2
        band = (elev[i] + .3, max(elev[i] + .8, top - .5))
        # what stands on the edge: envelope elements of this storey reaching into the band
        stand = [geo[e.id()]['fp'] for e in els if e.id() in geo and e.is_a() in ENVELOPE and geo[e.id()]['fp'] is not None
                 and geo[e.id()]['z'][1] > band[0] and geo[e.id()]['z'][0] < band[1]]
        standing = unary_union(stand).buffer(.35) if stand else None
        rings = [floor.exterior] if floor.geom_type == 'Polygon' else [p.exterior for p in floor.geoms]
        total = covered = 0.0
        for ring in rings:
            L = ring.length
            n = max(4, int(L / .25))
            run = []
            for k in range(n + 1):
                p = ring.interpolate(k * L / n)
                ok = standing is not None and standing.contains(p)
                total += L / n
                covered += L / n if ok else 0
                if not ok:
                    run.append((p.x, p.y))
                elif run:
                    open_lines[s.Name].append(run); run = []
            run and open_lines[s.Name].append(run)
        pct = round(100 * covered / total, 1) if total else 0
        summary.setdefault('envelope', {})[s.Name] = f'{pct}% of {round(total, 1)} m of floor edge enclosed'
        for run in open_lines[s.Name]:
            length = LineString(run).length if len(run) > 1 else 0
            if length >= 1.0:
                mid = run[len(run) // 2]
                add('ENVELOPE_OPEN', s.Name, None, f'{round(length, 1)} m of floor edge with nothing standing on it', mid)
        # walls stopping short of the floor above
        walls = [geo[e.id()]['z'][1] for e in els if e.is_a('IfcWall') and e.id() in geo]
        if i + 1 < len(elev) and walls:
            reach = sorted(walls)[int(len(walls) * .9)]
            if reach < elev[i + 1] - .6:
                add('STOREY_EMPTY_BAND', s.Name, None, f'90% of walls stop by {round(reach, 2)}; the floor above is at {elev[i + 1]}')

    # ---- materials -----------------------------------------------------------------------------
    for el in f.by_type('IfcElement'):
        cls = el.is_a()
        if cls not in NEEDS_MATERIAL:
            continue
        st = container.get(el.id())
        names = [n for n in materials_of(el) if n is not None]
        c = geo.get(el.id())
        at = tuple(c['fp'].centroid.coords[0]) if c and c['fp'] is not None else None
        if not names:
            add('NO_MATERIAL', st.Name if st else None, el, 'no material assigned', at)
            continue
        if any('confirm' in n.lower() or n.strip() == '' for n in names):
            add('MATERIAL_UNCONFIRMED', st.Name if st else None, el, 'material: ' + ', '.join(names), at)
        glassy = any('glass' in n.lower() or 'glaz' in n.lower() for n in names)
        if cls in SOLID and glassy:
            add('MATERIAL_IMPLAUSIBLE', st.Name if st else None, el, f'glass on a {cls[3:]}: ' + ', '.join(names), at)
        if cls in ('IfcCurtainWall', 'IfcWindow') and not glassy and not any('confirm' in n.lower() for n in names):
            add('MATERIAL_IMPLAUSIBLE', st.Name if st else None, el, f'a {cls[3:]} with no glass: ' + ', '.join(names), at)
        # layer set against the drawn thickness
        if cls == 'IfcWall' and c and c['fp'] is not None:
            m = ue.get_material(el)
            if m is not None and m.is_a('IfcMaterialLayerSetUsage'):
                t_layers = sum(l.LayerThickness for l in m.ForLayerSet.MaterialLayers)
                mrr = c['fp'].minimum_rotated_rectangle
                xy = list(mrr.exterior.coords)
                sides = sorted(math.dist(xy[k], xy[k + 1]) for k in range(2))
                if abs(sides[0] - t_layers) > .010 and sides[0] < 1.0:
                    add('LAYER_THICKNESS', st.Name if st else None, el, f'layers {round(t_layers * 1000)} mm, geometry {round(sides[0] * 1000)} mm', at)

    # ---- IsExternal against the envelope ------------------------------------------------------
    for i, s in enumerate(storeys):
        floors = [geo[e.id()]['fp'] for e in ue.get_decomposition(s) if e.id() in geo and (e.is_a('IfcSlab') or e.is_a('IfcRoof')) and geo[e.id()]['fp'] is not None]
        if not floors:
            continue
        edge = unary_union(floors).buffer(0).boundary
        for el in ue.get_decomposition(s):
            if not el.is_a('IfcWall') or el.id() not in geo or geo[el.id()]['fp'] is None:
                continue
            ext = (ue.get_pset(el, 'Pset_WallCommon') or {}).get('IsExternal')
            if ext is None:
                continue
            near = geo[el.id()]['fp'].distance(edge) <= .4
            if bool(ext) != near:
                add('EXTERNAL_MISMATCH', s.Name, el, f'IsExternal={ext} but the wall is {"on" if near else "away from"} the floor edge',
                    tuple(geo[el.id()]['fp'].centroid.coords[0]))

    # ---- openings -------------------------------------------------------------------------------
    for op in f.by_type('IfcOpeningElement'):
        if not op.HasFillings:
            add('UNFILLED_OPENING', container.get(op.VoidsElements[0].RelatingBuildingElement.id()).Name if op.VoidsElements else None, op, 'a void with no door or window')
    for el in f.by_type('IfcDoor') + f.by_type('IfcWindow'):
        st = container.get(el.id())
        if not el.FillsVoids:
            add('UNFILLED_OPENING', st.Name if st else None, el, 'fills no void in a wall')
        w = el.OverallWidth or 0
        if el.is_a('IfcDoor') and (w < .6 or w > 2.6):
            add('OPENING_SIZE', st.Name if st else None, el, f'door {round(w, 2)} m wide')
        if el.is_a('IfcWindow') and w < .3:
            add('OPENING_SIZE', st.Name if st else None, el, f'window {round(w, 2)} m wide')

    # ---- storey fit -----------------------------------------------------------------------------
    for el in f.by_type('IfcElement'):
        st, c = container.get(el.id()), geo.get(el.id())
        if not st or not c or el.is_a('IfcGeographicElement') or el.is_a('IfcOpeningElement'):
            continue
        i = storeys.index(st)
        nxt = elev[i + 1] if i + 1 < len(elev) else elev[i] + 6
        if c['z'][0] < elev[i] - .5 or c['z'][1] > nxt + 1.5:
            add('OUTSIDE_STOREY', st.Name, el, f'geometry z {round(c["z"][0], 2)}..{round(c["z"][1], 2)} against storey {elev[i]}..{nxt}')

    # ---- IFC+SG fields still empty ---------------------------------------------------------------
    sg = collections.Counter()
    for el in f.by_type('IfcElement'):
        for name, props in ue.get_psets(el).items():
            if name.startswith('SGPset_') or name.startswith('Pset_'):
                sg[el.is_a()] += sum(1 for k, v in props.items() if k != 'id' and v is None)
    summary['sg_empty_fields'] = dict(sg)
    summary['by_code'] = dict(collections.Counter(x['code'] for x in find))
    return {'file': path, 'summary': summary, 'findings': find, 'open_edges': {k: v for k, v in open_lines.items()}}, geo, f


def plan(report, geo, f, out):
    """One small plan per storey: floor edge grey, what stands on it black, open stretches red."""
    import matplotlib
    matplotlib.use('Agg')
    import matplotlib.pyplot as plt
    storeys = sorted(f.by_type('IfcBuildingStorey'), key=lambda s: s.Elevation or 0)
    fig, axes = plt.subplots(1, len(storeys), figsize=(5 * len(storeys), 5.6))
    for ax, s in zip(np.atleast_1d(axes), storeys):
        for el in ue.get_decomposition(s):
            c = geo.get(el.id())
            if not c or c['fp'] is None:
                continue
            geoms = [c['fp']] if c['fp'].geom_type == 'Polygon' else list(getattr(c['fp'], 'geoms', []))
            for g in geoms:
                if g.geom_type != 'Polygon':
                    continue
                x, y = g.exterior.xy
                if el.is_a('IfcSlab') or el.is_a('IfcRoof'):
                    ax.fill(x, y, color='#e7e3dc', lw=.3, ec='#999')
                elif el.is_a() in ENVELOPE:
                    ax.fill(x, y, color='#222' if el.is_a() != 'IfcCurtainWall' else '#4a90c8', lw=0)
        for run in report['open_edges'].get(s.Name, []):
            if len(run) > 1:
                xs, ys = zip(*run)
                ax.plot(xs, ys, color='#d62728', lw=3)
        ax.set_title(f'{s.Name}  {report["summary"]["envelope"].get(s.Name, "")}', fontsize=8)
        ax.set_aspect('equal'); ax.axis('off')
    fig.tight_layout(); fig.savefig(out, dpi=110); plt.close(fig)


def main(argv):
    if len(argv) < 3:
        print(__doc__)
        return 2
    rep, geo, f = check(argv[1])
    open(argv[2], 'w', encoding='utf-8').write(json.dumps(rep, indent=1))
    if len(argv) > 3:
        plan(rep, geo, f, argv[3])
    print(json.dumps(rep['summary'], indent=1))
    return 1 if rep['findings'] else 0


if __name__ == '__main__':
    sys.exit(main(sys.argv))
