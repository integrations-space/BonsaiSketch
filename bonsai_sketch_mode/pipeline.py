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

"""One command from a drawn plan to an IFC model that knows what it owes.

AUTOMODEL.md's stage 9. Nothing here is new capability: every stage already
exists as a module, an operator or a verb, and this file only runs them in
the order a drafter would -- READ the file, HEAL the linework, STAND the
outlines up, CLASSIFY the layers, ASSIGN the classes, let the MCR
parameters attach, FILL what geometry states, CHECK what is still owed --
writing down what each stage did and, just as deliberately, what it
declined to do.

The report is the deliverable. It goes three places at once: returned as a
dict (what an agent plans against), written into a Text datablock a person
can open in Blender's editor, and summarised to the operator's INFO line.
Its shape is honest by construction because the stages underneath refuse
rather than guess: layers no convention resolves are listed for the agents'
propose/QA/approve flow, values geometry does not state stay null and
named, a shell that is not closed reports no volume.

Composing the existing verbs rather than reimplementing them is the design:
the UI, the text channel, the agents and this pipeline all drive the same
implementations, so a model built by one is indistinguishable from a model
built by another -- which is what makes the pipeline testable at all.
"""

from __future__ import annotations

import os
from typing import Optional

import bpy

from . import bridge, classify, derive, dxf, ir, walls

#: Where the human-readable report lands, findable in Blender's Text editor.
TEXT_NAME = "AutoModel Report"

#: The stages in running order. CLASSIFY moved ahead of STAND when WALLS
#: arrived: which layers are wall layers decides which route their
#: geometry takes, so the naming has to happen before the standing.
STAGES = ("READ", "HEAL", "CLASSIFY", "WALLS", "STAND", "ASSIGN", "MCR", "FILL", "CHECK")


def _as_dxf(path: str, context) -> tuple[Optional[str], str]:
    """The DXF to parse -- the file itself, or a conversion of a DWG."""
    if not path.lower().endswith(".dwg"):
        return path, ""
    from .ops import importer

    prefs = context.preferences.addons.get(__package__)
    converter = getattr(prefs.preferences, "oda_converter", "") if prefs else ""
    return importer.convert_dwg(path, converter)


def _wall_object(context, name: str, wall, height: float):
    """One standing solid from one semantic wall.

    The prism is the wall's resolved centreline widened by half its
    measured thickness each way, stood to the layer's height -- geometry
    with no invented number in it. Where junctions meet, neighbouring
    prisms overlap at the corner by construction: that is the butt-join
    reading, accepted rather than mitred, and written into the wall's
    diagnostics as the decision it is.
    """
    import bmesh

    from .ops import importer

    dx, dy = wall.end[0] - wall.start[0], wall.end[1] - wall.start[1]
    length = (dx * dx + dy * dy) ** 0.5
    ux, uy = dx / length, dy / length
    half = wall.thickness / 2.0
    nx, ny = -uy * half, ux * half
    corners = [
        (wall.start[0] - nx, wall.start[1] - ny),
        (wall.end[0] - nx, wall.end[1] - ny),
        (wall.end[0] + nx, wall.end[1] + ny),
        (wall.start[0] + nx, wall.start[1] + ny),
    ]
    obj = importer.layer_object(context, name)
    solid = bmesh.new()
    try:
        face = solid.faces.new(solid.verts.new((x, y, 0.0)) for x, y in corners)
        if height > 0.0:
            grown = bmesh.ops.extrude_face_region(solid, geom=[face])
            raised = [g for g in grown["geom"] if isinstance(g, bmesh.types.BMVert)]
            bmesh.ops.translate(solid, verts=raised, vec=(0.0, 0.0, height))
            bmesh.ops.recalc_face_normals(solid, faces=list(solid.faces))
        solid.normal_update()
        solid.to_mesh(obj.data)
    finally:
        solid.free()
    obj.data.update()
    wall.diagnostics.append(
        f"built as a butt-ended prism at {height:g} m; corner overlaps accepted"
    )
    return obj


def run(
    context,
    path: str,
    weld: float = 0.001,
    gap: float = 0.01,
    height: float = 3.0,
    heights: Optional[dict] = None,
) -> dict:
    """The whole pipeline over one drawing. Returns the report.

    ``height`` stands every classified-or-not layer up; ``heights`` overrides
    it per layer name (the drawing's own name, without the file stem). One
    number for everything is a blunt instrument on purpose -- a slab's real
    thickness is a judgement this pipeline will not make, and the stand-up
    operator exists precisely to re-cut a layer to a better number later.

    Every stage records what it did; a stage that cannot run records why and
    the pipeline stops rather than papering over it -- except CLASSIFY's
    unresolved layers, which are not a failure but the agents' seam, reported
    and left as sketch geometry every tool still works on.
    """
    from .ops import importer
    from .textmodel import commands

    heights = heights or {}
    report: dict = {
        "path": path, "stages": [], "objects": [], "unresolved": [],
        "walls": [], "junctions": [], "source_map": [],
    }

    def stage(name: str, ok: bool, note: str, **extra) -> bool:
        report["stages"].append(dict({"stage": name, "ok": ok, "note": note}, **extra))
        return ok

    def finish() -> dict:
        write_report(report)
        return report

    # READ ------------------------------------------------------------------
    dxf_path, why_not = _as_dxf(path, context)
    if dxf_path is None:
        stage("READ", False, why_not)
        return finish()
    try:
        with open(dxf_path, encoding="utf-8", errors="replace") as handle:
            drawing = dxf.parse(handle.read())
    except OSError as exc:
        stage("READ", False, f"could not read {dxf_path}: {exc}")
        return finish()
    if not drawing.layers:
        skipped = ", ".join(sorted(drawing.skipped)) or "nothing at all"
        stage("READ", False, f"no drafting linework found -- the file holds {skipped}")
        return finish()
    skipped_note = (
        "; outside the drafting subset: "
        + ", ".join(f"{n} {k}" for k, n in sorted(drawing.skipped.items()))
        if drawing.skipped
        else ""
    )
    stage(
        "READ", True,
        f"{len(drawing.layers)} layer(s) read in {drawing.unit_name}{skipped_note}",
        layers=sorted(drawing.layers),
    )

    # HEAL -- flat: the standing happens per layer later, so each can have
    # its own height rather than the one the import dialog would apply to all.
    stem = os.path.splitext(os.path.basename(path))[0]
    objects, notes = importer.build(context, drawing, stem, weld, gap, 0.0)
    stage("HEAL", True, "; ".join(notes))

    # CLASSIFY -- before any standing, because which layers are wall layers
    # decides which route their geometry takes below.
    resolved, unresolved = classify.classify_all([obj.name for obj in objects])
    report["unresolved"] = [p.as_dict() for p in unresolved]
    stage(
        "CLASSIFY",
        True,
        f"{len(resolved)} layer(s) resolved by convention, "
        f"{len(unresolved)} left for judgement",
    )

    # WALLS -- a wall layer's linework is read as a drafter drew it: parallel
    # pairs become semantic walls, junctions resolve their ends, and each
    # wall becomes its own standing solid. The layer's flat linework object
    # is kept as drawn evidence, not stood into an enclosure blob; a wall
    # layer where nothing pairs falls through to the blob route below,
    # which remains the honest fallback for single-line plans.
    source_map = ir.SourceMap()
    proposal_by_layer = {p.layer: p for p in resolved}
    by_name = {obj.name: obj for obj in objects}
    per_wall: list = []       # (object, proposal, SemanticWall)
    all_junctions: list = []
    walled_layers: set = set()
    leftover_segments = 0
    for proposal in resolved:
        if proposal.ifc_class != "IfcWall":
            continue
        obj = by_name.get(proposal.layer)
        layer_name = proposal.layer.rsplit("/", 1)[-1]
        polylines = drawing.layers.get(layer_name)
        if obj is None or not polylines:
            continue
        segs, handles = walls.explode(polylines)
        candidates, unpaired = walls.detect(segs, sources=handles)
        if not candidates:
            continue
        semantic, junctions = walls.resolve(
            candidates, source_map,
            first_wall=len(per_wall) + 1,
            first_junction=len(all_junctions) + 1,
        )
        walled_layers.add(proposal.layer)
        leftover_segments += len(unpaired)
        all_junctions.extend(junctions)
        target = float(heights.get(layer_name, height))
        for wall in semantic:
            wall_obj = _wall_object(context, f"{proposal.layer}/{wall.id}", wall, target)
            per_wall.append((wall_obj, proposal, wall))
    report["walls"] = [wall.as_dict() for _o, _p, wall in per_wall]
    report["junctions"] = [j.as_dict() for j in all_junctions]
    stage(
        "WALLS",
        True,
        f"{len(per_wall)} wall(s) from parallel pairs across {len(walled_layers)} "
        f"layer(s), {len(all_junctions)} junction(s) resolved"
        + (f"; {leftover_segments} drawn line(s) left unread" if leftover_segments else ""),
    )

    # STAND -- everything the wall reading did not claim.
    stood = 0
    volumes = {}
    for obj in objects:
        if obj.name in walled_layers:
            continue
        layer = obj.name.rsplit("/", 1)[-1]
        target = float(heights.get(layer, height))
        result = importer.stand_up_object(obj, weld, gap, target)
        if result is None:
            continue
        stood += 1
        extents, volume, _base = derive.measure_object(obj)
        if volume is not None:
            volumes[obj.name] = round(volume, 6)
    stage(
        "STAND",
        stood > 0 or bool(per_wall),
        f"{stood} layer(s) stood up as drawn; "
        f"{len(volumes)} closed shell(s) with measurable volume",
        volumes=volumes,
    )

    # ASSIGN ------------------------------------------------------------------
    try:
        commands.run("create_project", {})
    except commands.CommandError as exc:
        stage("ASSIGN", False, f"no project and none could be created: {exc}")
        return finish()
    assigned = []  # (object, proposal, SemanticWall or None)
    refusals = []
    to_assign = [(obj, proposal, wall) for obj, proposal, wall in per_wall] + [
        (by_name[p.layer], p, None)
        for p in resolved
        if p.layer not in walled_layers and p.layer in by_name
    ]
    for obj, proposal, wall in to_assign:
        params = {"object": obj.name, "ifc_class": proposal.ifc_class}
        if proposal.predefined_type:
            params["predefined_type"] = proposal.predefined_type
        try:
            commands.run("assign_class", params)
            assigned.append((obj, proposal, wall))
        except commands.CommandError as exc:
            refusals.append(f"{obj.name}: {exc}")
            continue
        if wall is not None:
            entity = bridge.get_entity(obj)
            if entity is not None:
                wall.ifc_guid = getattr(entity, "GlobalId", None)
                if wall.ifc_guid:
                    source_map.record("EMIT", [wall.id], wall.ifc_guid, f"IfcWall {obj.name}")
    # Re-serialise: the walls now know their GlobalIds, and the report's
    # copy from the WALLS stage predates the emission.
    report["walls"] = [wall.as_dict() for _o, _p, wall in per_wall]
    report["source_map"] = source_map.as_list()
    stage(
        "ASSIGN",
        bool(assigned) or not to_assign,
        f"{len(assigned)} element(s) assigned"
        + (f"; refused: {'; '.join(refusals)}" if refusals else ""),
    )
    if not assigned:
        return finish()

    # MCR -- the creation listener attached the parameters during ASSIGN; this
    # stage only counts what arrived, because a count of zero here is the
    # signal that attachment is switched off or the stage asks nothing.
    import ifcopenshell.util.element

    asked = 0
    for obj, _proposal, _wall in assigned:
        entity = bridge.get_entity(obj)
        if entity is None:
            continue
        for pset_name in (derive.PSET_NAME, derive.DELIVERY_PSET_NAME):
            own = ifcopenshell.util.element.get_pset(entity, pset_name, should_inherit=False)
            if own:
                asked += len(own) - 1  # get_pset smuggles the set's id in
    stage(
        "MCR",
        True,
        f"{asked} required parameter(s) attached as open questions"
        + ("" if asked else " -- attachment may be off, or this stage asks nothing"),
    )

    # FILL --------------------------------------------------------------------
    filled = left = 0
    for obj, proposal, wall in assigned:
        outcome = commands.run("derive_values", {"object": obj.name})
        filled += outcome["filled_count"]
        left += outcome["left_count"]
        report["objects"].append(
            {
                "object": obj.name,
                "layer": proposal.layer,
                "ifc_class": proposal.ifc_class,
                "predefined_type": proposal.predefined_type,
                "wall": wall.id if wall is not None else None,
                "sources": list(wall.sources) if wall is not None else None,
                "filled": outcome["filled"],
                "left": outcome["left"],
            }
        )
    stage(
        "FILL", True,
        f"{filled} value(s) stated by geometry and written; "
        f"{left} left visibly unanswered for judgement",
    )

    # CHECK -------------------------------------------------------------------
    still_missing = 0
    for entry, (obj, _proposal, _wall) in zip(report["objects"], assigned):
        verdict = commands.run("check_ifc_sg", {"object": obj.name})
        entry["check"] = {
            "status": verdict.get("status"),
            "missing": verdict.get("missing", []),
        }
        still_missing += len(verdict.get("missing", []))
    stage(
        "CHECK", True,
        f"{still_missing} parameter(s) still owed across {len(assigned)} element(s) "
        "-- the checker's report closes the loop",
    )
    return finish()


def write_report(report: dict) -> str:
    """The report as prose in a Text datablock, replaced on every run."""
    text = bpy.data.texts.get(TEXT_NAME) or bpy.data.texts.new(TEXT_NAME)
    text.clear()
    lines = [f"AutoModel -- {os.path.basename(report.get('path', ''))}", "=" * 40, ""]
    for entry in report["stages"]:
        mark = "ok " if entry["ok"] else "REFUSED"
        lines.append(f"{entry['stage']:<9} {mark:<8} {entry['note']}")
    if report["unresolved"]:
        lines += ["", "Left for judgement (the agents' seam):"]
        for item in report["unresolved"]:
            lines.append(f"  {item['layer']} -- {item['reason']}")
    if report.get("walls"):
        lines += ["", "Walls, as the drawing states them:"]
        for item in report["walls"]:
            lines.append(
                f"  {item['id']}: {item['length']:.3f} m x {item['thickness']:.3f} m"
                f", from {', '.join(str(s) for s in item['sources'])}"
                + (f"  [{item['ifc_guid']}]" if item.get("ifc_guid") else "")
            )
    if report["objects"]:
        lines += ["", "Elements:"]
        for item in report["objects"]:
            owed = sum(len(v) for v in item["left"].values())
            answered = sum(len(v) for v in item["filled"].values())
            lines.append(
                f"  {item['layer']} -> {item['ifc_class']}"
                + (f"/{item['predefined_type']}" if item["predefined_type"] else "")
                + f": {answered} value(s) from geometry, {owed} still owed"
            )
    text.write("\n".join(lines) + "\n")
    return TEXT_NAME


class BONSAI_SKETCH_MODE_OT_auto_model(bpy.types.Operator):
    bl_idname = "bonsai_sketch_mode.auto_model"
    bl_label = "CAD Drawing to IFC (AutoModel)"
    bl_description = (
        "Run the whole AutoModel pipeline on a DXF or DWG plan: heal the "
        "linework, stand the outlines up, classify the layers by drafting "
        "convention, assign IFC classes, attach the IFC+SG requirements and "
        "fill the values geometry states. The stage-by-stage report lands "
        "in the '" + TEXT_NAME + "' text block; layers and values needing "
        "judgement are listed there, never guessed"
    )
    bl_options = {"REGISTER", "UNDO"}

    filepath: bpy.props.StringProperty(subtype="FILE_PATH")
    filter_glob: bpy.props.StringProperty(default="*.dxf;*.dwg", options={"HIDDEN"})

    height: bpy.props.FloatProperty(
        name="Height",
        description="How tall the enclosed outlines stand, for every layer alike. "
        "Re-cut any layer afterwards with Stand Up Outlines",
        default=3.0,
        min=0.0,
        subtype="DISTANCE",
    )
    weld: bpy.props.FloatProperty(
        name="Weld",
        description="Endpoints closer than this are the same point",
        default=0.001,
        min=0.0,
        subtype="DISTANCE",
    )
    gap: bpy.props.FloatProperty(
        name="Close Gaps Up To",
        description="An outline whose free ends are nearer than this is enclosed",
        default=0.01,
        min=0.0,
        subtype="DISTANCE",
    )

    def invoke(self, context, event):
        context.window_manager.fileselect_add(self)
        return {"RUNNING_MODAL"}

    def execute(self, context):
        report = run(
            context, self.filepath, weld=self.weld, gap=self.gap, height=self.height
        )
        failed = [s for s in report["stages"] if not s["ok"]]
        if failed:
            self.report({"WARNING"}, f"{failed[0]['stage']}: {failed[0]['note']}")
            return {"CANCELLED"} if failed[0]["stage"] == "READ" else {"FINISHED"}
        last = report["stages"][-1]
        self.report({"INFO"}, f"AutoModel ran {len(report['stages'])} stage(s); "
                              f"{last['note']} -- full report in '{TEXT_NAME}'")
        return {"FINISHED"}


def menu_entry(self, context) -> None:
    self.layout.operator(BONSAI_SKETCH_MODE_OT_auto_model.bl_idname)


def register() -> None:
    bpy.utils.register_class(BONSAI_SKETCH_MODE_OT_auto_model)
    bpy.types.TOPBAR_MT_file_import.append(menu_entry)


def unregister() -> None:
    try:
        bpy.types.TOPBAR_MT_file_import.remove(menu_entry)
    except Exception:
        pass
    try:
        bpy.utils.unregister_class(BONSAI_SKETCH_MODE_OT_auto_model)
    except RuntimeError:
        pass
