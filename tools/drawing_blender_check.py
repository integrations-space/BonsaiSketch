# SPDX-License-Identifier: GPL-3.0-or-later
"""Isolated Blender operator check; does not enable or install extensions."""
import importlib.util
import json
from pathlib import Path
import shutil
import sys
import tempfile
import types

import bpy

root = Path(__file__).resolve().parents[1]
# Reuse the installed Bonsai wheels read-only, without extension registration.
deps = Path.home() / 'AppData/Roaming/Blender Foundation/Blender' / f'{bpy.app.version[0]}.{bpy.app.version[1]}' / 'extensions/.local/lib' / f'python{sys.version_info.major}.{sys.version_info.minor}/site-packages'
if deps.is_dir():
    sys.path.insert(0, str(deps))
for name, path in (('_drawing_test', root/'bonsai_sketch_mode'), ('_drawing_test.ops', root/'bonsai_sketch_mode/ops')):
    package = types.ModuleType(name)
    package.__path__ = [str(path)]
    sys.modules[name] = package
spec = importlib.util.spec_from_file_location('_drawing_test.ops.drawing_project', root/'bonsai_sketch_mode/ops/drawing_project.py')
module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)
cls = module.BONSAI_SKETCH_MODE_OT_build_drawing_project
bpy.utils.register_class(cls)
try:
    with tempfile.TemporaryDirectory() as tmp:
        for name in ('project.json', 'plan.dxf'):
            shutil.copy(root/'examples/drawing_project'/name, Path(tmp)/name)
        before = set(bpy.data.objects)
        result = bpy.ops.bonsai_sketch_mode.build_drawing_project(filepath=str(Path(tmp)/'project.json'))
        assert result == {'FINISHED'}, result
        assert Path(tmp,'project.ifc').is_file()
        assert set(bpy.data.objects) == before, 'Builder modified the open Blender model'
        import ifcopenshell
        model = ifcopenshell.open(str(Path(tmp)/'project.ifc'))
        assert len(model.by_type('IfcWall')) == 1
        assert len(model.by_type('IfcWindow')) == 1
        saved = Path(tmp,'project.ifc').read_bytes()
        try:
            bpy.ops.bonsai_sketch_mode.build_drawing_project(filepath=str(Path(tmp)/'project.json'))
        except RuntimeError:
            pass  # Blender raises when an operator reports ERROR.
        assert Path(tmp,'project.ifc').read_bytes() == saved
        print('Drawing operator: registration, IFC output, scene preservation, overwrite protection PASS')
finally:
    bpy.utils.unregister_class(cls)
