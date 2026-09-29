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

"""The verbs, described for a model rather than for a person.

``commands`` holds what the verbs *do*. This holds what they are *for*, in the
form the Messages API wants: one tool definition per verb, same names, same
parameters. There is exactly one vocabulary, and both callers -- the socket and
Claude -- get it from the same place. A verb that gains a parameter and is not
described here keeps working over the socket and quietly stops being offered to
Claude, which is the failure this file's test is checking for.

The descriptions carry the ordering constraints, because they are the only
place a model can learn them: there is no project until one is created, no wall
without a wall type, and no IFC element from a sketch until it is assigned a
class. Saying so here costs a sentence; leaving it out costs a failed call and
a retry.

Not marked ``strict``. The parameter readers in ``commands`` already refuse bad
input with a message naming the fix, and a refusal a model can read and correct
is worth more here than one the API rejects before we see it.
"""

from __future__ import annotations

#: A point on the ground, or in space. Shared by every verb that takes a run.
_POINTS = {
    "type": "array",
    "minItems": 2,
    "description": (
        "Points in metres, in order. Each is [x, y] for a point on the ground "
        "or [x, y, z] to give a height. Repeat the first point at the end to "
        "close a loop."
    ),
    "items": {
        "type": "array",
        "minItems": 2,
        "maxItems": 3,
        "items": {"type": "number"},
    },
}


TOOLS: dict = {
    "ping": {
        "description": (
            "Check the connection and report what is running: Blender and Bonsai "
            "versions, and whether an IFC project is open."
        ),
        "schema": {"type": "object", "properties": {}},
    },
    "describe": {
        "description": (
            "Survey the model before changing it: the project name and schema, a "
            "count of elements by IFC class, the construction types that exist, "
            "and any plain sketch geometry not yet assigned a class. Call this "
            "first when you do not already know what is in the file."
        ),
        "schema": {"type": "object", "properties": {}},
    },
    "list_elements": {
        "description": (
            "List elements of one IFC class with their ids, names and positions."
        ),
        "schema": {
            "type": "object",
            "properties": {
                "ifc_class": {
                    "type": "string",
                    "description": "An IFC class, such as IfcWall. Defaults to IfcElement.",
                },
                "limit": {"type": "integer", "description": "Maximum to return. Default 200."},
            },
        },
    },
    "create_project": {
        "description": (
            "Create an IFC project. Nothing else that writes to the model works "
            "until one exists. Safe to call when one is already open -- it does "
            "nothing and says so."
        ),
        "schema": {"type": "object", "properties": {}},
    },
    "create_type": {
        "description": (
            "Create a construction type, which occurrences are made from. A new "
            "project has none, so a wall needs an IfcWallType before it can be "
            "placed. The type carries the material layers that give a wall its "
            "thickness."
        ),
        "schema": {
            "type": "object",
            "properties": {
                "ifc_class": {
                    "type": "string",
                    "description": "A type class, such as IfcWallType or IfcSlabType.",
                }
            },
            "required": ["ifc_class"],
        },
    },
    "add_walls": {
        "description": (
            "Build parametric walls along a run of points -- one wall per "
            "segment, joined at the corners, with real material layers and "
            "thickness. This is the right way to make walls: prefer it over "
            "drawing and extruding a shape. Needs an IfcWallType to exist first. "
            "For a closed room, repeat the first point at the end."
        ),
        "schema": {
            "type": "object",
            "properties": {
                "points": _POINTS,
                "height": {
                    "type": "number",
                    "description": "Wall height in metres. Default 3.0.",
                },
                "type_id": {
                    "type": "integer",
                    "description": "Which IfcWallType to use. Defaults to the first one.",
                },
            },
            "required": ["points"],
        },
    },
    "sketch_polyline": {
        "description": (
            "Draw plain geometry -- edges, and a face if the loop closes. This is "
            "not IFC yet, which is deliberate: draw the shape, then give it a "
            "class with assign_class. Use this for shapes Bonsai has no "
            "parametric generator for, such as a slab outline. Do not use it to "
            "make walls; add_walls does that properly."
        ),
        "schema": {
            "type": "object",
            "properties": {
                "points": _POINTS,
                "close": {
                    "type": "boolean",
                    "description": "Join the last point back to the first, making a face.",
                },
                "object": {
                    "type": "string",
                    "description": (
                        "Continue an existing sketch by name. Omit to start a new one."
                    ),
                },
            },
            "required": ["points"],
        },
    },
    "push_pull": {
        "description": (
            "Extrude one face of a sketch to give it thickness or height. The "
            "distance follows the face normal, which for a shape drawn flat on "
            "the ground usually points down -- the reply reports the normal used, "
            "so negate the distance if it went the wrong way. Refuses IFC "
            "elements, whose shape is generated and must not be overwritten."
        ),
        "schema": {
            "type": "object",
            "properties": {
                "object": {"type": "string", "description": "The sketch object's name."},
                "distance": {"type": "number", "description": "Distance in metres."},
                "face": {
                    "type": "integer",
                    "description": "Which face to push. Default 0, the first.",
                },
            },
            "required": ["object", "distance"],
        },
    },
    "assign_class": {
        "description": (
            "Turn finished sketch geometry into a real IFC element. This is the "
            "second half of draw-then-name. Give an occurrence class such as "
            "IfcSlab or IfcColumn, not a type class such as IfcSlabType."
        ),
        "schema": {
            "type": "object",
            "properties": {
                "object": {"type": "string", "description": "The sketch object's name."},
                "ifc_class": {
                    "type": "string",
                    "description": "An occurrence class, such as IfcSlab.",
                },
                "predefined_type": {
                    "type": "string",
                    "description": "Optional predefined type, such as FLOOR for an IfcSlab.",
                },
            },
            "required": ["object", "ifc_class"],
        },
    },
}


TOOLS.update({
    "ifc_sg_requirements": {
        "description": "Read stage-specific IFC+SG candidate requirements, source and limitations. Not a compliance verdict.",
        "schema": {"type": "object", "properties": {
            "ifc_class": {"type": "string"}, "stage": {"type": "string"},
            "predefined_type": {"type": "string"}}, "required": ["ifc_class"]}},
    "check_ifc_sg": {
        "description": "Read an IFC object's candidate missing parameter names and exact property evidence. Applicability and official Pset mapping need review.",
        "schema": {"type": "object", "properties": {
            "object": {"type": "string"}, "stage": {"type": "string"}}, "required": ["object"]}},
})

TOOLS.update({
    "derive_values": {
        "description": (
            "Fill the geometric requirement values an element's own shape "
            "states -- height, thickness, a closed shell's volume -- and "
            "report by name every question the geometry leaves open. Needs "
            "an element that has been through assign_class. Nothing here "
            "guesses; the returned 'left' list is what an agent still owes."
        ),
        "schema": {"type": "object", "properties": {
            "object": {"type": "string", "description": "The IFC element's object name."},
        }, "required": ["object"]},
    },
    "detect_walls": {
        "description": (
            "Read parallel-line wall candidates out of a flat plan sketch "
            "object: centrelines, measured thicknesses, lengths and the "
            "evidence in sentences. Candidates, not walls -- what does not "
            "pair comes back counted as unpaired rather than misread."
        ),
        "schema": {"type": "object", "properties": {
            "object": {"type": "string", "description": "A flat sketch object holding the plan lines."},
        }, "required": ["object"]},
    },
    "classify_layers": {
        "description": (
            "Read layer names against the drafting conventions, never "
            "guessing: resolved pairs carry their IFC class and evidence, "
            "and the unresolved list is the real product -- the layers "
            "whose classes need somebody's judgement."
        ),
        "schema": {"type": "object", "properties": {
            "objects": {"type": "array", "items": {"type": "string"},
                        "description": "Object names to read; every sketch object when omitted."},
        }},
    },
    "auto_model": {
        "description": (
            "Compile one 2D plan (DXF/DWG) into semantic IFC: walls with "
            "junctions, openings with doors and windows, labelled spaces, "
            "every element carrying its source-map provenance. Refusals and "
            "diagnostics come back in the report rather than being guessed "
            "over. For a set of sheets, use auto_building instead."
        ),
        "schema": {"type": "object", "properties": {
            "path": {"type": "string", "description": "The drawing file."},
            "height": {"type": "number",
                       "description": "Default extrusion height in metres. Default 3."},
            "heights": {"type": "object",
                        "description": "Optional per-layer heights, layer name to metres."},
            "weld": {"type": "number", "description": "Weld tolerance in metres."},
            "gap": {"type": "number", "description": "Healing gap tolerance in metres."},
        }, "required": ["path"]},
    },
    "auto_building": {
        "description": (
            "Compile a whole drawing set -- plans, sections, elevations -- "
            "into one multi-storey IFC building. Sheets earn their identity, "
            "transform and storey from evidence; sections contribute "
            "measurements to plan objects; disagreements become conflicts "
            "for human review, never silent resolutions. The report carries "
            "drawings, transforms, storeys, per-storey compilations, "
            "conflicts, failure tallies and KPIs."
        ),
        "schema": {"type": "object", "properties": {
            "paths": {"type": "array", "items": {"type": "string"},
                      "description": "The sheet files, in register order."},
            "height": {"type": "number",
                       "description": "Default wall height in metres. Default 3."},
            "heights": {"type": "object",
                        "description": "Optional per-layer heights, layer name to metres."},
            "georeference": {"type": "object",
                             "description": "Optional CRS configuration; otherwise "
                                            "georeference.json beside the first sheet."},
            "weld": {"type": "number", "description": "Weld tolerance in metres."},
            "gap": {"type": "number", "description": "Healing gap tolerance in metres."},
        }, "required": ["paths"]},
    },
    "camera_perspective": {
        "description": (
            "Place a presentation camera from the current view: level, at eye "
            "height, verticals kept vertical by lens shift (two-point "
            "perspective). Makes it the scene camera. Use it before rendering "
            "a perspective for a person to judge."
        ),
        "schema": {"type": "object", "properties": {
            "lens": {"type": "number",
                     "description": "Focal length in mm. Default 32."},
            "eye_height": {"type": "number",
                           "description": "Camera height in metres above zero; "
                                          "0 keeps the view's own height. Default 1.6."},
        }},
    },
    "sketch_style": {
        "description": (
            "Switch the sketch render look on or off: flat material colour, "
            "cavity shading and traced ink lines, in the viewport and in the "
            "render. Off restores exactly the shading recorded when it went on."
        ),
        "schema": {"type": "object", "properties": {
            "mode": {"type": "string", "enum": ["on", "off"],
                     "description": "Default on."},
        }},
    },
})


def tool_definitions(names: list) -> list:
    """Messages API tool definitions for ``names``, in a stable order.

    Stable because the tool list is part of the prompt-cache prefix, and a set
    iterated in whatever order it happens to produce would invalidate the cache
    on every call for no reason at all.
    """
    tools = []
    for name in sorted(names):
        spec = TOOLS.get(name)
        if spec is None:
            continue
        tools.append(
            {
                "name": name,
                "description": spec["description"],
                "input_schema": spec["schema"],
            }
        )
    return tools


def undescribed(names: list) -> list:
    """Verbs with no tool definition -- reachable over the socket, invisible here."""
    return sorted(set(names) - set(TOOLS))
