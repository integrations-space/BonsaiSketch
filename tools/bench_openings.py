"""Measure the opening reading against deliberately hostile synthetic plans.

Run with plain Python:

    python3 tools/bench_openings.py

Each drawing states its truth -- where the openings are, how wide, and
what fills them -- and is written out as real DXF text: wall faces, swing
arcs, block inserts, glazing lines, plus the drafting noise that should
convince nobody. The chain then runs blind: parse, explode, pair,
resolve, detect openings.

The metrics stay separate on purpose. Opening detection, door
classification, window classification, width error, position error and
false classifications answer different questions, and one blended
accuracy number would hide exactly the failure a regression introduces.
Interventions -- candidates the system hands to a human instead of
deciding -- are counted too, because a gap alone *should* cost an
intervention, and that cost belongs on the record, not in a guess.

Required cases gate the run with floors; aspirational cases are printed,
not gated -- they are the known limits, stated (a block with no wall gap
anchors nothing; a corner window spans two hosts). Moving one from
aspirational to required is how the detector grows.
"""

import math
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
openings = importlib.import_module("bonsai_sketch_mode.openings")

DETECTION_FLOOR = 0.95      # opening P and R
CLASSIFICATION_FLOOR = 0.90  # door and window P and R, each
WIDTH_ERROR_FLOOR = 0.020    # mean absolute, metres
POSITION_ERROR_FLOOR = 0.050
FALSE_CLASSIFIED_FLOOR = 0   # per whole run, on negative drawings

T = 0.2  # wall thickness throughout, metres


def wall_run(entities, x1, x2, gaps=()):
    """One horizontal wall from x1 to x2 at y=0.1, broken at the gaps."""
    edges = [x1]
    for start, width in sorted(gaps):
        edges += [start, start + width]
    edges.append(x2)
    for a, b in zip(edges[::2], edges[1::2]):
        for y in (0.0, T):
            entities.append(("LINE", {8: "WALLS", 10: a, 20: y, 11: b, 21: y}))


def arc(entities, cx, cy, radius):
    entities.append(("ARC", {8: "DOORS", 10: cx, 20: cy, 40: radius, 50: 0, 51: 90}))


def insert(entities, name, cx, cy):
    entities.append(("INSERT", {8: "SYMB", 2: name, 10: cx, 20: cy}))


def glazing(entities, x1, x2):
    entities.append(("LINE", {8: "WALLS", 10: x1, 20: T / 2, 11: x2, 21: T / 2}))


def text(items):
    pairs = [(0, "SECTION"), (2, "HEADER"), (9, "$INSUNITS"), (70, 6),
             (0, "ENDSEC"), (0, "SECTION"), (2, "ENTITIES")]
    for kind, fields in items:
        pairs.append((0, kind))
        for code, value in fields.items():
            pairs.append((code, value))
    pairs += [(0, "ENDSEC"), (0, "EOF")]
    return "\n".join(str(x) for pair in pairs for x in pair) + "\n"


def build(builder):
    entities = []
    truths = builder(entities)
    return text(entities), truths


# Each truth: (centre x, width, kind) -- kind None means "an opening a
# human must still name", which is an intervention, not a detection miss.


def case_full_evidence(e):
    wall_run(e, 0.0, 5.0, gaps=[(2.0, 0.9)])
    arc(e, 2.0, 0.1, 0.9)
    insert(e, "DOOR-900", 2.45, 0.1)
    return [(2.45, 0.9, "DOOR")]


def case_arc_only(e):
    wall_run(e, 0.0, 5.0, gaps=[(2.0, 0.9)])
    arc(e, 2.9, 0.1, 0.9)
    return [(2.45, 0.9, "DOOR")]


def case_block_only_with_gap(e):
    wall_run(e, 0.0, 5.0, gaps=[(1.4, 0.8)])
    insert(e, "P-DR-01", 1.8, 0.1)
    return [(1.8, 0.8, "DOOR")]


def case_mirrored_block(e):
    wall_run(e, 0.0, 5.0, gaps=[(2.0, 0.9)])
    insert(e, "DOOR-900-MIRRORED", 2.45, 0.15)
    return [(2.45, 0.9, "DOOR")]


def case_rotated_block(e):
    wall_run(e, 0.0, 5.0, gaps=[(2.0, 0.9)])
    insert(e, "M_Door-Single_R90", 2.45, 0.05)
    return [(2.45, 0.9, "DOOR")]


def case_double_door(e):
    wall_run(e, 0.0, 6.0, gaps=[(2.0, 1.8)])
    arc(e, 2.0, 0.1, 0.9)
    arc(e, 3.8, 0.1, 0.9)
    return [(2.9, 1.8, "DOOR")]


def case_sliding_door(e):
    wall_run(e, 0.0, 5.0, gaps=[(2.0, 1.5)])
    insert(e, "SLIDING-DOOR-1500", 2.75, 0.1)
    return [(2.75, 1.5, "DOOR")]


def case_window_block(e):
    wall_run(e, 0.0, 5.0, gaps=[(2.0, 1.2)])
    insert(e, "WINDOW-1200", 2.6, 0.1)
    return [(2.6, 1.2, "WINDOW")]


def case_window_glazing(e):
    wall_run(e, 0.0, 5.0, gaps=[(2.0, 1.2)])
    glazing(e, 2.05, 3.15)
    return [(2.6, 1.2, "WINDOW")]


def case_window_widths(e):
    wall_run(e, 0.0, 8.0, gaps=[(1.0, 0.6), (5.0, 2.4)])
    glazing(e, 1.05, 1.55)
    glazing(e, 5.05, 7.35)
    return [(1.3, 0.6, "WINDOW"), (6.2, 2.4, "WINDOW")]


def case_bare_gap(e):
    wall_run(e, 0.0, 5.0, gaps=[(2.0, 1.1)])
    return [(2.55, 1.1, None)]


def case_drafting_break(e):
    wall_run(e, 0.0, 5.0, gaps=[(2.0, 0.02)])
    return []


def case_column_stub(e):
    wall_run(e, 0.0, 5.0)
    # a 400mm column face touching the wall: two short perpendiculars
    for x in (2.0, 2.4):
        e.append(("LINE", {8: "COLS", 10: x, 20: T, 11: x, 21: T + 0.4}))
    e.append(("LINE", {8: "COLS", 10: 2.0, 20: T + 0.4, 11: 2.4, 21: T + 0.4}))
    return []


def case_dimension_crossing(e):
    wall_run(e, 0.0, 5.0)
    e.append(("LINE", {8: "DIMS", 10: 2.5, 20: -1.0, 11: 2.5, 21: 1.5}))
    return []


def case_adjacent_segments(e):
    # two wall runs meeting end to end: a joint, not an opening
    wall_run(e, 0.0, 2.5)
    wall_run(e, 2.5, 5.0)
    return []


def case_block_no_gap(e):  # aspirational
    wall_run(e, 0.0, 5.0)
    insert(e, "DOOR-900", 2.45, 0.1)
    return [(2.45, 0.9, "DOOR")]


def case_corner_window(e):  # aspirational
    # The window sits at the very end of the wall, wrapping the corner
    # onto a perpendicular return: there is no second collinear piece to
    # state a gap, so nothing anchors.
    wall_run(e, 0.0, 3.4)
    for x in (4.2, 4.4):
        e.append(("LINE", {8: "WALLS", 10: x, 20: 0.1, 11: x, 21: 3.0}))
    glazing(e, 3.45, 4.15)
    return [(3.8, 0.8, "WINDOW")]


REQUIRED = [
    ("door: block + arc + gap", case_full_evidence),
    ("door: arc + gap only", case_arc_only),
    ("door: block + gap only", case_block_only_with_gap),
    ("door: mirrored block", case_mirrored_block),
    ("door: rotated block", case_rotated_block),
    ("door: double, two leaf arcs", case_double_door),
    ("door: sliding, block-named", case_sliding_door),
    ("window: block + gap", case_window_block),
    ("window: glazing lines + gap", case_window_glazing),
    ("window: 600 and 2400 in one wall", case_window_widths),
    ("negative: bare gap stays a question", case_bare_gap),
    ("negative: drafting break", case_drafting_break),
    ("negative: column touching the wall", case_column_stub),
    ("negative: dimension line crossing", case_dimension_crossing),
    ("negative: two adjacent segments", case_adjacent_segments),
]

ASPIRATIONAL = [
    ("block with no wall gap", case_block_no_gap,
     "gaps anchor candidates; a symbol on an unbroken wall waits for wall-gap evidence"),
    ("corner window across two walls", case_corner_window,
     "a wall-end opening has no second collinear piece to state a gap; "
     "needs corner reasoning between hosts"),
]


def run_case(builder):
    dxf_text, truths = build(builder)
    drawing = dxf.parse(dxf_text)
    segs, handles = walls.explode(drawing.layers["WALLS"])
    candidates, unpaired = walls.detect(segs, sources=handles)
    resolved, _junctions = walls.resolve(candidates)
    found, merged = openings.detect(
        resolved,
        arcs=drawing.arcs,
        inserts=drawing.inserts,
        glazing_segments=[segs[i] for i in unpaired],
        glazing_sources=[handles[i] for i in unpaired],
    )
    # openings back into drawing coordinates, for scoring against truth
    placed = []
    for opening in found:
        host = next(w for w in merged if w.id == opening.host_wall)
        dx, dy = host.end[0] - host.start[0], host.end[1] - host.start[1]
        length = math.hypot(dx, dy)
        centre = (host.start[0] + dx / length * opening.position,
                  host.start[1] + dy / length * opening.position)
        placed.append((centre, opening))
    return placed, merged


def main():
    detect_tp = detect_fp = detect_fn = 0
    kind_tp = {"DOOR": 0, "WINDOW": 0}
    kind_fp = {"DOOR": 0, "WINDOW": 0}
    kind_fn = {"DOOR": 0, "WINDOW": 0}
    width_errors = []
    position_errors = []
    false_classified = 0
    interventions = 0
    rows = []

    for name, builder in REQUIRED:
        placed, _merged = run_case(builder)
        _text, truths = build(builder)
        matched_truth = set()
        matched_found = set()
        for f_index, (centre, opening) in enumerate(placed):
            for t_index, (tx, twidth, _tkind) in enumerate(truths):
                if t_index in matched_truth:
                    continue
                if (abs(centre[0] - tx) <= 0.15
                        and abs(opening.width - twidth) <= 0.1 * twidth):
                    matched_truth.add(t_index)
                    matched_found.add(f_index)
                    width_errors.append(abs(opening.width - twidth))
                    position_errors.append(abs(centre[0] - tx))
                    tkind = truths[t_index][2]
                    fkind = opening.classification
                    if tkind is not None:
                        if fkind == tkind:
                            kind_tp[tkind] += 1
                        else:
                            kind_fn[tkind] += 1
                            if fkind in kind_fp:
                                kind_fp[fkind] += 1
                    elif fkind is not None:
                        false_classified += 1
                    break
        case_fp = len(placed) - len(matched_found)
        case_fn = len(truths) - len(matched_truth)
        detect_tp += len(matched_found)
        detect_fp += case_fp
        detect_fn += case_fn
        negative = not truths or all(k is None for _x, _w, k in truths)
        if negative:
            false_classified += sum(
                1 for i, (_c, o) in enumerate(placed)
                if i not in matched_found and o.classification is not None)
        interventions += sum(
            1 for _c, o in placed if o.status != "resolved")
        verdict = "exact" if case_fp == 0 and case_fn == 0 else (
            "MISSED" if case_fn else "EXTRA")
        rows.append((name, len(truths), len(placed), verdict))

    print("OPENING READING -- hostile synthetic ground truth")
    print(f"{'drawing':<40} {'truth':>5} {'found':>5}  verdict")
    for name, truth_count, found_count, verdict in rows:
        print(f"{name:<40} {truth_count:>5} {found_count:>5}  {verdict}")

    def ratio(tp, other):
        return tp / (tp + other) if tp + other else 1.0

    detection_p = ratio(detect_tp, detect_fp)
    detection_r = ratio(detect_tp, detect_fn)
    door_p = ratio(kind_tp["DOOR"], kind_fp["DOOR"])
    door_r = ratio(kind_tp["DOOR"], kind_fn["DOOR"])
    window_p = ratio(kind_tp["WINDOW"], kind_fp["WINDOW"])
    window_r = ratio(kind_tp["WINDOW"], kind_fn["WINDOW"])
    width_mean = sum(width_errors) / len(width_errors) if width_errors else 0.0
    position_mean = sum(position_errors) / len(position_errors) if position_errors else 0.0

    print(f"\nopening detection     P {detection_p:.3f} / R {detection_r:.3f}"
          f"  (floors {DETECTION_FLOOR})")
    print(f"door classification   P {door_p:.3f} / R {door_r:.3f}"
          f"  (floors {CLASSIFICATION_FLOOR})")
    print(f"window classification P {window_p:.3f} / R {window_r:.3f}"
          f"  (floors {CLASSIFICATION_FLOOR})")
    print(f"width error           mean {width_mean * 1000:.1f} mm"
          f"  (floor {WIDTH_ERROR_FLOOR * 1000:.0f} mm)")
    print(f"position error        mean {position_mean * 1000:.1f} mm"
          f"  (floor {POSITION_ERROR_FLOOR * 1000:.0f} mm)")
    print(f"falsely classified    {false_classified}  (floor {FALSE_CLASSIFIED_FLOOR})")
    print(f"interventions asked   {interventions} across {len(REQUIRED)} drawings"
          "  (informational: a bare gap SHOULD cost one)")

    print("\naspirational (reported, not gated):")
    for name, builder, why in ASPIRATIONAL:
        placed, _merged = run_case(builder)
        _text, truths = build(builder)
        outcome = "detected" if placed else "not detected"
        print(f"  {name}: {outcome} -- {why}")

    ok = (detection_p >= DETECTION_FLOOR and detection_r >= DETECTION_FLOOR
          and door_p >= CLASSIFICATION_FLOOR and door_r >= CLASSIFICATION_FLOOR
          and window_p >= CLASSIFICATION_FLOOR and window_r >= CLASSIFICATION_FLOOR
          and width_mean <= WIDTH_ERROR_FLOOR
          and position_mean <= POSITION_ERROR_FLOOR
          and false_classified <= FALSE_CLASSIFIED_FLOOR)
    print("\n" + ("floors held" if ok else "BELOW FLOOR"))
    if not ok:
        sys.exit(1)


main()
