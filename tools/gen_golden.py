"""Regenerate the golden acceptance project's drawings, byte for byte.

Run with plain Python:

    python3 tools/gen_golden.py

The files under golden/ are committed and permanent: every future
capability must compile them unchanged, which is what protects the
compiler's determinism as features arrive. This script exists for
transparency -- the drawings are generated, not drafted, and anyone can
see exactly what was generated -- and for the day the fixture must
deliberately grow, when the change to this script and the change to
golden/expected.json land together, reviewed as one decision.

golden/expected.json is NOT written here, on purpose. Expectations are
truth stated by hand from the drawings' arithmetic, never captured from
the compiler's own output -- an expectation file regenerated from output
would lock in whatever bug was live on the day it was written.
"""

import json
import os

ROOT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "golden")


def dxf_pairs(*items):
    return "\n".join(str(x) for pair in items for x in pair) + "\n"


def storey_sheet(title, level, dx, dy, rooms, door_mark, window_mark):
    """One acceptance-grade storey: three rooms behind mixed-thickness
    walls, a marked door in one divider, a marked window in the top wall."""

    def line(layer, x1, y1, x2, y2):
        return ((0, "LINE"), (8, layer),
                (10, x1 + dx), (20, y1 + dy), (11, x2 + dx), (21, y2 + dy))

    def word(layer, x, y, words):
        return ((0, "TEXT"), (8, layer), (10, x + dx), (20, y + dy), (1, words))

    entities = []
    entities += line("WALLS", 0, 0, 4000, 0)
    entities += line("WALLS", 4000, 0, 4000, 3000)
    entities += line("WALLS", 0, 3000, 0, 0)
    entities += line("WALLS", 200, 200, 3800, 200)
    entities += line("WALLS", 3800, 200, 3800, 2800)
    entities += line("WALLS", 200, 2800, 200, 200)
    # the top wall's two faces, broken by the 600mm window
    entities += line("WALLS", 0, 3000, 2900, 3000)
    entities += line("WALLS", 3500, 3000, 4000, 3000)
    entities += line("WALLS", 200, 2800, 2900, 2800)
    entities += line("WALLS", 3500, 2800, 3800, 2800)
    entities += line("WALLS", 2900, 2900, 3500, 2900)  # glazing across the gap
    entities += word("MARKS", 3200, 3100, window_mark)
    # divider one, 200mm, broken by the 900mm doorway
    entities += line("WALLS", 1400, 200, 1400, 1200)
    entities += line("WALLS", 1600, 200, 1600, 1200)
    entities += line("WALLS", 1400, 2100, 1400, 2800)
    entities += line("WALLS", 1600, 2100, 1600, 2800)
    entities += ((0, "ARC"), (8, "DOORS"), (10, 1500 + dx), (20, 1200 + dy),
                 (40, 900), (50, 0), (51, 90))
    entities += word("MARKS", 1500, 1650, door_mark)
    # divider two, 100mm, solid -- at x=2500, a clear 400mm from the
    # window jamb at 2900, so its junction with the top wall is solidly
    # interior rather than a knife-edge of the T/L reach window
    entities += line("WALLS", 2450, 200, 2450, 2800)
    entities += line("WALLS", 2550, 200, 2550, 2800)
    entities += line("GRID", 0, -1000, 0, 4000) + word("GRID", 0, -1500, "A")
    entities += line("GRID", 4000, -1000, 4000, 4000) + word("GRID", 4000, -1500, "B")
    entities += line("GRID", -1000, 0, 5000, 0) + word("GRID", -1500, 0, "1")
    entities += word("NOTES", 4500, 4500, title)
    entities += word("NOTES", 4500, 4000, level)
    for x, y, room_label in rooms:
        entities += word("ROOMS", x, y, room_label)
    return dxf_pairs(
        (0, "SECTION"), (2, "HEADER"), (9, "$INSUNITS"), (70, 4), (0, "ENDSEC"),
        (0, "SECTION"), (2, "ENTITIES"), *entities, (0, "ENDSEC"), (0, "EOF"),
    )


SECTION_SHEET = dxf_pairs(
    (0, "SECTION"), (2, "HEADER"), (9, "$INSUNITS"), (70, 4), (0, "ENDSEC"),
    (0, "SECTION"), (2, "ENTITIES"),
    (0, "TEXT"), (8, "NOTES"), (10, 0), (20, 9000), (1, "SECTION A-A"),
    (0, "TEXT"), (8, "NOTES"), (10, 1000), (20, 5000), (1, "D1 H=2100"),
    (0, "TEXT"), (8, "NOTES"), (10, 1000), (20, 4500), (1, "D2 H=2100"),
    (0, "TEXT"), (8, "NOTES"), (10, 1000), (20, 4000), (1, "D1 W=1000"),
    (0, "TEXT"), (8, "NOTES"), (10, 1000), (20, 3000), (1, "D9 H=2000"),
    (0, "ENDSEC"), (0, "EOF"),
)

GEOREFERENCE = {
    "_comment": [
        "The golden project's coordinate reference. Deliberately fictional:",
        "a real submission states its own CRS here, verified against current",
        "authoritative guidance (for Singapore, CORENET-X's).",
    ],
    "projected_crs": {"Name": "FIXTURE:0001",
                      "Description": "stated by the acceptance fixture"},
    "coordinate_operation": {"Eastings": 28001.0, "Northings": 38001.0,
                             "OrthogonalHeight": 5.0, "Scale": 1.0},
}


def main():
    os.makedirs(ROOT, exist_ok=True)
    files = {
        "01_PLAN_GF.dxf": storey_sheet(
            "GROUND FLOOR PLAN", "FFL +0.000", 0, 0,
            [(700, 1500, "HALL"), (2000, 1500, "DEN"), (3200, 1500, "SNUG")],
            "D1", "W1"),
        "02_PLAN_L2.dxf": storey_sheet(
            "SECOND STOREY PLAN", "FFL +3.600", 12500, -8200,
            [(700, 1500, "BED 1"), (2000, 1500, "BED 2"), (3200, 1500, "BED 3")],
            "D2", "W2"),
        "03_SEC_A.dxf": SECTION_SHEET,
    }
    for name, content in files.items():
        with open(os.path.join(ROOT, name), "w", encoding="utf-8") as handle:
            handle.write(content)
        print(f"wrote golden/{name}")
    with open(os.path.join(ROOT, "georeference.json"), "w", encoding="utf-8") as handle:
        json.dump(GEOREFERENCE, handle, indent=1)
        handle.write("\n")
    print("wrote golden/georeference.json")


main()
