# SPDX-License-Identifier: GPL-3.0-or-later
"""Editable project defaults and explicit schedule reconciliation, in metres."""
from copy import deepcopy
import math


DEFAULTS = {
    'wall': {'material': 'Hollow block masonry'},
    'shelter': {'material': 'Precast concrete'},
    'column': {'material': 'Concrete'},
    'beam': {'material': 'Precast concrete'},
    'slab': {'material': 'Precast concrete'},
    'footing': {'material': 'Concrete'},
    'foundation': {'material': 'Concrete'},
    'platform': {'material': 'Concrete'},
    'ramp': {'material': 'Concrete'},
    'stair': {'material': 'Concrete'},
    'flat_roof': {'material': 'Concrete'},
    'pitched_roof': {'material': None},
    'window': {'material': 'Glass', 'frame_material': 'Aluminium',
               'frame_width_m': 0.05, 'frame_depth_m': 0.05,
               'glass_thickness_m': 0.012, 'glass_colour': 'transparent'},
    'door': {'material': 'Timber', 'height_m': 2.1, 'panel_depth_m': 0.04},
}
GLASS_COLOURS = {'blue': (0.3, 0.6, 0.9), 'green': (0.35, 0.7, 0.55),
                 'black': (0.08, 0.08, 0.1), 'transparent': (0.85, 0.95, 1.0)}


def resolve(component, schedules=None, project_defaults=None):
    """Defaults < project defaults < component < schedule. Conflicts stay visible.

    A schedule value has to cite a source. Fire ratings never receive a default.
    Full-height doors need an explicit host clear height, rather than a guessed
    floor-to-floor height. Returned values can be edited and rebuilt identically.
    """
    kind = component['kind']
    if kind not in DEFAULTS and kind not in ('boundary', 'setback', 'terrain', 'entrance'):
        raise ValueError(f'Unknown component kind: {kind}')
    values = deepcopy(DEFAULTS.get(kind, {}))
    values.update((project_defaults or {}).get(kind, {}))
    defaults = sorted(k for k in values if k not in component)
    values.update(deepcopy(component))
    findings = []
    tag = component.get('schedule_tag')
    entry = (schedules or {}).get(tag) if tag else None
    if tag and not entry:
        findings.append({'code': 'SCHEDULE_MISSING', 'message': f'No schedule entry for {tag}'})
    if entry:
        if not entry.get('source'):
            raise ValueError(f'Schedule {tag} needs a source drawing reference')
        if entry.get('kind') != kind:
            raise ValueError(f'Schedule {tag} is not a {kind}')
        permitted = {'width_m', 'height_m', 'material', 'fire_rating', 'frame_material',
                     'frame_width_m', 'frame_depth_m', 'glass_thickness_m', 'glass_colour',
                     'panel_depth_m', 'operation'}
        for key in permitted & entry.keys():
            if key in component and component[key] != entry[key]:
                findings.append({'code': 'SCHEDULE_CONFLICT', 'field': key,
                                 'drawing': component[key], 'schedule': entry[key], 'source': entry['source']})
            values[key] = entry[key]
            if key in defaults:
                defaults.remove(key)
        values['schedule_source'] = entry['source']
    if values.get('height_m') == 'full_height':
        values['height_m'] = values.get('clear_height_m')
        if values['height_m'] is None:
            raise ValueError('Full-height door needs clear_height_m from the elevation/section')
    for key in ('width_m', 'height_m', 'frame_width_m', 'frame_depth_m', 'glass_thickness_m', 'panel_depth_m'):
        if key in values:
            value = values[key]
            if isinstance(value, bool) or not isinstance(value, (float, int)) or not math.isfinite(value) or value <= 0:
                raise ValueError(f'{key} must be a positive finite number')
    if kind == 'window':
        if values['glass_colour'] not in GLASS_COLOURS:
            raise ValueError('glass_colour must be blue, green, black or transparent')
        if values['glass_thickness_m'] > values['frame_depth_m']:
            raise ValueError('Glass thickness exceeds frame depth')
        if any(values.get(k, float('inf')) <= 2 * values['frame_width_m'] for k in ('width_m', 'height_m')):
            raise ValueError('Window is too small for the selected frame')
    if kind in ('door', 'window') and 'fire_rating' not in values:
        findings.append({'code': 'FIRE_RATING_UNRESOLVED', 'message': 'Check the schedule; no rating assumed'})
    values['defaulted_fields'] = defaults
    return values, findings
