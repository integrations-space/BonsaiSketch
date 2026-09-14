# IFC+SG and Sketch Agents

## Setup and use

1. Enable Bonsai and Bonsai Sketch Mode. Open Sketch, press N, select Sketch.
2. Set the project stage in **IFC+SG Requirements**. Select IFC elements to see
   candidate missing fields. **Check Selected IFC+SG** saves a complete report
   as `Sketch IFC+SG Report.json` in Blender's Text Editor.
3. Set an Anthropic API key and an available Claude model in the add-on
   preferences. `ANTHROPIC_API_KEY` is also supported. No Node server, SDK install,
   browser extension, or additional listener is needed for this native workflow.
4. Type your request in **Sketch Agents**, then **Plan with Agents**. Wait for
   Geometry, BIM/IFC, Compliance, Coordinator and mandatory QA to finish.
5. Inspect **Open Full Review**. It changes the current area to the Text Editor;
   use the editor-type selector to return to 3D View. The report includes every
   parameter, reason, specialist finding and question. Editing this text does not
   edit the pending plan. To modify a proposal, revise the prompt and plan again.
6. **Approve and Apply** shows the commands before confirmation. **Reject Plan**
   discards them. Questions and a QA rejection block application.

Example: "Propose a 5 by 4 metre rectangular wall path, 3 metres high, using the
existing wall type #123. Check which IFC+SG fields are missing at my selected
stage." Substitute a real type ID. Clear internal dimensions differ from a wall
path; state which you need. Wall thickness comes from the existing type.

Generation makes five sequential model requests, each with a 120-second HTTP
timeout. Model data includes selected objects (or the scene if none selected),
properties, geometry dimensions, global type inventory and the stage checklist.
Selection limits object detail but does not hide global model summary/type names.
Do not include data in a request unless it may be sent to your configured provider.
API keys are not written into the generated review or execution reports.

## IFC+SG scope and sources

The shipped `data/ifc_sg.json` is extracted from **IFC+SG Model Content
Requirements V2.0, 20 Mar 2026**; its class mapping is separately maintained in
`data/ifc_sg_classes.json`. `tools/extract_ifc_sg.py` regenerates the checklist
from its matching workbook format. It is not an importer for the CORENET X
mapping workbook, which has a different structure.

The checker retains stage, discipline and sub-element context, reports exact
property paths as evidence, and accepts zero and false as populated values.
Unknown classes remain unmapped. Roof slabs use Roof candidates; non-ceiling
coverings are not silently checked as ceilings. Inherited type properties are
included. No empty or invented SGPsets are written into the model.

A present property name means **present, unverified**. The checklist cannot prove
that the correct Pset, type, units, controlled value, applicability, geometry or
submission-stage requirements have been satisfied. It never issues a compliance
pass. Schematic/detailed workbook stages are not automatically mapped to CORENET X
gateways. IDS execution, full submission validation and TRHS checking are not
implemented by this feature.

Official references checked on 14 September 2026:

- [IFC+SG Excel Mapping File](https://info.corenet.gov.sg/ifc-sg/requirements---submission/ifc-sg-excel-mapping-file)
  defines exact IFC entities, SGPsets, properties and controlled values; its page
  lists the mapping version as 4 December 2025. Use it with the Code of Practice
  and component glossary when preparing submission data.
- [CORENET X onboarding](https://info.corenet.gov.sg/ifc-sg/start-here/ifcsg-onboarding-checklist)
  covers model preparation and validation.
- [CORENET X Model Checker](https://info.corenet.gov.sg/model-checker)
  checks IFC, modelling standards and selected regulatory requirements.

## Architecture and execution

`sg.py` collects context on Blender's main thread. `textmodel/agents.py` invokes
separate specialist contexts over the existing HTTPS transport, forces structured
review outputs, validates command schemas locally, and always runs QA last.
The only tool offered to these LLM calls is `submit_review`; it cannot mutate
Blender. Specialist questions survive coordinator synthesis.

`textmodel/ui.py` keeps a private in-memory pending plan, presents its review and
applies approved commands on the main thread through Bonsai's IFC transaction.
The fingerprint covers the full IFC serialization, mesh topology and coordinates,
transforms, file/scene identity, selection and stage. Changes invalidate the plan.
Plans cannot be approved through the text-to-model socket and cannot be replayed.

The operation vocabulary is intentionally bounded:

- Create a project or default IFC construction type.
- Create parametric wall paths with an explicit height and type ID.
- Sketch a polyline, push/pull a sketch face, assign an occurrence IFC class.
- Read model summary, elements, stage requirements and IFC+SG field evidence.

Command parameters may use `{"$ref": "0.id"}` or `{"$ref": "2.object"}` to refer
to real results of earlier actions. Unknown operations/parameters, wrong types,
non-finite numbers, forward references and incomplete provider responses fail
closed. Object Mode and a scene unit scale of one metre are required.

Storey/material editing, arbitrary property writes, deletion, general transforms,
IDS and rendering are not in this action vocabulary. A request needing them
should produce questions or a QA block. The UI does not claim arbitrary full BIM
authoring support. The original low-level socket and `claude.build()` remain
explicit developer interfaces that can mutate immediately; the Sketch Agents
panel uses the proposal pipeline exclusively.

Execution stops on the first command error. Completed operations and the failed
index are logged, and the plan is consumed even on failure. Changes are grouped
in Bonsai's IFC undo transaction, but failures are not automatically rolled back.
Inspect the model and execution report before continuing.

## Verification

```
python tools/agents_check.py
blender --background --factory-startup --python-exit-code 1 --python tools/agents_blender_check.py
blender --background --python tools/smoke_test.py
blender --python tools/describe_check.py -- describe_check.txt
```

The pure tests use stub structured provider responses and exercise every agent,
QA/questions, validation, stale/replayed plans, references and partial failures.
The isolated Blender test exercises registration and real sketch extrusion without
enabling installed extensions. The GUI test exercises proposal then explicit
approval using a local stub HTTP server; it does not spend API credits.


## Version 0.4.0 release validation

The merged release was verified on Blender 5.2 with 208/208 smoke checks,
13 offline agent tests, the isolated Blender agent/IFC evidence checks, and
19/19 GUI proposal-and-approval checks using a stub provider. The GUI test
confirmed that planning creates no project and approval creates four parametric
walls with the requested dimensions. Live Anthropic requests were not exercised.
