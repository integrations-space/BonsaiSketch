"""Check the scan-recovery rules against bitmaps drawn by hand.

Run with plain Python:

    python3 tools/raster_check.py

Every fixture is stamped pixel by pixel here, so every recovered stroke
has a stated answer. The refusals matter most: no stated scale means no
geometry, no named layer means no geometry, and a blank page says so
instead of returning an empty success.
"""

import math
import os
import sys
import tempfile
import types
from pathlib import Path

lines = []
failures = []
checks = 0


def check(label, condition, detail=""):
    global checks
    checks += 1
    if condition:
        lines.append("  ok    %s" % label)
    else:
        lines.append("  FAIL  %s%s" % (label, " -- %s" % detail if detail else ""))
        failures.append(label)


def section(title):
    lines.append("\n%s" % title)


root = Path(__file__).resolve().parent.parent
package = types.ModuleType("bonsai_sketch_mode")
package.__path__ = [str(root / "bonsai_sketch_mode")]
sys.modules["bonsai_sketch_mode"] = package

import importlib

raster = importlib.import_module("bonsai_sketch_mode.raster")


def page(width, height, value=255):
    return width, height, bytearray([value]) * (width * height)


def stamp_line(bitmap, x1, y1, x2, y2, radius=1, value=0):
    """A thick stroke: discs stamped densely along the run."""
    width, height, pixels = bitmap
    length = math.hypot(x2 - x1, y2 - y1)
    steps = max(2, int(length * 3))
    for step in range(steps + 1):
        t = step / steps
        cx, cy = x1 + (x2 - x1) * t, y1 + (y2 - y1) * t
        for dy in range(-radius, radius + 1):
            for dx in range(-radius, radius + 1):
                if dx * dx + dy * dy <= radius * radius + 0.5:
                    px, py = int(round(cx + dx)), int(round(cy + dy))
                    if 0 <= px < width and 0 <= py < height:
                        pixels[py * width + px] = value


def near(a, b, tolerance):
    return abs(a - b) <= tolerance


def endpoints(path):
    return path[0], path[-1]


section("Otsu finds the valley of a bimodal page")
_w, _h, bimodal = page(20, 20, 240)
for i in range(80):
    bimodal[i] = 20
threshold = raster.otsu(bimodal)
check("the threshold sits with the ink, below the paper",
      20 <= threshold < 240, str(threshold))
check("an even grey page still answers with a number",
      isinstance(raster.otsu(bytearray([128]) * 100), int))


section("A straight stroke comes back as one segment")
bitmap = page(120, 60)
stamp_line(bitmap, 10, 30, 110, 30)
recovered = raster.vectorise(*bitmap)
check("one open path", len(recovered["paths"]) == 1
      and recovered["closed"] == [False], str(recovered["paths"]))
check("simplified to its two endpoints", len(recovered["paths"][0]) == 2,
      str(recovered["paths"][0]))
(ax, ay), (bx, by) = endpoints(recovered["paths"][0])
check("endpoints within scanner jitter of the drawn ones",
      near(min(ax, bx), 10, 2.0) and near(max(ax, bx), 110, 2.0)
      and near(ay, 30, 1.5) and near(by, 30, 1.5),
      str(endpoints(recovered["paths"][0])))
check("stroke width is measured, not assumed",
      1.5 <= recovered["stroke_width"] <= 4.5, str(recovered["stroke_width"]))


section("Corners and junctions break strokes where they should")
bitmap = page(100, 100)
stamp_line(bitmap, 20, 20, 80, 20)
stamp_line(bitmap, 80, 20, 80, 80)
recovered = raster.vectorise(*bitmap)
corner_points = sorted(len(p) for p in recovered["paths"])
check("an L is one bent path holding its corner",
      len(recovered["paths"]) == 1 and len(recovered["paths"][0]) == 3,
      str(recovered["paths"]))
middle = recovered["paths"][0][1] if len(recovered["paths"][0]) == 3 else (0, 0)
check("the corner sits where it was drawn",
      near(middle[0], 80, 2.0) and near(middle[1], 20, 2.0), str(middle))

bitmap = page(100, 100)
stamp_line(bitmap, 10, 50, 90, 50)
stamp_line(bitmap, 50, 10, 50, 90)
recovered = raster.vectorise(*bitmap)
check("a cross splits into four strokes at the junction",
      len(recovered["paths"]) == 4, str(len(recovered["paths"])))
hub_hits = sum(1 for p in recovered["paths"]
               if any(near(x, 50, 3.0) and near(y, 50, 3.0) for x, y in p))
check("all four strokes end at the hub", hub_hits == 4, str(hub_hits))


section("A ring is a closed loop, not four orphans")
bitmap = page(120, 120)
for (x1, y1), (x2, y2) in (((20, 20), (100, 20)), ((100, 20), (100, 100)),
                           ((100, 100), (20, 100)), ((20, 100), (20, 20))):
    stamp_line(bitmap, x1, y1, x2, y2)
recovered = raster.vectorise(*bitmap)
check("one closed path", recovered["closed"] == [True],
      str(recovered["closed"]))
check("simplified to about its four corners",
      3 <= len(recovered["paths"][0]) <= 6, str(len(recovered["paths"][0])))


section("Specks are counted, never built from")
bitmap = page(60, 60)
stamp_line(bitmap, 10, 30, 50, 30)
_w, _h, pixels = bitmap
pixels[5 * 60 + 5] = 0
recovered = raster.vectorise(*bitmap)
check("the stroke survives and the speck is a count",
      len(recovered["paths"]) == 1 and recovered["specks"] + recovered["short"] == 1,
      str((len(recovered["paths"]), recovered["specks"], recovered["short"])))
blank = raster.vectorise(*page(40, 40))
check("a blank page says it is blank",
      blank["paths"] == [] and "blank" in blank["note"], blank["note"])


section("The page's skew is voted by its own strokes")
tilt = math.radians(2.0)
bitmap = page(300, 200)
for (x1, y1), (x2, y2) in (((40, 60), (260, 60)), ((40, 140), (260, 140)),
                           ((60, 40), (60, 160))):
    cx, cy = 150, 100
    r1 = (cx + (x1 - cx) * math.cos(tilt) - (y1 - cy) * math.sin(tilt),
          cy + (x1 - cx) * math.sin(tilt) + (y1 - cy) * math.cos(tilt))
    r2 = (cx + (x2 - cx) * math.cos(tilt) - (y2 - cy) * math.sin(tilt),
          cy + (x2 - cx) * math.sin(tilt) + (y2 - cy) * math.cos(tilt))
    stamp_line(bitmap, r1[0], r1[1], r2[0], r2[1])
recovered = raster.vectorise(*bitmap)
angle, note = raster.deskew_angle(recovered["paths"])
check("two degrees of tilt is found within a fifth of a degree",
      near(math.degrees(abs(angle)), 2.0, 0.2), f"{math.degrees(angle):.3f} deg")
check("the vote is written in a sentence", "weighted median" in note, note)
angle0, note0 = raster.deskew_angle([[(0.0, 0.0), (30.0, 30.0)]])
check("a lone true diagonal casts no vote",
      angle0 == 0.0 and "no near-axis" in note0, note0)


section("Scale is a statement or a refusal")
value, note = raster.metres_per_pixel({"metres_per_pixel": 0.02})
check("a stated scale is taken as stated", value == 0.02 and "stated" in note)
value, note = raster.metres_per_pixel({"dpi": 300, "paper_scale": 100})
check("dpi and paper scale compute the same statement",
      near(value, 0.0254 / 300 * 100, 1e-12), str(value))
value, note = raster.metres_per_pixel({})
check("no statement, no scale", value is None and "human decision" in note, note)
value, note = raster.metres_per_pixel({"dpi": 300})
check("dpi alone is not a statement", value is None)
value, note = raster.metres_per_pixel({"metres_per_pixel": -1})
check("a negative scale is nonsense, said plainly", value is None)


section("The whole recovery lands in the compiler's currency")
bitmap = page(200, 120)
stamp_line(bitmap, 20, 30, 180, 30)   # high on the page
stamp_line(bitmap, 20, 90, 180, 90)   # low on the page
config = {"metres_per_pixel": 0.02, "layer": "WALLS"}
drawing, notes, why = raster.interpret(*bitmap, config)
check("a configured scan yields a drawing", why is None and drawing is not None,
      str(why))
check("everything lands on the stated layer",
      list(drawing.layers) == ["WALLS"] and len(drawing.layers["WALLS"]) == 2)
ys = sorted(polyline.points[0][1] for polyline in drawing.layers["WALLS"])
check("the page's top is the drawing's high y (flipped, scaled)",
      near(ys[0], (119 - 90) * 0.02, 0.05) and near(ys[1], (119 - 30) * 0.02, 0.05),
      str(ys))
check("sources name the scan strokes",
      all(p.source.startswith("SCAN:#") for p in drawing.layers["WALLS"]))
check("the notes carry scale, strokes and the OCR boundary",
      any("stated" in n for n in notes) and any("recovered" in n for n in notes)
      and any("OCR" in n for n in notes), str(notes))

drawing, notes, why = raster.interpret(*bitmap, {"metres_per_pixel": 0.02})
check("no layer statement refuses with the reason",
      drawing is None and "judgement" in why, str(why))
drawing, notes, why = raster.interpret(*bitmap, {"layer": "WALLS"})
check("no scale statement refuses with the reason",
      drawing is None and "human decision" in why, str(why))
drawing, notes, why = raster.interpret(*page(40, 40), config)
check("a blank scan refuses rather than compiling nothing",
      drawing is None and "blank" in why, str(why))


section("A broken through-line rejoins; an ambiguous one stays split")
bitmap = page(200, 120)
stamp_line(bitmap, 20, 60, 180, 60)   # the through wall's face
stamp_line(bitmap, 100, 60, 100, 110)  # a partition face stopping against it
recovered = raster.vectorise(*bitmap)
joined, closed_flags, fused = raster.join_through_lines(
    recovered["paths"], recovered["closed"])
check("the T's crossbar is one stroke again, the stem still ends there",
      fused == 1 and len(joined) == 2,
      str((fused, [len(p) for p in joined])))
spans = sorted(max(math.hypot(p[-1][0] - p[0][0], p[-1][1] - p[0][1])
                   for p in (path,)) for path in joined)
check("the crossbar spans its full drawn run",
      near(spans[-1], 160, 5.0), str(spans))


section("A scanned plan reaches walls and spaces, by rules alone")
walls = importlib.import_module("bonsai_sketch_mode.walls")
spaces = importlib.import_module("bonsai_sketch_mode.spaces")

MPP = 0.02
W, H, MARGIN = 360, 260, 24
TILT = math.radians(1.5)
plan = page(W, H)


def to_scan(mx, my):
    x = MARGIN + mx / MPP
    y = (H - 1) - (MARGIN + my / MPP)
    cx, cy = W / 2, H / 2
    return (cx + (x - cx) * math.cos(TILT) - (y - cy) * math.sin(TILT),
            cy + (x - cx) * math.sin(TILT) + (y - cy) * math.cos(TILT))


def scan_rect(a, b):
    (x1, y1), (x2, y2) = a, b
    for p, q in (((x1, y1), (x2, y1)), ((x2, y1), (x2, y2)),
                 ((x2, y2), (x1, y2)), ((x1, y2), (x1, y1))):
        (sx1, sy1), (sx2, sy2) = to_scan(*p), to_scan(*q)
        stamp_line(plan, sx1, sy1, sx2, sy2)


scan_rect((0, 0), (6, 4))
scan_rect((0.2, 0.2), (5.8, 3.8))
for x in (2.45, 2.55):
    (sx1, sy1), (sx2, sy2) = to_scan(x, 0.2), to_scan(x, 3.8)
    stamp_line(plan, sx1, sy1, sx2, sy2)

drawing, notes, why = raster.interpret(
    *plan, {"metres_per_pixel": MPP, "layer": "WALLS"})
check("the tilted scan compiles into a drawing", why is None, str(why))
check("the deskew found the scanner's tilt",
      any("deskewed -1.5" in n or "deskewed -1.4" in n for n in notes),
      str(notes))
scan_segments = []
for polyline in drawing.layers["WALLS"]:
    run = polyline.points + ([polyline.points[0]] if polyline.closed else [])
    scan_segments += list(zip(run, run[1:]))
candidates, _refused = walls.detect(scan_segments)
check("four perimeter walls and the partition, no fragments",
      len(candidates) == 5
      and sorted(round(c.thickness, 1) for c in candidates)
      == [0.1, 0.2, 0.2, 0.2, 0.2],
      str([(round(c.thickness, 3), round(c.length, 2)) for c in candidates]))
lengths = sorted(round(c.length, 1) for c in candidates)
check("the walls run their full drawn lengths",
      near(lengths[-1], 5.6, 0.2) and near(lengths[-2], 5.6, 0.2)
      and all(near(v, 3.6, 0.2) for v in lengths[:3]), str(lengths))
semantic, junctions = walls.resolve(candidates)
kinds = {}
for junction in junctions:
    kinds[junction.kind] = kinds.get(junction.kind, 0) + 1
check("the corners are Ls and the partition ends are Ts",
      kinds == {"L": 4, "T": 2}, str(kinds))
found = spaces.detect(semantic, junctions)
rooms = found[0] if isinstance(found, tuple) else found
check("both rooms close, at their drawn areas",
      sorted(round(s.area, 1) for s in rooms) == [8.1, 11.7],
      str(sorted(round(s.area, 2) for s in rooms)))


section("PGM round-trips")
bitmap = page(31, 17, 200)
stamp_line(bitmap, 5, 8, 25, 8)
path = os.path.join(tempfile.gettempdir(), "raster_check_fixture.pgm")
raster.write_pgm(path, *bitmap)
width, height, pixels = raster.read_pgm(path)
check("what was written reads back exactly",
      (width, height) == (31, 17) and pixels == bitmap[2])
os.unlink(path)
try:
    raster.read_pgm(__file__)
    check("a non-PGM refuses", False)
except ValueError as exc:
    check("a non-PGM refuses", "PGM" in str(exc), str(exc))


print("\n".join(lines))
print(f"\n{checks} checks, {len(failures)} failures")
if failures:
    sys.exit(1)
