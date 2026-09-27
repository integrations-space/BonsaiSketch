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

"""The failure taxonomy: what real drawings will break, counted by kind.

Real projects will expose cases that do not fit TP/FP/FN, and the point
of naming them is to let measured frequency pick the roadmap: if F07
dominates the hold-outs, space topology is worth more than a stair
generator, and no amount of intuition should outvote that table.

Every human intervention the compiler requests maps to one of these
codes, and :func:`tally` derives the counts from the building report's
*structured* fields -- statuses, lists, flags -- not from parsing prose,
so a reworded diagnostic cannot silently move a failure between
categories. Codes the compiler cannot yet detect are reported as
uninstrumented rather than as zero, because "we did not look" and "we
looked and found none" are different claims.
"""

from __future__ import annotations

from .classify import ANNOTATION_REASON

#: The taxonomy. Stable codes, human names.
CODES = {
    "F01": "Unsupported CAD entity",
    "F02": "Unknown layer convention",
    "F03": "Geometry damaged",
    "F04": "Wall pairing ambiguous",
    "F05": "Junction ambiguous",
    "F06": "Opening ambiguous",
    "F07": "Space not closed",
    "F08": "Drawing type unknown",
    "F09": "Cross-sheet alignment unresolved",
    "F10": "Conflicting evidence",
    "F11": "Missing required evidence",
    "F12": "IFC+SG mapping failure",
    "F13": "External-checker failure",
}

#: What tally() cannot yet see. An uninstrumented code never reads as a
#: reassuring zero.
UNINSTRUMENTED = ("F03", "F05", "F12", "F13")


def tally(report: dict) -> dict:
    """Counts and instances per code, from one building report.

    Returns ``{code: {"name", "count", "instances" | "instrumented":
    False}}`` plus ``"interventions"``, the total of instances -- each
    one is a question the compiler handed to a person instead of
    guessing, which is exactly what an intervention is.
    """
    out: dict = {}
    instances: dict = {code: [] for code in CODES}

    for drawing in report.get("drawings", []):
        for note in drawing.get("diagnostics", []):
            if "outside the drafting subset" in note:
                instances["F01"].append(f"{drawing['id']}: {note}")
        if drawing.get("view_type") == "UNKNOWN":
            instances["F08"].append(f"{drawing['id']} ({drawing['source_file']})")

    for compilation in report.get("compilations", []):
        storey = compilation.get("storey", "?")
        for item in compilation.get("unresolved", []):
            if item.get("reason") != ANNOTATION_REASON:
                instances["F02"].append(f"{storey}: {item['layer']} -- {item['reason']}")
        for stage in compilation.get("stages", []):
            if stage.get("unpaired"):
                instances["F04"].append(
                    f"{storey}: {stage['unpaired']} drawn line(s) left unread")
        for opening in compilation.get("openings", []):
            if opening.get("status") != "resolved":
                instances["F06"].append(
                    f"{storey}: {opening['id']} {opening['status']}")
        if compilation.get("walls") and not compilation.get("spaces"):
            instances["F07"].append(f"{storey}: walls enclose no space")

    for transform in report.get("transforms", []):
        if transform.get("status") == "UNRESOLVED":
            instances["F09"].append(f"{transform['drawing']} ({transform['id']})")

    for conflict in report.get("conflicts", []):
        instances["F10"].append(
            f"{conflict['id']}: {conflict['object']}.{conflict['property']}")

    for assertion in report.get("unmatched_assertions", []):
        instances["F11"].append(
            f"{assertion['mark']}.{assertion['property']} cited, drawn nowhere")
    for storey in report.get("storeys", []):
        if storey.get("elevation") is None:
            instances["F11"].append(f"{storey['id']}: elevation unstated")

    interventions = 0
    for code, name in CODES.items():
        if code in UNINSTRUMENTED:
            out[code] = {"name": name, "instrumented": False}
            continue
        out[code] = {
            "name": name,
            "count": len(instances[code]),
            "instances": list(instances[code]),
        }
        interventions += len(instances[code])
    out["interventions"] = interventions
    return out
