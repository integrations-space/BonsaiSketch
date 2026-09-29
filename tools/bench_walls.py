"""Measure the wall reading against synthetic plans with known answers.

Run with plain Python:

    python3 tools/bench_walls.py

Every drawing below is generated from a stated truth -- walls with known
centrelines and thicknesses, written out as the two face lines a drafter
would draw, through the same DXF text the real pipeline reads. The
detector and junction resolver then run blind, and what they found is
scored against what was stated: precision (of what was found, how much is
real) and recall (of what is real, how much was found), per drawing and
overall.

This is the synthetic half of the benchmark. It proves the machinery
against controlled variation -- units, rotation, jitter, junction kinds,
mixed thicknesses -- and it gates regressions: the run fails below the
floors at the bottom. What it cannot prove is performance on real
drawings, whose messiness nobody generates on purpose; that needs a
hold-out set of actual plans with agreed truth, which is recorded in
AUTOMODEL.md as an open need.
"""

import math
import random
import sys
import types
from pathlib import Path

root = Path(__file__).resolve().parent.parent
package = types.ModuleType("bonsai_sketch_mode")
package.__path__ = [str(root / "bonsai_sketch_mode")]
sys.modules["bonsai_sketch_mode"] = package

import importlib

dxf = importlib.import_module("bonsai_sketch_mode.dxf")
walls = importlib.import_module("bonsai_sketch_mode.walls")

#: Overall floors. Synthetic plans are clean by construction, so the bar
#: is high; a real hold-out set will earn its own, lower, honest bar.
PRECISION_FLOOR = 0.95
RECALL_FLOOR = 0.95

#: file-unit factors: $INSUNITS code, multiplier from metres into the file.
UNITS = {"m": (6, 1.0), "mm": (4, 1000.0), "cm": (5, 100.0)}


class Truth:
    def __init__(self, start, end, thickness):
        self.start = start
        self.end = end
        self.thickness = thickness

    @property
    def midpoint(self):
        return ((self.start[0] + self.end[0]) / 2.0, (self.start[1] + self.end[1]) / 2.0)

    @property
    def length(self):
        return math.hypot(self.end[0] - self.start[0], self.end[1] - self.start[1])


def rotated(point, degrees):
    angle = math.radians(degrees)
    c, s = math.cos(angle), math.sin(angle)
    return (point[0] * c - point[1] * s, point[0] * s + point[1] * c)


def room(thickness=0.2, rotate=0.0):
    """A 4x3 room's four walls, centrelines meeting at the corners."""
    half = thickness / 2.0
    corners = [(half, half), (4 - half, half), (4 - half, 3 - half), (half, 3 - half)]
    truths = [
        Truth(corners[i], corners[(i + 1) % 4], thickness) for i in range(4)
    ]
    if rotate:
        for t in truths:
            t.start, t.end = rotated(t.start, rotate), rotated(t.end, rotate)
    return truths


def faces(truth):
    """The two lines a drafter draws for one wall."""
    dx, dy = truth.end[0] - truth.start[0], truth.end[1] - truth.start[1]
    length = math.hypot(dx, dy)
    nx, ny = -dy / length * truth.thickness / 2.0, dx / length * truth.thickness / 2.0
    return [
        ((truth.start[0] + nx, truth.start[1] + ny), (truth.end[0] + nx, truth.end[1] + ny)),
        ((truth.start[0] - nx, truth.start[1] - ny), (truth.end[0] - nx, truth.end[1] - ny)),
    ]


def drawing_text(truths, units="m", jitter=0.0, seed=0):
    code, factor = UNITS[units]
    rng = random.Random(seed)

    def coord(value):
        wobble = rng.uniform(-jitter, jitter) if jitter else 0.0
        return repr((value + wobble) * factor)

    pairs = [(0, "SECTION"), (2, "HEADER"), (9, "$INSUNITS"), (70, code),
             (0, "ENDSEC"), (0, "SECTION"), (2, "ENTITIES")]
    for truth in truths:
        for (x1, y1), (x2, y2) in faces(truth):
            pairs += [(0, "LINE"), (8, "WALLS"),
                      (10, coord(x1)), (20, coord(y1)),
                      (11, coord(x2)), (21, coord(y2))]
    pairs += [(0, "ENDSEC"), (0, "EOF")]
    return "\n".join(str(x) for pair in pairs for x in pair) + "\n"


def score(truths, found):
    """Greedy one-to-one matching, nearest midpoint first."""
    matches = []
    for f_index, wall in enumerate(found):
        mid = ((wall.start[0] + wall.end[0]) / 2.0, (wall.start[1] + wall.end[1]) / 2.0)
        for t_index, truth in enumerate(truths):
            distance = math.hypot(mid[0] - truth.midpoint[0], mid[1] - truth.midpoint[1])
            if (distance <= 0.10
                    and abs(wall.thickness - truth.thickness) <= 0.1 * truth.thickness
                    and abs(wall.length - truth.length) <= 0.05 * truth.length + 0.02):
                matches.append((distance, f_index, t_index))
    matches.sort()
    used_found, used_truth = set(), set()
    true_positive = 0
    for _distance, f_index, t_index in matches:
        if f_index in used_found or t_index in used_truth:
            continue
        used_found.add(f_index)
        used_truth.add(t_index)
        true_positive += 1
    return true_positive, len(found) - true_positive, len(truths) - true_positive


DRAWINGS = [
    ("clean room, metres", room(), dict(units="m")),
    ("clean room, millimetres", room(), dict(units="mm")),
    ("clean room, centimetres", room(), dict(units="cm")),
    ("room rotated 30 degrees", room(rotate=30.0), dict(units="mm")),
    ("room of 100mm walls", room(thickness=0.1), dict(units="mm")),
    ("room of 300mm walls", room(thickness=0.3), dict(units="mm")),
    ("two rooms and a divider (T)",
     room() + [Truth((2.0, 0.1), (2.0, 2.9), 0.2)], dict(units="mm")),
    ("crossing partition pair (X)",
     [Truth((0.0, 1.0), (4.0, 1.0), 0.2), Truth((2.0, -1.0), (2.0, 3.0), 0.15)],
     dict(units="mm")),
    ("acute corner, 45 degrees",
     [Truth((0.0, 0.0), (2.0, 0.0), 0.1), Truth((2.0, 0.0), (3.4, 1.4), 0.1)],
     dict(units="mm")),
    ("half-millimetre drafting jitter", room(), dict(units="mm", jitter=0.0005, seed=7)),
    ("jitter on a rotated plan", room(rotate=17.0), dict(units="mm", jitter=0.0005, seed=11)),
]


def main():
    rows = []
    totals = [0, 0, 0]
    for name, truths, options in DRAWINGS:
        parsed = dxf.parse(drawing_text(truths, **options))
        segs, handles = walls.explode(parsed.layers["WALLS"])
        candidates, _unpaired = walls.detect(segs, sources=handles)
        found, _junctions = walls.resolve(candidates)
        tp, fp, fn = score(truths, found)
        totals[0] += tp
        totals[1] += fp
        totals[2] += fn
        rows.append((name, len(truths), tp, fp, fn))

    print("WALL DETECTION -- synthetic ground truth")
    print(f"{'drawing':<34} {'truth':>5} {'found':>5} {'FP':>3} {'FN':>3}  verdict")
    failures = 0
    for name, truth_count, tp, fp, fn in rows:
        ok = fp == 0 and fn == 0
        failures += 0 if ok else 1
        print(f"{name:<34} {truth_count:>5} {tp:>5} {fp:>3} {fn:>3}  "
              + ("exact" if ok else "MISSED" if fn else "EXTRA"))

    tp, fp, fn = totals
    precision = tp / (tp + fp) if tp + fp else 0.0
    recall = tp / (tp + fn) if tp + fn else 0.0
    print(f"\nwalls stated {tp + fn}, found {tp + fp}, correct {tp}")
    print(f"precision {precision:.3f} (floor {PRECISION_FLOOR}), "
          f"recall {recall:.3f} (floor {RECALL_FLOOR})")
    if precision < PRECISION_FLOOR or recall < RECALL_FLOOR:
        print("BELOW FLOOR")
        sys.exit(1)
    print("floors held")


main()
