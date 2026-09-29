"""Check derive.py against solids whose measurements are known analytically.

Run with any Python that has ifcopenshell:

    python3 tools/derive_check.py

No Blender. Everything derive.py does except measure_object() is pure
ifcopenshell, and the measuring side is checked in tools/smoke_test.py where
a real mesh exists. Here the extents, volumes and footprints are stated by
construction -- a 4 x 0.2 x 3 wall encloses 2.4 cubic metres because
arithmetic says so -- which is what makes a wrong answer unarguable.
"""

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


def close(a, b, tolerance=1e-6):
    return a is not None and b is not None and abs(a - b) <= tolerance * max(1.0, abs(b))


# The package's __init__ imports bpy, which plain Python does not have. The
# modules under test are pure, so the package is stood up as an empty shell
# and the modules imported through it -- the same trick their relative
# imports need and nothing more.
root = Path(__file__).resolve().parent.parent
package = types.ModuleType("bonsai_sketch_mode")
package.__path__ = [str(root / "bonsai_sketch_mode")]
sys.modules["bonsai_sketch_mode"] = package

import importlib

derive = importlib.import_module("bonsai_sketch_mode.derive")
psets = importlib.import_module("bonsai_sketch_mode.psets")

import ifcopenshell
import ifcopenshell.api.pset
import ifcopenshell.api.project
import ifcopenshell.api.root
import ifcopenshell.api.unit
import ifcopenshell.util.element


section("Name normalisation")
check("spellings collapse to one key",
      derive._normalise("Overall Height") == derive._normalise("OverallHeight") == "OVERALLHEIGHT")
check("punctuation is spelling too", derive._normalise("Stair Height (Top To Bottom)") ==
      derive._normalise("StairHeight(TopToBottom)"))


section("The wall reading")
# A stood-up wall outline: 4 long, 0.2 thick, 3 high.
wall = derive.measures("IfcWall", (4.0, 0.2, 3.0), volume=2.4, base_area=0.8)
check("height is the vertical extent", close(wall.get("HEIGHT"), 3.0))
check("length runs long", close(wall.get("LENGTH"), 4.0))
check("width runs short", close(wall.get("WIDTH"), 0.2))
check("thickness is the thinnest direction", close(wall.get("THICKNESS"), 0.2))
check("a closed shell states its volume", close(wall.get("VOLUME"), 2.4))
check("a wall's Area stays a question -- elevation or footprint is not the box's call",
      "AREA" not in wall)
check("subclasses read as their parent",
      derive.measures("IfcWallStandardCase", (4.0, 0.2, 3.0)) ==
      derive.measures("IfcWall", (4.0, 0.2, 3.0)))


section("The plate reading")
slab = derive.measures("IfcSlab", (5.0, 4.0, 0.15), volume=3.0, base_area=20.0)
check("a prism slab owns its footprint area", close(slab.get("AREA"), 20.0))
check("its thickness is the thin direction", close(slab.get("THICKNESS"), 0.15))
# A pyramid over the same footprint encloses a third of the prism's volume,
# which is exactly what disqualifies its bottom face from being "the Area".
pyramid = derive.measures("IfcSlab", (2.0, 2.0, 3.0), volume=4.0, base_area=4.0)
check("a non-prism keeps its volume", close(pyramid.get("VOLUME"), 4.0))
check("but its footprint is nobody's Area", "AREA" not in pyramid)


section("Refusals")
open_shell = derive.measures("IfcWall", (4.0, 0.2, 3.0), volume=None, base_area=0.8)
check("an open shell has no volume to report", "VOLUME" not in open_shell)
check("its extents still speak", close(open_shell.get("HEIGHT"), 3.0))
flat = derive.measures("IfcWall", (4.0, 0.2, 0.0))
check("an unextruded outline asserts no height", "HEIGHT" not in flat)
check("nor a thickness through a zero direction", "THICKNESS" not in flat)
column = derive.measures("IfcColumn", (0.4, 0.6, 3.0), volume=0.72, base_area=0.24)
check("a column keeps height and volume",
      close(column.get("HEIGHT"), 3.0) and close(column.get("VOLUME"), 0.72))
check("and gives up its plan dimensions -- b and h are the section's to say",
      not {"LENGTH", "WIDTH", "BREADTH", "AREA"} & set(column))
check("an unknown class keeps only what no reading can change",
      set(derive.measures("IfcChimney", (1.0, 1.0, 8.0), volume=8.0)) == {"HEIGHT", "VOLUME"})
space = derive.measures("IfcSpace", (3.6, 2.6, 3.0), volume=28.08, base_area=9.36)
check("a space's extents are its internal dimensions",
      close(space.get("INTERNALLENGTH"), 3.6) and close(space.get("INTERNALWIDTH"), 2.6)
      and close(space.get("AREA"), 9.36), str(space))


section("The panel reading")
door = derive.measures("IfcDoor", (0.9, 0.05, 2.1))
check("a door's overall width is its larger horizontal extent",
      close(door.get("OVERALLWIDTH"), 0.9))
check("so is its plain Width -- a door is a panel, not a prism",
      close(door.get("WIDTH"), 0.9))
check("overall height is vertical", close(door.get("OVERALLHEIGHT"), 2.1))
check("thickness is the leaf's", close(door.get("THICKNESS"), 0.05))


section("Filling a real file")


def project(unit_prefix=None):
    ifc = ifcopenshell.api.project.create_file(version="IFC4")
    ifcopenshell.api.root.create_entity(ifc, ifc_class="IfcProject", name="Check")
    units = [ifcopenshell.api.unit.add_si_unit(ifc, unit_type="LENGTHUNIT", prefix=unit_prefix),
             ifcopenshell.api.unit.add_si_unit(ifc, unit_type="AREAUNIT", prefix=unit_prefix),
             ifcopenshell.api.unit.add_si_unit(ifc, unit_type="VOLUMEUNIT", prefix=unit_prefix)]
    ifcopenshell.api.unit.assign_unit(ifc, units=units)
    return ifc


def wall_with_questions(ifc, names, delivery_names=()):
    element = ifcopenshell.api.root.create_entity(ifc, ifc_class="IfcWall", name="W")
    for pset_name, asked in ((psets.PSET_NAME, names), (psets.DELIVERY_PSET_NAME, delivery_names)):
        if not asked:
            continue
        pset = ifcopenshell.api.pset.add_pset(ifc, product=element, name=pset_name)
        ifcopenshell.api.pset.edit_pset(
            ifc, pset=pset, properties={n: None for n in asked}, should_purge=False)
    return element


ifc = project()
element = wall_with_questions(
    ifc, ["Height", "Thickness", "Fire Rating"], ["Length", "Volume", "Area", "b"])
report = derive.fill(ifc, element, (4.0, 0.2, 3.0), volume=2.4, base_area=0.8)

own = ifcopenshell.util.element.get_pset(element, psets.PSET_NAME, should_inherit=False)
delivery = ifcopenshell.util.element.get_pset(element, psets.DELIVERY_PSET_NAME,
                                              should_inherit=False)
check("height lands in the IFC+SG set", close(own.get("Height"), 3.0))
check("thickness lands beside it", close(own.get("Thickness"), 0.2))
check("the delivery set fills independently",
      close(delivery.get("Length"), 4.0) and close(delivery.get("Volume"), 2.4))
check("a fire rating is not geometry", own.get("Fire Rating", "sentinel") is None)
check("a wall's Area stays null in the file too", delivery.get("Area", "sentinel") is None)
check("b stays the section's question", delivery.get("b", "sentinel") is None)
check("the report counts what it filled", report["filled_count"] == 4,
      f"got {report['filled_count']}: {report['filled']}")
check("and names what it left", sorted(report["left"].get(psets.PSET_NAME, [])) == ["Fire Rating"]
      and sorted(report["left"].get(psets.DELIVERY_PSET_NAME, [])) == ["Area", "b"],
      f"got {report['left']}")

again = derive.fill(ifc, element, (4.0, 0.2, 3.0), volume=2.4, base_area=0.8)
check("a second pass has nothing to add", again["filled_count"] == 0, f"got {again['filled']}")

ifc2 = project()
element2 = wall_with_questions(ifc2, ["Height", "Thickness"])
pset2 = ifc2.by_id(
    ifcopenshell.util.element.get_pset(element2, psets.PSET_NAME, should_inherit=False)["id"])
ifcopenshell.api.pset.edit_pset(ifc2, pset=pset2, properties={"Height": 99.0})
derive.fill(ifc2, element2, (4.0, 0.2, 3.0), volume=2.4, base_area=0.8)
own2 = ifcopenshell.util.element.get_pset(element2, psets.PSET_NAME, should_inherit=False)
check("a value somebody entered is out of bounds, even a wrong one",
      close(own2.get("Height"), 99.0), f"got {own2.get('Height')!r}")
check("the null beside it still fills", close(own2.get("Thickness"), 0.2))


section("Project units")
mm = project(unit_prefix="MILLI")
element3 = wall_with_questions(mm, ["Height", "Thickness", "Volume"])
derive.fill(mm, element3, (4.0, 0.2, 3.0), volume=2.4, base_area=0.8)
own3 = ifcopenshell.util.element.get_pset(element3, psets.PSET_NAME, should_inherit=False)
check("a millimetre project reads 3000, not 3", close(own3.get("Height"), 3000.0),
      f"got {own3.get('Height')!r}")
check("volumes convert by the cube", close(own3.get("Volume"), 2.4e9),
      f"got {own3.get('Volume')!r}")
check("a file with no units at all is taken as metres",
      derive._unit_scale(ifcopenshell.file(schema="IFC4")) == 1.0)


print("\n".join(lines))
print(f"\n{checks} checks, {len(failures)} failures")
if failures:
    sys.exit(1)
