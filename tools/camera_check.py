"""Check the two-point camera arithmetic against angles worked by hand.

Run with plain Python:

    python3 tools/camera_check.py

Every answer here is computed on paper first. The refusals matter as much
as the sums: a vertical view has no yaw to keep, and a bird's view gets
levelled without pretending its framing survived.
"""

import math
import sys
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


def near(a, b, tolerance=1e-9):
    return a is not None and abs(a - b) <= tolerance


root = Path(__file__).resolve().parent.parent
package = types.ModuleType("bonsai_sketch_mode")
package.__path__ = [str(root / "bonsai_sketch_mode")]
sys.modules["bonsai_sketch_mode"] = package

import importlib

camera = importlib.import_module("bonsai_sketch_mode.camera")


section("Decomposing a view direction")
pitch, yaw = camera.pitch_yaw((0.0, 1.0, 0.0))
check("looking due north and level: zero pitch, zero yaw",
      near(pitch, 0.0) and near(yaw, 0.0))
pitch, yaw = camera.pitch_yaw((1.0, 0.0, 0.0))
check("looking due east: yaw is a quarter turn clockwise",
      near(pitch, 0.0) and near(yaw, -math.pi / 2.0))
pitch, yaw = camera.pitch_yaw((0.0, 1.0, 1.0))
check("up at forty-five: pitch reads forty-five",
      near(pitch, math.radians(45.0)) and near(yaw, 0.0))
pitch, yaw = camera.pitch_yaw((0.0, math.cos(math.radians(10)), -math.sin(math.radians(10))))
check("down ten degrees: pitch is minus ten",
      near(pitch, math.radians(-10.0), 1e-12))
pitch, yaw = camera.pitch_yaw((0.0, 0.0, -1.0))
check("straight down: no yaw, pitch carries the sign",
      yaw is None and near(pitch, -math.pi / 2.0))
pitch, yaw = camera.pitch_yaw((0.0, 0.0, 1.0))
check("straight up likewise", yaw is None and near(pitch, math.pi / 2.0))


section("The shift that recovers the framing")
check("a level view needs no shift", near(camera.two_point_shift(0.0), 0.0))
# tan(10 deg) * 32 / 36, on paper: 0.176327 * 0.888889 = 0.156735
check("ten degrees up on the default lens",
      near(camera.two_point_shift(math.radians(10.0), 32.0, 36.0),
           math.tan(math.radians(10.0)) * 32.0 / 36.0)
      and abs(camera.two_point_shift(math.radians(10.0), 32.0, 36.0) - 0.156735) < 1e-5)
check("looking down shifts down",
      camera.two_point_shift(math.radians(-20.0)) < 0.0)
check("a longer lens needs more shift for the same tilt",
      camera.two_point_shift(math.radians(10.0), 85.0)
      > camera.two_point_shift(math.radians(10.0), 32.0))


section("Levelling a view")
yaw, shift, note = camera.level((0.0, 1.0, -math.tan(math.radians(15.0))))
check("a gentle survey view levels with its framing kept",
      near(yaw, 0.0) and note == ""
      and near(shift, -math.tan(math.radians(15.0)) * 32.0 / 36.0, 1e-9),
      f"yaw={yaw} shift={shift} note={note!r}")
yaw, shift, note = camera.level((0.0, 1.0, -2.0))
check("a bird's view levels but says the framing was let go",
      yaw is not None and near(shift, 0.0) and "framing not preserved" in note,
      note)
yaw, shift, note = camera.level((0.0, 0.0, -1.0))
check("a plan view is refused outright: nothing horizontal to keep",
      yaw is None and "straight up or down" in note)
yaw, shift, note = camera.level((1.0, 1.0, 0.0))
check("yaw follows the horizontal projection",
      near(yaw, -math.pi / 4.0) and note == "")


section("The constants say what a person expects")
check("eye height is a standing person", 1.4 <= camera.EYE_HEIGHT <= 1.8)
check("the pitch limit sits at forty-five degrees",
      near(camera.MAX_PITCH, math.radians(45.0)))
check("just inside the limit still frames",
      camera.level((0.0, 1.0, math.tan(camera.MAX_PITCH) * 0.999))[2] == "")
check("just outside does not",
      "framing not preserved"
      in camera.level((0.0, 1.0, math.tan(camera.MAX_PITCH) * 1.001))[2])


print("\n".join(lines))
print(f"\n{checks} checks, {len(failures)} failures")
if failures:
    sys.exit(1)
