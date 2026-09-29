# SPDX-License-Identifier: GPL-3.0-or-later
"""Read back IFC geometry and relationships without repairing the model."""
import ifcopenshell.geom
import ifcopenshell.util.element


def check(model):
    findings = []
    settings = ifcopenshell.geom.settings()
    settings.set(settings.USE_WORLD_COORDS, True)
    boxes = {}
    for el in model.by_type('IfcElement'):
        try:
            shape = ifcopenshell.geom.create_shape(settings, el)
            coords = shape.geometry.verts
            if not coords or not shape.geometry.faces:
                raise ValueError('Empty solid/surface geometry')
            boxes[el.id()] = [(min(coords[i::3]), max(coords[i::3])) for i in range(3)]
        except Exception as exc:
            findings.append({'severity': 'error', 'code': 'GEOMETRY_INVALID', 'element': el.GlobalId, 'message': str(exc)})
        if el.is_a('IfcOpeningElement'):
            if len(el.VoidsElements) != 1 or len(el.HasFillings) != 1:
                findings.append({'severity': 'error', 'code': 'OPENING_RELATIONSHIP', 'element': el.GlobalId})
        elif not el.is_a('IfcGeographicElement') and ifcopenshell.util.element.get_material(el) is None:
            findings.append({'severity': 'warning', 'code': 'MATERIAL_MISSING', 'element': el.GlobalId})
    for op in model.by_type('IfcOpeningElement'):
        if not op.VoidsElements or op.id() not in boxes:
            continue
        host = op.VoidsElements[0].RelatingBuildingElement
        a, b = boxes[op.id()], boxes.get(host.id())
        if b and any(min(x[1], y[1]) <= max(x[0], y[0]) for x, y in zip(a, b)):
            findings.append({'severity': 'error', 'code': 'OPENING_MISSES_HOST', 'element': op.GlobalId})
    return findings
