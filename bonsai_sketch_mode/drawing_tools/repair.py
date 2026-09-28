# SPDX-License-Identifier: GPL-3.0-or-later
"""Inspect and repair a single semantic layer, preserving holes and evidence."""
import math

from shapely.geometry import LineString, Point, Polygon
from shapely.ops import polygonize_full, unary_union


def repair(polylines, gap_m=0.02):
    """Return polygon profiles, unresolved linework and every added bridge.

    Only mutually unique free-end pairs within the tolerance are bridged.
    Junctions and intentional large gaps remain unresolved. Input coordinates
    must already be in metres and aligned to the common project origin.
    """
    if not math.isfinite(gap_m) or gap_m < 0:
        raise ValueError('gap_m must be finite and non-negative')
    lines, invalid = [], []
    for index, item in enumerate(polylines):
        points = [tuple(float(v) for v in p) for p in item['points']]
        if any(len(p) != 2 or not all(math.isfinite(v) for v in p) for p in points):
            raise ValueError('Repair needs finite XY coordinates in metres')
        points = [p for i, p in enumerate(points) if i == 0 or p != points[i - 1]]
        if len(points) < 2:
            invalid.append(index)
            continue
        if item.get('closed') and points[-1] != points[0]:
            points.append(points[0])
        line = LineString(points)
        # Do not turn a crossing closed outline into two apparently valid walls.
        if not line.is_simple:
            invalid.append(index)
        else:
            lines.append(line)
    network = unary_union(lines)
    segments = list(network.geoms) if hasattr(network, 'geoms') else [network]
    ends = {}
    for line in segments:
        if line.is_empty:
            continue
        for p in (tuple(line.coords[0]), tuple(line.coords[-1])):
            ends[p] = ends.get(p, 0) + 1
    free = sorted(p for p, degree in ends.items() if degree == 1)
    neighbours = {p: [q for q in free if q != p and math.dist(p, q) <= gap_m] for p in free}
    bridges = []
    for p in free:
        candidates = neighbours[p]
        if len(candidates) != 1:
            continue
        q = candidates[0]
        if p >= q or neighbours[q] != [p]:
            continue
        bridge = LineString([p, q])
        crossing = bridge.intersection(network)
        # A bridge may touch its endpoints only; it cannot cross another edge.
        if not crossing.difference(Point(p).union(Point(q))).is_empty:
            continue
        if any(bridge.intersects(LineString(b)) for b in bridges):
            continue
        bridges.append([p, q])
    joined = unary_union(lines + [LineString(b) for b in bridges])
    pieces = list(joined.geoms) if hasattr(joined, 'geoms') else [joined]
    polygons, cuts, dangles, bad = polygonize_full(pieces)
    candidates = list(polygons.geoms)
    shells = [Polygon(p.exterior) for p in candidates]
    profiles = []
    for p in candidates:
        # polygonize emits nested inner faces too. Odd/even fill keeps voids.
        depth = sum(shell.contains(p.representative_point()) for shell in shells)
        if depth % 2:
            profiles.append({'outer': list(p.exterior.coords)[:-1],
                             'holes': [list(r.coords)[:-1] for r in p.interiors]})
    profiles.sort(key=lambda p: (min(p['outer']), len(p['outer'])))
    unresolved = [list(line.coords) for group in (cuts, dangles, bad) for line in group.geoms]
    return {'profiles': profiles, 'bridges': bridges, 'unresolved': unresolved,
            'invalid_polylines': invalid,
            'ambiguous_endpoints': [p for p in free if len(neighbours[p]) > 1],
            'ready': bool(profiles) and not unresolved and not invalid}
