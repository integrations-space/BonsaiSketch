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

"""Importing a drawn plan and standing it up.

File > Import > CAD Drawing brings a DXF in as sketch geometry -- one object
per layer, named after it, marked as ours, so choosing which layers matter is
ordinary object selection and every existing tool works on what arrives. The
answer NEXT.md left open -- does imported linework become sketch geometry or
IFC -- lands on the same side as the drawing tools: sketch first, assign
meaning second, through Bonsai's Assign IFC Class when a shape is right.

The import chains three steps a drafter otherwise does by hand, each with an
adjustable, unit-aware value in the redo panel so the result can be re-cut
without re-importing:

1. heal.py welds the linework into chains and bridges gaps up to a chosen
   tolerance, enclosing the n-sided polygons the plan almost drew;
2. closed loops become faces;
3. a non-zero Extrude stands every faced loop up into a solid of that height
   -- a plan of room outlines becomes massing in one import.

DWG goes through ODA File Converter first, pointed at by a preference. It is
a proprietary format with no reliable free reader; converting is the honest
route, and without the converter the import says exactly what to install
rather than failing quietly.
"""

from __future__ import annotations

import os
import glob
import shutil
import subprocess
import tempfile
from typing import Optional

import bmesh
import bpy
from bpy_extras.io_utils import ImportHelper

from .. import dxf, heal, sketchmesh

#: How long a DWG conversion may take before it is declared stuck, in seconds.
CONVERT_TIMEOUT = 120


def find_oda_converter(configured: str = "") -> str:
    """Respect an explicit path, otherwise discover a standard ODA installation."""
    if configured:
        return bpy.path.abspath(configured)
    on_path = shutil.which("ODAFileConverter")
    if on_path:
        return on_path
    patterns = ["/Applications/ODAFileConverter*.app/Contents/MacOS/ODAFileConverter"]
    for base in (os.environ.get("ProgramFiles"), os.environ.get("ProgramFiles(x86)")):
        if base:
            patterns.append(os.path.join(base, "ODA", "ODAFileConverter*", "ODAFileConverter.exe"))
    return next((path for pattern in patterns for path in sorted(glob.glob(pattern), reverse=True)
                 if os.path.isfile(path)), "")


def import_preferences(context):
    addon = context.preferences.addons.get(__package__.rsplit(".", 1)[0])
    return addon.preferences if addon else None


def layer_object(context: bpy.types.Context, name: str) -> bpy.types.Object:
    """A new, empty sketch object for one imported layer.

    Linked at the scene root for the same reason sketchmesh.create links
    there: with an IFC project open the active collection is Bonsai's spatial
    hierarchy, and imported linework has no containment to claim yet.
    """
    mesh = bpy.data.meshes.new(name)
    obj = bpy.data.objects.new(name, mesh)
    obj[sketchmesh.MARKER] = True
    context.scene.collection.objects.link(obj)
    return obj


def build_layer(
    context: bpy.types.Context,
    name: str,
    polylines: list,
    weld: float,
    gap: float,
    extrude: float,
) -> tuple[bpy.types.Object, "heal.Report", int]:
    """One layer's linework healed, faced, and optionally stood up.

    Returns the object, the heal report, and how many loops could not be
    faced -- a healed loop that crosses itself has no single face, and it is
    kept as edges rather than guessed at.
    """
    pairs = [(p.points, p.closed) for p in polylines]
    loops, opens, report = heal.heal(pairs, weld, gap)

    obj = layer_object(context, name)
    bm = bmesh.new()
    try:
        unfaceable = 0
        faces = []
        for loop in loops:
            verts = [bm.verts.new((x, y, 0.0)) for x, y in loop]
            # The crossing test lives out here because bmesh will not do it:
            # faces.new checks topology, not geometry, and builds a bowtie
            # quad without complaint. The ValueError catch below still covers
            # the topological refusals -- duplicate vertices, a face that
            # already exists.
            if heal.self_crossing(loop):
                unfaceable += 1
                for i in range(len(verts)):
                    bm.edges.new((verts[i], verts[(i + 1) % len(verts)]))
                continue
            try:
                faces.append(bm.faces.new(verts))
            except ValueError:
                unfaceable += 1
                for i in range(len(verts)):
                    edge = (verts[i], verts[(i + 1) % len(verts)])
                    if bm.edges.get(edge) is None:
                        bm.edges.new(edge)
        for chain in opens:
            verts = [bm.verts.new((x, y, 0.0)) for x, y in chain]
            for start, end in zip(verts, verts[1:]):
                bm.edges.new((start, end))

        if extrude > 0.0 and faces:
            # The sheet-to-solid path Push/Pull's EXTRUDE mode takes: the
            # original faces stay as bottom caps, a copy travels up, and the
            # winding -- arbitrary, since a drafted loop runs whichever way
            # it was drawn -- is settled per closed shell afterwards.
            grown = bmesh.ops.extrude_face_region(bm, geom=faces)
            raised = [g for g in grown["geom"] if isinstance(g, bmesh.types.BMVert)]
            bmesh.ops.translate(bm, verts=raised, vec=(0.0, 0.0, extrude))
            bmesh.ops.recalc_face_normals(bm, faces=list(bm.faces))

        bm.normal_update()
        bm.to_mesh(obj.data)
    finally:
        bm.free()
    obj.data.update()
    return obj, report, unfaceable


def build(
    context: bpy.types.Context,
    drawing: "dxf.Drawing",
    stem: str,
    weld: float,
    gap: float,
    extrude: float,
) -> tuple[list[bpy.types.Object], list[str], dict]:
    """Objects for every layer, the sentences worth saying, and the counts.

    The counts exist for the failure taxonomy: an unfaceable loop is
    damaged geometry (F03) whether or not anyone reads the sentence
    about it, so it travels as a number too.
    """
    objects = []
    notes = []
    total = heal.Report()
    unfaceable = 0
    for layer_name in sorted(drawing.layers):
        obj, report, failed = build_layer(
            context, f"{stem}/{layer_name}", drawing.layers[layer_name],
            weld, gap, extrude,
        )
        objects.append(obj)
        unfaceable += failed
        total.closed_already += report.closed_already
        total.welded += report.welded
        total.bridged += report.bridged
        total.left_open += report.left_open

    notes.append(
        f"{len(objects)} layer(s), read in {drawing.unit_name}: {total.summary()}"
    )
    if unfaceable:
        notes.append(f"{unfaceable} healed loop(s) cross themselves and stay as edges")
    if drawing.skipped:
        skipped = ", ".join(f"{count} {kind}" for kind, count in sorted(drawing.skipped.items()))
        notes.append(f"not read (outside the drafting subset): {skipped}")
    stats = {"welded": total.welded, "bridged": total.bridged,
             "left_open": total.left_open, "unfaceable": unfaceable}
    return objects, notes, stats


def convert_dwg(path: str, converter: str) -> tuple[Optional[str], str]:
    """A DXF produced from a DWG by ODA File Converter, or why not.

    The converter works folder to folder, so the file gets a private pair of
    them. The returned path lives in a temp directory the caller reads
    promptly; the OS owns its cleanup.
    """
    if not converter:
        return None, (
            "DWG is a proprietary format; converting it needs ODA File Converter "
            "from opendesign.com (subject to ODA's licence terms). Install it "
            "or set its executable path in the file picker or add-on preferences"
        )
    if not os.path.isfile(converter):
        return None, f"ODA File Converter not found at {converter!r} -- check the preference"

    staging = tempfile.mkdtemp(prefix="bonsai_sketch_dwg_")
    in_dir = os.path.join(staging, "in")
    out_dir = os.path.join(staging, "out")
    os.makedirs(in_dir)
    os.makedirs(out_dir)
    shutil.copy(path, in_dir)
    try:
        subprocess.run(
            # input dir, output dir, output version, output type, recurse, audit
            [converter, in_dir, out_dir, "ACAD2018", "DXF", "0", "1"],
            check=True,
            timeout=CONVERT_TIMEOUT,
            capture_output=True,
        )
    except subprocess.TimeoutExpired:
        return None, f"ODA File Converter did not finish within {CONVERT_TIMEOUT}s"
    except (subprocess.CalledProcessError, OSError) as exc:
        return None, f"ODA File Converter failed: {exc}"

    stem = os.path.splitext(os.path.basename(path))[0]
    produced = os.path.join(out_dir, f"{stem}.dxf")
    if not os.path.isfile(produced):
        return None, "ODA File Converter ran but produced no DXF"
    return produced, ""


class BONSAI_SKETCH_MODE_OT_import_cad(bpy.types.Operator, ImportHelper):
    bl_idname = "bonsai_sketch_mode.import_cad"
    bl_label = "CAD Drawing (.dxf/.dwg)"
    bl_description = (
        "Import a DXF or DWG plan as sketch geometry, one object per layer. "
        "Broken outlines are healed up to the gap tolerance, closed outlines "
        "become faces, and a non-zero height stands them up as solids"
    )
    bl_options = {"REGISTER", "UNDO"}

    filename_ext = ".dxf"
    filter_glob: bpy.props.StringProperty(default="*.dxf;*.dwg", options={"HIDDEN"})

    weld: bpy.props.FloatProperty(
        name="Weld",
        description="Endpoints closer than this are the same point",
        default=0.001,
        min=0.0,
        subtype="DISTANCE",
    )
    gap: bpy.props.FloatProperty(
        name="Close Gaps Up To",
        description=(
            "An almost-closed outline whose ends are nearer than this is "
            "enclosed with a straight segment. Wider gaps stay open -- a "
            "doorway is not a drafting error"
        ),
        default=0.01,
        min=0.0,
        subtype="DISTANCE",
    )
    extrude: bpy.props.FloatProperty(
        name="Extrude",
        description=(
            "Stand every closed outline up into a solid of this height. "
            "Zero imports the plan flat"
        ),
        default=0.0,
        min=0.0,
        subtype="DISTANCE",
    )

    def draw(self, context: bpy.types.Context) -> None:
        layout = self.layout
        layout.use_property_split = True
        layout.prop(self, "weld")
        layout.prop(self, "gap")
        layout.prop(self, "extrude")
        if self.filepath.lower().endswith(".dwg"):
            prefs = import_preferences(context)
            converter = find_oda_converter(getattr(prefs, "oda_converter", ""))
            if converter and os.path.isfile(converter):
                layout.label(text="DWG converter ready", icon="CHECKMARK")
            else:
                layout.label(text="DWG needs ODA File Converter", icon="ERROR")
                if prefs:
                    layout.prop(prefs, "oda_converter")
                layout.operator("wm.url_open", text="Get ODA File Converter", icon="URL").url = (
                    "https://www.opendesign.com/guestfiles/oda_file_converter")
                layout.label(text="Subject to ODA's licence terms")

    @classmethod
    def poll(cls, context):
        return context.mode == "OBJECT"

    def execute(self, context: bpy.types.Context):
        path = self.filepath
        if not path.lower().endswith((".dxf", ".dwg")):
            self.report({"ERROR"}, "Choose a DXF or DWG drawing")
            return {"CANCELLED"}
        if path.lower().endswith(".dwg"):
            prefs = import_preferences(context)
            converter = find_oda_converter(getattr(prefs, "oda_converter", ""))
            converted, why_not = convert_dwg(path, converter)
            if converted is None:
                self.report({"ERROR"}, why_not)
                return {"CANCELLED"}
            path = converted

        try:
            with open(path, encoding="utf-8", errors="replace") as handle:
                drawing = dxf.parse(handle.read())
        except OSError as exc:
            self.report({"ERROR"}, f"Could not read {path}: {exc}")
            return {"CANCELLED"}

        if not drawing.layers:
            skipped = ", ".join(sorted(drawing.skipped)) or "nothing at all"
            self.report(
                {"WARNING"},
                f"No lines, polylines, arcs or circles found -- the file holds {skipped}",
            )
            return {"CANCELLED"}

        stem = os.path.splitext(os.path.basename(self.filepath))[0]
        objects, notes, _stats = build(
            context, drawing, stem, self.weld, self.gap, self.extrude
        )
        for obj in context.selected_objects:
            obj.select_set(False)
        for obj in objects:
            obj.select_set(True)
        if objects:
            context.view_layer.objects.active = objects[-1]
        for note in notes[1:]:
            self.report({"WARNING"}, note)
        self.report({"INFO"}, notes[0])
        return {"FINISHED"}


def stand_up_object(
    obj: bpy.types.Object, weld: float, gap: float, height: float
) -> Optional[tuple["heal.Report", int]]:
    """Heal one flat sketch object's loose linework and stand its faces up.

    Returns (report, unfaceable loops), or None when the object is not flat
    linework -- already standing, or drawn out of the plane. Declining is the
    honest answer there: extruding an extrusion doubles it, and this operator
    exists to be re-run with different numbers, not to stack.

    The wire edges are rebuilt wholesale from the heal's answer -- loops
    become faces, still-open chains stay edges -- because heal does not say
    which source segment landed where, and a rebuild from its output is
    simpler than bookkeeping that only exists to avoid one. Faces the object
    already has are left exactly as they are and join the extrusion.
    """
    bm = bmesh.new()
    try:
        bm.from_mesh(obj.data)
        if bm.verts:
            zs = [v.co.z for v in bm.verts]
            if max(zs) - min(zs) > max(weld, 1e-9):
                return None
            floor = min(zs)
        else:
            floor = 0.0

        wires = [e for e in bm.edges if not e.link_faces]
        segments = [
            ([(e.verts[0].co.x, e.verts[0].co.y), (e.verts[1].co.x, e.verts[1].co.y)], False)
            for e in wires
        ]
        loops, opens, report = heal.heal(segments, weld, gap)

        wire_verts = {v for e in wires for v in e.verts}
        for edge in wires:
            bm.edges.remove(edge)
        for vert in wire_verts:
            if vert.is_valid and not vert.link_edges and not vert.link_faces:
                bm.verts.remove(vert)

        unfaceable = 0
        for loop in loops:
            verts = [bm.verts.new((x, y, floor)) for x, y in loop]
            if heal.self_crossing(loop):
                unfaceable += 1
                for i in range(len(verts)):
                    bm.edges.new((verts[i], verts[(i + 1) % len(verts)]))
                continue
            try:
                bm.faces.new(verts)
            except ValueError:
                unfaceable += 1
                for i in range(len(verts)):
                    edge = (verts[i], verts[(i + 1) % len(verts)])
                    if bm.edges.get(edge) is None:
                        bm.edges.new(edge)
        for chain in opens:
            verts = [bm.verts.new((x, y, floor)) for x, y in chain]
            for start, end in zip(verts, verts[1:]):
                bm.edges.new((start, end))

        if height > 0.0 and bm.faces:
            grown = bmesh.ops.extrude_face_region(bm, geom=list(bm.faces))
            raised = [g for g in grown["geom"] if isinstance(g, bmesh.types.BMVert)]
            bmesh.ops.translate(bm, verts=raised, vec=(0.0, 0.0, height))
            bmesh.ops.recalc_face_normals(bm, faces=list(bm.faces))

        bm.normal_update()
        bm.to_mesh(obj.data)
    finally:
        bm.free()
    obj.data.update()
    return report, unfaceable


class BONSAI_SKETCH_MODE_OT_stand_up(bpy.types.Operator):
    bl_idname = "bonsai_sketch_mode.stand_up"
    bl_label = "Stand Up Outlines"
    bl_description = (
        "Heal the selected sketch layers' loose linework -- welding endpoints, "
        "enclosing outlines whose gaps are within the tolerance -- and stand "
        "every closed outline up to the given height. Each run is one height, "
        "so selecting one layer at a time gives each layer its own"
    )
    bl_options = {"REGISTER", "UNDO"}

    height: bpy.props.FloatProperty(
        name="Height",
        description="How tall the enclosed outlines stand. Zero heals and faces, standing nothing up",
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

    @classmethod
    def poll(cls, context: bpy.types.Context) -> bool:
        return context.mode == "OBJECT" and bool(context.selected_objects)

    def execute(self, context: bpy.types.Context):
        stood = 0
        not_ours = 0
        not_flat = 0
        unfaceable = 0
        healed = heal.Report()
        for obj in context.selected_objects:
            if not sketchmesh.is_sketch_object(obj):
                # IFC elements and foreign meshes alike: an element's shape
                # is Bonsai's to generate, and geometry we did not mark is
                # not ours to rebuild.
                not_ours += 1
                continue
            result = stand_up_object(obj, self.weld, self.gap, self.height)
            if result is None:
                not_flat += 1
                continue
            report, failed = result
            stood += 1
            unfaceable += failed
            healed.closed_already += report.closed_already
            healed.welded += report.welded
            healed.bridged += report.bridged
            healed.left_open += report.left_open

        if not stood:
            reasons = []
            if not_ours:
                reasons.append(f"{not_ours} not sketch geometry")
            if not_flat:
                reasons.append(f"{not_flat} already standing or not flat")
            self.report({"WARNING"}, "Nothing to stand up: " + (", ".join(reasons) or "nothing selected"))
            return {"CANCELLED"}

        if unfaceable:
            self.report({"WARNING"}, f"{unfaceable} loop(s) cross themselves and stay as edges")
        if not_flat:
            self.report({"WARNING"}, f"{not_flat} object(s) already standing were left alone")
        verb = f"stood up to {self.height:.2f}m" if self.height > 0 else "healed flat"
        self.report({"INFO"}, f"{stood} layer(s) {verb}: {healed.summary()}")
        return {"FINISHED"}


def menu_entry(self, context: bpy.types.Context) -> None:
    self.layout.operator(BONSAI_SKETCH_MODE_OT_import_cad.bl_idname, text="CAD Drawing (.dxf/.dwg)")


def object_menu_entry(self, context: bpy.types.Context) -> None:
    self.layout.operator(BONSAI_SKETCH_MODE_OT_stand_up.bl_idname)


class BONSAI_SKETCH_MODE_MT_sketch(bpy.types.Menu):
    bl_label = "Sketch"
    bl_idname = "BONSAI_SKETCH_MODE_MT_sketch"

    def draw(self, context):
        self.layout.operator_context = "INVOKE_DEFAULT"
        self.layout.operator(BONSAI_SKETCH_MODE_OT_import_cad.bl_idname,
                             text="Import DXF / DWG...", icon="IMPORT")
        self.layout.operator(BONSAI_SKETCH_MODE_OT_stand_up.bl_idname)


def sketch_menu_entry(self, context):
    from ..workspace import WORKSPACE_NAME
    if context.workspace and context.workspace.name == WORKSPACE_NAME:
        self.layout.menu(BONSAI_SKETCH_MODE_MT_sketch.bl_idname)
