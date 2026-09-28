# SPDX-License-Identifier: GPL-3.0-or-later
"""Parametric geometry recipes, independent of Blender and IFC."""
import math


def sloping_slab(length_m, width_m, thickness_m, rise_m):
    """Closed ramp or roof panel; rise is along local X, thickness is vertical."""
    if not all(math.isfinite(v) for v in (length_m, width_m, thickness_m, rise_m)) or min(length_m, width_m, thickness_m) <= 0:
        raise ValueError('Slab dimensions must be positive and finite; rise must be finite')
    l, w, t, r = length_m, width_m, thickness_m, rise_m
    return {'vertices_m': [[0,0,0],[l,0,r],[l,w,r],[0,w,0],
                           [0,0,t],[l,0,r+t],[l,w,r+t],[0,w,t]],
            'faces': [[3,2,1,0],[4,5,6,7],[0,1,5,4],[1,2,6,5],[2,3,7,6],[3,0,4,7]]}


def terrain(points, boundary):
    """Triangulate supplied XYZ survey points inside a supplied XY boundary.

    Boundary vertices must have measured heights in points. No heights are
    guessed. This is a point-based TIN, not a constrained contour triangulator.
    Concave boundaries that cannot be covered without extra points are refused.
    """
    from shapely.geometry import MultiPoint, Polygon
    from shapely.ops import triangulate, unary_union
    if any(len(p) != 3 or not all(math.isfinite(v) for v in p) for p in points):
        raise ValueError('Terrain points need finite XYZ coordinates')
    xy = [tuple(p[:2]) for p in points]
    if len(set(xy)) != len(xy):
        raise ValueError('Terrain XY points must be unique')
    region = Polygon(boundary)
    if not region.is_valid or region.area <= 0:
        raise ValueError('Invalid terrain boundary')
    if any(tuple(p) not in xy for p in boundary):
        raise ValueError('Each terrain boundary vertex needs a survey height')
    indices = {p: i for i, p in enumerate(xy)}
    tris = [t for t in triangulate(MultiPoint(xy)) if region.covers(t)]
    if region.symmetric_difference(unary_union(tris)).area > max(1e-8, region.area*1e-8):
        raise ValueError('Add survey points to resolve the concave terrain boundary')
    return {'vertices_m': points, 'faces': [[indices[tuple(p)] for p in list(t.exterior.coords)[:3]] for t in tris]}
