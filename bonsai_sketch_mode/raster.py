# Bonsai Sketch Mode - direct-modelling interaction for Bonsai
# Copyright (C) 2026 Innovations & Integrations
#
# This program is free software: you can redistribute it and/or modify
# it under the terms of the GNU General Public License as published by
# the Free Software Foundation, either version 3 of the License, or
# (at your option) any later version.
#
# This program is distributed in the hope that it will be useful,
# but WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
# GNU General Public License for more details.
#
# You should have received a copy of the GNU General Public License
# along with this program.  If not, see <http://www.gnu.org/licenses/>.

"""Recovering a scanned drawing's linework, by rules alone.

Most images an architect actually holds are not concept sketches but
scans: orthogonal drawings that once were vectors and need *recovery*,
not interpretation. Everything here is classical image processing --
Otsu's threshold, Zhang-Suen thinning, stroke tracing, Douglas-Peucker
simplification, a deskew earned from the strokes' own angles -- with no
learned model anywhere in the chain. The output is the same ``Drawing``
structure ``dxf.parse`` produces, so the scan feeds the *existing*
compiler, which already knows how to heal small gaps, refuse what it
cannot read, and say so.

Two things a scan cannot state are refused rather than guessed:

* **Scale.** Pixels are not metres. A ``raster.json`` beside the image
  must state ``metres_per_pixel``, or ``dpi`` and ``paper_scale``
  together (a 1:100 drawing scanned at 300 dpi). No configuration, no
  geometry -- a scan's scale is a human decision, recorded as
  configuration exactly as a coordinate reference system is.
* **Meaning.** A scan has no layers, and which linework is wall
  footprint is somebody's judgement. ``raster.json`` names the one
  layer the recovered strokes land on (``"layer": "WALLS"``); the
  classifier downstream treats that name by the same conventions as a
  drawn file's.

What a scan loses against a vector file is reported, not papered over:
no text is read (labels, marks and levels wait for the OCR rung of the
ladder), so spaces come back unlabelled and elevations unknown -- which
the compiler already treats as valid, visible states.

Pure Python, no dependencies, like every reader before it. The PGM
image format is read and written here so the checks and fixtures need
no imaging library either; other formats arrive through Blender's own
image loader in the pipeline glue.
"""

from __future__ import annotations

import math
from typing import Optional

from .dxf import Drawing, Polyline

#: A path shorter than this many pixels end to end is a speck or a
#: scanning artefact, counted and dropped rather than built from.
MIN_PATH_PIXELS = 4.0

#: Douglas-Peucker tolerance in pixels: within scanner jitter, a drawn
#: straight line comes back as one segment.
SIMPLIFY_TOLERANCE = 1.2

#: Only segments at least this long, and within this many degrees of an
#: axis, vote on the page's skew; short strokes and genuine diagonals
#: are somebody's drawing, not the scanner's rotation.
DESKEW_MIN_LENGTH = 10.0
DESKEW_MAX_DEVIATION = math.radians(10.0)


# --- PGM ------------------------------------------------------------------

def read_pgm(path: str) -> tuple[int, int, bytearray]:
    """(width, height, pixels) of a P5 or P2 PGM, rows top to bottom."""
    with open(path, "rb") as handle:
        data = handle.read()

    tokens = []
    index = 0
    while len(tokens) < 4 and index < len(data):
        while index < len(data) and data[index:index + 1].isspace():
            index += 1
        if data[index:index + 1] == b"#":
            while index < len(data) and data[index] != 0x0A:
                index += 1
            continue
        start = index
        while index < len(data) and not data[index:index + 1].isspace():
            index += 1
        tokens.append(data[start:index])
    if len(tokens) < 4:
        raise ValueError("not a PGM: header incomplete")
    magic = tokens[0]
    if magic not in (b"P5", b"P2"):
        raise ValueError(f"not a PGM: magic {magic!r}")
    width, height, maxval = int(tokens[1]), int(tokens[2]), int(tokens[3])
    if width <= 0 or height <= 0 or not 0 < maxval < 65536:
        raise ValueError("not a PGM: dimensions make no sense")

    if magic == b"P5":
        if maxval > 255:
            raise ValueError("16-bit PGM is outside this reader's subset")
        pixels = bytearray(data[index + 1:index + 1 + width * height])
    else:
        values = data[index:].split()
        pixels = bytearray(min(int(v), 255) for v in values[:width * height])
    if len(pixels) != width * height:
        raise ValueError("not a PGM: pixel data short")
    return width, height, pixels


def write_pgm(path: str, width: int, height: int, pixels) -> None:
    """A P5 PGM, for fixtures: the one image the checks can make alone."""
    with open(path, "wb") as handle:
        handle.write(b"P5\n%d %d\n255\n" % (width, height))
        handle.write(bytes(pixels))


# --- Threshold ------------------------------------------------------------

def otsu(pixels) -> int:
    """Otsu's threshold: the split that maximises between-class variance."""
    histogram = [0] * 256
    for value in pixels:
        histogram[value] += 1
    total = len(pixels)
    total_sum = sum(i * histogram[i] for i in range(256))

    best, best_variance = 128, -1.0
    weight_low = 0
    sum_low = 0.0
    for threshold in range(256):
        weight_low += histogram[threshold]
        if weight_low == 0:
            continue
        weight_high = total - weight_low
        if weight_high == 0:
            break
        sum_low += threshold * histogram[threshold]
        mean_low = sum_low / weight_low
        mean_high = (total_sum - sum_low) / weight_high
        variance = weight_low * weight_high * (mean_low - mean_high) ** 2
        if variance > best_variance:
            best_variance = variance
            best = threshold
    return best


# --- Skeleton -------------------------------------------------------------

def _binarise(width: int, height: int, pixels, threshold: int) -> bytearray:
    """Ink = 1 where at or below the threshold (Otsu's low class is
    inclusive); the border stays paper so every later neighbourhood read
    is safe without bounds checks."""
    ink = bytearray(width * height)
    for y in range(1, height - 1):
        row = y * width
        for x in range(1, width - 1):
            if pixels[row + x] <= threshold:
                ink[row + x] = 1
    return ink


def _thin(width: int, height: int, ink: bytearray) -> bytearray:
    """Zhang-Suen thinning: strokes reduced to one-pixel centrelines."""
    changed = True
    while changed:
        changed = False
        for phase in (0, 1):
            deletions = []
            for y in range(1, height - 1):
                row = y * width
                for x in range(1, width - 1):
                    index = row + x
                    if not ink[index]:
                        continue
                    p2 = ink[index - width]
                    p3 = ink[index - width + 1]
                    p4 = ink[index + 1]
                    p5 = ink[index + width + 1]
                    p6 = ink[index + width]
                    p7 = ink[index + width - 1]
                    p8 = ink[index - 1]
                    p9 = ink[index - width - 1]
                    filled = p2 + p3 + p4 + p5 + p6 + p7 + p8 + p9
                    if not 2 <= filled <= 6:
                        continue
                    sequence = (p2, p3, p4, p5, p6, p7, p8, p9, p2)
                    transitions = sum(
                        1 for a, b in zip(sequence, sequence[1:])
                        if a == 0 and b == 1)
                    if transitions != 1:
                        continue
                    if phase == 0:
                        if p2 * p4 * p6 or p4 * p6 * p8:
                            continue
                    else:
                        if p2 * p4 * p8 or p2 * p6 * p8:
                            continue
                    deletions.append(index)
            for index in deletions:
                ink[index] = 0
            if deletions:
                changed = True
    return ink


# --- Tracing --------------------------------------------------------------

_NEIGHBOURS = ((0, -1), (1, -1), (1, 0), (1, 1), (0, 1), (-1, 1), (-1, 0), (-1, -1))


def _trace(width: int, height: int, skeleton: bytearray):
    """(open paths, closed paths, specks) walked out of the skeleton.

    Nodes -- endpoints and junctions, any pixel whose degree is not two
    -- break the skeleton into strokes. Thinning leaves a junction as a
    small *cluster* of such pixels rather than one, so adjacent node
    pixels are contracted to a single junction point first; otherwise a
    T sheds a confetti of two-pixel fragments and the real strokes end
    short of the corner. Paths run junction centroid to junction
    centroid. What remains after the node walks is closed loops; what
    never joins anything is a speck.
    """
    def neighbours(x, y):
        found = []
        for dx, dy in _NEIGHBOURS:
            if skeleton[(y + dy) * width + (x + dx)]:
                found.append((x + dx, y + dy))
        return found

    degree = {}
    for y in range(1, height - 1):
        row = y * width
        for x in range(1, width - 1):
            if skeleton[row + x]:
                degree[(x, y)] = len(neighbours(x, y))

    node_pixels = {p for p, d in degree.items() if d != 2}

    # Contract each 8-connected component of node pixels to its centroid.
    cluster_of = {}
    centroids = []
    specks = 0
    for pixel in sorted(node_pixels):
        if pixel in cluster_of:
            continue
        component = [pixel]
        cluster_of[pixel] = len(centroids)
        queue = [pixel]
        while queue:
            current = queue.pop()
            for neighbour in neighbours(*current):
                if neighbour in node_pixels and neighbour not in cluster_of:
                    cluster_of[neighbour] = len(centroids)
                    component.append(neighbour)
                    queue.append(neighbour)
        if len(component) == 1 and degree[pixel] == 0:
            specks += 1
            centroids.append(None)
            continue
        if not any(nb not in node_pixels
                   for p in component for nb in neighbours(*p)):
            # An isolated knot of node pixels with no stroke leaving it:
            # a blot, not linework.
            specks += 1
            centroids.append(None)
            continue
        centroids.append((sum(x for x, _y in component) / len(component),
                          sum(y for _x, y in component) / len(component)))

    visited = set()
    open_paths = []
    seen_stubs = set()

    for pixel in sorted(node_pixels):
        cluster = cluster_of[pixel]
        if centroids[cluster] is None:
            continue
        for start in neighbours(*pixel):
            if start in node_pixels:
                other = cluster_of[start]
                if other != cluster and centroids[other] is not None:
                    # Two junction clusters touching: a stroke with no
                    # interior. Record it once.
                    key = (min(cluster, other), max(cluster, other))
                    if key not in seen_stubs:
                        seen_stubs.add(key)
                        open_paths.append([centroids[cluster], centroids[other]])
                continue
            if start in visited:
                continue
            path = [centroids[cluster], start]
            visited.add(start)
            previous, current = pixel, start
            while True:
                options = [p for p in neighbours(*current) if p != previous]
                after = next(
                    (p for p in options if p in node_pixels or p not in visited),
                    None)
                if after is None:
                    break
                if after in node_pixels:
                    end = cluster_of[after]
                    if centroids[end] is not None:
                        path.append(centroids[end])
                    break
                path.append(after)
                visited.add(after)
                previous, current = current, after
            open_paths.append(path)

    closed_paths = []
    for pixel, count in degree.items():
        if count != 2 or pixel in visited or pixel in node_pixels:
            continue
        path = [pixel]
        visited.add(pixel)
        previous, current = None, pixel
        while True:
            options = [p for p in neighbours(*current) if p != previous]
            after = next((p for p in options if p not in visited), None)
            if after is None:
                break
            path.append(after)
            visited.add(after)
            previous, current = current, after
        closed_paths.append(path)

    return open_paths, closed_paths, specks


# --- Simplification -------------------------------------------------------

def _deviation(point, start, end) -> float:
    (px, py), (ax, ay), (bx, by) = point, start, end
    dx, dy = bx - ax, by - ay
    length = math.hypot(dx, dy)
    if length < 1e-9:
        return math.hypot(px - ax, py - ay)
    return abs(dx * (ay - py) - dy * (ax - px)) / length


def simplify(points, tolerance: float = SIMPLIFY_TOLERANCE):
    """Douglas-Peucker: the fewest vertices within tolerance of the walk."""
    if len(points) < 3:
        return list(points)
    worst_index, worst = 0, -1.0
    for index in range(1, len(points) - 1):
        d = _deviation(points[index], points[0], points[-1])
        if d > worst:
            worst_index, worst = index, d
    if worst <= tolerance:
        return [points[0], points[-1]]
    head = simplify(points[:worst_index + 1], tolerance)
    tail = simplify(points[worst_index:], tolerance)
    return head[:-1] + tail


def _simplify_closed(points, tolerance: float = SIMPLIFY_TOLERANCE):
    """A loop has no endpoints to anchor on, so it is split at the point
    farthest from its start and simplified as two arcs."""
    if len(points) < 4:
        return list(points)
    origin = points[0]
    far = max(range(1, len(points)),
              key=lambda i: (points[i][0] - origin[0]) ** 2
              + (points[i][1] - origin[1]) ** 2)
    first = simplify(points[:far + 1], tolerance)
    second = simplify(points[far:] + [points[0]], tolerance)
    return first[:-1] + second[:-1]


#: An interior vertex turning less than this is scanner wobble on a
#: straight run, not a drawn corner.
COLLINEAR_TOLERANCE = math.radians(5.0)


def _tidy(points, corner_reach: float, cyclic: bool = False):
    """Straighten wobble and sharpen thinned corners, by two rules.

    Thinning rounds every corner over about a stroke's width, and the
    skeleton wanders a pixel or two along a run; Douglas-Peucker keeps
    both faithfully. So: an interior vertex that turns less than
    :data:`COLLINEAR_TOLERANCE` is dropped, and an interior segment
    shorter than ``corner_reach`` whose neighbours are long is replaced
    by those neighbours' intersection -- the corner the drafter drew,
    recovered from the two runs that met there.
    """
    def straighten(pts):
        changed = True
        while changed and len(pts) > 2:
            changed = False
            limit = len(pts) if cyclic else len(pts) - 1
            index = 0 if cyclic else 1
            while index < limit and len(pts) > 2:
                a = pts[(index - 1) % len(pts)]
                b = pts[index % len(pts)]
                c = pts[(index + 1) % len(pts)]
                angle_in = math.atan2(b[1] - a[1], b[0] - a[0])
                angle_out = math.atan2(c[1] - b[1], c[0] - b[0])
                turn = (angle_out - angle_in + math.pi) % (2 * math.pi) - math.pi
                if abs(turn) < COLLINEAR_TOLERANCE:
                    del pts[index % len(pts)]
                    limit -= 1
                    changed = True
                else:
                    index += 1
        return pts

    def sharpen(pts):
        index = 0 if cyclic else 1
        while len(pts) > 3:
            limit = len(pts) if cyclic else len(pts) - 2
            if index >= limit:
                break
            a = pts[(index - 1) % len(pts)]
            b = pts[index % len(pts)]
            c = pts[(index + 1) % len(pts)]
            d = pts[(index + 2) % len(pts)]
            short = math.hypot(c[0] - b[0], c[1] - b[1])
            before = math.hypot(b[0] - a[0], b[1] - a[1])
            after = math.hypot(d[0] - c[0], d[1] - c[1])
            if short <= corner_reach and before > corner_reach and after > corner_reach:
                d1x, d1y = b[0] - a[0], b[1] - a[1]
                d2x, d2y = c[0] - d[0], c[1] - d[1]
                cross = d1x * d2y - d1y * d2x
                if abs(cross) > 1e-9:
                    t = ((d[0] - a[0]) * d2y - (d[1] - a[1]) * d2x) / cross
                    corner = (a[0] + d1x * t, a[1] + d1y * t)
                    if (math.hypot(corner[0] - b[0], corner[1] - b[1])
                            <= 2 * corner_reach):
                        pts[index % len(pts)] = corner
                        del pts[(index + 1) % len(pts)]
                        continue
            index += 1
        return pts

    return straighten(sharpen(straighten(list(points))))


def _refit(raw, tidied, corner_reach: float, cyclic: bool = False):
    """Refit each straight run by orthogonal least squares over the raw
    skeleton, and place corners at run intersections.

    Douglas-Peucker picks two skeleton pixels and calls them a line; a
    pixel of wobble at either pick leans the whole run, which downstream
    reads as a tapering wall. The drafter's line is better recovered by
    fitting *all* the run's pixels -- total least squares, with a
    ``corner_reach`` margin trimmed at each end so a thinned corner's
    rounding does not contaminate the fit.
    """
    if len(tidied) < 2 or len(raw) < 3:
        return list(tidied)

    def nearest(point):
        px, py = point
        best, best_distance = 0, float("inf")
        for index, (x, y) in enumerate(raw):
            d = (x - px) ** 2 + (y - py) ** 2
            if d < best_distance:
                best, best_distance = index, d
        return best

    def fit(points):
        n = len(points)
        mx = sum(x for x, _y in points) / n
        my = sum(y for _x, y in points) / n
        sxx = sum((x - mx) ** 2 for x, _y in points)
        syy = sum((y - my) ** 2 for _x, y in points)
        sxy = sum((x - mx) * (y - my) for x, y in points)
        angle = 0.5 * math.atan2(2.0 * sxy, sxx - syy)
        return (mx, my), (math.cos(angle), math.sin(angle))

    def run_line(start_index, end_index):
        if end_index < start_index:
            window = raw[start_index:] + raw[:end_index + 1]
        else:
            window = raw[start_index:end_index + 1]
        trim = int(corner_reach)
        if len(window) > 3 * trim > 0:
            window = window[trim:-trim]
        if len(window) < 3:
            a, b = raw[start_index], raw[end_index]
            if a == b:
                return None
            length = math.hypot(b[0] - a[0], b[1] - a[1])
            return a, ((b[0] - a[0]) / length, (b[1] - a[1]) / length)
        return fit(window)

    def intersect(line_a, line_b, fallback):
        (ax, ay), (ux, uy) = line_a
        (bx, by), (vx, vy) = line_b
        cross = ux * vy - uy * vx
        if abs(cross) < 1e-6:
            return fallback
        t = ((bx - ax) * vy - (by - ay) * vx) / cross
        return (ax + ux * t, ay + uy * t)

    def project(point, line):
        (ax, ay), (ux, uy) = line
        t = (point[0] - ax) * ux + (point[1] - ay) * uy
        return (ax + ux * t, ay + uy * t)

    anchors = [nearest(vertex) for vertex in tidied]
    if cyclic:
        lines = []
        for k in range(len(tidied)):
            line = run_line(anchors[k], anchors[(k + 1) % len(anchors)])
            if line is None:
                return list(tidied)
            lines.append(line)
        return [intersect(lines[k - 1], lines[k], tidied[k])
                for k in range(len(tidied))]

    lines = []
    for k in range(len(tidied) - 1):
        line = run_line(anchors[k], anchors[k + 1])
        if line is None:
            return list(tidied)
        lines.append(line)
    refitted = [project(tidied[0], lines[0])]
    for k in range(1, len(tidied) - 1):
        refitted.append(intersect(lines[k - 1], lines[k], tidied[k]))
    refitted.append(project(tidied[-1], lines[-1]))
    return refitted


# --- Deskew ---------------------------------------------------------------

def _weighted_median(pairs) -> float:
    """The value at half the total weight; pairs are (value, weight)."""
    ordered = sorted(pairs)
    half = sum(weight for _value, weight in ordered) / 2.0
    accumulated = 0.0
    for value, weight in ordered:
        accumulated += weight
        if accumulated >= half:
            return value
    return ordered[-1][0] if ordered else 0.0


def deskew_angle(paths) -> tuple[float, str]:
    """(radians, note): the page's rotation, voted by its own strokes.

    Each long-enough segment's deviation from the nearest axis is one
    vote, weighted by length; the weighted median is robust against the
    drawing's genuine diagonals, which sit outside the deviation window
    and never vote at all.
    """
    votes = []
    for path in paths:
        for (ax, ay), (bx, by) in zip(path, path[1:]):
            length = math.hypot(bx - ax, by - ay)
            if length < DESKEW_MIN_LENGTH:
                continue
            angle = math.atan2(by - ay, bx - ax)
            deviation = (angle + math.pi / 4.0) % (math.pi / 2.0) - math.pi / 4.0
            if abs(deviation) <= DESKEW_MAX_DEVIATION:
                votes.append((deviation, length))
    if not votes:
        return 0.0, "no near-axis strokes to vote on a skew; left as scanned"
    angle = _weighted_median(votes)
    return angle, (f"deskewed {math.degrees(angle):+.2f} degrees, the weighted "
                   f"median of {len(votes)} stroke(s)")


def rotate(paths, angle: float, center) -> list:
    cos, sin = math.cos(-angle), math.sin(-angle)
    cx, cy = center
    turned = []
    for path in paths:
        turned.append([
            (cx + (x - cx) * cos - (y - cy) * sin,
             cy + (x - cx) * sin + (y - cy) * cos)
            for x, y in path])
    return turned


# --- Rejoining through-lines ----------------------------------------------

#: Endpoints within a thinned junction cluster's diameter are the same
#: junction; directions within this of straight-on are the same line.
JOIN_REACH = 3.5
JOIN_STRAIGHTNESS = math.radians(6.0)


def join_through_lines(paths, closed):
    """Fuse strokes that arrive collinear at a junction, back into one.

    Thinning breaks every drawn line at every junction it passes: a
    partition's faces stopping against a through wall leave that wall's
    face as two strokes either side of a T. The drafter drew one line,
    and the junction resolver downstream expects one -- a T is an end
    against a *middle*. So at every meeting point, a pair of strokes
    arriving within :data:`JOIN_STRAIGHTNESS` of straight-on is fused,
    and only an unambiguous pair: two candidates for the same
    continuation is somebody's judgement, left split and visible.

    Returns (paths, closed, fused_count).
    """
    paths = [list(p) for p in paths]
    closed = list(closed)
    fused = 0

    def direction_out(path, at_start):
        # The direction leaving the endpoint, into the path.
        if at_start:
            (ax, ay), (bx, by) = path[0], path[1]
        else:
            (ax, ay), (bx, by) = path[-1], path[-2]
        length = math.hypot(bx - ax, by - ay)
        return ((bx - ax) / length, (by - ay) / length) if length else (0.0, 0.0)

    changed = True
    while changed:
        changed = False
        ends = []
        for index, path in enumerate(paths):
            if path is None or closed[index] or len(path) < 2:
                continue
            ends.append((index, True, path[0]))
            ends.append((index, False, path[-1]))
        for position in range(len(ends)):
            index_a, at_start_a, point_a = ends[position]
            if paths[index_a] is None:
                continue
            nearby = []
            for other in range(len(ends)):
                if other == position:
                    continue
                index_b, at_start_b, point_b = ends[other]
                if paths[index_b] is None:
                    continue
                if math.hypot(point_b[0] - point_a[0],
                              point_b[1] - point_a[1]) > JOIN_REACH:
                    continue
                ua = direction_out(paths[index_a], at_start_a)
                ub = direction_out(paths[index_b], at_start_b)
                # Straight-on continuation: the two outgoing directions
                # are opposite.
                dot = ua[0] * ub[0] + ua[1] * ub[1]
                if dot < -math.cos(JOIN_STRAIGHTNESS):
                    nearby.append((index_b, at_start_b))
            if len(nearby) != 1:
                continue
            index_b, at_start_b = nearby[0]
            if index_b == index_a:
                # A stroke meeting itself straight-on is a loop.
                closed[index_a] = True
                changed = True
                fused += 1
                continue
            a = paths[index_a] if not at_start_a else list(reversed(paths[index_a]))
            b = paths[index_b] if at_start_b else list(reversed(paths[index_b]))
            paths[index_a] = a + b[1:]
            paths[index_b] = None
            fused += 1
            changed = True
            break

    kept_paths, kept_closed = [], []
    for path, is_loop in zip(paths, closed):
        if path is None:
            continue
        kept_paths.append(path)
        kept_closed.append(is_loop)
    return kept_paths, kept_closed, fused


# --- Configuration --------------------------------------------------------

def metres_per_pixel(config: dict) -> tuple[Optional[float], str]:
    """The stated scale, or (None, why) -- never a guess.

    Either ``metres_per_pixel`` directly, or ``dpi`` with ``paper_scale``
    (1:100 scanned at 300 dpi: one pixel is 25.4/300 mm of paper, times
    a hundred of building).
    """
    stated = config.get("metres_per_pixel")
    if stated is not None:
        try:
            value = float(stated)
        except (TypeError, ValueError):
            return None, "metres_per_pixel must be a number"
        if value <= 0:
            return None, "metres_per_pixel must be positive"
        return value, f"scale stated: {value:g} m per pixel"
    dpi = config.get("dpi")
    paper = config.get("paper_scale")
    if dpi is not None and paper is not None:
        try:
            dpi, paper = float(dpi), float(paper)
        except (TypeError, ValueError):
            return None, "dpi and paper_scale must be numbers"
        if dpi <= 0 or paper <= 0:
            return None, "dpi and paper_scale must be positive"
        value = 0.0254 / dpi * paper
        return value, f"scale stated: 1:{paper:g} at {dpi:g} dpi ({value * 1000:.3f} mm per pixel)"
    return None, ("scan scale is not stated: raster.json needs metres_per_pixel, "
                  "or dpi and paper_scale together -- a scan's scale is a human "
                  "decision, not a guess")


# --- The whole recovery ---------------------------------------------------

def vectorise(width: int, height: int, pixels) -> dict:
    """Threshold, thin and trace one bitmap into simplified pixel paths.

    Returns paths (each a list of (x, y) pixel points), closed flags,
    the threshold used, the mean stroke width in pixels, and counts for
    everything dropped -- specks and too-short paths are reported, never
    silently gone.
    """
    threshold = otsu(pixels)
    ink = _binarise(width, height, pixels, threshold)
    ink_count = sum(ink)
    if ink_count == 0:
        return {"paths": [], "closed": [], "threshold": threshold,
                "stroke_width": 0.0, "specks": 0, "short": 0,
                "note": "the page is blank at this threshold"}
    skeleton = _thin(width, height, bytearray(ink))
    skeleton_count = sum(skeleton)
    stroke_width = ink_count / skeleton_count if skeleton_count else 0.0

    open_paths, closed_paths, specks = _trace(width, height, skeleton)

    paths, closed, short = [], [], 0
    corner_reach = max(4.0, 3.0 * stroke_width)
    for path in open_paths:
        (ax, ay), (bx, by) = path[0], path[-1]
        if math.hypot(bx - ax, by - ay) < MIN_PATH_PIXELS and len(path) < MIN_PATH_PIXELS:
            short += 1
            continue
        raw = [(float(x), float(y)) for x, y in path]
        simplified = _refit(
            raw, _tidy(simplify(raw), corner_reach), corner_reach)
        # A stroke that walks back to its own start is a loop that a
        # corner's junction cluster made look open; close it rather than
        # leaving a hairline gap for the healer to wonder about. The
        # tolerance is a thinned corner's own diameter.
        (ax, ay), (bx, by) = simplified[0], simplified[-1]
        if len(simplified) > 3 and math.hypot(bx - ax, by - ay) <= 3.5:
            paths.append(simplified[:-1])
            closed.append(True)
        else:
            paths.append(simplified)
            closed.append(False)
    for path in closed_paths:
        if len(path) < MIN_PATH_PIXELS:
            short += 1
            continue
        raw = [(float(x), float(y)) for x, y in path]
        paths.append(_refit(
            raw, _tidy(_simplify_closed(raw), corner_reach, cyclic=True),
            corner_reach, cyclic=True))
        closed.append(True)

    return {"paths": paths, "closed": closed, "threshold": threshold,
            "stroke_width": stroke_width, "specks": specks, "short": short,
            "note": ""}


def interpret(width: int, height: int, pixels, config: dict):
    """(drawing, notes, why_not): one scan into the compiler's own currency.

    The drawing carries every recovered stroke as a Polyline on the one
    configured layer, in metres, y up, deskewed; sources name the scan
    stroke (``SCAN:#7``) so provenance survives into the ledger. Notes
    are the evidence sentences; why_not is the refusal when scale or
    layer is unstated or the page holds nothing.
    """
    scale, scale_note = metres_per_pixel(config)
    if scale is None:
        return None, [], scale_note
    layer = config.get("layer")
    if not isinstance(layer, str) or not layer.strip():
        return None, [], ("raster.json names no linework layer -- which strokes "
                          "are wall footprint is a judgement, stated as "
                          '"layer", never guessed')
    layer = layer.strip()

    recovered = vectorise(width, height, pixels)
    if not recovered["paths"]:
        why = recovered["note"] or "no linework survived tracing"
        return None, [], f"nothing recovered from the scan: {why}"

    # Pixel rows run down; drawings run up. Flip before the deskew vote
    # so the angle is already in drawing-space terms.
    upright = [[(x, float(height - 1) - y) for x, y in path]
               for path in recovered["paths"]]
    angle, deskew_note = deskew_angle(upright)
    if angle:
        points = [p for path in upright for p in path]
        center = (sum(x for x, _y in points) / len(points),
                  sum(y for _x, y in points) / len(points))
        upright = rotate(upright, angle, center)

    upright, closed_flags, fused = join_through_lines(upright, recovered["closed"])
    if fused:
        # A fuse leaves the two old endpoints as near-collinear interior
        # vertices; straighten them out.
        upright = [_tidy(path, 0.0) if not is_loop else path
                   for path, is_loop in zip(upright, closed_flags)]

    drawing = Drawing()
    drawing.scale = scale
    drawing.unit_name = "pixels, scaled by statement"
    for number, (path, is_closed) in enumerate(zip(upright, closed_flags), 1):
        drawing.add(Polyline(
            layer,
            [(x * scale, y * scale) for x, y in path],
            is_closed,
            source=f"SCAN:#{number}"))

    notes = [
        scale_note,
        (f"recovered {len(upright)} stroke(s) at threshold "
         f"{recovered['threshold']}, mean stroke width "
         f"{recovered['stroke_width']:.1f} px"),
        deskew_note,
    ]
    if fused:
        notes.append(f"rejoined {fused} through-line(s) that thinning had "
                     "broken at junctions")
    dropped = recovered["specks"] + recovered["short"]
    if dropped:
        notes.append(f"dropped {dropped} speck(s) shorter than {MIN_PATH_PIXELS:g} px")
    notes.append("no text read from the scan: labels, marks and levels wait "
                 "for OCR; unlabelled is a valid state downstream")
    return drawing, notes, None
