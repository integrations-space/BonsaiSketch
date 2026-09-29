# SPDX-License-Identifier: GPL-3.0-or-later
"""Run the modular drawing tools from Sketch, saving a separate IFC."""
import json
from pathlib import Path

import bpy
from bpy_extras.io_utils import ImportHelper


class BONSAI_SKETCH_MODE_OT_build_drawing_project(bpy.types.Operator, ImportHelper):
    bl_idname = 'bonsai_sketch_mode.build_drawing_project'
    bl_label = 'Build IFC from Drawing Project'
    bl_description = 'Read a drawing-project JSON, check it, and save a separate IFC beside it'
    filename_ext = '.json'
    filter_glob: bpy.props.StringProperty(default='*.json', options={'HIDDEN'})

    def execute(self, context):
        path = Path(self.filepath)
        output = path.with_suffix('.ifc')
        if output.exists():
            self.report({'ERROR'}, f'Output already exists: {output.name}. Use a new project JSON filename.')
            return {'CANCELLED'}
        try:
            from ..drawing_tools.project import prepare
            from ..drawing_tools.ifc import build
            from ..drawing_tools.checks import check
            manifest = json.loads(path.read_text(encoding='utf-8-sig'))
            recipe = prepare(manifest, path.parent)
            report = bpy.data.texts.new('Drawing Project Review')
            report.write(json.dumps(recipe, indent=2, allow_nan=False))
            if any(f['severity'] == 'error' for f in recipe['findings']):
                self.report({'ERROR'}, 'Resolve findings in Text Editor > Drawing Project Review, then rebuild')
                return {'CANCELLED'}
            model = build(recipe)
            findings = check(model)
            check_report = bpy.data.texts.new('Drawing IFC Checks')
            check_report.write(json.dumps(findings, indent=2))
            if any(f['severity'] == 'error' for f in findings):
                self.report({'ERROR'}, 'IFC geometry checks failed; see Drawing IFC Checks in the Text Editor')
                return {'CANCELLED'}
            model.write(str(output))
        except ImportError as exc:
            self.report({'ERROR'}, f'Drawing tools need Bonsai with IfcOpenShell and Shapely: {exc}')
            return {'CANCELLED'}
        except Exception as exc:
            self.report({'ERROR'}, f'Drawing project: {exc}')
            return {'CANCELLED'}
        warnings = sum(f['severity'] == 'warning' for f in recipe['findings'] + findings)
        self.report({'WARNING'} if warnings else {'INFO'}, f'Saved {output.name}; {warnings} review findings. Open the IFC with Bonsai.')
        return {'FINISHED'}
