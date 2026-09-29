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

from . import bridge, classify, derive, dxf, failures, ir, openings, requirements, sg, spaces, walls

#: Where the human-readable report lands, findable in Blender's Text editor.
TEXT_NAME = "AutoModel Report"

#: The stages in running order. CLASSIFY moved ahead of STAND when WALLS
#: arrived: which layers are wall layers decides which route their
#: geometry takes, so the naming has to happen before the standing.
STAGES = ("READ", "HEAL", "CLASSIFY", "WALLS", "OPENINGS", "STAND", "ASSIGN",
          "SPACES", "MCR", "FILL", "CHECK")


def _as_dxf(path: str, context) -> tuple[Optional[str], str]:
    """The DXF to parse -- the file itself, or a conversion of a DWG."""
    if not path.lower().endswith(".dwg"):
        return path, ""
    from .ops import importer

    prefs = context.preferences.addons.get(__package__)
    converter = getattr(prefs.preferences, "oda_converter", "") if prefs else ""
    return importer.convert_dwg(path, converter)


#: Bitmap extensions the scan route accepts. PGM is read here without
#: any imaging library; the rest go through Blender's own image loader.
RASTER_EXTENSIONS = (".pgm", ".png", ".jpg", ".jpeg", ".tif", ".tiff", ".bmp")


def _load_bitmap(path: str):
    """((width, height, pixels), why_not): one greyscale bitmap, rows top
    to bottom, by whichever loader can read it."""
    from . import raster

    if path.lower().endswith(".pgm"):
        try:
            return raster.read_pgm(path), ""
        except (OSError, ValueError) as exc:
            return None, f"could not read the scan: {exc}"
    try:
        image = bpy.data.images.load(path)
    except RuntimeError as exc:
        return None, f"could not load the image: {exc}"
    try:
        width, height = image.size
        floats = image.pixels[:]
        pixels = bytearray(width * height)
        # Blender stores rows bottom-up; the raster reader expects the
        # scan's own order, top-down.
        for y in range(height):
            source_row = (height - 1 - y) * width * 4
            target_row = y * width
            for x in range(width):
                base = source_row + x * 4
                grey = (0.2126 * floats[base] + 0.7152 * floats[base + 1]
                        + 0.0722 * floats[base + 2])
                pixels[target_row + x] = min(255, int(grey * 255.0 + 0.5))
    finally:
        bpy.data.images.remove(image)
    return (width, height, pixels), ""


def _read_sheet(path: str, context):
    """(drawing, notes, why_not): a sheet's geometry however it is stored.

    A DXF (or a DWG through the converter) parses as ever. A scan takes
    the rule-based raster route -- and needs a ``raster.json`` beside it
    stating the scale and the linework layer, because both are human
    decisions a bitmap cannot make.
    """
    if path.lower().endswith(RASTER_EXTENSIONS):
        import json as _json

        from . import raster

        config_path = os.path.join(os.path.dirname(path), "raster.json")
        if not os.path.isfile(config_path):
            return None, [], (
                "a scanned sheet needs raster.json beside it, stating "
                "metres_per_pixel (or dpi and paper_scale) and the linework "
                "layer -- a scan's scale and meaning are human decisions")
        try:
            with open(config_path, encoding="utf-8") as handle:
                config = _json.load(handle)
        except (OSError, ValueError) as exc:
            return None, [], f"raster.json is unreadable: {exc}"
        bitmap, why_not = _load_bitmap(path)
        if bitmap is None:
            return None, [], why_not
        width, height, pixels = bitmap
        return raster.interpret(width, height, pixels, config)

    dxf_path, why_not = _as_dxf(path, context)
    if dxf_path is None:
        return None, [], why_not
    try:
        with open(dxf_path, encoding="utf-8", errors="replace") as handle:
            return dxf.parse(handle.read()), [], None
    except OSError as exc:
        return None, [], f"could not read {dxf_path}: {exc}"


def _prism_object(context, name: str, polygon, height: float, z0: float = 0.0):
    """A standing solid over a stated polygon: the one shape this pipeline
    ever builds, because everything it believes is a footprint and a
    height, and both are on the record. ``z0`` is the storey's floor."""
    import bmesh

    from .ops import importer

    obj = importer.layer_object(context, name)
    solid = bmesh.new()
    try:
        face = solid.faces.new(solid.verts.new((x, y, z0)) for x, y in polygon)
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
    return obj


def _wall_object(context, name: str, wall, height: float, z0: float = 0.0):
    """One standing solid from one semantic wall.

    The prism is the wall's resolved centreline widened by half its
    measured thickness each way, stood to the layer's height -- geometry
    with no invented number in it. Where junctions meet, neighbouring
    prisms overlap at the corner by construction: that is the butt-join
    reading, accepted rather than mitred, and written into the wall's
    diagnostics as the decision it is.
    """
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
    obj = _prism_object(context, name, corners, height, z0)
    wall.diagnostics.append(
        f"built as a butt-ended prism at {height:g} m; corner overlaps accepted"
    )
    return obj


def _assign_space(context, obj, space):
    """Make the space object an IfcSpace, or record exactly why not.

    Spaces are spatial elements, not building elements, so this cannot go
    through the ``assign_class`` verb, which pins the product to
    occurrences on purpose. A refusal is written into the candidate's
    diagnostics rather than raised: the enclosure and its label are
    findings worth keeping whether or not this Bonsai will make the
    element headless.
    """
    props = bridge.root_props()
    if props is None:
        space.diagnostics.append("IfcSpace assignment refused: Bonsai's class properties unavailable")
        return None
    bpy.ops.object.select_all(action="DESELECT")
    obj.select_set(True)
    context.view_layer.objects.active = obj
    try:
        props.ifc_product = "IfcSpatialElement"
        props.ifc_class = "IfcSpace"
        bpy.ops.bim.assign_class()
    except Exception as exc:
        space.diagnostics.append(f"IfcSpace assignment refused: {exc}")
        return None
    entity = bridge.get_entity(obj)
    if entity is None:
        space.diagnostics.append("IfcSpace assignment refused: no element came back")
        return None
    if space.label:
        try:
            entity.Name = space.label
            entity.LongName = space.label
        except Exception:
            pass
    space.ifc_guid = getattr(entity, "GlobalId", None)
    return space.ifc_guid


def _fill_measured(ifc_file, entity, normalized_name, value_metres, note) -> int:
    """Answer every null property spelt like this with an earned value.

    The same contract as derive.fill: only nulls are written, the value
    converts into project units, and the note lands on nothing -- the
    caller records where the answer came from, because the caller holds
    the evidence.
    """
    import ifcopenshell.api.pset

    scale = derive._unit_scale(ifc_file)
    written = 0
    for pset in derive._own_psets(entity):
        answers = {}
        for prop in pset.HasProperties or ():
            if (prop.is_a("IfcPropertySingleValue")
                    and derive._normalise(prop.Name) == normalized_name
                    and prop.NominalValue is None):
                answers[prop.Name] = round(value_metres / scale, 6)
        if answers:
            ifcopenshell.api.pset.edit_pset(
                ifc_file, pset=pset, properties=dict(answers), should_purge=False)
            written += len(answers)
    return written


def _fill_space_name(ifc_file, entity, space) -> bool:
    """Answer a null 'Space Name' with the drawing's own label.

    Not geometry, but stated evidence all the same: the drawing wrote the
    name, the label's source handle is on the record, and the fill is
    written down as coming from it. Only a null is ever written to, the
    same contract derive.py keeps.
    """
    if not space.label:
        return False
    import ifcopenshell.api.pset

    for pset in derive._own_psets(entity):
        for prop in pset.HasProperties or ():
            if (
                prop.is_a("IfcPropertySingleValue")
                and prop.Name == "Space Name"
                and prop.NominalValue is None
            ):
                ifcopenshell.api.pset.edit_pset(
                    ifc_file, pset=pset,
                    properties={"Space Name": space.label}, should_purge=False,
                )
                space.diagnostics.append(
                    f"Space Name filled from drawing label {space.label_source or '?'}"
                )
                return True
    return False


def run(
    context,
    path: str,
    weld: float = 0.001,
    gap: float = 0.01,
    height: float = 3.0,
    heights: Optional[dict] = None,
    drawing=None,
    elevation: float = 0.0,
    container=None,
    source_map: Optional[ir.SourceMap] = None,
    shared: Optional[dict] = None,
    text_name: Optional[str] = TEXT_NAME,
    collect: Optional[dict] = None,
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

    The building compiler drives this same function once per storey:
    ``drawing`` supplies an already-parsed (and already-transformed) sheet,
    ``elevation`` is the storey's floor, ``container`` the IfcBuildingStorey
    everything emitted belongs to, ``source_map`` and ``shared`` keep one
    ledger and one id sequence across the whole building -- a name that
    means two things is worse than no name -- and ``text_name=None`` leaves
    the combined report to the caller.
    """
    from .ops import importer
    from .textmodel import commands

    heights = heights or {}
    shared = shared if shared is not None else {
        "wall": 0, "junction": 0, "opening": 0, "merge": 0, "space": 0}
    if source_map is None:
        source_map = ir.SourceMap()
    report: dict = {
        "path": path, "stages": [], "objects": [], "unresolved": [],
        "walls": [], "junctions": [], "openings": [], "merges": [],
        "spaces": [], "source_map": [],
    }

    def stage(name: str, ok: bool, note: str, **extra) -> bool:
        report["stages"].append(dict({"stage": name, "ok": ok, "note": note}, **extra))
        return ok

    def finish() -> dict:
        if text_name:
            write_report(report, text_name)
        return report

    # READ ------------------------------------------------------------------
    scan_notes = []
    if drawing is None:
        drawing, scan_notes, why_not = _read_sheet(path, context)
        if drawing is None:
            stage("READ", False, why_not)
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
    scan_note = "; " + "; ".join(scan_notes) if scan_notes else ""
    stage(
        "READ", True,
        f"{len(drawing.layers)} layer(s) read in {drawing.unit_name}"
        f"{skipped_note}{scan_note}",
        layers=sorted(drawing.layers),
    )

    # HEAL -- flat: the standing happens per layer later, so each can have
    # its own height rather than the one the import dialog would apply to all.
    stem = os.path.splitext(os.path.basename(path))[0]
    objects, notes, heal_stats = importer.build(context, drawing, stem, weld, gap, 0.0)
    stage("HEAL", True, "; ".join(notes), unfaceable=heal_stats["unfaceable"])

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
    # pairs become semantic walls and junctions resolve their ends. The
    # solids wait until OPENINGS has spoken, because a doorway merges its
    # host first. The layer's flat linework stays as drawn evidence, and a
    # wall layer where nothing pairs falls through to the blob route below,
    # which remains the honest fallback for single-line plans.
    by_name = {obj.name: obj for obj in objects}
    wall_layers: list = []    # (proposal, semantic walls, glazing segs/handles)
    all_junctions: list = []
    walled_layers: set = set()
    leftover_segments = 0
    paired = 0
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
            first_wall=shared["wall"] + 1,
            first_junction=shared["junction"] + 1,
        )
        paired += len(candidates)
        shared["wall"] += len(candidates)
        shared["junction"] += len(junctions)
        walled_layers.add(proposal.layer)
        leftover_segments += len(unpaired)
        all_junctions.extend(junctions)
        wall_layers.append(
            (proposal, semantic,
             [segs[i] for i in unpaired], [handles[i] for i in unpaired])
        )
    report["junctions"] = [j.as_dict() for j in all_junctions]
    stage(
        "WALLS",
        True,
        f"{paired} wall(s) from parallel pairs across {len(walled_layers)} "
        f"layer(s), {len(all_junctions)} junction(s) resolved"
        + (f"; {leftover_segments} drawn line(s) left unread" if leftover_segments else ""),
        unpaired=leftover_segments,
    )

    # OPENINGS -- where independent evidence converges. Wall gaps anchor the
    # candidates, arcs and blocks and glazing lines classify them, and each
    # interrupted host merges across its gap with the merge on the record.
    # Only then does every wall become its own standing solid.
    all_openings: list = []
    all_merges: list = []
    per_wall: list = []       # (object, proposal, SemanticWall)
    for proposal, semantic, glazing_segs, glazing_srcs in wall_layers:
        found, semantic = openings.detect(
            semantic,
            arcs=drawing.arcs,
            inserts=drawing.inserts,
            glazing_segments=glazing_segs,
            glazing_sources=glazing_srcs,
            labels=drawing.texts,
            source_map=source_map,
            first=shared["opening"] + 1,
        )
        all_openings.extend(found)
        shared["opening"] += len(found)
        # Continuation after openings: doorway gaps are already
        # explained, so what remains is drafting fragmentation, judged
        # predicate by predicate and recorded either way.
        semantic, merges = walls.merge_continuations(
            semantic,
            junctions=all_junctions,
            openings=all_openings,
            source_map=source_map,
            first=shared["merge"] + 1,
        )
        all_merges.extend(merges)
        shared["merge"] += len(merges)
        target = float(heights.get(proposal.layer.rsplit("/", 1)[-1], height))
        for wall in semantic:
            wall_obj = _wall_object(
                context, f"{proposal.layer}/{wall.id}", wall, target, z0=elevation)
            per_wall.append((wall_obj, proposal, wall))
    report["walls"] = [wall.as_dict() for _o, _p, wall in per_wall]
    report["openings"] = [o.as_dict() for o in all_openings]
    report["merges"] = [m.as_dict() for m in all_merges]
    if collect is not None:
        collect.setdefault("openings", []).extend(all_openings)
    resolved_openings = sum(1 for o in all_openings if o.status == "resolved")
    continued = sum(1 for m in all_merges if m.decision == "MERGE_GEOMETRY")
    stage(
        "OPENINGS",
        True,
        f"{len(all_openings)} opening(s) anchored on wall gaps; "
        f"{resolved_openings} resolved by converging evidence, "
        f"{len(all_openings) - resolved_openings} awaiting judgement; "
        f"{continued} continuation(s) merged of {len(all_merges)} considered",
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
        if elevation:
            obj.location.z = elevation
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
    wall_entities: dict = {}
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
                wall_entities[wall.id] = entity
                wall.ifc_guid = getattr(entity, "GlobalId", None)
                if wall.ifc_guid:
                    source_map.record("EMIT", [wall.id], wall.ifc_guid, f"IfcWall {obj.name}")

    # Openings void their hosts and, where the evidence resolved, are
    # filled -- the proper chain, IfcRelVoidsElement then
    # IfcRelFillsElement, never a cut in the wall's geometry. A filling's
    # width is the measured gap; its height stays a visible question until
    # section or elevation evidence exists to state one.
    import ifcopenshell.api.feature
    import ifcopenshell.api.root
    import ifcopenshell.api.spatial

    ifc = bridge.ifc_file()
    wall_by_id = {wall.id: wall for _o, _p, wall in per_wall}
    storeys = ifc.by_type("IfcBuildingStorey") if ifc is not None else []
    filling_entries: list = []
    for opening in all_openings:
        host_entity = wall_entities.get(opening.host_wall)
        if host_entity is None:
            opening.diagnostics.append("host wall was not emitted; the opening stays in the report")
            continue
        opening_entity = ifcopenshell.api.root.create_entity(
            ifc, ifc_class="IfcOpeningElement", name=opening.id)
        ifcopenshell.api.feature.add_feature(ifc, feature=opening_entity, element=host_entity)
        opening.opening_guid = opening_entity.GlobalId
        source_map.record("EMIT", [opening.id], opening.opening_guid,
                          f"IfcOpeningElement voids {opening.host_wall}")
        if opening.status != "resolved" or opening.classification not in ("DOOR", "WINDOW"):
            continue
        filling_class = "IfcDoor" if opening.classification == "DOOR" else "IfcWindow"
        filling = ifcopenshell.api.root.create_entity(
            ifc, ifc_class=filling_class,
            name=f"{opening.id} {opening.classification.title()}")
        ifcopenshell.api.feature.add_filling(ifc, opening=opening_entity, element=filling)
        if storeys:
            ifcopenshell.api.spatial.assign_container(
                ifc, products=[filling], relating_structure=storeys[0])
        opening.element_guid = filling.GlobalId
        source_map.record("EMIT", [opening.id], opening.element_guid,
                          f"{filling_class} fills {opening.id}")
        host = wall_by_id[opening.host_wall]
        outcome = derive.fill(ifc, filling, (opening.width, host.thickness, 0.0))
        opening.diagnostics.append(
            "width filled from the measured gap; height awaits section/elevation evidence")
        verdict = requirements.check_element(
            filling_class, sg.stage(), bridge.element_properties(filling))
        filling_entries.append(
            {
                "object": None,
                "layer": opening.id,
                "ifc_class": filling_class,
                "predefined_type": None,
                "wall": None,
                "opening": opening.id,
                "sources": list(opening.sources),
                "filled": outcome["filled"],
                "left": outcome["left"],
                "check": {"status": verdict.get("status"),
                          "missing": verdict.get("missing", [])},
            }
        )

    # Re-serialise: walls and openings now know their GlobalIds, and the
    # report's copies from the earlier stages predate the emission.
    report["walls"] = [wall.as_dict() for _o, _p, wall in per_wall]
    report["openings"] = [o.as_dict() for o in all_openings]
    report["source_map"] = source_map.as_list()
    stage(
        "ASSIGN",
        bool(assigned) or not to_assign,
        f"{len(assigned)} element(s) assigned; {len(all_openings)} opening(s) emitted, "
        f"{len(filling_entries)} filled as doors or windows"
        + (f"; refused: {'; '.join(refusals)}" if refusals else ""),
    )
    if not assigned:
        return finish()

    # SPACES -- what the walls enclose, named by the drawing's own words.
    # Enclosure and label are findings worth reporting even where the
    # IfcSpace element cannot be made; the diagnostics say which happened.
    space_candidates = []
    emitted_spaces = 0
    if per_wall:
        semantic_walls = [wall for _obj, _proposal, wall in per_wall]
        space_candidates = spaces.detect(
            semantic_walls, all_junctions, drawing.texts, source_map,
            first=shared["space"] + 1,
        )
        shared["space"] += len(space_candidates)
        for space in space_candidates:
            space_obj = _prism_object(
                context, f"{stem}/{space.id}", space.boundary, height, z0=elevation)
            guid = _assign_space(context, space_obj, space)
            if guid:
                emitted_spaces += 1
                source_map.record("EMIT", [space.id], guid, f"IfcSpace {space_obj.name}")
                entity = bridge.get_entity(space_obj)
                if entity is not None:
                    _fill_space_name(bridge.ifc_file(), entity, space)
                assigned.append((space_obj, classify.Proposal(space.id, "IfcSpace"), None))
    # The openings now say which rooms they join -- the relationship a
    # door actually is, and the reason space detection was right not to
    # close doorway gaps itself.
    connections = 0
    for opening in all_openings:
        host = wall_by_id.get(opening.host_wall)
        if host is None:
            continue
        opening.connects = openings.connects(opening, host, space_candidates)
        connections += len(opening.connects)
        for space_id in opening.connects:
            source_map.record("CONNECT", [opening.id], space_id, "opens into it")
    # The building compiler says which storey owns what was emitted;
    # standalone runs leave Bonsai's default containment alone.
    if container is not None:
        import ifcopenshell.api.aggregate
        import ifcopenshell.api.spatial

        contained = list(wall_entities.values())
        held = [bridge.ifc_file().by_guid(o.element_guid)
                for o in all_openings if o.element_guid]
        if contained or held:
            ifcopenshell.api.spatial.assign_container(
                bridge.ifc_file(), products=contained + held,
                relating_structure=container)
        housed = [bridge.ifc_file().by_guid(s.ifc_guid)
                  for s in space_candidates if s.ifc_guid]
        if housed:
            ifcopenshell.api.aggregate.assign_object(
                bridge.ifc_file(), products=housed, relating_object=container)
    report["openings"] = [o.as_dict() for o in all_openings]
    report["spaces"] = [space.as_dict() for space in space_candidates]
    report["source_map"] = source_map.as_list()
    named = sum(1 for space in space_candidates if space.label)
    stage(
        "SPACES", True,
        f"{len(space_candidates)} space(s) enclosed, {named} named by the drawing, "
        f"{emitted_spaces} became IfcSpace; {connections} door/space connection(s)",
    )

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
    # The fillings were checked at emission -- they have no Blender object
    # for the checker verb to start from -- and join the ledger here.
    still_missing += sum(len(e["check"]["missing"]) for e in filling_entries)
    report["objects"].extend(filling_entries)
    stage(
        "CHECK", True,
        f"{still_missing} parameter(s) still owed across "
        f"{len(assigned) + len(filling_entries)} element(s) "
        "-- the checker's report closes the loop",
    )
    return finish()


def write_report(report: dict, text_name: str = TEXT_NAME) -> str:
    """The report as prose in a Text datablock, replaced on every run."""
    text = bpy.data.texts.get(text_name) or bpy.data.texts.new(text_name)
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
    if report.get("openings"):
        lines += ["", "Openings, where the evidence converged:"]
        for item in report["openings"]:
            what = item["classification"] or "unclassified"
            lines.append(
                f"  {item['id']} {what} ({item['status']}): {item['width']:.3f} m in "
                f"{item['host_wall']} at {item['position']:.3f} m"
                + (f", connects {', '.join(item['connects'])}" if item["connects"] else "")
                + (f"  [{item['element_guid']}]" if item.get("element_guid") else "")
            )
    if report.get("spaces"):
        lines += ["", "Spaces, as the walls enclose them:"]
        for item in report["spaces"]:
            lines.append(
                f"  {item['id']} {item['label'] or '(unnamed)'}: {item['area']:.3f} m2, "
                f"bounded by {', '.join(item['walls'])}"
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
    return text_name


#: Where the building-level report lands.
BUILDING_TEXT_NAME = "AutoModel Building Report"


def run_set(
    context,
    paths,
    weld: float = 0.001,
    gap: float = 0.01,
    height: float = 3.0,
    heights: Optional[dict] = None,
    georeference: Optional[dict] = None,
) -> dict:
    """A drawing set compiled into one building. Returns the report.

    The plan compiler above runs once per storey; this pass does what no
    single sheet can: establish each drawing's identity, earn the
    transforms that put the sheets in one coordinate system, assemble
    the storeys from level evidence, hold one ledger and one id sequence
    across the whole building, and ask the cross-storey questions at the
    end. A sheet whose transform is UNRESOLVED or whose elevation nobody
    stated is reported and skipped, never guessed into place.
    """
    from . import drawings as drawings_module
    from . import align, storeys as storeys_module
    from .textmodel import commands

    report: dict = {
        "paths": list(paths), "drawings": [], "transforms": [],
        "storeys": [], "compilations": [], "building": {}, "source_map": [],
    }
    source_map = ir.SourceMap()

    parsed = {}
    candidates = []
    for index, path in enumerate(paths, 1):
        drawing_id = "D%02d" % index
        sheet, scan_notes, why_not = _read_sheet(path, context)
        if sheet is None:
            broken = ir.DrawingCandidate(drawing_id, os.path.basename(path))
            broken.diagnostics.append(why_not)
            candidates.append(broken)
            continue
        stem = os.path.splitext(os.path.basename(path))[0]
        candidate = drawings_module.classify(drawing_id, stem, sheet)
        candidate.evidence.extend(scan_notes)
        parsed[drawing_id] = (path, sheet)
        candidates.append(candidate)

    plans = [c for c in candidates if c.view_type == "PLAN"]
    transforms = {}
    if plans:
        reference = plans[0]
        for number, candidate in enumerate(plans, 1):
            transform = align.to_reference(candidate, reference, "T%02d" % number)
            transforms[transform.id] = transform
            source_map.record(
                "ALIGN", [candidate.id, reference.id], transform.id,
                f"{transform.status}"
                + (f", residual {transform.residual * 1000:.1f} mm"
                   if transform.residual is not None else ""),
            )

    storey_candidates = storeys_module.build(plans)
    shared = {"wall": 0, "junction": 0, "opening": 0, "merge": 0, "space": 0}
    collected: dict = {}
    compiled = 0
    if storey_candidates:
        commands.run("create_project", {})
        ifc = bridge.ifc_file()
        buildings = ifc.by_type("IfcBuilding")
        scale = derive._unit_scale(ifc)
        import ifcopenshell.api.aggregate
        import ifcopenshell.api.root

        for storey in storey_candidates:
            plan_candidate = next(c for c in plans if c.id == storey.plans[0])
            transform = transforms.get(plan_candidate.transform or "")
            if storey.elevation is None:
                storey.diagnostics.append("not compiled: elevation unknown")
                continue
            if transform is None or transform.status == "UNRESOLVED":
                storey.diagnostics.append(
                    "not compiled: no earned transform places this sheet")
                continue
            path, sheet = parsed[plan_candidate.id]
            _transform_drawing(sheet, transform)
            storey_entity = ifcopenshell.api.root.create_entity(
                ifc, ifc_class="IfcBuildingStorey", name=storey.name)
            if buildings:
                ifcopenshell.api.aggregate.assign_object(
                    ifc, products=[storey_entity], relating_object=buildings[0])
            try:
                storey_entity.Elevation = storey.elevation / scale
            except Exception:
                pass
            storey.ifc_guid = storey_entity.GlobalId
            source_map.record("EMIT", [storey.id], storey.ifc_guid,
                              f"IfcBuildingStorey at {storey.elevation:g} m")
            sub_report = run(
                context, path, weld=weld, gap=gap, height=height, heights=heights,
                drawing=sheet, elevation=storey.elevation, container=storey_entity,
                source_map=source_map, shared=shared, text_name=None,
                collect=collected,
            )
            compiled += 1
            report["compilations"].append({
                "storey": storey.id,
                "stages": sub_report["stages"],
                "walls": sub_report["walls"],
                "openings": sub_report["openings"],
                "merges": sub_report["merges"],
                "spaces": sub_report["spaces"],
                "objects": sub_report["objects"],
                "unresolved": sub_report["unresolved"],
            })

    # The other views speak now: sections and elevations contribute
    # evidence to the openings the plans already made -- never duplicate
    # objects -- and disagreement becomes a Conflict, never arithmetic.
    # Two dialects of the same currency: the assertion grammar (a note a
    # drafter writes) and the drawn geometry itself (levels for the
    # datum, jamb pairs for the openings), reconciled identically.
    from . import reconcile as reconcile_module
    from . import sections as sections_module

    assertions = []
    storey_conflicts = []
    for candidate in candidates:
        if candidate.view_type in ("SECTION", "ELEVATION") and candidate.id in parsed:
            sheet_drawing = parsed[candidate.id][1]
            assertions += reconcile_module.extract(candidate, sheet_drawing)
            drawn, level_lines = sections_module.extract_geometry(candidate, sheet_drawing)
            assertions += drawn
            for assertion in drawn:
                source_map.record(
                    "MEASURE", [assertion.source], assertion.mark,
                    f"{assertion.property} = {assertion.value:g} m off drawn geometry")
            storey_conflicts += sections_module.corroborate_storeys(
                storey_candidates, level_lines, candidate,
                first_conflict=len(storey_conflicts) + 1)
    all_ir_openings = collected.get("openings", [])
    fills, conflicts, unmatched = reconcile_module.reconcile(
        all_ir_openings, assertions, source_map,
        first_conflict=len(storey_conflicts) + 1)
    conflicts = storey_conflicts + conflicts
    for conflict in storey_conflicts:
        source_map.record(
            "CONFLICT", [e["source"] for e in conflict.evidence], conflict.id,
            f"{conflict.object}.{conflict.property}: human review")
    filled_count = 0
    if fills and bridge.has_project():
        ifc = bridge.ifc_file()
        for opening, property, value, sources in fills:
            if not opening.element_guid:
                opening.diagnostics.append(
                    f"{property} corroborated but no element was emitted to carry it")
                continue
            entity = ifc.by_guid(opening.element_guid)
            wrote = _fill_measured(
                ifc, entity, derive._normalise(property), value,
                f"{property} from {', '.join(sources)}")
            if wrote:
                filled_count += wrote
                opening.diagnostics.append(
                    f"{property} filled from view evidence: {', '.join(sources)}")
                source_map.record("ASSERT", sources, opening.element_guid,
                                  f"{property} written to the element")
    report["assertions"] = [a.as_dict() for a in assertions]
    report["conflicts"] = [c.as_dict() for c in conflicts]
    report["unmatched_assertions"] = [a.as_dict() for a in unmatched]

    report["drawings"] = [c.as_dict() for c in candidates]
    report["transforms"] = [t.as_dict() for t in transforms.values()]
    report["storeys"] = [s.as_dict() for s in storey_candidates]
    # Openings re-serialise: marks, corroborations and contests arrived
    # after the per-storey reports were cut.
    for compilation in report["compilations"]:
        ids = {o["id"] for o in compilation["openings"]}
        compilation["openings"] = [
            o.as_dict() for o in all_ir_openings if o.id in ids]
    report["building"] = _cross_storey_qa(report["compilations"], storey_candidates)
    report["building"]["compiled_storeys"] = compiled
    report["building"]["georeference"] = _georeference(
        paths, georeference, source_map)
    report["building"]["evidence"] = {
        "assertions": len(assertions),
        "values_filled": filled_count,
        "conflicts_detected": len(conflicts),
        "conflicts_escalated": len(conflicts),
        "silently_resolved": 0,
        "unmatched_marks": sorted({a.mark for a in unmatched}),
    }
    # An external checker's results, when someone has recorded them
    # beside the drawings -- schema validation never stands in for
    # regulatory acceptance, so the difference is an explicit state.
    external = None
    for sheet_path in paths:
        candidate_path = os.path.join(os.path.dirname(sheet_path), "external_checker.json")
        if os.path.isfile(candidate_path):
            import json as _json

            try:
                with open(candidate_path, encoding="utf-8") as handle:
                    external = dict(_json.load(handle), status="recorded")
            except (OSError, ValueError) as exc:
                external = {"status": "broken", "note": str(exc)}
            break
    report["building"]["external"] = external or {
        "status": "not run",
        "note": "schema validation is not regulatory acceptance; record the "
                "checker's results as external_checker.json beside the drawings",
    }

    # Every intervention the compiler asked for, mapped to its failure
    # code -- the table that lets measured frequency pick the roadmap.
    report["building"]["failures"] = failures.tally(report)
    generated = sum(len(c["objects"]) for c in report["compilations"])
    interventions = report["building"]["failures"]["interventions"]
    report["building"]["kpi"] = {
        "generated_objects": generated,
        "interventions": interventions,
        # How much correct model arrives before a person must step in --
        # commercially, the number that matters more than raw accuracy.
        "objects_per_intervention": (
            round(generated / interventions, 1) if interventions else None),
        # Only a person with a stopwatch can fill these; a synthetic run
        # asserting them would be theatre.
        "human_review_minutes_per_100_objects": None,
        "corrections_per_100_objects": None,
    }
    report["source_map"] = source_map.as_list()
    _write_building_report(report)
    return report


def _georeference(paths, config, source_map) -> dict:
    """Apply the configured coordinate reference, or say plainly that none is.

    The CRS is data, never code: it comes from an explicit ``georeference``
    parameter or a ``georeference.json`` beside the first sheet, because the
    right reference system -- CORENET-X's included -- is the project's to
    state against current authoritative guidance, not this module's to
    freeze in. Absent configuration is a visible state, not a default.
    """
    if config is None:
        for path in paths:
            candidate_path = os.path.join(os.path.dirname(path), "georeference.json")
            if os.path.isfile(candidate_path):
                import json

                try:
                    with open(candidate_path, encoding="utf-8") as handle:
                        config = json.load(handle)
                except (OSError, ValueError) as exc:
                    return {"status": "broken",
                            "note": f"georeference.json unreadable: {exc}"}
                break
    if not config:
        return {
            "status": "absent",
            "note": (
                "no coordinate reference configured; supply georeference.json "
                "beside the drawings (projected_crs + coordinate_operation), "
                "verifying the required CRS against current authoritative "
                "guidance -- for Singapore submissions, CORENET-X's own"
            ),
        }
    if not bridge.has_project():
        return {"status": "absent", "note": "no project to georeference"}
    projected = dict(config.get("projected_crs") or {})
    operation = dict(config.get("coordinate_operation") or {})
    if not projected.get("Name"):
        return {"status": "broken", "note": "projected_crs.Name is required"}
    import ifcopenshell.api.georeference

    ifc = bridge.ifc_file()
    if not ifc.by_type("IfcProjectedCRS"):
        ifcopenshell.api.georeference.add_georeferencing(ifc, name=projected["Name"])
    ifcopenshell.api.georeference.edit_georeferencing(
        ifc, projected_crs=projected, coordinate_operation=operation)
    source_map.record(
        "GEOREF", [projected["Name"]], ifc.by_type("IfcProjectedCRS")[0].Name,
        "coordinate reference applied from configuration")
    return {"status": "configured", "crs": projected["Name"],
            "coordinate_operation": {k: v for k, v in operation.items()}}


def _transform_drawing(sheet, transform) -> None:
    """The whole sheet into building coordinates, geometry and words alike."""
    for polylines in sheet.layers.values():
        for polyline in polylines:
            polyline.points = [transform.apply(p) for p in polyline.points]
    for label in sheet.texts:
        label.position = transform.apply(label.position)
    for arc in sheet.arcs:
        arc.center = transform.apply(arc.center)
    for insert in sheet.inserts:
        insert.position = transform.apply(insert.position)


def _cross_storey_qa(compilations, storey_candidates) -> dict:
    """The questions only a whole building can be asked.

    Reports, never judges: an upper wall with no wall below is a setback
    or a mistake, and which one is the architect's knowledge, not this
    function's. The numbers make the question precise.
    """
    import math

    qa: dict = {}
    elevations = [s.elevation for s in storey_candidates if s.elevation is not None]
    qa["elevations_ascending"] = elevations == sorted(elevations)

    walls_by_storey = [c["walls"] for c in compilations]
    deviations = []
    unmatched = 0
    for below, above in zip(walls_by_storey, walls_by_storey[1:]):
        for wall in above:
            best = None
            wx = (wall["start"][0] + wall["end"][0]) / 2.0
            wy = (wall["start"][1] + wall["end"][1]) / 2.0
            wdx = wall["end"][0] - wall["start"][0]
            wdy = wall["end"][1] - wall["start"][1]
            wlen = math.hypot(wdx, wdy) or 1.0
            for under in below:
                udx = under["end"][0] - under["start"][0]
                udy = under["end"][1] - under["start"][1]
                ulen = math.hypot(udx, udy) or 1.0
                if abs(wdx * udy - wdy * udx) > 0.03 * wlen * ulen:
                    continue
                lateral = abs(
                    (wx - under["start"][0]) * udy / ulen
                    - (wy - under["start"][1]) * udx / ulen)
                if best is None or lateral < best:
                    best = lateral
            if best is None or best > 0.5:
                unmatched += 1
            else:
                deviations.append(best)
    qa["wall_alignment"] = {
        "compared": len(deviations),
        "max_deviation": round(max(deviations), 6) if deviations else None,
        "unmatched_above": unmatched,
    }

    spaces_by_storey = [c["spaces"] for c in compilations]
    stacked = 0
    upper_total = 0
    for below, above in zip(spaces_by_storey, spaces_by_storey[1:]):
        for space in above:
            upper_total += 1
            cx = sum(p[0] for p in space["boundary"]) / len(space["boundary"])
            cy = sum(p[1] for p in space["boundary"]) / len(space["boundary"])
            from .spaces import contains

            if any(contains([tuple(p) for p in under["boundary"]], (cx, cy))
                   for under in below):
                stacked += 1
    qa["space_stacking"] = {"stacked": stacked, "upper_spaces": upper_total}

    xs = []
    ys = []
    for walls_list in walls_by_storey:
        for wall in walls_list:
            xs += [wall["start"][0], wall["end"][0]]
            ys += [wall["start"][1], wall["end"][1]]
    qa["extents"] = (
        {"x": [round(min(xs), 3), round(max(xs), 3)],
         "y": [round(min(ys), 3), round(max(ys), 3)]}
        if xs else None)
    return qa


def _write_building_report(report: dict) -> str:
    text = bpy.data.texts.get(BUILDING_TEXT_NAME) or bpy.data.texts.new(BUILDING_TEXT_NAME)
    text.clear()
    lines = ["AutoModel -- building compilation", "=" * 40, "", "Drawings:"]
    for item in report["drawings"]:
        lines.append(
            f"  {item['id']} {item['source_file']}: {item['view_type']}"
            + (f", storey hint {item['storey_hint']}" if item["storey_hint"] else ""))
        for note in item["diagnostics"]:
            lines.append(f"      ! {note}")
    lines += ["", "Transforms:"]
    for item in report["transforms"]:
        lines.append(
            f"  {item['id']} {item['drawing']}: {item['status']}, "
            f"rotation {item['rotation_degrees']:g} deg, "
            f"translation {item['translation']}"
            + (f", residual {item['residual'] * 1000:.1f} mm"
               if item["residual"] is not None else ""))
    lines += ["", "Storeys:"]
    for item in report["storeys"]:
        lines.append(
            f"  {item['id']} {item['name']}: elevation "
            + (f"{item['elevation']:g} m" if item["elevation"] is not None else "unknown")
            + (f", floor-to-floor {item['floor_to_floor']:g} m"
               if item["floor_to_floor"] is not None else ""))
        for note in item["diagnostics"]:
            lines.append(f"      ! {note}")
    if report.get("conflicts"):
        lines += ["", "CONFLICTS -- human review required:"]
        for item in report["conflicts"]:
            lines.append(f"  {item['id']} {item['object']}.{item['property']}:")
            for claim in item["evidence"]:
                lines.append(
                    f"      {claim['value']:g} m from {claim['view']} ({claim['source']})")
    if report.get("unmatched_assertions"):
        lines += ["", "Assertions citing marks nobody carries:"]
        for item in report["unmatched_assertions"]:
            lines.append(f"  {item['mark']} {item['property']} = {item['value']:g} m"
                         f" ({item['view']})")
    qa = report.get("building", {})
    lines += ["", "Cross-storey QA:", f"  {qa}"]
    text.write("\n".join(lines) + "\n")
    return BUILDING_TEXT_NAME


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
