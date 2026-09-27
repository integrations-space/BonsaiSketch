"""Compile one hold-out blind and preserve the first result as baseline.

Run with:

    blender -b --python tools/holdout_run.py -- holdouts/holdout-001

Reads every drawing in <dir>/source (sorted, so the register's order is
the filename order), applies <dir>/config/project.json (stage, typology,
heights), runs the building compiler once, and writes the full report:

* to ``results/baseline.json`` if none exists -- and never overwrites
  it, because the first blind result IS the baseline, defects included;
* to ``results/latest.json`` otherwise, for runs during development.

Scoring is a separate, Blender-free step: tools/holdout_score.py.
"""

import json
import os
import sys

import bpy

BONSAI = "bl_ext.blender_org.bonsai"
ADDON = "bl_ext.user_default.bonsai_sketch_mode"

argv = sys.argv[sys.argv.index("--") + 1:] if "--" in sys.argv else []
if len(argv) != 1:
    raise SystemExit(__doc__)
holdout = os.path.abspath(argv[0])
source = os.path.join(holdout, "source")
if not os.path.isdir(source):
    raise SystemExit(f"{holdout} has no source/ directory")

bpy.ops.preferences.addon_enable(module=BONSAI)
bpy.ops.preferences.addon_enable(module=ADDON)
addon = sys.modules[ADDON]

config = {}
config_path = os.path.join(holdout, "config", "project.json")
if os.path.isfile(config_path):
    with open(config_path, encoding="utf-8") as handle:
        config = json.load(handle)

scene = bpy.context.scene
scene.bonsai_sketch_sg_stage = config.get("stage", "detailed")
scene.bonsai_sketch_sg_typology = config.get("typology", "none")

paths = sorted(
    os.path.join(source, name)
    for name in os.listdir(source)
    if name.lower().endswith((".dxf", ".dwg"))
)
if not paths:
    raise SystemExit(f"{source} holds no drawings")

report = addon.textmodel.commands.run("auto_building", {
    "paths": paths,
    "height": float(config.get("height", 3.0)),
    "heights": config.get("heights") or {},
})

results = os.path.join(holdout, "results")
os.makedirs(results, exist_ok=True)
baseline = os.path.join(results, "baseline.json")
target = baseline if not os.path.exists(baseline) else os.path.join(results, "latest.json")
with open(target, "w", encoding="utf-8") as handle:
    json.dump(report, handle, indent=1)
    handle.write("\n")

kind = "BASELINE (preserved; defects included)" if target == baseline else "latest"
building = report.get("building", {})
print(f"\nHOLD-OUT RUN -- {os.path.basename(holdout)} -> {target} [{kind}]")
print(f"storeys compiled: {building.get('compiled_storeys')}")
print(f"interventions:    {building.get('failures', {}).get('interventions')}")
print(f"silent resolutions: "
      f"{building.get('evidence', {}).get('silently_resolved')} (gate: 0)")
print("score it, without Blender: python3 tools/holdout_score.py "
      + os.path.relpath(holdout))
