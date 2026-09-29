"""Score a hold-out's blind run against its frozen truth.

Run with plain Python:

    python3 tools/holdout_score.py holdouts/holdout-001 [results/baseline.json]

Truth was established by hand before the run and lives in truth/; the
run's report lives in results/ (the baseline by default). The score is
per project, never only aggregated, and one number is a hard gate:
silent unsupported assertions must be zero, because a visible
unresolved question is safer than a beautifully modelled claim nothing
supports.
"""

import json
import math
import os
import sys


def load(path):
    with open(path, encoding="utf-8") as handle:
        return json.load(handle)


def ratio(tp, other):
    return tp / (tp + other) if tp + other else None


def fmt(value, pattern="{:.3f}"):
    return "—" if value is None else pattern.format(value)


def main():
    if len(sys.argv) < 2:
        raise SystemExit(__doc__)
    holdout = os.path.abspath(sys.argv[1])
    result_path = (os.path.join(holdout, sys.argv[2]) if len(sys.argv) > 2
                   else os.path.join(holdout, "results", "baseline.json"))
    report = load(result_path)
    truth_dir = os.path.join(holdout, "truth")

    def truth(name):
        path = os.path.join(truth_dir, name)
        return load(path) if os.path.isfile(path) else None

    compilations = report.get("compilations", [])
    got_walls = [w for c in compilations for w in c["walls"]]
    got_spaces = [s for c in compilations for s in c["spaces"]]
    got_openings = []
    for compilation in compilations:
        wall_by_id = {w["id"]: w for w in compilation["walls"]}
        for opening in compilation["openings"]:
            host = wall_by_id.get(opening["host_wall"])
            if host is None:
                continue
            dx = host["end"][0] - host["start"][0]
            dy = host["end"][1] - host["start"][1]
            length = math.hypot(dx, dy) or 1.0
            centre = (host["start"][0] + dx / length * opening["position"],
                      host["start"][1] + dy / length * opening["position"])
            got_openings.append((centre, opening))

    lines = [f"HOLD-OUT — {os.path.basename(holdout)}",
             f"report: {os.path.relpath(result_path, holdout)}", ""]
    gate_failed = False
    truth_total = correct_total = 0

    walls_truth = truth("walls.json")
    if walls_truth is not None:
        matched_truth, matched_got = set(), set()
        for gi, wall in enumerate(got_walls):
            mid = ((wall["start"][0] + wall["end"][0]) / 2,
                   (wall["start"][1] + wall["end"][1]) / 2)
            for ti, want in enumerate(walls_truth):
                if ti in matched_truth:
                    continue
                tmid = ((want["start"][0] + want["end"][0]) / 2,
                        (want["start"][1] + want["end"][1]) / 2)
                if (math.hypot(mid[0] - tmid[0], mid[1] - tmid[1]) <= 0.15
                        and abs(wall["thickness"] - want["thickness"])
                        <= 0.1 * want["thickness"]):
                    matched_truth.add(ti)
                    matched_got.add(gi)
                    break
        tp = len(matched_got)
        fp, fn = len(got_walls) - tp, len(walls_truth) - tp
        truth_total += len(walls_truth)
        correct_total += tp
        lines += ["Walls",
                  f"  TP {tp} / FP {fp} / FN {fn}",
                  f"  precision {fmt(ratio(tp, fp))} / recall {fmt(ratio(tp, fn))}", ""]

    openings_truth = truth("openings.json")
    if openings_truth is not None:
        matched = []
        used = set()
        for centre, opening in got_openings:
            for ti, want in enumerate(openings_truth):
                if ti in used:
                    continue
                if (math.hypot(centre[0] - want["center"][0],
                               centre[1] - want["center"][1]) <= 0.15
                        and abs(opening["width"] - want["width"])
                        <= 0.1 * want["width"]):
                    used.add(ti)
                    matched.append((opening, want))
                    break
        tp = len(matched)
        fp, fn = len(got_openings) - tp, len(openings_truth) - tp
        truth_total += len(openings_truth)
        correct_total += tp
        width_errors = [abs(o["width"] - w["width"]) for o, w in matched]
        lines += ["Openings",
                  f"  opening P {fmt(ratio(tp, fp))} / R {fmt(ratio(tp, fn))}"]
        for kind in ("DOOR", "WINDOW"):
            k_tp = sum(1 for o, w in matched
                       if w["classification"] == kind
                       and o["classification"] == kind)
            k_fn = sum(1 for _o, w in matched if w["classification"] == kind) - k_tp
            k_fp = sum(1 for o, w in matched
                       if o["classification"] == kind
                       and w["classification"] != kind)
            lines.append(f"  {kind.lower()} classification "
                         f"P {fmt(ratio(k_tp, k_fp))} / R {fmt(ratio(k_tp, k_fn))}")
        lines += [f"  width MAE {fmt(1000 * sum(width_errors) / len(width_errors), '{:.1f}')} mm"
                  if width_errors else "  width MAE —", ""]

    spaces_truth = truth("spaces.json")
    if spaces_truth is not None:
        from types import ModuleType
        package = ModuleType("bonsai_sketch_mode")
        package.__path__ = [os.path.join(os.path.dirname(os.path.abspath(__file__)),
                                         "..", "bonsai_sketch_mode")]
        sys.modules.setdefault("bonsai_sketch_mode", package)
        import importlib
        contains = importlib.import_module("bonsai_sketch_mode.spaces").contains

        hits = 0
        label_hits = 0
        deviations = []
        for want in spaces_truth:
            home = next((s for s in got_spaces
                         if contains([tuple(p) for p in s["boundary"]],
                                     tuple(want["inside"]))), None)
            if home is None:
                continue
            hits += 1
            deviations.append(abs(home["area"] - want["area"]) / want["area"])
            if (home.get("label") or "") == want.get("label"):
                label_hits += 1
        truth_total += len(spaces_truth)
        correct_total += hits
        lines += ["Spaces",
                  f"  detected {hits} / {len(spaces_truth)}",
                  f"  area deviation "
                  f"{fmt(100 * max(deviations), '{:.1f}')}% max" if deviations
                  else "  area deviation —",
                  f"  label accuracy {label_hits}/{hits}" if hits else "  label accuracy —",
                  ""]

    storeys_truth = truth("storeys.json")
    if storeys_truth is not None:
        got = [s for s in report.get("storeys", []) if s["elevation"] is not None]
        errors = []
        for want in storeys_truth:
            nearest = min(got, key=lambda s: abs(s["elevation"] - want["elevation"]),
                          default=None)
            if nearest is not None:
                errors.append(abs(nearest["elevation"] - want["elevation"]))
        residuals = [t.get("residual") for t in report.get("transforms", [])
                     if t.get("residual") is not None]
        lines += ["Building",
                  f"  storeys {len(got)} / {len(storeys_truth)}",
                  f"  elevation error max {fmt(1000 * max(errors), '{:.1f}')} mm"
                  if errors else "  elevation error —",
                  f"  cross-sheet residual max {fmt(1000 * max(residuals), '{:.2f}')} mm"
                  if residuals else "  cross-sheet residual —",
                  ""]

    building = report.get("building", {})
    tally = building.get("failures", {})
    lines.append("Failures")
    for code in sorted(k for k in tally if k.startswith("F")):
        entry = tally[code]
        if entry.get("instrumented") is False:
            lines.append(f"  {code} {entry['name']}: uninstrumented")
        elif entry["count"]:
            lines.append(f"  {code} {entry['name']}: {entry['count']}")
    silent = building.get("evidence", {}).get("silently_resolved")
    interventions = tally.get("interventions")
    lines += ["", "Evidence",
              f"  conflicts detected {building.get('evidence', {}).get('conflicts_detected')}",
              f"  human interventions {interventions}",
              f"  silent unsupported assertions {silent}  (gate: 0)"]
    if silent != 0:
        gate_failed = True

    kpi = building.get("kpi", {})
    generated = kpi.get("generated_objects")
    timings = {}
    config_path = os.path.join(holdout, "config", "project.json")
    if os.path.isfile(config_path):
        timings = load(config_path).get("timings", {})
    review = timings.get("review_minutes")
    corrections = timings.get("corrections")
    lines += ["", "KPIs",
              f"  generated objects {generated}",
              f"  correct objects per intervention "
              f"{fmt(correct_total / interventions, '{:.1f}') if interventions else '—'}",
              f"  review minutes / 100 objects "
              + (fmt(100 * review / generated, '{:.1f}')
                 if review and generated else "— (record timings in config)"),
              f"  corrections / 100 objects "
              + (fmt(100 * corrections / generated, '{:.1f}')
                 if corrections is not None and generated else "—"),
              "", "Truth objects reconstructed "
              f"{correct_total} / {truth_total}"]

    print("\n".join(lines))
    if gate_failed:
        print("\nGATE FAILED: silent resolutions must be zero")
        sys.exit(1)


main()
